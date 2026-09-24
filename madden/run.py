"""Run a week.

    python -m madden.run --tranche sunday

The sheet is found in MADDEN_SHEETS_DIR; --sheet overrides it.
Degrade and warn on a data fault, never stop. Halt only on a sheet fault.
Madden never submits, never contacts, never publishes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .core import make_pick, tiebreaker
from . import health
from . import injuries
from . import schedule
from .market import fetch_lines, fetch_scores, load_offline, soonest
from .sheet import SheetFault, parse_sheet
from .weather import forecast_many

TRANCHES = {
    "thursday": ("Wednesday", "Thursday"),
    "international": ("Saturday",),
    "sunday": ("Saturday", "Sunday", "Monday"),
    "all": None,
}

# "Eustace - NFL2026w0.xlsx" -> 0, "NFL2026w12.xlsx" -> 12
WEEK_IN_NAME = re.compile(r"w(?:eek)?[ _-]?(\d{1,2})(?!\d)", re.IGNORECASE)


def load_env(start: Path | None = None) -> None:
    """Read .env from the project root into os.environ. Existing vars always win."""
    here = (start or Path(__file__).resolve().parent.parent)
    for candidate in (here / ".env", Path.cwd() / ".env"):
        if not candidate.is_file():
            continue
        for raw in candidate.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val
        return


def rating_module():
    """The power rating, if one has ever been built. None today, and that is by design.

    Keyed on whether a rating EXISTS, never on `power_rating.enabled`. The flag is a
    statement of intent and the module is the fact, and only the fact decides whether the
    model term can be anything but zero -- `make_pick`'s `model_term` defaults to 0.0 and
    run.py passes nothing, so flipping the flag alone changes no number on the board.

    That the rating is not built is a design decision recorded in the spec and the README,
    tested once and found to make results worse. A decision is not a run-health event, so a
    run says nothing about it. What a run does say is when the flag and the fact disagree,
    because that is the state where the board would quietly stop matching its own config.
    """
    try:
        from . import rating
    except ImportError:
        return None
    return rating if hasattr(rating, "model_term") else None


def week_of(path: Path):
    """The week number in a filename, or None."""
    m = WEEK_IN_NAME.search(path.stem)
    return int(m.group(1)) if m else None


def pick_sheet(params, root: Path, want_week: int | None = None):
    """Choose the week's sheet by the number in its NAME, not its timestamp.

    Modification time is not a week number. Re-saving an old sheet, a Drive re-sync,
    or just opening one to look at it all touch the timestamp, and the failure would be
    silent: a normal-looking board priced against last week's frozen lines. The name is
    what the operator actually sets.

    Returns (path, warnings).
    """
    raw = os.environ.get("MADDEN_SHEETS_DIR") or (
        params.get("sheets") or {}).get("directory", "sheets")
    folder = Path(raw).expanduser()
    if not folder.is_absolute():
        folder = root / folder
    if not folder.is_dir():
        raise SheetFault(
            f"sheets directory {folder} does not exist. Set MADDEN_SHEETS_DIR in .env "
            f"to wherever you keep the weekly sheets.")

    found = [f for f in folder.glob("*.xlsx") if not f.name.startswith("~$")]
    if not found:
        raise SheetFault(
            f"no xlsx found in {folder}. Put this week's sheet there, or pass --sheet.")

    numbered = [(week_of(f), f) for f in found]
    numbered = [(w, f) for w, f in numbered if w is not None]
    unnumbered = [f for f in found if week_of(f) is None]
    warnings = []

    if want_week is not None:
        matches = [f for w, f in numbered if w == want_week]
        if not matches:
            raise SheetFault(
                f"no sheet for week {want_week} in {folder}. Found: "
                f"{', '.join(sorted(f.name for f in found))}")
        if len(matches) > 1:
            warnings.append(
                f"{len(matches)} sheets name week {want_week}; using "
                f"{max(matches, key=lambda f: f.stat().st_mtime).name}")
        return max(matches, key=lambda f: f.stat().st_mtime), warnings

    if not numbered:
        chosen = max(found, key=lambda f: f.stat().st_mtime)
        warnings.append(
            f"no week number in any filename, so the newest file was used ({chosen.name}). "
            f"Timestamps are not week numbers -- check this is the right sheet, or pass "
            f"--sheet or --sheet-week.")
        return chosen, warnings

    top = max(w for w, _ in numbered)
    matches = [f for w, f in numbered if w == top]
    chosen = max(matches, key=lambda f: f.stat().st_mtime)
    if len(matches) > 1:
        warnings.append(
            f"{len(matches)} sheets name week {top}; using {chosen.name}")
    if unnumbered:
        warnings.append(
            f"ignored {len(unnumbered)} file(s) with no week number in the name: "
            f"{', '.join(sorted(f.name for f in unnumbered))}")
    return chosen, warnings


def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


PROJECTS = Path.home() / ".claude" / "projects"
SETTINGS = Path.home() / ".claude" / "settings.json"
# The posture file, passed at launch with --settings. It carries the sandbox, the
# allowlist and the denyWrite list without writing anything global: user settings are
# shared with every other project on this machine, and a machine-wide allowlist
# starved two Flathead runs. Paths inside it must be absolute or ~/-relative: a bare
# "./x" in a --settings file resolves against neither the repo nor the project, so it
# would protect nothing while reading exactly like protection.
POSTURE = Path.home() / ".config" / "madden" / "settings.json"
OFF_LIST_HOST = "example.com"   # reserved for documentation; must never be allowlisted


def project_dir_name(path: Path) -> str:
    """Claude Code's own name for a starting directory under ~/.claude/projects:
    every character that is not a letter or a digit becomes a hyphen. Verified
    2026-09-11 against the directories on this machine."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def session_transcript() -> Path | None:
    """This session's transcript, wherever the session was started.

    WHERE IT STARTED NO LONGER GATES ANYTHING. Until 2026-09-11 the guard required
    the session to have started in ~/dev/madden, because that was the only directory
    whose project settings carried the rules. The rules now live in user settings and
    load in every session, so the engine runs from anywhere and this function exists
    only to date the session for the staleness check below.
    """
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid or not re.fullmatch(r"[A-Za-z0-9._-]{8,64}", sid):
        return None
    if not PROJECTS.is_dir():
        return None
    hits = sorted(PROJECTS.glob(f"*/{sid}.jsonl"))
    return hits[0] if hits else None


def settings_newer_than_session() -> str | None:
    """Warn when ~/.claude/settings.json was written after this session started.

    A session reads the rules when it starts. Edit them afterwards and what the file
    says and what the session enforces can disagree, with the file looking correct.
    That is how the install-check step 6 claim came to be false: it recorded a refusal
    that a later session, with newer rules, no longer produced.

    A WARNING, NOT A REFUSAL. Scott's call, 2026-09-11, and the evidence is on his
    side: the sandbox was seen hot-reloading its network policy mid-session that
    evening -- api.anthropic.com went from blocked to reachable with no restart -- so
    the divergence this check assumes may not happen at all. Blocking a Sunday-morning
    board on a settings edit made an hour earlier is a certain cost against a
    speculative one. It prints under run health so the condition is never silent.
    """
    t = session_transcript()
    if t is None:
        return ("this session cannot be located under ~/.claude/projects, so the rules "
                "it started with cannot be dated against the settings file")
    if not SETTINGS.is_file():
        return f"{SETTINGS} does not exist, so there are no user-scope rules to load"
    st = t.stat()
    born = getattr(st, "st_birthtime", st.st_ctime)
    changed = SETTINGS.stat().st_mtime
    if changed > born:
        return (f"{SETTINGS} was written at {datetime.fromtimestamp(changed):%H:%M:%S} "
                f"and this session started at {datetime.fromtimestamp(born):%H:%M:%S}, so "
                f"the rules on disk are not necessarily the rules this session loaded. "
                f"A session started after that edit would load them cleanly")
    return None


def _rule_paths(rules) -> list[Path]:
    """Absolute paths out of permission rules like Edit(~/dev/madden/**)."""
    out = []
    for r in rules or []:
        m = re.fullmatch(r"Edit\((.+?)\)", str(r).strip())
        if not m:
            continue
        raw = m.group(1)
        raw = "/" + raw[2:] if raw.startswith("//") else raw   # // means absolute
        raw = re.sub(r"^/+", "/", raw)   # POSIX gives a doubled leading slash its own meaning
        raw = raw.split("*", 1)[0]
        out.append(Path(raw).expanduser())
    return out


def settings_sources(repo: Path) -> list[Path]:
    """Every settings file that can carry a permission rule this session loaded.

    Not one hardcoded path. A rule can live in managed settings, user settings, a
    project file, a local file, or the posture file passed at launch with --settings,
    and which one holds it is Scott's arrangement to change rather than the engine's
    to assume.
    """
    return [
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
        Path("/etc/claude-code/managed-settings.json"),
        SETTINGS,
        Path.home() / ".claude" / "settings.local.json",
        POSTURE,
        repo / ".claude" / "settings.json",
        repo / ".claude" / "settings.local.json",
    ]


def declared_guardrails(repo: Path) -> list[str]:
    """The one guardrail with no behavioural sibling: the file-tool gate.

    REWRITTEN 2026-09-13. This used to read five assertions out of
    ~/.claude/settings.json. Four of them are PROVEN elsewhere in guard_inputs and
    proven for this run rather than for a file: SANDBOX_RUNTIME covers
    sandbox.enabled and allowUnsandboxedCommands, because a command retried outside
    the sandbox carries neither; the off-list probe covers strictAllowlist; and the
    writability test covers denyWrite, more tightly than the declaration did, since
    it tests the files this run actually opens instead of a list of paths. Reading a
    declaration of those four added nothing but a dependency on which file happened
    to carry them -- and that dependency broke the day the posture moved off
    ~/.claude/settings.json, refusing a board over a file that no longer needs to say
    anything. That is the same failure this guard has now made three times: asking
    where something is declared instead of whether it is true now.

    What no sibling proves: Claude's file tools sit outside the sandbox entirely --
    verified in the act on 2026-09-11, when Bash was refused a write and the Write
    tool then created that exact path. The writability check tests what THIS PROCESS
    can open and says nothing about whether Edit and Write prompt. An ask/deny Edit
    rule is the only thing that binds them, and it cannot be probed from inside a
    session, because an approved prompt and an absent prompt look identical from in
    here. So it is read -- but from every source that can carry it.

    Still a declaration, and still weaker than its siblings. It fails closed: no
    readable source, or no covering rule, is a refusal.
    """
    seen, gated, unreadable = [], [], []
    for src in settings_sources(repo):
        if not src.is_file():
            continue
        try:
            cfg = json.loads(src.read_text())
        except (OSError, ValueError) as exc:
            unreadable.append(f"{src} ({exc})")
            continue
        seen.append(src)
        perms = cfg.get("permissions") or {}
        gated += _rule_paths(perms.get("ask")) + _rule_paths(perms.get("deny"))

    if any(g == repo or g in repo.parents or repo in g.parents for g in gated):
        return []
    where = ", ".join(str(s) for s in seen) if seen else "no readable settings file"
    note = f" (unparseable: {'; '.join(unreadable)})" if unreadable else ""
    return [f"no permissions ask/deny Edit(...) rule covering {repo} was found in "
            f"{where}{note}, so Claude's file tools can write the engine without "
            f"asking"]


def allowlist_in_force(timeout: float = 3.0) -> tuple[str, str]:
    """Probe a host that must never be allowlisted. Returns (verdict, detail).

    "blocked" -- the proxy refused it, so the allowlist is doing something.
    "open"    -- an off-list host answered, so it is not.
    "unknown" -- neither; reported as a warning, never as a refusal, because a slow
                 or odd network on a Sunday morning must not cost Scott his board.
    """
    try:
        urllib.request.urlopen(f"https://{OFF_LIST_HOST}/", timeout=timeout)
    except urllib.error.HTTPError:
        return "open", f"{OFF_LIST_HOST} answered, so it is not being blocked"
    except urllib.error.URLError as exc:
        if "Tunnel connection failed" in str(exc) or "Forbidden" in str(exc):
            return "blocked", f"{OFF_LIST_HOST} refused by the proxy"
        return "unknown", f"{OFF_LIST_HOST} failed for another reason ({exc})"
    except Exception as exc:                      # noqa: BLE001 - never fatal
        return "unknown", f"the probe itself failed ({type(exc).__name__}: {exc})"
    return "open", f"{OFF_LIST_HOST} was reached, so the allowlist is not in force"


def guard_inputs(paths, cache: bool, repo: Path | None = None) -> str | None:
    """Under Claude Code, refuse a run whose guardrails are not in force.

    The question is whether the rules bind, never where the session started. Checks,
    in order, cheapest and most certain first:

    1. Is the sandbox running at all (SANDBOX_RUNTIME)?
    2. Is an Edit rule gating Claude's file tools on the repo, in any settings source
       that can carry one? The only assertion here with no behavioural sibling; the
       sandbox, the allowlist and denyWrite are proven by 1, 4 and 3 below.
    3. Do the filesystem rules actually bind? Every input this run will read must be
       unwritable by this process. Behavioural, and the only check here that proves
       rather than reads.
    4. Is an off-list host actually refused? Only a positive "open" refuses; an
       inconclusive probe is a warning (see guardrail_warnings).

    Two conditions warn rather than refuse, and both print under run health: a
    settings file newer than this session, and a probe that could not reach a verdict.
    """
    if os.environ.get("CLAUDECODE") != "1":
        return None
    if cache:
        return "--cache reads files this session can write; refused under Claude Code"
    repo = repo or Path(__file__).resolve().parent.parent

    if os.environ.get("SANDBOX_RUNTIME") != "1":
        return ("SANDBOX_RUNTIME is not set, so this session is not running under the "
                "sandbox and none of the filesystem or network rules bind")
    missing = declared_guardrails(repo)
    if missing:
        return "; ".join(missing)
    for p in filter(None, paths):
        try:
            fd = os.open(p, os.O_WRONLY | os.O_APPEND)   # no O_CREAT: creates nothing
        except OSError:
            continue
        os.close(fd)
        return (f"{p} is writable by this process: it was made in this session, or it "
                f"sits outside the directories the sandbox protects. Either way the "
                f"board would not be the engine's own.")
    verdict, detail = allowlist_in_force()
    if verdict == "open":
        return (f"the network allowlist is declared but not in force: {detail}. The "
                f"engine's sources are not the only hosts this session can reach")
    return None


def guardrail_warnings(repo: Path | None = None) -> list[str]:
    """Soft findings about the guardrails: reported under run health, never fatal."""
    if os.environ.get("CLAUDECODE") != "1":
        return []
    out = []
    stale = settings_newer_than_session()
    if stale:
        out.append(f"the rules may not be the ones this session loaded: {stale}. The "
                   f"board stands; the guardrails are unconfirmed for this run")
    verdict, detail = allowlist_in_force()
    if verdict == "unknown":
        out.append(f"could not confirm the network allowlist is in force: {detail}. The "
                   f"board is unaffected; the guardrail is unverified for this run")
    return out


def pct(healthy: int, total: int) -> str:
    """"9/11   82%", or an em dash when the side has no listed starters to count."""
    if not total:
        return "-"
    return f"{healthy}/{total}  {100 * healthy / total:3.0f}%"


NO_LINE_PLAYED = "already played"
NO_LINE_FETCH_FAILED = "fetch failed"
NO_LINE_ABSENT = "not in the feed"
# A line was fetched and then rejected as too far from the sheet to believe. Distinct from
# the three above, all of which mean no line arrived at all: this game has a number and the
# number is the problem, and labelling it "not in the feed" would name the wrong fault.
NO_LINE_SUSPECT = "line suspect"


def no_line_reason(game, scores, fetch_failed: bool) -> tuple[str, str]:
    """Why this game has no market line: (label for the board, sentence for run health).

    The spreads feed drops a game once it has been played, so a finished game and a game
    the feed never listed both arrive as no line. Reporting both as "line missing" hid
    two finished games in the week 1 board. The scores endpoint is what separates them.
    """
    if fetch_failed:
        return NO_LINE_FETCH_FAILED, (
            "the line fetch failed, so this game was never priced this run. Whether it "
            "has already been played is not known here.")
    final = scores.get(frozenset((game.home, game.away)))
    if final is not None and final.completed:
        return NO_LINE_PLAYED, (
            f"already played ({final.text}). The feed drops a finished game, so there was "
            f"no line to pick against.")
    return NO_LINE_ABSENT, (
        f"the feed lists no meeting for {game.away} at {game.home}, and the score check "
        f"does not show it finished. No line, and the reason is not known.")


def handback_lines(picks) -> list[str]:
    """The handback sections: games that carry a lean, then games with no pick at all.

    A game with no market line has no lean. make_pick withholds the side rather than
    fabricating one, so the line cannot sit under a header promising a lean; the header
    used to promise one for every handback. Games with no pick get their own section
    naming the consequence, because an unpicked game is a favorite pick by default.
    """
    leaned = [p for p in picks if p.blind and p.side]
    no_pick = [p for p in picks if p.side is None]
    out: list[str] = []
    if leaned:
        out.append("HANDBACKS (each carries a lean, so these are still submittable)")
        for p in leaned:
            g = p.game
            out.append(f"  {g.away} at {g.home}: lean {p.side}; "
                       f"{'; '.join(p.warnings) or 'flagged'}")
    if no_pick:
        out.append("NO PICK (no lean either: nothing to submit, so under the pool's rule "
                   "these revert to the favorite)")
        for p in no_pick:
            g = p.game
            out.append(f"  {g.away} at {g.home}: {'; '.join(p.warnings) or 'flagged'}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Madden: weekly ATS picks for the office pool")
    ap.add_argument("--sheet", help="the operator's xlsx; defaults to the highest "
                                    "week number in MADDEN_SHEETS_DIR")
    ap.add_argument("--sheet-week", type=int,
                    help="use the sheet naming this week number rather than the highest")
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--week", help="week file: neutral sites, blind flags, overrides")
    ap.add_argument("--tranche", default="all", choices=sorted(TRANCHES))
    ap.add_argument("--offline-lines", help="hand-entered lines instead of the API")
    ap.add_argument("--expect", type=int, help="expected game count; mismatch is a hard stop")
    ap.add_argument("--log", default="logs", help="directory for the run log")
    ap.add_argument("--no-injuries", action="store_true",
                    help="skip the injury report (the exposure section then says UNKNOWN)")
    ap.add_argument("--no-weather", action="store_true", help="skip the forecast fetch")
    ap.add_argument("--cache", action="store_true",
                    help="debugging only: read and write forecasts (6h) on disk. A real run "
                         "never uses this; the spec says perishable data is fetched fresh "
                         "and never written to disk")
    args = ap.parse_args(argv)

    load_env()
    params = load_yaml(args.params)
    week = load_yaml(args.week) if args.week else {}
    temps = dict(week.get("temperatures", {}) or {})
    winds = dict(week.get("wind_mph", {}) or {})
    neutral = [tuple(p.split("@")) for p in (week.get("neutral_sites") or [])]
    blind_games = set(week.get("blind") or [])
    open_roofs = set(week.get("retractable_open") or [])

    warnings: list[str] = []
    if args.cache:
        warnings.append("CACHE IN USE (--cache): forecasts may be up to 6h old. "
                        "Not a submittable run")
    try:
        if args.sheet:
            sheet_path = Path(args.sheet).expanduser()
        else:
            sheet_path, sheet_warnings = pick_sheet(
                params, Path(__file__).resolve().parent.parent, args.sheet_week)
            warnings.extend(sheet_warnings)
        wk = week_of(sheet_path)
        print(f"sheet: {sheet_path.name}" + (f"  (week {wk})" if wk is not None else ""))
        print(f"  {sheet_path}")
        problem = guard_inputs(
            [args.params, sheet_path, args.week, args.offline_lines], cache=args.cache)
        if problem:
            print(f"GUARDRAIL, halting: {problem}", file=sys.stderr)
            return 3
        warnings.extend(guardrail_warnings())
        games = parse_sheet(str(sheet_path), expected_games=args.expect,
                            neutral_sites=neutral, announce=print)

        # Which week this is, worked out from the games themselves. A week file still
        # wins, but it is now optional rather than load-bearing, and the filename is only
        # cross-checked. An unresolved week halts: the injury report is keyed on season
        # and week, and a wrong week fetches cleanly, returns nothing, and reports every
        # team UNKNOWN without a single warning. See schedule.py.
        if week.get("season") and week.get("week"):
            resolved = schedule.Resolution(
                season=int(week["season"]), week=int(week["week"]),
                matched=0, total=len(games), source="week file")
            print(f"week:  season {resolved.season} week {resolved.week}, "
                  f"declared in {args.week}")
            warnings.extend(schedule.confirm(resolved.season, resolved.week, games))
        else:
            print("resolving the week from the nflverse schedule...", flush=True)
            resolved = schedule.resolve(games)
            print(f"week:  {resolved}")
            warnings.extend(schedule.filename_cross_check(resolved, wk))
    except SheetFault as exc:
        print(f"SHEET FAULT, halting: {exc}", file=sys.stderr)
        return 2

    line_fetch_failed = False
    try:
        lines = load_offline(args.offline_lines) if args.offline_lines else fetch_lines(params)
    except Exception as exc:                      # degrade and warn, never stop
        warnings.append(f"line fetch failed ({exc}); every game is running without a market line")
        lines = {}
        line_fetch_failed = True

    days = TRANCHES[args.tranche]
    in_tranche = [g for g in games if not days or g.day in days]

    # Quarterback exposure. Names only: injuries reach the picks through the market line,
    # and a second injury number would double count it. Nothing here touches a pick.
    report = None
    if args.no_injuries:
        warnings.append("injury report skipped by --no-injuries: exposure is UNKNOWN for "
                        "every game")
    else:
        print("fetching the official injury report and depth chart...", flush=True)
        report, inj_warnings = injuries.fetch(resolved.season, resolved.week)
        warnings.extend(inj_warnings)
        if report.error:
            # A data fault, so this degrades rather than halting, per the spec's
            # guardrails. It is loud because the board below still looks complete.
            warnings.append(injuries.header(report))
        elif report.empty:
            warnings.append(
                f"the injury report holds no rows at all for season {resolved.season} "
                f"week {resolved.week}, so exposure is UNKNOWN for every game. nflverse "
                f"rebuilds daily around 12:00 UTC and the league's first report of the "
                f"week lands Wednesday, so before that this is expected. It is said out "
                f"loud because a clean fetch of an empty week is indistinguishable from a "
                f"clean fetch of a healthy one.")

    # Weather, for outdoor games with no temperature already supplied. The week file
    # always wins: a value someone entered deliberately beats a forecast.
    if args.no_weather:
        warnings.append("forecast skipped by --no-weather: temperature rules cannot fire")
    else:
        need = []
        for g in in_tranche:
            if g.home in temps or g.neutral_site:
                continue
            ml, _ = soonest(lines, g.home, g.away)
            kickoff = ml.starts_at() if ml else None
            if kickoff is not None:
                need.append((g.home, kickoff))
        if need:
            print(f"fetching forecasts for {len(need)} stadiums...", flush=True)
            got_t, got_w, w_warn = forecast_many(need, use_cache=args.cache)
            for k, v in got_t.items():
                temps.setdefault(k, v)
            for k, v in got_w.items():
                if v is not None:
                    winds.setdefault(k, v)
            warnings.extend(w_warn)

    now = datetime.now(timezone.utc)
    max_days = params["odds_api"]["max_kickoff_days"]
    market_lines: dict = {}
    picks = []
    for g in games:
        if days and g.day not in days:
            continue
        ml, pair_warnings = soonest(lines, g.home, g.away)
        warnings.extend(pair_warnings)
        start = ml.starts_at() if ml else None
        if start is not None and start > now + timedelta(days=max_days):
            warnings.append(
                f"{g.away} at {g.home}: the only meeting in the feed kicks off "
                f"{ml.commence_time}, more than {max_days} days out. That is not this "
                f"week's game, so the line is treated as missing.")
            ml = None
        if ml is None:
            warnings.append(f"no market line for {g.away} at {g.home}")
        age = ml.age_hours() if ml else None
        if age is not None and age > params["odds_api"]["max_line_age_hours"]:
            warnings.append(f"{g.away} at {g.home}: line is {age:.1f}h old")
        market_lines[(g.home, g.away)] = ml

        pick = make_pick(
            g, ml.line_for(g.home) if ml else None, params,
            temp_f=temps.get(g.home), retractable_open=g.home in open_roofs,
            blind=f"{g.away}@{g.home}" in blind_games)
        picks.append(pick)

    # Say why each unpriced game has no line. Costs 2 credits, so it is asked once, and
    # only when something came back unpriced.
    no_line_labels: dict = {}
    # Games with no line at all. A suspect line is deliberately NOT in here: it has a
    # number, so asking the scores endpoint why it has none would answer a question nobody
    # asked and label the game with the wrong reason.
    unpriced = [p for p in picks if p.market_home_line is None]
    for p in picks:
        if p.side is None and p.market_home_line is not None:
            no_line_labels[(p.game.home, p.game.away)] = NO_LINE_SUSPECT
    scores: dict = {}
    if unpriced and not line_fetch_failed:
        print(f"checking whether {len(unpriced)} unpriced game(s) have been played...",
              flush=True)
        try:
            scores = fetch_scores(params)
        except Exception as exc:                  # degrade and warn, never stop
            warnings.append(f"score check failed ({exc}); a game already played cannot be "
                            f"told apart from one the feed never listed")
    for p in unpriced:
        label, sentence = no_line_reason(p.game, scores, fetch_failed=line_fetch_failed)
        no_line_labels[(p.game.home, p.game.away)] = label
        p.warnings.append(sentence)

    submittable = [p for p in picks if p.side]
    deviations = [p for p in submittable if p.deviates_from_favorite]

    print(f"\nMADDEN  tranche={args.tranche}  games={len(picks)}  "
          f"deviations from favorite={len(deviations)}\n")
    print(f"{'GAME':<26}{'SHEET':>7}{'MKT':>7}{'ADJ':>7}{'NUM':>7}{'EDGE':>7}  "
          f"{'PICK':<5}{'BAND':<11}DRIVER")
    for p in picks:
        g = p.game
        name = f"{g.away} at {g.home}"
        if p.side is None:
            # The market column still prints when a line was fetched and rejected. The
            # rejected number is the whole finding; blanking it would hide what happened.
            mkt = f"{p.market_home_line:>7.1f}" if p.market_home_line is not None else f"{'--':>7}"
            print(f"{name:<26}{g.sheet_home_line:>7.1f}{mkt}{'--':>7}{'--':>7}{'--':>7}  "
                  f"{'--':<5}{'blind':<11}"
                  f"{no_line_labels.get((g.home, g.away), 'line missing')}")
            continue
        print(f"{name:<26}{g.sheet_home_line:>7.1f}{p.market_home_line:>7.1f}"
              f"{p.adjustment_total:>7.1f}{p.madden_number:>7.1f}{p.edge:>7.1f}  "
              f"{p.side:<5}{p.band:<11}{p.drivers[0]}")
        # Every driver, not just the first: a high band on a small edge is a key-number
        # crossing, and hiding that line makes the band look unexplained.
        for extra in p.drivers[1:]:
            print(f"{'':<79}{extra}")

    # Exposure, directly under the board: which games to look at before submitting.
    exposure_log: dict = {}
    print("\nEXPOSURE  quarterbacks with an unresolved status")
    if report is None:
        print("  UNKNOWN for every game: no injury report was read (see run health)")
    else:
        print(f"  {injuries.header(report)}")
        clear, dark = [], []
        for p in picks:
            g = p.game
            names, unknown = injuries.exposure(report, g.home, g.away)
            exposure_log[f"{g.away}@{g.home}"] = {"names": names, "unknown": unknown}
            if unknown:
                dark.append(f"{g.away} at {g.home}")
            if not names and not unknown:
                clear.append(f"{g.away} at {g.home}")
                continue
            parts = list(names)
            if unknown and not report.error:
                parts.append(f"UNKNOWN for {', '.join(unknown)}: no official report "
                             f"in this build")
            elif unknown:
                parts.append("UNKNOWN")
            print(f"  {g.away} at {g.home}: {'; '.join(parts)}")
        if clear:
            # "In this build": the report is only as current as nflverse's last daily
            # rebuild, which can be a report behind the league's.
            print(f"  no unresolved quarterback in this build: {', '.join(clear)}")
        if dark and not report.empty:
            # Per-game UNKNOWNs print above, but only under the board. A reader who goes
            # straight to run health should still learn the exposure layer has holes.
            warnings.append(
                f"exposure could not be resolved for {len(dark)} of {len(picks)} games "
                f"({', '.join(dark)}): a team in each has no row in this injury build. "
                f"Those games are UNKNOWN, not clear.")

    # Starter health and injured quarterbacks, both display only, on the same terms as
    # exposure above: counts and names, no points, no effect on any pick, band or edge.
    board_teams: list = []
    for p in picks:
        for t in (p.game.away, p.game.home):
            if t not in board_teams:
                board_teams.append(t)

    health_log: dict = {}
    print("\nSTARTER HEALTH  listed starters with no row on this week's official report")
    if report is None or report.error:
        print("  UNKNOWN for every team: no injury report was read (see run health)")
    elif report.depth_error:
        print("  UNKNOWN for every team: the depth chart did not fetch, so there is no "
              "starter list to count against (see run health)")
    else:
        print(f"  {'TEAM':<7}{'OFFENSE':>14}{'DEFENSE':>14}{'TOTAL':>14}")
        dark, tot = [], [0, 0, 0, 0]
        for team, oh, on, dh, dn in health.health(report, board_teams):
            health_log[team] = {"offense": [oh, on], "defense": [dh, dn]}
            if not on and not dn:
                dark.append(team)
                print(f"  {team:<7}{'UNKNOWN: not in this depth chart build':>39}")
                continue
            tot = [tot[0] + oh, tot[1] + on, tot[2] + dh, tot[3] + dn]
            print(f"  {team:<7}{pct(oh, on):>14}{pct(dh, dn):>14}{pct(oh + dh, on + dn):>14}")
        if tot[1] or tot[3]:
            print(f"  {'BOARD':<7}{pct(tot[0], tot[1]):>14}{pct(tot[2], tot[3]):>14}"
                  f"{pct(tot[0] + tot[2], tot[1] + tot[3]):>14}")
        print("  healthy means no row on the report at all, so a full-participation note "
              "counts here exactly")
        print("  like a DNP and a rest day counts like an injury. No points, changes nothing")
        if dark:
            warnings.append(
                f"starter health is UNKNOWN for {len(dark)} of {len(board_teams)} teams "
                f"({', '.join(dark)}): no rows in this depth chart build, so those teams "
                f"are unknown, not clear")

    qb_log: dict = {}
    print("\nINJURED QUARTERBACKS  every quarterback on the report, by depth-chart rank")
    if report is None or report.error:
        print("  UNKNOWN for every team: no injury report was read (see run health)")
    else:
        clear = []
        for team, rows in health.quarterbacks(report, board_teams):
            qb_log[team] = [f"{label} {name}, {said}" for label, name, said in rows]
            if not rows:
                clear.append(team)
                continue
            for i, (label, name, said) in enumerate(rows):
                print(f"  {team if i == 0 else '':<5}{label:<10}{name:<23}{said}")
        if clear:
            print(f"  no quarterback on the report: {', '.join(clear)}")

    sections = handback_lines(picks)
    if sections:
        print()
        for line in sections:
            print(line)

    monday = [p for p in picks if p.game.day == "Monday"]
    if monday:
        g = monday[0].game
        ml = market_lines.get((g.home, g.away))
        tb = tiebreaker(ml.total if ml else None, params, wind_mph=winds.get(g.home))
        print(f"\nTIEBREAKER  {g.away} at {g.home} combined score: {tb['guess']}")
        print(f"  {tb['reason']}")

    all_warnings = warnings + [w for p in picks for w in p.warnings]

    logged, log_error = write_log(args, params, sheet_path, resolved, report,
                                  exposure_log, health_log, qb_log, temps, picks,
                                  deviations, all_warnings)
    if log_error:
        all_warnings = all_warnings + [log_error]

    print("\nRUN HEALTH")
    for w in dict.fromkeys(all_warnings):
        print(f"  ! {w}")
    if not all_warnings:
        # An empty heading reads the same as a section that never ran. Say which it is.
        print("  every input fetched, no warnings")
    if params["power_rating"]["enabled"] and rating_module() is None:
        print("  ! params.yaml sets power_rating.enabled: true, but no rating is built, so "
              "the model term is still zero and the number is the market plus the matrix. "
              "The config claims a layer the engine does not have")

    if logged:
        print(f"\nlogged to {logged}")
    else:
        print("\nNOT LOGGED: this board has no run log, so no figure in it can be "
              "checked against a file afterwards")
    return 0 if logged else 4


def write_log(args, params, sheet_path, resolved, report, exposure_log, health_log,
              qb_log, temps, picks, deviations,
              all_warnings) -> tuple[Path | None, str | None]:
    """Write the run log. Returns (path, None) or (None, a run-health line).

    A log write that cannot land is a data fault and degrades like any other: it is
    named in run health and the exit code says it happened. It used to raise, which
    took the whole run down AFTER the board had printed -- an unhandled PermissionError
    on 2026-09-11, from a session whose sandbox did not allow writes to logs/. The
    board was already correct and complete on stdout and the run still exited 1 with a
    traceback under it.

    The log is written BEFORE run health prints, so that its own failure can appear
    there. Its failure is therefore the one warning the log itself can never carry.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logdir = Path(args.log)
    path = logdir / f"run-{stamp}-{args.tranche}.json"
    record = {
        "run": stamp, "tranche": args.tranche, "sheet": str(sheet_path),
        "sheet_week": week_of(sheet_path),
        "season": resolved.season, "week": resolved.week,
        "week_source": resolved.source,
        "week_games_matched": resolved.matched, "week_games_total": resolved.total,
        "spec_version": params["spec_version"],
        "deviations": len(deviations),
        "injury_report": ({"built": report.built, "depth_as_of": report.depth_as_of,
                           "error": report.error, "depth_error": report.depth_error}
                          if report else None),
        "exposure": exposure_log,
        "starter_health": health_log,
        "injured_quarterbacks": qb_log,
        "cache_used": args.cache,
        "temperatures_used": temps,
        "picks": [{
            "game": f"{p.game.away}@{p.game.home}", "day": p.game.day,
            "sheet_line": p.sheet_home_line, "market_line": p.market_home_line,
            "adjustments": [a.__dict__ for a in p.adjustments],
            "madden_number": p.madden_number, "edge": p.edge, "pick": p.side,
            "band": p.band, "deviation": p.deviates_from_favorite if p.side else None,
            "drivers": p.drivers, "warnings": p.warnings,
        } for p in picks],
        "warnings": list(dict.fromkeys(all_warnings)),
    }
    try:
        logdir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2))
    except OSError as exc:
        return None, (f"the run log could not be written to {path} ({exc.strerror}), so "
                      f"this run left no record on disk and nothing printed above can be "
                      f"checked against a file. The board itself is unaffected")
    return path, None


if __name__ == "__main__":
    raise SystemExit(main())
