"""Run a week.

    python -m madden.run --tranche sunday --week examples/week1-2026.yaml

The sheet is found in the configured sheets directory; --sheet overrides it.
Degrade and warn on a data fault, never stop. Halt only on a sheet fault.
Madden never submits, never contacts, never publishes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .core import make_pick, tiebreaker
from .market import fetch_lines, load_offline
from .sheet import SheetFault, parse_sheet

TRANCHES = {
    "thursday": ("Wednesday", "Thursday"),
    "international": ("Saturday",),
    "sunday": ("Saturday", "Sunday", "Monday"),
    "all": None,
}


def load_env(start: Path | None = None) -> None:
    """Read .env from the project root into os.environ. Existing vars always win.

    The key belongs in .env and nowhere else, so the program reads it rather than
    asking the operator to export it by hand every run.
    """
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
    """Find the most recent xlsx in the configured sheets directory.

    The weekly file should live in one stable place, not wherever a browser dropped it.
    """
    raw = (params.get("sheets") or {}).get("directory", "sheets")
    folder = Path(raw).expanduser()
    if not folder.is_absolute():
        folder = root / folder
    if not folder.is_dir():
        raise SheetFault(
            f"sheets directory {folder} does not exist. Create it, or point "
            f"sheets.directory in params.yaml at your Drive-synced folder.")
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
                                    "file in the sheets directory from params.yaml")
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--week", help="week file: temperatures, neutral sites, blind flags")
    ap.add_argument("--tranche", default="all", choices=sorted(TRANCHES))
    ap.add_argument("--offline-lines", help="hand-entered lines instead of the API")
    ap.add_argument("--expect", type=int, help="expected game count; mismatch is a hard stop")
    ap.add_argument("--log", default="logs", help="directory for the run log")
    args = ap.parse_args(argv)

    load_env()
    params = load_yaml(args.params)
    week = load_yaml(args.week) if args.week else {}
    temps = week.get("temperatures", {}) or {}
    winds = week.get("wind_mph", {}) or {}
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
    picks = []
    for g in games:
        if days and g.day not in days:
            continue
        key = frozenset((g.home, g.away))
        ml = lines.get(key)
        if ml is None:
            warnings.append(f"no market line for {g.away} at {g.home}")
        age = ml.age_hours() if ml else None
        if age is not None and age > params["odds_api"]["max_line_age_hours"]:
            warnings.append(f"{g.away} at {g.home}: line is {age:.1f}h old")
        picks.append(make_pick(
            g, ml.home_line if ml else None, params,
            temp_f=temps.get(g.home), retractable_open=g.home in open_roofs,
            blind=f"{g.away}@{g.home}" in blind_games))

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
        ml = lines.get(frozenset((g.home, g.away)))
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
