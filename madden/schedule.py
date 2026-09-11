"""Which season and week this sheet is, derived from the games printed on it.

NOT from the filename. The operator numbers his files from zero -- `NFL2026w0.xlsx` is
NFL week 1 -- while the sheet's own tab name and title row both say Week 01. A week taken
from the filename is therefore off by one against a convention observed on exactly one
file. That is a guess with a fact's confidence, which is the error the Evidence Ledger
exists to catch.

NOT from the current date either. The sheet freezes Tuesday and is run from Thursday
through Monday, and a Tuesday snapshot run prices the sheet for the week ahead. Date
arithmetic lands right most weeks and silently wrong at the boundary -- the same failure
shape that stopped the engine choosing sheets by timestamp.

From the matchups. nflverse publishes the season schedule; a full slate of pairings
identifies exactly one week of it, and it does so without caring what the file is called,
what day it is, or which side the operator capitalised. Pairs are matched unordered, so a
neutral site cannot mislead the match the way it misleads the ALL CAPS convention.

The filename week survives as a cross-check only, exactly like ALL CAPS: a disagreement is
reported, never obeyed.

A sheet matching no week HALTS. That is not a new halting condition -- it is the one
`sheet.py` already documents, a sheet that does not match the slate. Nothing downstream may
run with an unresolved week, because the injury report is keyed on season and week and a
wrong week is the quietest failure in the engine: it fetches cleanly, returns an empty
slice, and reports every team UNKNOWN without raising a single warning.
"""

from __future__ import annotations

import csv
import io
import math
import urllib.request
from dataclasses import dataclass

from .net import urlopen
from .sheet import SheetFault
from .teams import from_nflverse

RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
SCHEDULE_URL = f"{RELEASES}/schedules/games.csv"
TIMEOUT = 60

# A correct week matches every game on the sheet. The margin below that is for a schedule
# file rebuilt mid-relocation or a pairing nflverse spells differently, not for a sheet
# that is nearly right: a near miss on a full slate means something is wrong, and the
# engine would rather halt than price a board against the wrong week's injury report.
MIN_MATCH_FRACTION = 0.75


@dataclass
class Resolution:
    season: int
    week: int
    matched: int              # sheet games found in that week of the schedule
    total: int                # games on the sheet
    opens: str = ""           # first gameday in the resolved week
    closes: str = ""          # last gameday
    source: str = "nflverse schedule"

    def __str__(self) -> str:
        span = f", {self.opens} to {self.closes}" if self.opens else ""
        return (f"season {self.season} week {self.week} "
                f"({self.matched}/{self.total} games matched the {self.source}{span})")


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "madden/1.0"})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _by_week(rows) -> dict:
    """(season, week) -> {frozenset({away, home}): gameday}. Regular season only."""
    out: dict = {}
    for r in rows:
        if (r.get("game_type") or "REG") != "REG":
            continue
        try:
            key = (int(r["season"]), int(r["week"]))
        except (KeyError, TypeError, ValueError):
            continue
        away = from_nflverse(r.get("away_team", ""))
        home = from_nflverse(r.get("home_team", ""))
        if not away or not home:
            continue
        out.setdefault(key, {})[frozenset((away, home))] = (r.get("gameday") or "")
    return out


def resolve(games, get=None) -> Resolution:
    """Work out which season and week these games are. Raises SheetFault if it cannot.

    `games` are sheet.Game objects; only their two team abbreviations are used, so the
    operator's capitalisation and any neutral site are irrelevant here.
    """
    get = get or _http
    try:
        text = get(SCHEDULE_URL).decode("utf-8")
    except Exception as exc:                                        # noqa: BLE001
        raise SheetFault(
            f"could not fetch the nflverse schedule, so which week this sheet covers is "
            f"unknown ({type(exc).__name__}: {exc}). The injury report is keyed on season "
            f"and week, and a wrong week fetches cleanly and reports every team UNKNOWN "
            f"with no warning. Halting rather than printing a board with a dark exposure "
            f"layer. To run anyway, put `season:` and `week:` in a week file and pass "
            f"--week; that overrides this lookup entirely.") from exc

    by_week = _by_week(csv.DictReader(io.StringIO(text)))
    wanted = [frozenset((g.favorite, g.underdog)) for g in games]
    if not wanted:
        raise SheetFault("no games to resolve a week from")

    scored = sorted(((sum(1 for p in wanted if p in pairs), key)
                     for key, pairs in by_week.items()), reverse=True)
    if not scored:
        raise SheetFault(
            "the nflverse schedule parsed to no weeks at all. Its format may have changed; "
            "do not guess at the week.")

    best, key = scored[0]
    need = max(1, math.ceil(MIN_MATCH_FRACTION * len(wanted)))

    if best < need:
        near = ", ".join(f"{s}w{w} matched {h}" for h, (s, w) in scored[:3] if h)
        raise SheetFault(
            f"these {len(wanted)} games match no week of the nflverse schedule "
            f"(best was {best}, and {need} are needed). "
            + (f"Closest: {near}. " if near else "")
            + "This sheet does not describe a real slate, or the team names on it did not "
              "resolve the way the schedule spells them. Halting rather than pricing a "
              "board against a week that is not this one.")

    tied = [k for h, k in scored if h == best]
    if len(tied) > 1:
        where = ", ".join(f"{s} week {w}" for s, w in sorted(tied))
        raise SheetFault(
            f"these games match {len(tied)} different weeks equally well ({where}). "
            f"The week is ambiguous and nothing downstream may guess at it. Name the week "
            f"in a week file with `season:` and `week:` and pass --week.")

    season, week = key
    days = sorted(d for d in by_week[key].values() if d)
    return Resolution(season=season, week=week, matched=best, total=len(wanted),
                      opens=days[0] if days else "", closes=days[-1] if days else "")


def confirm(season: int, week: int, games, get=None) -> list[str]:
    """Check a hand-declared season and week against the schedule. Warns, never halts.

    The week file is the escape hatch for a run when nflverse cannot be reached, so its
    override has to survive this lookup failing. What it must not do is override in
    silence: a week file left over from last week is exactly the stale input this whole
    mechanism exists to stop, and it would put the dark exposure layer back by hand.
    """
    try:
        found = resolve(games, get=get)
    except SheetFault:
        return [f"the week file declares season {season} week {week}, and that could not be "
                f"confirmed against the nflverse schedule. Running on the declared week."]
    if (found.season, found.week) == (season, week):
        return []
    return [f"the week file declares season {season} week {week}, but these games are "
            f"season {found.season} week {found.week} in the nflverse schedule "
            f"({found.matched}/{found.total} matched). The week file wins, so the injury "
            f"report below was read for the week the file names. If that file is a "
            f"leftover, the exposure section is for the wrong week."]


def filename_cross_check(res: Resolution, filename_week: int | None) -> list[str]:
    """The filename's week number against the resolved one. Reported, never obeyed.

    The operator's files are numbered from zero, so a filename one below the NFL week is
    the expected case and is stated rather than warned about. Anything else means the
    wrong file may have been picked up, and that is worth interrupting for.
    """
    if filename_week is None or filename_week == res.week:
        return []
    if filename_week == res.week - 1:
        return []
    return [f"the filename numbers this week {filename_week}, but the games on it are NFL "
            f"week {res.week}. The operator numbers his files from zero, so one below is "
            f"normal and this is not. The games decide the week; check this is the sheet "
            f"you meant."]
