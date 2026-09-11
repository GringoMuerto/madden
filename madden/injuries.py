"""Quarterback exposure: which games have a quarterback whose status is still unresolved.

This is NOT a price. It attaches no points and changes no pick and no band.

Injuries reach the picks through the market line. The sheet is frozen Tuesday and the
market is not: when a starter is ruled out the books move, the sheet does not, and the
drift term already prices that gap. A second injury number on top would double count
what the market did. So this module only names, for each game, any quarterback whose
status is unresolved, so Scott knows which games to look at before he submits.

Source: the official league injury report as nflverse publishes it -- one row per
player per week, the latest report, rebuilt daily at about 12:00 UTC. Not ESPN's feed,
whose status is its own news summary, not the official designation: in week 1 it listed
a quarterback "Out" on a coach's statement while the official report, with no game
statuses yet, had him at full participation. It may prove right; it is still not
official. Depth-chart rank comes from nflverse's daily depth-chart snapshot and is shown
as a label, never used as a filter.

Unresolved means:
  * a game status of Questionable or Doubtful, or
  * no game status yet, on a team whose final report has not come out, and the latest
    practice was DNP or Limited.
Out is resolved (the market prices it). Full participation is resolved. A team with no
rows in the build is UNKNOWN and says so -- never reported clean.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .net import urlopen
from .teams import from_nflverse

RELEASES = "https://github.com/nflverse/nflverse-data/releases/download"
RELEASE_API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags"
TIMEOUT = 30

UNRESOLVED_GAME_STATUS = {"questionable", "doubtful"}
UNRESOLVED_PRACTICE = {
    "did not participate in practice": "did not practice",
    "limited participation in practice": "limited in practice",
}


@dataclass
class Quarterback:
    team: str
    name: str
    gsis_id: str
    game_status: str       # verbatim from the report, may be empty
    practice_status: str   # verbatim from the report
    injury: str


@dataclass
class Report:
    season: int
    week: int
    built: str = "unknown"                               # release asset's updated_at
    quarterbacks: list = field(default_factory=list)     # this week's QB rows
    teams: set = field(default_factory=set)              # teams with any row this week
    final_report_out: set = field(default_factory=set)   # teams with any game status
    depth: dict = field(default_factory=dict)            # gsis_id -> QB rank
    depth_as_of: str = ""
    error: str = ""                                      # report fetch failed
    depth_error: str = ""

    @property
    def empty(self) -> bool:
        """Fetched cleanly, but this season and week hold no rows at all.

        The quietest failure available here. A wrong week number returns HTTP 200 and an
        empty slice, every team then reports UNKNOWN, and without this nothing in run
        health says why. Loud, per game and once in run health.
        """
        return not self.error and not self.teams


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "madden/1.0"})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _built_at(season: int, get) -> str:
    """The release asset's own timestamp: the only date this data carries."""
    rel = json.loads(get(f"{RELEASE_API}/injuries"))
    for a in rel.get("assets", []):
        if a.get("name") == f"injuries_{season}.csv":
            return a.get("updated_at") or "unknown"
    return "unknown"


def fetch(season: int, week: int, get=None) -> tuple:
    """Returns (Report, warnings). Never raises: a failure is recorded and reported."""
    get = get or _http
    rep, warnings = Report(season=season, week=week), []

    try:
        text = get(f"{RELEASES}/injuries/injuries_{season}.csv").decode("utf-8")
        rows = [r for r in csv.DictReader(io.StringIO(text))
                if str(r.get("week")) == str(week) and r.get("game_type", "REG") == "REG"]
    except Exception as exc:                                        # noqa: BLE001
        rep.error = f"{type(exc).__name__}: {exc}"
        return rep, warnings

    for r in rows:
        t = from_nflverse(r.get("team", ""))
        rep.teams.add(t)
        if (r.get("report_status") or "").strip():
            rep.final_report_out.add(t)
        if (r.get("position") or "").upper() == "QB":
            rep.quarterbacks.append(Quarterback(
                team=t, name=r.get("full_name", ""), gsis_id=r.get("gsis_id", ""),
                game_status=(r.get("report_status") or "").strip(),
                practice_status=(r.get("practice_status") or "").strip(),
                injury=(r.get("report_primary_injury")
                        or r.get("practice_primary_injury") or "").strip()))

    try:
        rep.built = _built_at(season, get)
    except Exception as exc:                                        # noqa: BLE001
        warnings.append(f"injury report build time unavailable ({type(exc).__name__}: "
                        f"{exc}); cannot say which day's report this is")

    try:
        raw = get(f"{RELEASES}/depth_charts/depth_charts_{season}.csv.gz")
        drows = [r for r in csv.DictReader(io.StringIO(gzip.decompress(raw).decode("utf-8")))
                 if r.get("pos_abb") == "QB"]
        latest: dict = {}
        for r in drows:
            latest[r["team"]] = max(latest.get(r["team"], ""), r["dt"])
        for r in drows:
            if r["dt"] == latest[r["team"]] and r.get("gsis_id"):
                rep.depth[r["gsis_id"]] = int(r["pos_rank"])
        rep.depth_as_of = max(latest.values()) if latest else ""
    except Exception as exc:                                        # noqa: BLE001
        rep.depth_error = f"{type(exc).__name__}: {exc}"
        warnings.append(f"depth chart unavailable ({rep.depth_error}); exposure lines "
                        f"name quarterbacks without their rank")
    return rep, warnings


def _unresolved(rep: Report, qb: Quarterback) -> str | None:
    """Why this quarterback is unresolved, in the report's own words, or None."""
    gs = qb.game_status.lower()
    if gs in UNRESOLVED_GAME_STATUS:
        return qb.game_status
    if not gs and qb.team not in rep.final_report_out:
        practice = UNRESOLVED_PRACTICE.get(qb.practice_status.lower())
        if practice:
            return f"no game status yet, {practice}"
    return None


def exposure(rep: Report, home: str, away: str) -> tuple:
    """(names, unknown_teams) for one game. Names carry no points."""
    if rep.error:
        return [], [away, home]
    names, unknown = [], []
    for team in (away, home):
        if team not in rep.teams:
            unknown.append(team)
            continue
        for qb in rep.quarterbacks:
            if qb.team != team:
                continue
            why = _unresolved(rep, qb)
            if why is None:
                continue
            if rep.depth_error:
                rank = ""
            elif qb.gsis_id in rep.depth:
                rank = f" (QB{rep.depth[qb.gsis_id]})"
            else:
                rank = " (not on the depth chart)"
            names.append(f"{team} QB {qb.name}{rank}, {why}"
                         + (f" ({qb.injury})" if qb.injury else ""))
    return names, unknown


def header(rep: Report) -> str:
    if rep.error:
        return (f"INJURY REPORT FETCH FAILED ({rep.error}): exposure is UNKNOWN for "
                f"every game")
    return (f"official injury report, nflverse build {rep.built}; depth chart "
            f"{rep.depth_as_of or 'unavailable'}. Names only: no points, changes nothing")
