"""Price a whole archived season with the real engine and grade the result.

    python -m madden.backtest --archive "<season-final>.xlsx" --season 2025

Built 2026-09-20 to answer one question -- whether a coin-flip band should default to the
favorite -- and kept because of what it found on the way: it reproduces the spec's 2025
figures, which until now existed only as a claim. The spec says so itself, that the
sandbox which produced 56.9% was discarded and the number cannot be re-derived from this
repo. It can now.

WHAT IT PRICES WITH. The engine. make_pick, the real params.yaml, the real matrix. This
module supplies inputs and grades outputs; it does not reimplement any part of the
arithmetic, because a backtest that reimplements the thing it is testing measures the
reimplementation.

THREE CAVEATS, none of which this module can fix, all of which belong beside any number
it prints:

1. THE MARKET LINE IS THE CLOSING LINE. nflverse carries closing spreads and the free
   tier of the odds API does not sell history, so the drift measured here is
   frozen-sheet-to-close, not frozen-sheet-to-Sunday-morning, which is Scott's actual
   decision point. The close is later and therefore better informed, so this flatters the
   drift term by an unknown amount. The spec records the same caveat against the same
   measurement.
2. THE MATRIX IS PARTLY IN SAMPLE. Its two rules were fitted on 1999-2012 and held out on
   2013-2025, and 2025 is inside that holdout, so it is not fitted here -- but the
   thresholds and the band cutoffs were chosen after seeing seasons that include this one.
3. ONE SEASON IS NOT A RESULT. 272 picks carries a standard error near 3 points. Any two
   rules compared here should be compared on the games where they actually DIFFER, which
   is a much smaller sample than the season, and the report prints that count for exactly
   that reason.

WEATHER IS CACHED, AND THAT IS NOT THE PERISHABLE-DATA RULE BEING BROKEN. The spec forbids
writing lines, designations and forecasts to disk because a cached live number would make
the engine report no drift on the game where drift was the point. A 2025 kickoff
temperature is not perishable; it is a historical fact that cannot change. It is cached so
a rerun does not hit open-meteo 49 more times.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from .core import crosses_key_number, make_pick
from .net import urlopen
from .schedule import SCHEDULE_URL, _http
from .sheet import Game
from .teams import abbr, from_nflverse, is_dome_based, is_outdoors
from .weather import STADIUMS

ARCHIVE_TEMP_URL = "https://archive-api.open-meteo.com/v1/archive"
CACHE = Path(".cache")


class BacktestFault(Exception):
    """An input could not be read or joined. Never worked around."""


# --------------------------------------------------------------------------- inputs

def parse_archive(path: Path, weeks=range(1, 19)) -> list[dict]:
    """Read a season-final pool workbook: one tab per week, one row per game.

    This is NOT the weekly sheet format and does not go through sheet.py. The archive
    workbook the operator keeps is laid out differently -- column B the favorite, C the
    spread, D the underdog, E the score, F his own cover result -- and the live parser
    would rightly refuse it. Column F is read only as a cross-check on our own arithmetic.
    """
    try:
        import openpyxl
    except ImportError as exc:                                      # pragma: no cover
        raise BacktestFault("openpyxl is needed to read the archive workbook") from exc
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:                                        # noqa: BLE001
        raise BacktestFault(f"could not open {path}: {exc}") from exc

    out: list[dict] = []
    for week in weeks:
        tab = f"{week:02d}"
        if tab not in wb.sheetnames:
            continue
        ws = wb[tab]
        for row in range(1, ws.max_row + 1):
            fav_name, spread, dog_name, score, cover = (
                ws.cell(row, col).value for col in (2, 3, 4, 5, 6))
            if not isinstance(fav_name, str) or not isinstance(dog_name, str):
                continue
            if not isinstance(spread, (int, float)):
                continue
            try:
                favorite, underdog = abbr(fav_name), abbr(dog_name)
            except ValueError:
                continue                       # a header or a stray row, not a game
            out.append({"week": week, "favorite": favorite, "underdog": underdog,
                        "spread": float(spread), "score": score, "operator_cover": cover})
    if not out:
        raise BacktestFault(f"no games parsed out of {path}")
    return out


def load_schedule(season: int, get=None) -> dict:
    """(week, frozenset{away, home}) -> the nflverse row, for one season."""
    get = get or _http
    try:
        text = get(SCHEDULE_URL).decode("utf-8")
    except Exception as exc:                                        # noqa: BLE001
        raise BacktestFault(f"could not fetch the nflverse schedule: {exc}") from exc
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("season") != str(season) or (r.get("game_type") or "REG") != "REG":
            continue
        away, home = from_nflverse(r["away_team"]), from_nflverse(r["home_team"])
        out[(int(r["week"]), frozenset((away, home)))] = r
    if not out:
        raise BacktestFault(f"the nflverse schedule has no regular season for {season}")
    return out


def kickoff_temperature(home: str, gameday: str, gametime: str, cache: dict) -> float | None:
    """Temperature at kickoff from open-meteo's historical archive, or None.

    Hourly, indexed in Eastern time because that is the timezone the schedule's gametime
    is written in; asking open-meteo for the same timezone makes the two line up whatever
    the stadium's own offset is.
    """
    key = f"{home}|{gameday}|{gametime}"
    if key in cache:
        return cache[key]
    coords = STADIUMS.get(home)
    if not coords or not gameday or not gametime:
        cache[key] = None
        return None
    query = urllib.parse.urlencode({
        "latitude": coords[0], "longitude": coords[1],
        "start_date": gameday, "end_date": gameday,
        "hourly": "temperature_2m", "temperature_unit": "fahrenheit",
        "timezone": "America/New_York"})
    req = urllib.request.Request(f"{ARCHIVE_TEMP_URL}?{query}",
                                 headers={"User-Agent": "madden/1.0"})
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
        idx = payload["hourly"]["time"].index(f"{gameday}T{gametime[:2]}:00")
        cache[key] = payload["hourly"]["temperature_2m"][idx]
    except Exception:                                               # noqa: BLE001
        cache[key] = None                      # the rule then does not fire, and says so
    time.sleep(0.1)
    return cache[key]


def needs_temperature(home: str, away: str, neutral: bool) -> bool:
    """Only the games the 75F rule could possibly fire on are worth a fetch."""
    return not neutral and is_outdoors(home) and is_dome_based(away)


# --------------------------------------------------------------------------- pricing

def price_season(archive, schedule, params, temps: dict) -> tuple[list[dict], list[str]]:
    rows, skipped = [], []
    for g in archive:
        key = (g["week"], frozenset((g["favorite"], g["underdog"])))
        r = schedule.get(key)
        if r is None:
            skipped.append(f"week {g['week']} {g['favorite']}/{g['underdog']}: "
                           f"no such game in the nflverse schedule")
            continue
        home, away = from_nflverse(r["home_team"]), from_nflverse(r["away_team"])
        # Venue from the schedule, never from the operator's capitalisation. The spec is
        # explicit, and the 2025 archive disagrees with the schedule on two games.
        neutral = (r.get("location") or "Home") != "Home"
        spread_line = (r.get("spread_line") or "").strip()
        home_score, away_score = (r.get("home_score") or "").strip(), (r.get("away_score") or "").strip()
        if not spread_line:
            skipped.append(f"week {g['week']} {away} at {home}: no closing spread")
            continue
        if not home_score or not away_score:
            skipped.append(f"week {g['week']} {away} at {home}: no final score")
            continue

        game = Game(favorite=g["favorite"], underdog=g["underdog"], spread=g["spread"],
                    day="Sunday", nominal_home=home, row=0)
        game.neutral_site = neutral
        temp = temps.get(f"{home}|{r.get('gameday')}|{r.get('gametime')}")
        pick = make_pick(game, float(spread_line), params, temp_f=temp)

        margin = int(home_score) - int(away_score)
        sheet_line = game.sheet_home_line
        if margin == sheet_line:
            skipped.append(f"week {g['week']} {away} at {home}: push on {sheet_line:+.1f}")
            continue
        covered = home if margin > sheet_line else away
        favorite = home if sheet_line > 0 else away

        operator = None
        if g["operator_cover"] in ("F", "U"):
            operator = g["favorite"] if g["operator_cover"] == "F" else g["underdog"]

        # Which key number, if any, the number stepped across. Recomputed rather than
        # carried out of make_pick because the Pick does not keep it, and the two reasons
        # a game lands in the high band are the question being asked of this data.
        key = None
        if pick.madden_number is not None:
            key = crosses_key_number(pick.madden_number, sheet_line,
                                     params["bands"]["key_numbers"])

        rows.append({"week": g["week"], "away": away, "home": home, "neutral": neutral,
                     "sheet_line": sheet_line, "market_line": float(spread_line),
                     "adjustment": pick.adjustment_total, "edge": pick.edge,
                     "side": pick.side, "band": pick.band, "margin": margin,
                     "key": key, "favorite": favorite, "covered": covered,
                     "operator": operator})
    return rows, skipped


# --------------------------------------------------------------------------- variants

def as_built(r) -> str | None:
    """The engine as it stands: the side is the sign of the edge, whatever the band."""
    return r["side"]


def coin_flip_takes_the_favorite(r) -> str | None:
    """The alternative under test: below the method's own threshold, take the base rate."""
    if r["side"] is None:
        return None
    return r["favorite"] if r["band"] == "coin flip" else r["side"]


def score(rows, rule) -> tuple[int, int]:
    live = [r for r in rows if rule(r) is not None]
    return sum(rule(r) == r["covered"] for r in live), len(live)


def head_to_head(rows, a, b) -> dict:
    """Compare two rules only where they disagree, which is the only sample that informs.

    Comparing them across the whole season buries the difference under the games they
    agree on and makes a small effect look like a large one.
    """
    differ = [r for r in rows if a(r) is not None and b(r) is not None and a(r) != b(r)]
    a_hits = sum(a(r) == r["covered"] for r in differ)
    n = len(differ)
    # Standard error on the count, under the null that each disagreement is a coin toss.
    se = (n * 0.25) ** 0.5 if n else 0.0
    return {"n": n, "a": a_hits, "b": n - a_hits, "se": se,
            "z": ((a_hits - n / 2) / se) if se else 0.0}


# --------------------------------------------------------------------------- reporting

def rec(pair) -> str:
    w, n = pair
    return f"{w}-{n - w}  ({w / n:.1%}) of {n}" if n else "none"


def market_side(r) -> str:
    return r["home"] if r["market_line"] > r["sheet_line"] else r["away"]


# Drift buckets for the market-side rule. Lines move in half points, so these are the
# only gaps that exist. The 2.0+ row is printed as its own line as well, because that is
# the cut the spec quotes a figure against.
DRIFT_BUCKETS = ((0.5, 1.0, "0.5"), (1.0, 2.0, "1.0-1.5"),
                 (2.0, 3.0, "2.0-2.5"), (3.0, float("inf"), "3.0+"))


def high_band_split(rows, params) -> tuple[list, list]:
    """The high band holds two different populations under one label.

    A pick is high either because the edge is large, or because a small edge steps across
    3, 7, 10 or 14. Those are not the same claim: one says the number moved a lot, the
    other says it moved very little but across the part of the distribution where a half
    point is worth several points elsewhere. Graded together they cannot contradict each
    other, which is the only reason the label survived this long unexamined.
    """
    threshold = params["bands"]["high_points"]
    high = [r for r in rows if r["band"] == "high" and r["edge"] is not None]
    by_magnitude = [r for r in high if abs(r["edge"]) >= threshold]
    by_key = [r for r in high if abs(r["edge"]) < threshold]
    return by_magnitude, by_key


def report(rows, skipped, season, params) -> list[str]:
    out = [f"BACKTEST  season {season}  games priced {len(rows)}", ""]

    disagree = [r for r in rows if r["operator"] and r["operator"] != r["covered"]]
    out.append("CROSS-CHECK")
    out.append(f"  our cover side vs the operator's own result column: "
               f"{len(rows) - len(disagree)}/{len(rows)} agree")
    for r in disagree[:10]:
        out.append(f"  ! week {r['week']} {r['away']} at {r['home']}: we say "
                   f"{r['covered']}, his sheet says {r['operator']}")

    out += ["", "BASELINES"]
    out.append(f"  take every favorite   {rec(score(rows, lambda r: r['favorite']))}")
    out.append(f"  every home team       {rec(score(rows, lambda r: r['home']))}")
    mkt = [r for r in rows if abs(r["market_line"] - r["sheet_line"]) > 1e-9]
    out.append(f"  market side vs sheet  {rec(score(mkt, market_side))}")
    mx = [r for r in rows if abs(r["adjustment"]) > 1e-9]
    out.append(f"  situational matrix    "
               f"{rec(score(mx, lambda r: r['home'] if r['adjustment'] > 0 else r['away']))}")

    out += ["", "THE ENGINE AS BUILT"]
    out.append(f"  all games             {rec(score(rows, as_built))}")
    for band in ("high", "medium", "coin flip", "blind"):
        s = [r for r in rows if r["band"] == band]
        if s:
            out.append(f"  {band:<22}{rec(score(s, as_built))}")
    dev = [r for r in rows if r["side"] and r["side"] != r["favorite"]]
    out.append(f"  deviations from favorite  {rec(score(dev, as_built))}")

    by_magnitude, by_key = high_band_split(rows, params)
    out += ["", "THE HIGH BAND, SPLIT  (two populations under one label)"]
    out.append(f"  high by magnitude, edge >= {params['bands']['high_points']}   "
               f"{rec(score(by_magnitude, as_built))}")
    out.append(f"  high by key-number crossing only  {rec(score(by_key, as_built))}")
    both = [r for r in by_magnitude if r["key"] is not None]
    out.append(f"  (of the magnitude group, {len(both)} also cross a key number; the "
               f"magnitude branch claims them first)")
    keys: dict = {}
    for r in by_key:
        w, n = keys.get(r["key"], (0, 0))
        keys[r["key"]] = (w + (r["side"] == r["covered"]), n + 1)
    for k in sorted(keys):
        out.append(f"    across {k:<3} {rec(keys[k])}")

    out += ["", "MARKET SIDE BY DRIFT SIZE  (the rule alone, matrix ignored)"]
    for lo, hi, label in DRIFT_BUCKETS:
        bucket = [r for r in rows
                  if lo - 1e-9 <= abs(r["market_line"] - r["sheet_line"]) < hi]
        out.append(f"  drift {label:<9} {rec(score(bucket, market_side))}")
    two_plus = [r for r in rows if abs(r["market_line"] - r["sheet_line"]) >= 2.0 - 1e-9]
    out.append(f"  drift 2.0+      {rec(score(two_plus, market_side))}"
               f"   <- the spec quotes 66.7% (28-14) here")
    flat = [r for r in rows if abs(r["market_line"] - r["sheet_line"]) < 1e-9]
    out.append(f"  no drift: {len(flat)} game(s), no market side, not scored above")

    out += ["", "VARIANT: a coin flip takes the favorite instead of the edge side"]
    out.append(f"  all games             {rec(score(rows, coin_flip_takes_the_favorite))}")
    h = head_to_head(rows, as_built, coin_flip_takes_the_favorite)
    out.append(f"  head to head, on the {h['n']} games where the two rules differ:")
    out.append(f"    as built {h['a']}, favorite {h['b']}, "
               f"standard error {h['se']:.1f} games, z = {h['z']:+.2f}")

    out += ["", "SPLIT HALF  (one season is not a result; a half season is less of one)"]
    for lo, hi in ((1, 9), (10, 18)):
        s = [r for r in rows if lo <= r["week"] <= hi]
        if s:
            out.append(f"  weeks {lo}-{hi}: as built {rec(score(s, as_built))}   "
                       f"variant {rec(score(s, coin_flip_takes_the_favorite))}")

    if skipped:
        out += ["", "NOT PRICED"]
        out += [f"  ! {s}" for s in skipped[:20]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Price an archived season with the engine and grade it")
    ap.add_argument("--archive", required=True,
                    help="the operator's season-final xlsx, one tab per week")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--params", default="params.yaml")
    ap.add_argument("--no-weather", action="store_true",
                    help="skip the temperature fetch; the 75F rule then cannot fire")
    args = ap.parse_args(argv)

    params = yaml.safe_load(Path(args.params).read_text())
    try:
        archive = parse_archive(Path(args.archive).expanduser())
        schedule = load_schedule(args.season)
    except BacktestFault as exc:
        print(f"BACKTEST FAULT: {exc}", file=sys.stderr)
        return 2

    cache_file = CACHE / f"backtest-temps-{args.season}.json"
    temps: dict = {}
    if cache_file.is_file():
        try:
            temps = json.loads(cache_file.read_text())
        except ValueError:
            temps = {}
    if not args.no_weather:
        wanted = []
        for g in archive:
            r = schedule.get((g["week"], frozenset((g["favorite"], g["underdog"]))))
            if r is None:
                continue
            home, away = from_nflverse(r["home_team"]), from_nflverse(r["away_team"])
            neutral = (r.get("location") or "Home") != "Home"
            if needs_temperature(home, away, neutral):
                wanted.append((home, r.get("gameday"), r.get("gametime")))
        todo = [w for w in wanted if f"{w[0]}|{w[1]}|{w[2]}" not in temps]
        if todo:
            print(f"fetching {len(todo)} kickoff temperature(s)...", flush=True)
        for home, day, tm in todo:
            kickoff_temperature(home, day, tm, temps)
        try:
            CACHE.mkdir(exist_ok=True)
            cache_file.write_text(json.dumps(temps))
        except OSError:
            pass                                # a cache that cannot be written is fine

    rows, skipped = price_season(archive, schedule, params, temps)
    if not rows:
        print("BACKTEST FAULT: nothing could be priced", file=sys.stderr)
        return 2
    print("\n".join(report(rows, skipped, args.season, params)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
