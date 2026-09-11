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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .core import make_pick, tiebreaker
from .injuries import fetch_all, game_confidence, summarise
from .market import fetch_lines, load_offline, soonest
from .sheet import SheetFault, parse_sheet
from .weather import forecast_many

TRANCHES = {
    "thursday": ("Wednesday", "Thursday"),
    "international": ("Saturday",),
    "sunday": ("Saturday", "Sunday", "Monday"),
    "all": None,
}


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


def newest_sheet(params, root: Path) -> Path:
    """Find the most recent xlsx in the configured sheets directory."""
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
    return max(found, key=lambda f: f.stat().st_mtime)


def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Madden: weekly ATS picks for the office pool")
    ap.add_argument("--sheet", help="the operator's xlsx; defaults to the newest "
                                    "file in MADDEN_SHEETS_DIR")
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--week", help="week file: neutral sites, blind flags, overrides")
    ap.add_argument("--tranche", default="all", choices=sorted(TRANCHES))
    ap.add_argument("--offline-lines", help="hand-entered lines instead of the API")
    ap.add_argument("--expect", type=int, help="expected game count; mismatch is a hard stop")
    ap.add_argument("--log", default="logs", help="directory for the run log")
    ap.add_argument("--no-injuries", action="store_true", help="skip the injury fetch")
    ap.add_argument("--no-weather", action="store_true", help="skip the forecast fetch")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the disk cache and refetch everything")
    args = ap.parse_args(argv)

    load_env()
    params = load_yaml(args.params)
    week = load_yaml(args.week) if args.week else {}
    temps = dict(week.get("temperatures", {}) or {})
    winds = dict(week.get("wind_mph", {}) or {})
    neutral = [tuple(p.split("@")) for p in (week.get("neutral_sites") or [])]
    blind_games = set(week.get("blind") or [])
    open_roofs = set(week.get("retractable_open") or [])

    try:
        sheet_path = Path(args.sheet).expanduser() if args.sheet else newest_sheet(
            params, Path(__file__).resolve().parent.parent)
        print(f"sheet: {sheet_path}")
        games = parse_sheet(str(sheet_path), expected_games=args.expect,
                            neutral_sites=neutral)
    except SheetFault as exc:
        print(f"SHEET FAULT, halting: {exc}", file=sys.stderr)
        return 2

    warnings: list[str] = []
    try:
        lines = load_offline(args.offline_lines) if args.offline_lines else fetch_lines(params)
    except Exception as exc:                      # degrade and warn, never stop
        warnings.append(f"line fetch failed ({exc}); every game is running without a market line")
        lines = {}

    days = TRANCHES[args.tranche]
    in_tranche = [g for g in games if not days or g.day in days]

    # Injuries. On by default: an input that silently does not exist is the failure
    # this run-health block exists for. One league-wide call, cached for an hour.
    reports: dict = {}
    if args.no_injuries:
        warnings.append("injury fetch skipped by --no-injuries: nothing in this run "
                        "reflects availability except through the market line")
    else:
        print("fetching injury designations...", flush=True)
        try:
            reports = fetch_all([t for g in in_tranche for t in (g.home, g.away)],
                                use_cache=not args.fresh)
            warnings.extend(summarise(reports))
        except Exception as exc:                  # noqa: BLE001
            warnings.append(f"INJURY FETCH FAILED ({exc}): nothing in this run reflects "
                            f"availability except through the market line")

    # Weather, for outdoor games with no temperature already supplied. The week file
    # always wins: a value someone entered deliberately beats a forecast.
    if args.no_weather:
        warnings.append("forecast skipped by --no-weather: temperature rules cannot fire")
    else:
        need = []
        for g in in_tranche:
            if g.home in temps or getattr(g, "neutral", False):
                continue
            ml, _ = soonest(lines, g.home, g.away)
            kickoff = ml.starts_at() if ml else None
            if kickoff is not None:
                need.append((g.home, kickoff))
        if need:
            print(f"fetching forecasts for {len(need)} stadiums...", flush=True)
            got_t, got_w, w_warn = forecast_many(need)
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

        # A status finding lowers confidence in this game's number. Under the spec it can
        # never flip a pick, so it is reported and carried, never applied to the edge.
        penalty, reasons = game_confidence(reports, g.home, g.away) if reports else (0.0, [])
        force_blind = penalty >= params.get("injuries", {}).get("blind_threshold", 0.9)

        pick = make_pick(
            g, ml.line_for(g.home) if ml else None, params,
            temp_f=temps.get(g.home), retractable_open=g.home in open_roofs,
            blind=(f"{g.away}@{g.home}" in blind_games) or force_blind)
        for r in reasons:
            pick.warnings.append(r)
        picks.append(pick)

    submittable = [p for p in picks if p.side]
    handbacks = [p for p in picks if p.blind or p.side is None]
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
                  f"{'--':<5}{'blind':<11}line missing")
            continue
        print(f"{name:<26}{g.sheet_home_line:>7.1f}{p.market_home_line:>7.1f}"
              f"{p.adjustment_total:>7.1f}{p.madden_number:>7.1f}{p.edge:>7.1f}  "
              f"{p.side:<5}{p.band:<11}{p.drivers[0]}")

    if handbacks:
        print("\nHANDBACKS (each still carries a lean, so the sheet is always submittable)")
        for p in handbacks:
            g = p.game
            print(f"  {g.away} at {g.home}: {'; '.join(p.warnings) or 'flagged'}")

    monday = [p for p in picks if p.game.day == "Monday"]
    if monday:
        g = monday[0].game
        ml = market_lines.get((g.home, g.away))
        tb = tiebreaker(ml.total if ml else None, params, wind_mph=winds.get(g.home))
        print(f"\nTIEBREAKER  {g.away} at {g.home} combined score: {tb['guess']}")
        print(f"  {tb['reason']}")

    all_warnings = warnings + [w for p in picks for w in p.warnings]
    if all_warnings:
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
        "spec_version": params["spec_version"],
        "deviations": len(deviations),
        "injuries_fetched": sorted(t for t, r in reports.items() if r.fetched),
        "injuries_failed": sorted(t for t, r in reports.items() if not r.fetched),
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
