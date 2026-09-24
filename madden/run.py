"""Run a week.

    python3 "<Scott's Second Brain>/Apps/madden/madden/run.py"   # from any directory
    python3 -m madden.run --tranche sunday       # from the repo, or with it importable

The tranche defaults to auto: the earliest one whose first kickoff is still ahead.
The sheet is found in MADDEN_SHEETS_DIR; --sheet overrides it, but must still sit there.
Before anything is read, the checks in guard.py must pass, or the run exits 3.
Degrade and warn on a data fault, never stop. Halt only on a sheet fault.
Madden never submits, never contacts, never publishes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

if __name__ == "__main__" and not __package__:
    # Run by path (python3 ~/dev/madden/madden/run.py) from any directory: re-enter as
    # the package, so the relative imports below resolve without an install or a cd.
    import runpy
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    runpy.run_module("madden.run", run_name="__main__", alter_sys=True)
    raise SystemExit(0)

from .core import make_pick, tiebreaker
from . import guard
from . import health
from . import injuries
from . import schedule
from .market import fetch_lines, fetch_scores, load_offline, soonest
from .net import blocked_hosts
from .sheet import SheetFault, parse_sheet
from .weather import FORECAST_URL, forecast_many

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


# The tranche that owns a game for submission. Order matters: Saturday sits in both the
# international and the sunday day-sets, and an overseas Saturday kickoff is the whole
# reason the international tranche exists, so it claims Saturday first.
TRANCHE_ORDER = ("thursday", "international", "sunday")


def owning_tranche(day: str) -> str | None:
    for name in TRANCHE_ORDER:
        if day in (TRANCHES[name] or ()):
            return name
    return None


def tranche_deadlines(games, kickoffs) -> dict:
    """tranche -> (deadline, [games]). The deadline is that tranche's earliest kickoff.

    A tranche's deadline is not a clock time and is deliberately not read off one. It is
    the moment its first game starts, because that is when the pool stops taking a pick
    for it and the revert-to-favorite rule fires on anything unsubmitted.
    """
    out: dict = {}
    for g in games:
        name = owning_tranche(g.day)
        when = kickoffs.get(frozenset((g.home, g.away)))
        if name is None or when is None:
            continue
        deadline, listed = out.get(name, (None, []))
        listed.append(f"{g.away} at {g.home}")
        out[name] = (when if deadline is None or when < deadline else deadline, listed)
    return out


class NoTrancheLeft(Exception):
    """--tranche auto found nothing still ahead. The message is the plain reason."""


def choose_tranche(games, kickoffs, now) -> tuple[str, str]:
    """--tranche auto: the earliest tranche whose deadline is still ahead.

    Returns (tranche, the run-health line saying why). The deadline is the tranche's
    first kickoff, from tranche_deadlines, so a tranche whose first game has started is
    skipped even if later games in it have not: its deadline has passed.
    """
    if not kickoffs:
        raise NoTrancheLeft(
            "no kickoff times are known for this week, so --tranche auto cannot tell which "
            "tranche is next; name one with --tranche")
    deadlines = tranche_deadlines(games, kickoffs)
    ahead = sorted((d, name) for name, (d, _) in deadlines.items() if d > now)
    if not ahead:
        raise NoTrancheLeft(
            "every tranche on this sheet has already kicked off, so there is nothing left "
            "to pick; name one with --tranche to run it anyway")
    deadline, name = ahead[0]
    passed = sorted(n for n, (d, _) in deadlines.items() if d <= now)
    local = deadline.astimezone().strftime("%a %Y-%m-%d %H:%M %Z")
    why = (f"TRANCHE: auto chose {name}, the earliest tranche whose first kickoff is still "
           f"ahead ({local})")
    if passed:
        why += f"; already kicked off: {', '.join(passed)}"
    return name, why


def logged_runs(logdir: Path, season: int, week: int) -> list[tuple[str, datetime]]:
    """(tranche, written_at) for every readable log covering this season and week."""
    out: list[tuple[str, datetime]] = []
    try:
        paths = sorted(Path(logdir).glob("run-*.json"))
    except OSError:
        return out
    for p in paths:
        try:
            rec = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if rec.get("season") != season or rec.get("week") != week:
            continue
        try:
            when = datetime.strptime(str(rec.get("run")), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        out.append((str(rec.get("tranche")), when))
    return out


def missed_tranches(deadlines, runs, now) -> list[str]:
    """Tranches whose deadline has passed with no run that beat it.

    This is the absence-of-output check, and it is the reason it lives at the START of a
    run rather than the end: the thing being detected is a run that did not happen, and
    nothing inside that run can report it. The next run is the earliest moment anything
    in this repo can speak, so the Sunday run is what tells Scott about the Thursday miss
    -- while he can still do something about the rest of the week.

    A run written AFTER the deadline does not count as covering it. That is not pedantry:
    week 1's thursday tranche ran two and a half hours after its own kickoff, produced a
    log, and would satisfy any check that only asked whether a log exists.
    """
    out: list[str] = []
    for name in TRANCHE_ORDER:
        if name not in deadlines:
            continue
        deadline, listed = deadlines[name]
        if deadline > now:
            continue                                   # not due yet, nothing to say
        mine = [w for t, w in runs if t in (name, "all")]
        if any(w < deadline for w in mine):
            continue                                   # covered in time
        when = deadline.strftime("%Y-%m-%d %H:%M UTC")
        if mine:
            latest = max(mine).strftime("%Y-%m-%d %H:%M UTC")
            out.append(
                f"MISSED TRANCHE: the {name} tranche kicked off {when} and the only run "
                f"covering it was written {latest}, after the deadline. Those picks were "
                f"made against games already under way. {len(listed)} game(s): "
                f"{', '.join(listed)}")
        else:
            out.append(
                f"MISSED TRANCHE: the {name} tranche kicked off {when} and no run covers "
                f"it. Under the pool's rule those games reverted to the favorite. "
                f"{len(listed)} game(s): {', '.join(listed)}")
    return out


def forecast_needs(in_tranche, temps, kickoffs) -> tuple[list, list[str]]:
    """(home, kickoff) for every outdoor game still needing a forecast, plus warnings.

    The kickoff comes from the nflverse schedule, the engine's one source of kickoff
    times; tranche deadlines already use it. It used to come from the odds feed, so
    when week 3's line fetch failed ATL at GB was never forecast and the dome rule
    went unevaluated, though the schedule knew exactly when the game started.
    """
    need, warnings = [], []
    for g in in_tranche:
        if g.home in temps or g.neutral_site:
            continue
        kickoff = kickoffs.get(frozenset((g.home, g.away)))
        if kickoff is None:
            warnings.append(f"no kickoff time for {g.away} at {g.home} in the schedule, so "
                            f"no forecast was fetched; the temperature rule cannot fire")
            continue
        need.append((g.home, kickoff))
    return need, warnings


def needed_urls(args, params) -> list[str]:
    """One URL on every host this run will fetch from. The schedule URL redirects to
    GitHub's download host, so checking it covers both github.com and that host."""
    urls = [schedule.SCHEDULE_URL]
    if not args.offline_lines:
        urls.append(params["odds_api"]["base_url"])
    if not args.no_weather:
        urls.append(FORECAST_URL)
    return urls


def network_refusal(blocked: list[str]) -> str:
    hosts = " and ".join(blocked)
    return (f"this machine's network refuses to connect to {hosts}, so the engine cannot "
            f"fetch what it needs from there; add {hosts} to this environment's network "
            f"allowlist")


def already_started(in_tranche, kickoffs, now) -> list[str]:
    """Games in THIS run that have already kicked off.

    soonest() drops a started game's line, so the pick is withheld rather than priced --
    but only when the odds feed supplies a commence_time, and only as a side effect that
    says nothing out loud. This says it. Week 1's SF at LAR was priced off a live in-play
    line of -19.0 while SF led by twenty, banded high, and reported as a win.
    """
    out: list[str] = []
    started = []
    for g in in_tranche:
        when = kickoffs.get(frozenset((g.home, g.away)))
        if when is not None and when <= now:
            started.append((g, when))
    if not started:
        return out
    out.append(
        f"{len(started)} of {len(in_tranche)} game(s) in this tranche have already kicked "
        f"off. A line fetched now is a live price on a game in progress, not a number to "
        f"pick against, and any edge computed from one is read off the scoreboard")
    for g, when in started:
        out.append(f"  already under way: {g.away} at {g.home}, kicked off "
                   f"{when.strftime('%Y-%m-%d %H:%M UTC')}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Madden: weekly ATS picks for the office pool")
    ap.add_argument("--sheet", help="the operator's xlsx; defaults to the highest "
                                    "week number in MADDEN_SHEETS_DIR")
    ap.add_argument("--sheet-week", type=int,
                    help="use the sheet naming this week number rather than the highest")
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--week", help="week file: neutral sites, blind flags, overrides")
    ap.add_argument("--tranche", default="auto", choices=["auto", *sorted(TRANCHES)],
                    help="default auto: the earliest tranche whose first kickoff is ahead")
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

    # Runs from anywhere: every relative path resolves against the repo root, never the
    # working directory, so `python3 -m madden.run` needs no cd.
    root = Path(__file__).resolve().parent.parent
    for attr in ("params", "log", "week", "offline_lines"):
        value = getattr(args, attr)
        if value is not None:
            p = Path(value).expanduser()
            setattr(args, attr, str(p if p.is_absolute() else root / p))

    load_env()
    if args.cache and os.environ.get("CLAUDECODE") == "1":
        print("GUARDRAIL, halting: --cache reads forecasts from disk, so it is not a "
              "submittable run; refused under Claude Code", file=sys.stderr)
        return 3
    # Checks 1 and 2 run before any input is read: only code and inputs that match
    # GitHub's main may produce picks. See guard.py.
    try:
        github_warning = guard.check_repo({"--params": args.params, "--week": args.week,
                                           "--offline-lines": args.offline_lines})
    except guard.Refusal as exc:
        print(f"GUARDRAIL, halting: {exc}", file=sys.stderr)
        return 3

    params = load_yaml(args.params)
    # Every host this run needs, before anything is fetched. A proxy that refuses one
    # refuses it on every run, so the run stops and names it rather than printing a
    # board with no lines, as week 3 did from Cowork. A hiccup is not a refusal: those
    # still degrade and warn at the fetch that meets them.
    blocked = blocked_hosts(needed_urls(args, params))
    if blocked:
        print(f"GUARDRAIL, halting: {network_refusal(blocked)}", file=sys.stderr)
        return 3
    week = load_yaml(args.week) if args.week else {}
    temps = dict(week.get("temperatures", {}) or {})
    winds = dict(week.get("wind_mph", {}) or {})
    neutral = [tuple(p.split("@")) for p in (week.get("neutral_sites") or [])]
    blind_games = set(week.get("blind") or [])
    open_roofs = set(week.get("retractable_open") or [])

    notes: list[str] = []                     # run-health lines that are facts, not faults
    warnings: list[str] = [github_warning] if github_warning else []
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
        # Check 4. The sheet is the one input nobody guarantees: it only has to sit in
        # the pick'em folder, so run health names it and when it last changed.
        try:
            notes.append(guard.sheet_from_folder(sheet_path))
        except guard.Refusal as exc:
            print(f"GUARDRAIL, halting: {exc}", file=sys.stderr)
            return 3
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

    if args.tranche == "auto":
        try:
            args.tranche, why = choose_tranche(games, resolved.kickoffs,
                                               datetime.now(timezone.utc))
        except NoTrancheLeft as exc:
            print(f"TRANCHE, halting: {exc}", file=sys.stderr)
            return 3
        notes.append(why)

    line_fetch_failed = False
    try:
        lines = load_offline(args.offline_lines) if args.offline_lines else fetch_lines(params)
    except Exception as exc:                      # degrade and warn, never stop
        warnings.append(f"line fetch failed ({exc}); every game is running without a market line")
        lines = {}
        line_fetch_failed = True

    days = TRANCHES[args.tranche]
    in_tranche = [g for g in games if not days or g.day in days]

    # Absence of output, which the spec names as the most common real-world agent failure
    # and the least instrumented. Computed over the WHOLE sheet, not this tranche, because
    # the miss being looked for is in a tranche this run is not covering.
    now = datetime.now(timezone.utc)
    if not resolved.kickoffs:
        warnings.append(
            f"no kickoff times are known for this week (the week came from {resolved.source}), "
            f"so neither the missed-tranche check nor the already-kicked-off check could "
            f"run. This is not a clean result from either of them")
    else:
        deadlines = tranche_deadlines(games, resolved.kickoffs)
        unknown = [g for g in games
                   if frozenset((g.home, g.away)) not in resolved.kickoffs]
        if unknown:
            warnings.append(
                f"{len(unknown)} game(s) on the sheet have no kickoff time in the schedule, "
                f"so they count toward no tranche deadline: "
                f"{', '.join(f'{g.away} at {g.home}' for g in unknown)}")
        warnings.extend(missed_tranches(
            deadlines, logged_runs(Path(args.log), resolved.season, resolved.week), now))
        warnings.extend(already_started(in_tranche, resolved.kickoffs, now))

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
        need, no_kickoff = forecast_needs(in_tranche, temps, resolved.kickoffs)
        warnings.extend(no_kickoff)
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
                                  deviations, all_warnings, notes)
    if log_error:
        all_warnings = all_warnings + [log_error]

    print("\nRUN HEALTH")
    for n in notes:
        print(f"  {n}")
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
              all_warnings, notes=()) -> tuple[Path | None, str | None]:
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
        "health_notes": list(notes),          # the SHEET and TRANCHE lines
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
