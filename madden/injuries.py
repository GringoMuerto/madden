"""Official injury designations, in one request per run.

The first version of this made one index call per team plus two more for every
designation on it -- several hundred sequential requests with no timeout and no
progress output. It was not hung, it was crawling, and it looked identical to hung.
That is what this rewrite fixes.

ESPN publishes a league-wide injuries endpoint that returns every team inline. One
call. The per-team path is kept only as a fallback, capped, with a hard deadline.

No key, no betting sites, no search results. Undocumented, so failure degrades: the
run says what it could not fetch and picks anyway.

This never infers a designation. If the feed does not say a player is out, he is not
out -- a model asked whether someone is playing will produce a confident answer from
training data that looks exactly like a fetched one. And it never flips a pick; under
the spec a status finding can only lower confidence in a game's number.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LEAGUE_INJURIES = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
)
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

ESPN_TEAM_IDS = {
    "ARI": 22, "ATL": 1, "BAL": 33, "BUF": 2, "CAR": 29, "CHI": 3, "CIN": 4,
    "CLE": 5, "DAL": 6, "DEN": 7, "DET": 8, "GB": 9, "HOU": 34, "IND": 11,
    "JAX": 30, "KC": 12, "LV": 13, "LAC": 24, "LA": 14, "MIA": 15, "MIN": 16,
    "NE": 17, "NO": 18, "NYG": 19, "NYJ": 20, "PHI": 21, "PIT": 23, "SF": 25,
    "SEA": 26, "TB": 27, "TEN": 10, "WAS": 28,
}
ESPN_ABBR = {
    "WSH": "WAS", "LAR": "LA", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA",
}

SEVERITY = {"out": 1.0, "doubtful": 0.75, "questionable": 0.4, "probable": 0.1}
TIER2 = {"DE", "OLB", "EDGE", "CB", "LT", "RT", "OT", "C", "G", "OG", "WR"}

CACHE = Path(".cache")
CACHE_TTL_SECONDS = 3600


@dataclass
class Designation:
    team: str
    player: str
    position: str
    status: str
    detail: str = ""

    @property
    def severity(self) -> float:
        return SEVERITY.get(self.status, 0.0)

    @property
    def is_qb(self) -> bool:
        return self.position.upper() == "QB"


@dataclass
class TeamReport:
    team: str
    designations: list = field(default_factory=list)
    fetched: bool = False
    error: str = ""

    @property
    def quarterbacks(self) -> list:
        return [d for d in self.designations if d.is_qb and d.severity > 0]

    @property
    def tier2(self) -> list:
        return [d for d in self.designations if not d.is_qb
                and d.position.upper() in TIER2 and d.severity >= SEVERITY["doubtful"]]

    def confidence_penalty(self) -> float:
        if not self.fetched:
            return 0.0
        qb = max((d.severity for d in self.quarterbacks), default=0.0)
        return min(1.0, qb + min(0.25, 0.08 * len(self.tier2)))


def _norm(abbr: str) -> str:
    a = (abbr or "").upper()
    return ESPN_ABBR.get(a, a)


def _get(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": "madden/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _cached(name: str, ttl: int = CACHE_TTL_SECONDS):
    p = CACHE / name
    if p.is_file() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except ValueError:
            return None
    return None


def _store(name: str, payload) -> None:
    CACHE.mkdir(exist_ok=True)
    (CACHE / name).write_text(json.dumps(payload))


def _parse_league(payload) -> dict:
    """The league endpoint nests: injuries -> [ {team, injuries: [...]} ].

    Shapes vary between ESPN's surfaces, so this reads defensively and returns
    whatever it can rather than raising on an unexpected key.
    """
    out: dict = {}
    groups = payload.get("injuries") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        return out
    for group in groups:
        team = _norm((group.get("abbreviation")
                      or (group.get("team") or {}).get("abbreviation") or ""))
        if team not in ESPN_TEAM_IDS:
            continue
        report = out.setdefault(team, TeamReport(team=team, fetched=True))
        for item in (group.get("injuries") or []):
            status = str(item.get("status") or "").strip().lower()
            if not status:
                continue
            ath = item.get("athlete") or {}
            report.designations.append(Designation(
                team=team,
                player=ath.get("displayName") or ath.get("fullName") or "(unnamed)",
                position=((ath.get("position") or {}).get("abbreviation") or ""),
                status=status,
                detail=str((item.get("details") or {}).get("type")
                           or item.get("shortComment") or ""),
            ))
    return out


def fetch_all(teams, timeout: int = 15, deadline_seconds: int = 45,
              use_cache: bool = True) -> dict:
    """One call for the whole league. Falls back to per-team, capped by a deadline."""
    wanted = sorted({_norm(t) for t in teams})
    reports = {t: TeamReport(team=t) for t in wanted}

    payload = _cached("injuries.json") if use_cache else None
    if payload is None:
        try:
            payload = _get(LEAGUE_INJURIES, timeout)
            _store("injuries.json", payload)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
            payload = None
            reports[wanted[0]].error = str(exc)

    if payload is not None:
        parsed = _parse_league(payload)
        if parsed:
            for t in wanted:
                if t in parsed:
                    reports[t] = parsed[t]
            missing = [t for t in wanted if not reports[t].fetched]
            if not missing:
                return reports

    # Fallback: per team, with a hard deadline so this can never hang a run again.
    started = time.time()
    for t in [t for t in wanted if not reports[t].fetched]:
        if time.time() - started > deadline_seconds:
            reports[t].error = "deadline reached before this team was fetched"
            continue
        try:
            index = _get(f"{CORE}/teams/{ESPN_TEAM_IDS[t]}/injuries", timeout)
        except Exception as exc:                                    # noqa: BLE001
            reports[t].error = str(exc)
            continue
        reports[t].fetched = True
        # Deliberately does NOT resolve the per-athlete $ref pointers. That is what made
        # the first version take minutes. Status without a name is still usable.
        for item in (index.get("items") or [])[:25]:
            status = str(item.get("status") or "").strip().lower()
            if status:
                reports[t].designations.append(Designation(
                    team=t, player="(name not resolved)", position="", status=status))
    return reports


def summarise(reports: dict) -> list:
    """Run-health lines. Silence about a missing input is worse than the input."""
    out = []
    failed = sorted(t for t, r in reports.items() if not r.fetched)
    if failed and len(failed) == len(reports):
        return ["INJURY FETCH FAILED for every team: nothing in this run reflects "
                "availability except through the market line"]
    if failed:
        out.append(f"injury report unavailable for {', '.join(failed)}; those teams "
                   f"ran with no availability data")
    for team, r in sorted(reports.items()):
        for d in r.quarterbacks:
            out.append(f"{team}: QB {d.player} listed {d.status}"
                       + (f" ({d.detail})" if d.detail else ""))
        if r.tier2:
            names = ", ".join(f"{d.player} {d.position} {d.status}" for d in r.tier2[:4])
            out.append(f"{team}: {names}")
    if not out:
        out.append("injury reports fetched: no quarterback or high-impact designations")
    return out


def game_confidence(reports: dict, home: str, away: str) -> tuple:
    reasons, worst = [], 0.0
    for team in (_norm(home), _norm(away)):
        r = reports.get(team)
        if r is None or not r.fetched:
            continue
        p = r.confidence_penalty()
        if p <= 0:
            continue
        worst = max(worst, p)
        for d in r.quarterbacks:
            reasons.append(f"{team} QB {d.player} {d.status}")
    return worst, reasons
