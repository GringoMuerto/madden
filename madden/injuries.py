"""Official injury designations and inactives.

The reports are public and free. Nothing in the engine ever asked for them, which is
why every run before this one was priced on the sheet and the market line alone.

Source is ESPN's public endpoints, which need no key. They are undocumented, so a
failure here is a degrade condition, never an error: Madden reports what he could not
fetch and picks anyway.

What this module will NOT do:

  * It never infers a designation. If the feed does not say a player is out, he is not
    out. A model asked whether someone is playing will produce a confident answer from
    training data that looks exactly like a fetched one.
  * It never flips a pick. Under the spec a status finding can lower confidence in a
    game's number, shifting that game toward the market. That is its only power.
  * It never reads a betting site or a search result. This domain is among the most
    aggressively SEO-optimised on the internet.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ESPN's internal team ids. Stable for years, but verified rather than assumed: a wrong
# id returns another team's report, which is worse than returning nothing.
ESPN_TEAM_IDS = {
    "ARI": 22, "ATL": 1, "BAL": 33, "BUF": 2, "CAR": 29, "CHI": 3, "CIN": 4,
    "CLE": 5, "DAL": 6, "DEN": 7, "DET": 8, "GB": 9, "HOU": 34, "IND": 11,
    "JAX": 30, "KC": 12, "LV": 13, "LAC": 24, "LA": 14, "MIA": 15, "MIN": 16,
    "NE": 17, "NO": 18, "NYG": 19, "NYJ": 20, "PHI": 21, "PIT": 23, "SF": 25,
    "SEA": 26, "TB": 27, "TEN": 10, "WAS": 28,
}

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

# Points of line value, from the spec's quarterback section. Applied ONLY to lower
# confidence, never to move a number directly.
SEVERITY = {"out": 1.0, "doubtful": 0.75, "questionable": 0.4, "probable": 0.1}

QB_POSITIONS = {"QB"}
TIER2_POSITIONS = {"DE", "OLB", "EDGE", "CB", "LT", "RT", "OT", "C", "G", "OG", "WR"}


@dataclass
class Designation:
    team: str
    player: str
    position: str
    status: str          # verbatim from the feed, lowercased
    detail: str = ""
    source: str = ""     # the exact text this came from, for citation

    @property
    def severity(self) -> float:
        return SEVERITY.get(self.status, 0.0)

    @property
    def is_qb(self) -> bool:
        return self.position.upper() in QB_POSITIONS


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
        return [d for d in self.designations
                if not d.is_qb and d.position.upper() in TIER2_POSITIONS
                and d.severity >= SEVERITY["doubtful"]]

    def confidence_penalty(self) -> float:
        """How much to distrust this team's own number, 0 to 1.

        A quarterback dominates. Everything below quarterback is close to noise and is
        capped accordingly, per the spec: elite edge and corner half a point to one and a
        half, line and receiver half to one, and running backs and off-ball defenders at
        essentially nothing.
        """
        if not self.fetched:
            return 0.0
        qb = max((d.severity for d in self.quarterbacks), default=0.0)
        others = min(0.25, 0.08 * len(self.tier2))
        return min(1.0, qb + others)


def _get(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": "madden/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _resolve(ref: str, timeout: int = 12):
    """ESPN returns $ref pointers rather than inline objects."""
    if not ref:
        return {}
    return _get(ref.replace("http://", "https://"), timeout=timeout)


def fetch_team(team: str, timeout: int = 12, max_items: int = 40) -> TeamReport:
    report = TeamReport(team=team)
    tid = ESPN_TEAM_IDS.get(team)
    if tid is None:
        report.error = f"no ESPN id for {team}"
        return report
    try:
        index = _get(f"{CORE}/teams/{tid}/injuries", timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        report.error = str(exc)
        return report

    report.fetched = True
    for item in (index.get("items") or [])[:max_items]:
        try:
            entry = _resolve(item.get("$ref", ""), timeout=timeout)
        except Exception:                                  # noqa: BLE001
            continue
        status = str(entry.get("status") or "").strip().lower()
        if not status:
            continue
        athlete, position = "", ""
        try:
            ath = _resolve((entry.get("athlete") or {}).get("$ref", ""), timeout=timeout)
            athlete = ath.get("displayName") or ath.get("fullName") or ""
            position = ((ath.get("position") or {}).get("abbreviation")) or ""
        except Exception:                                  # noqa: BLE001
            pass
        detail = (entry.get("details") or {}).get("type") or entry.get("shortComment") or ""
        report.designations.append(Designation(
            team=team, player=athlete or "(unnamed)", position=position,
            status=status, detail=str(detail),
            source=f"ESPN team {tid} injuries: {athlete} {position} {status}".strip(),
        ))
    return report


def fetch_all(teams, timeout: int = 12) -> dict:
    return {t: fetch_team(t, timeout=timeout) for t in sorted(set(teams))}


def summarise(reports: dict) -> list:
    """Run-health lines. Silence about a missing input is worse than the missing input."""
    out = []
    failed = [t for t, r in reports.items() if not r.fetched]
    if failed and len(failed) == len(reports):
        out.append("INJURY FETCH FAILED for every team: nothing in this run reflects "
                   "availability except through the market line")
        return out
    if failed:
        out.append(f"injury report unavailable for {', '.join(sorted(failed))}; "
                   f"those teams ran with no availability data")
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
    """(penalty 0-1, reasons) for one game."""
    reasons = []
    worst = 0.0
    for side, team in (("home", home), ("away", away)):
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
