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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .core import make_pick, tiebreaker
from . import injuries
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


def guard_inputs(paths, cache: bool) -> str | None:
    """Under Claude Code, refuse any input this process could have written.

    The sandbox makes the engine, parameters, week files and sheets read-only to
    anything Claude runs. A writable input means the session started outside
    ~/dev/madden and the sandbox never loaded, or the file was made in this session.
    Either way the board would not be the engine's own.
    """
    if os.environ.get("CLAUDECODE") != "1":
        return None
    if cache:
        return "--cache reads files this session can write; refused under Claude Code"
    for p in filter(None, paths):
        try:
            fd = os.open(p, os.O_WRONLY | os.O_APPEND)   # no O_CREAT: creates nothing
        except OSError:
            continue
        os.close(fd)
        return (f"{p} is writable by this process: the guardrails are not loaded or the "
                f"file was made in this session. Start Claude Code in ~/dev/madden, or run "
                f"the engine from a terminal outside Claude Code.")
    return None


NO_LINE_PLAYED = "already played"
NO_LINE_FETCH_FAILED = "fetch failed"
NO_LINE_ABSENT = "not in the feed"


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
        games = parse_sheet(str(sheet_path), expected_games=args.expect,
                            neutral_sites=neutral)
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
    elif not (week.get("season") and week.get("week")):
        warnings.append("the week file names no season and week, so the injury report "
                        "cannot be matched to this slate: exposure is UNKNOWN for every game")
    else:
        print("fetching the official injury report and depth chart...", flush=True)
        report, inj_warnings = injuries.fetch(int(week["season"]), int(week["week"]))
        warnings.extend(inj_warnings)
        if report.error:
            warnings.append(injuries.header(report))

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
    unpriced = [p for p in picks if p.side is None]
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
            print(f"{name:<26}{g.sheet_home_line:>7.1f}{'--':>7}{'--':>7}{'--':>7}{'--':>7}  "
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
        clear = []
        for p in picks:
            g = p.game
            names, unknown = injuries.exposure(report, g.home, g.away)
            exposure_log[f"{g.away}@{g.home}"] = {"names": names, "unknown": unknown}
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
    print("\nRUN HEALTH")
    for w in dict.fromkeys(all_warnings):
        print(f"  ! {w}")
    if params["power_rating"]["enabled"] is False:
        print("  ! power rating layer disabled: the model term is zero, so every number here "
              "is the market plus the situational matrix and nothing else")

    logdir = Path(args.log)
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "run": stamp, "tranche": args.tranche, "sheet": str(sheet_path),
        "sheet_week": week_of(sheet_path),
        "spec_version": params["spec_version"],
        "deviations": len(deviations),
        "injury_report": ({"built": report.built, "depth_as_of": report.depth_as_of,
                           "error": report.error, "depth_error": report.depth_error}
                          if report else None),
        "exposure": exposure_log,
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
    path = logdir / f"run-{stamp}-{args.tranche}.json"
    path.write_text(json.dumps(record, indent=2))
    print(f"\nlogged to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
