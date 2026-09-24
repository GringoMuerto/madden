"""Grade a run log against final scores.

    python -m madden.grade logs/run-20260913T164534Z-sunday.json

Built 2026-09-20. Until then the README listed the backtest harness as not built and week
1 was graded by hand over the log and a downloaded score file. Hand grading is fine once
and useless as an instrument: the spec wants the baselines graded EVERY week, and a
measurement that takes a person an hour is one that stops happening in October.

What it does not do: fetch a line, price a game, or change a pick. It reads a log that the
engine already wrote and joins it to results. Every number it prints is either in that log
already or is arithmetic over the log and the scoreboard.

Scores come from nflverse, which is the spec's schedule source and carries the final score
in the same file. The odds API also has a scores endpoint; it is not used here because it
costs a credit per call and drops games after a few days, so it cannot grade a season.

THE REVERT RULE IS NOT COSMETIC. A game the engine withheld a pick on is not an
abstention: the pool scores it as the favorite. So two records are reported. "Picks made"
is the engine's own work. "As submitted" is what actually lands in the pool, reverts
included, and it is the one that pays.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .schedule import SCHEDULE_URL, _http, kickoff_at
from .teams import from_nflverse


class GradeFault(Exception):
    """The log and the scoreboard could not be joined. Never graded around."""


def load_results(get=None) -> dict:
    """(season, week, away, home) -> (away_score, home_score). Regular season only."""
    return load_schedule(get)[0]


def load_schedule(get=None) -> tuple[dict, dict]:
    """(final scores, kickoffs), both keyed (season, week, away, home). Regular season.

    Kickoffs are for grading by how long before kickoff each pick was made: since
    2026-09-24 every run prices every open game, so a game may be priced days out or
    the morning of, and the spec asks whether the later pick grades better.
    """
    get = get or _http
    try:
        text = get(SCHEDULE_URL).decode("utf-8")
    except Exception as exc:                                        # noqa: BLE001
        raise GradeFault(
            f"could not fetch the nflverse schedule, so there are no final scores to "
            f"grade against ({type(exc).__name__}: {exc}).") from exc

    out: dict = {}
    kickoffs: dict = {}
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("game_type") or "REG") != "REG":
            continue
        try:
            season, week = int(r["season"]), int(r["week"])
        except (KeyError, TypeError, ValueError):
            continue
        away, home = from_nflverse(r.get("away_team", "")), from_nflverse(r.get("home_team", ""))
        when = kickoff_at(r.get("gameday", ""), r.get("gametime", ""))
        if when is not None:
            kickoffs[(season, week, away, home)] = when
        a, h = (r.get("away_score") or "").strip(), (r.get("home_score") or "").strip()
        if not a or not h:
            continue                                    # not played yet; skipped, not zero
        try:
            out[(season, week, away, home)] = (int(float(a)), int(float(h)))
        except ValueError:
            continue
    return out, kickoffs


# How long before kickoff a game was priced. Three bands, chosen so a Wednesday run, a
# Friday or Saturday run, and a game-day run each land in their own.
LEAD_BANDS = (("under 24 hours", 0, 24), ("1 to 3 days", 24, 72), ("3 days or more", 72, None))


def lead_band(hours: float | None) -> str | None:
    if hours is None:
        return None
    for name, lo, hi in LEAD_BANDS:
        if hours >= lo and (hi is None or hours < hi):
            return name
    return None


def run_time(log) -> datetime | None:
    try:
        return datetime.strptime(str(log.get("run")), "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def resolve_week(log, results) -> tuple[int, int]:
    """The log's own season and week, or the one its pairings match.

    Older logs carry season: null -- the thursday tranche of week 1 does. Guessing would
    grade a board against the wrong week's scores and produce a number that looks fine, so
    an unresolvable log raises instead.
    """
    if log.get("season") and log.get("week"):
        return int(log["season"]), int(log["week"])

    wanted = {frozenset(p["game"].split("@")) for p in log.get("picks", [])}
    if not wanted:
        raise GradeFault("this log has no picks in it")
    tally: dict = {}
    for (season, week, away, home) in results:
        if frozenset((away, home)) in wanted:
            tally[(season, week)] = tally.get((season, week), 0) + 1
    if not tally:
        raise GradeFault(
            "this log records no season or week, and none of its games appear in the "
            "schedule, so which week it covers cannot be established. Not guessed at.")
    best = max(tally.values())
    hits = [k for k, v in tally.items() if v == best]
    if len(hits) > 1:
        where = ", ".join(f"{s} week {w}" for s, w in sorted(hits))
        raise GradeFault(
            f"this log records no season or week and its games match {len(hits)} weeks "
            f"equally well ({where}). Name it with --season and --week.")
    return hits[0]


def grade_log(log, results, season=None, week=None, kickoffs=None) -> dict:
    """Join a run log to final scores. Returns rows plus the records."""
    if season is None or week is None:
        season, week = resolve_week(log, results)
    ran = run_time(log)

    rows, ungraded = [], []
    for p in log.get("picks", []):
        away, home = p["game"].split("@")
        final = results.get((season, week, away, home))
        if final is None:
            ungraded.append(f"{p['game']}: no final score in the schedule for "
                            f"{season} week {week}")
            continue
        ascore, hscore = final
        margin = hscore - ascore
        shl = float(p["sheet_line"])
        favorite = home if shl > 0 else away
        if margin == shl:
            # The operator sets half points so nothing pushes. If one ever does, it is
            # said out loud rather than silently scored as a win or a loss.
            ungraded.append(f"{p['game']}: margin {margin:+d} landed exactly on the sheet "
                            f"line {shl:+.1f}, a push. Not scored.")
            continue
        covered = home if margin > shl else away

        kick = (kickoffs or {}).get((season, week, away, home))
        hours = (kick - ran).total_seconds() / 3600 if kick and ran else None

        pick = p.get("pick")
        reverted = pick is None
        submitted = favorite if reverted else pick
        rows.append({
            "game": p["game"], "away": away, "home": home,
            "away_score": ascore, "home_score": hscore, "margin": margin,
            "sheet_line": shl, "market_line": p.get("market_line"),
            "favorite": favorite, "covered": covered,
            "pick": pick, "submitted": submitted, "reverted": reverted,
            "band": p.get("band", "?"),
            "deviation": bool(p.get("deviation")),
            "pick_hit": (None if reverted else pick == covered),
            "submitted_hit": submitted == covered,
            "favorite_hit": favorite == covered,
            "hours_before": hours, "lead": lead_band(hours),
        })

    made = [r for r in rows if not r["reverted"]]
    deviations = [r for r in made if r["deviation"]]
    bands: dict = {}
    for r in made:
        w, n = bands.get(r["band"], (0, 0))
        bands[r["band"]] = (w + bool(r["pick_hit"]), n + 1)

    leads: dict = {}
    for r in made:
        if r["lead"] is None:
            continue
        w, n = leads.get(r["lead"], (0, 0))
        leads[r["lead"]] = (w + bool(r["pick_hit"]), n + 1)

    # The market side relative to the sheet: the spec's third baseline, and the engine's
    # primary input stripped of all computation. A game with no drift has no market side
    # and is left out rather than scored as a coin flip.
    mkt_w = mkt_n = 0
    for r in made:
        if r["market_line"] is None:
            continue
        drift = float(r["market_line"]) - r["sheet_line"]
        if abs(drift) < 1e-9:
            continue
        mkt_n += 1
        mkt_w += (r["home"] if drift > 0 else r["away"]) == r["covered"]

    return {
        "season": season, "week": week, "tranche": log.get("tranche"),
        "run": log.get("run"), "rows": rows, "ungraded": ungraded,
        "madden": (sum(bool(r["pick_hit"]) for r in made), len(made)),
        "submitted": (sum(r["submitted_hit"] for r in rows), len(rows)),
        "favorite": (sum(r["favorite_hit"] for r in rows), len(rows)),
        "deviations": (sum(bool(r["pick_hit"]) for r in deviations), len(deviations)),
        "bands": bands, "leads": leads,
        "market_side": (mkt_w, mkt_n),
        "reverts": [r for r in rows if r["reverted"]],
    }


def record(pair) -> str:
    w, n = pair
    if not n:
        return "  none"
    return f"{w}-{n - w}  ({w / n:.1%}) of {n}"


def report(g) -> list[str]:
    out = [f"GRADED  {g['season']} week {g['week']}  tranche={g['tranche']}  run={g['run']}",
           ""]
    out.append(f"{'GAME':<12}{'FINAL':<16}{'MARGIN':>7}{'SHEET':>7}  "
               f"{'FAV':<5}{'PICK':<6}{'COVER':<6}{'BAND':<11}{'DEV':<5}RESULT")
    for r in g["rows"]:
        final = f"{r['away']} {r['away_score']}-{r['home_score']} {r['home']}"
        pick = r["pick"] or "--"
        if r["reverted"]:
            result = f"{'WIN' if r['submitted_hit'] else 'LOSS'} (reverted to {r['favorite']})"
        else:
            result = "WIN" if r["pick_hit"] else "LOSS"
        out.append(f"{r['game']:<12}{final:<16}{r['margin']:>+7d}{r['sheet_line']:>+7.1f}  "
                   f"{r['favorite']:<5}{pick:<6}{r['covered']:<6}{r['band']:<11}"
                   f"{'yes' if r['deviation'] else '-':<5}{result}")

    out += ["", "RECORDS"]
    out.append(f"  Madden, picks made      {record(g['madden'])}")
    out.append(f"  Madden, as submitted    {record(g['submitted'])}")
    if g["reverts"]:
        out.append(f"    includes {len(g['reverts'])} game(s) with no pick, reverted to the "
                   f"favorite: {', '.join(r['game'] for r in g['reverts'])}")
    out.append(f"  Take every favorite     {record(g['favorite'])}")
    out.append(f"  Deviations from it      {record(g['deviations'])}")
    out.append(f"  Market side vs sheet    {record(g['market_side'])}")

    out += ["", "BY BAND  (picks made only)"]
    for band in ("high", "medium", "coin flip", "blind"):
        if band in g["bands"]:
            out.append(f"  {band:<12}{record(g['bands'][band])}")
    for band, pair in sorted(g["bands"].items()):
        if band not in ("high", "medium", "coin flip", "blind"):
            out.append(f"  {band:<12}{record(pair)}")

    if g.get("leads"):
        out += ["", "BY TIME BEFORE KICKOFF  (picks made only; one run, so this compares its "
                    "early and late games)"]
        for name, _, _ in LEAD_BANDS:
            if name in g["leads"]:
                out.append(f"  {name:<16}{record(g['leads'][name])}")

    if g["ungraded"]:
        out += ["", "NOT GRADED"]
        out += [f"  ! {u}" for u in g["ungraded"]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Grade a Madden run log against final scores")
    ap.add_argument("log", help="a run log written by python -m madden.run")
    ap.add_argument("--season", type=int, help="override the log's season")
    ap.add_argument("--week", type=int, help="override the log's week")
    args = ap.parse_args(argv)

    try:
        log = json.loads(Path(args.log).read_text())
    except (OSError, ValueError) as exc:
        print(f"could not read {args.log}: {exc}", file=sys.stderr)
        return 2

    try:
        results, kickoffs = load_schedule()
        graded = grade_log(log, results, season=args.season, week=args.week,
                           kickoffs=kickoffs)
    except GradeFault as exc:
        print(f"GRADE FAULT: {exc}", file=sys.stderr)
        return 2

    print("\n".join(report(graded)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
