"""Static NFL reference data: names, divisions, stadium roof types.

This is reference data, not tuning. It changes when a team moves or a stadium opens,
not when the scoreboard moves. Roof types are current for the 2026 season.
"""

from __future__ import annotations

# Canonical abbreviation -> full name as the pool operator and the odds API write it.
TEAMS = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"],
    "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"],
    "AFC West": ["DEN", "KC", "LV", "LAC"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"],
    "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"],
    "NFC West": ["ARI", "LAR", "SF", "SEA"],
}

_DIVISION_OF = {t: d for d, teams in DIVISIONS.items() for t in teams}

# Roof type of each team's home stadium.
#   outdoor     - open air
#   dome        - fixed roof, climate controlled
#   retractable - roof that can open; treated as indoors unless a week override says open
#   canopy      - SoFi: covered, open sided, not climate controlled. See params.venues.
ROOFS = {
    "ARI": "retractable", "ATL": "retractable", "BAL": "outdoor", "BUF": "outdoor",
    "CAR": "outdoor", "CHI": "outdoor", "CIN": "outdoor", "CLE": "outdoor",
    "DAL": "retractable", "DEN": "outdoor", "DET": "dome", "GB": "outdoor",
    "HOU": "retractable", "IND": "retractable", "JAX": "outdoor", "KC": "outdoor",
    "LAC": "canopy", "LAR": "canopy", "LV": "dome", "MIA": "outdoor",
    "MIN": "dome", "NE": "outdoor", "NO": "dome", "NYG": "outdoor",
    "NYJ": "outdoor", "PHI": "outdoor", "PIT": "outdoor", "SEA": "outdoor",
    "SF": "outdoor", "TB": "outdoor", "TEN": "outdoor", "WAS": "outdoor",
}

_BY_NAME = {v.lower(): k for k, v in TEAMS.items()}
_ALIASES = {
    "la rams": "LAR", "l.a. rams": "LAR", "rams": "LAR",
    "la chargers": "LAC", "l.a. chargers": "LAC", "chargers": "LAC",
    "las vegas": "LV", "raiders": "LV", "washington": "WAS",
    "ny giants": "NYG", "n.y. giants": "NYG", "giants": "NYG",
    "ny jets": "NYJ", "n.y. jets": "NYJ", "jets": "NYJ",
    "green bay": "GB", "kansas city": "KC", "new orleans": "NO",
    "new england": "NE", "san francisco": "SF", "tampa bay": "TB",
    "jacksonville": "JAX", "jaguars": "JAX",
}


def abbr(name: str) -> str:
    """Resolve a team name to its abbreviation. Raises rather than guessing."""
    key = " ".join(str(name).split()).lower()
    if key in _BY_NAME:
        return _BY_NAME[key]
    if key in _ALIASES:
        return _ALIASES[key]
    if key.upper() in TEAMS:
        return key.upper()
    # Last resort: unique suffix match on the nickname.
    hits = [k for k, v in TEAMS.items() if v.lower().endswith(key)]
    if len(hits) == 1:
        return hits[0]
    raise ValueError(f"cannot resolve team name: {name!r}")


def division_of(team: str) -> str:
    return _DIVISION_OF[team]


def is_divisional(home: str, away: str) -> bool:
    return _DIVISION_OF[home] == _DIVISION_OF[away]


def is_dome_based(team: str, canopy_counts: bool = False) -> bool:
    """True if the team's own home stadium is roofed, which is what the visitor rule measures."""
    roof = ROOFS[team]
    if roof == "canopy":
        return bool(canopy_counts)
    return roof in ("dome", "retractable")


def is_outdoors(home: str, *, canopy_is_outdoors: bool = False,
                retractable_open: bool = False) -> bool:
    """True if the game is played in open air at the home team's stadium."""
    roof = ROOFS[home]
    if roof == "outdoor":
        return True
    if roof == "canopy":
        return bool(canopy_is_outdoors)
    if roof == "retractable":
        return bool(retractable_open)
    return False
