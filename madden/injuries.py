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

This module also carries two things it does not itself print: every injury row, at every
position, keyed by player, and the latest depth chart's starters by side of the ball.
madden/health.py turns those into the starter-health chart and the injured-quarterback
list under the board. Both are display only, on the same terms as exposure: no points.

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
PRACTICE_SHORT = {
    "full participation in practice": "Full",
    "limited participation in practice": "Limited",
    "did not participate in practice": "DNP",
}

# The depth chart's own personnel groupings. Offence is the three-receiver package the
# chart publishes; defence is whichever base front the team lists, never both.
OFFENSE_GROUP = "3WR 1TE"
DEFENSE_GROUPS = ("Base 3-4 D", "Base 4-3 D")


@dataclass
class Quarterback:
    team: str
    name: str
    gsis_id: str
    game_status: str       # verbatim from the report, may be empty
    practice_status: str   # verbatim from the report
    injury: str


@dataclass
class Injured:
    """One row of the official report, normalised. Every position, not just quarterbacks."""
    team: str
    name: str
    position: str
    game_status: str       # verbatim, may be empty until the final report
    practice: str          # Full | Limited | DNP, or verbatim if unrecognised
    injury: str            # primary, plus a secondary the primary does not already name
    rest: bool             # "not injury related - resting player": a day off, not a doubt


@dataclass
class Report:
    season: int
    week: int
    built: str = "unknown"                               # release asset's updated_at
    quarterbacks: list = field(default_factory=list)     # this week's QB rows
    teams: set = field(default_factory=set)              # teams with any row this week
    final_report_out: set = field(default_factory=set)   # teams with any game status
    depth: dict = field(default_factory=dict)            # gsis_id -> QB rank
    rows: dict = field(default_factory=dict)             # gsis_id -> Injured, all positions
    starters: dict = field(default_factory=dict)         # team -> {"OFF": [...], "DEF": [...]}
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


def _injured(row: dict, team: str) -> Injured:
    """Normalise one report row. The report's own words, tidied, never reinterpreted."""
    primary = (row.get("report_primary_injury")
               or row.get("practice_primary_injury") or "").strip()
    secondary = (row.get("practice_secondary_injury") or "").strip()
    rest = primary.lower().startswith("not injury related")
    if rest:
        primary = "rest" + (f" / {secondary}" if secondary else "")
    elif secondary and secondary.lower() not in primary.lower():
        primary = f"{primary} / {secondary}" if primary else secondary
    practice = (row.get("practice_status") or "").strip()
    return Injured(
        team=team, name=row.get("full_name", ""),
        position=(row.get("position") or "").upper(),
        game_status=(row.get("report_status") or "").strip(),
        practice=PRACTICE_SHORT.get(practice.lower(), practice),
        injury=primary, rest=rest)


def _starters(snapshot: list) -> dict:
    """team -> {"OFF": [(pos, name, gsis_id)], "DEF": [...]} from the latest depth chart.

    Offence is rank 1 at every slot of the three-receiver package plus receivers ranked
    1-3, which is eleven men for most teams and twelve where the chart ranks a fourth
    receiver inside three. Defence is rank 1 at every slot of the team's own base front,
    which is twelve: the eleven plus the nickel back the chart lists beside them.
    Special teams are not starters here. A team that lists neither base front gets no
    defensive side and reports UNKNOWN rather than clean.
    """
    groups: dict = {}
    for r in snapshot:
        groups.setdefault(from_nflverse(r.get("team", "")), set()).add(r.get("pos_grp", ""))
    out: dict = {}
    for r in snapshot:
        team = from_nflverse(r.get("team", ""))
        try:
            rank = int(r["pos_rank"])
        except (TypeError, ValueError, KeyError):
            continue
        grp, pos = r.get("pos_grp", ""), r.get("pos_abb", "")
        base = next((g for g in DEFENSE_GROUPS if g in groups[team]), None)
        if grp == OFFENSE_GROUP and (rank == 1 or (pos == "WR" and rank <= 3)):
            side = "OFF"
        elif base and grp == base and rank == 1:
            side = "DEF"
        else:
            continue
        out.setdefault(team, {"OFF": [], "DEF": []})[side].append(
            (pos, r.get("player_name", ""), r["gsis_id"]))
    for team in out:
        for side in out[team]:
            out[team][side] = sorted(set(out[team][side]))
    return out


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
        gsis = (r.get("gsis_id") or "").strip()
        if gsis:
            rep.rows[gsis] = _injured(r, t)
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
        drows = list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode("utf-8"))))
        latest: dict = {}
        for r in drows:
            latest[r["team"]] = max(latest.get(r["team"], ""), r["dt"])
        # One snapshot per team: the chart is republished daily and the file keeps history.
        snapshot = [r for r in drows if r["dt"] == latest.get(r.get("team")) and r.get("gsis_id")]
        for r in snapshot:
            if r.get("pos_abb") == "QB":
                rep.depth[r["gsis_id"]] = int(r["pos_rank"])
        rep.starters = _starters(snapshot)
        rep.depth_as_of = max(latest.values()) if latest else ""
    except Exception as exc:                                        # noqa: BLE001
        rep.depth_error = f"{type(exc).__name__}: {exc}"
        warnings.append(f"depth chart unavailable ({rep.depth_error}); exposure lines "
                        f"name quarterbacks without their rank, and starter health is "
                        f"UNKNOWN for every team")
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
