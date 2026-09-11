"""Forecast temperature and wind at the stadium.

Exists because two games in the week 1 Sunday board could not be evaluated: Atlanta
and Dallas are dome-based teams playing outdoors, which is the strongest situational
rule in the spec at -2.8 points, and nothing supplied a temperature so the rule sat
idle. A rule that cannot fire is not a rule.

open-meteo needs no key and is not a betting site, which matters: an earlier week file
sourced temperatures from NFLWeather via a sportsbook, which is off the spec's
allowlist for exactly the reason the spec gives -- this domain is among the most
aggressively SEO-optimised on the internet.

A failure returns None. The temperature rule then does not fire and the run says so.
Nothing here ever guesses a temperature.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .net import urlopen

CACHE = Path(".cache")
CACHE_TTL_SECONDS = 6 * 3600

# Home stadium coordinates. Indoor venues are included because a retractable roof can
# be open; the caller decides whether the game is actually outdoors.
STADIUMS = {
    "ARI": (33.528, -112.263), "ATL": (33.755, -84.401), "BAL": (39.278, -76.623),
    "BUF": (42.774, -78.787), "CAR": (35.226, -80.853), "CHI": (41.863, -87.617),
    "CIN": (39.095, -84.516), "CLE": (41.506, -81.699), "DAL": (32.748, -97.093),
    "DEN": (39.744, -105.020), "DET": (42.340, -83.046), "GB": (44.501, -88.062),
    "HOU": (29.685, -95.411), "IND": (39.760, -86.164), "JAX": (30.324, -81.637),
    "KC": (39.049, -94.484), "LV": (36.091, -115.183), "LAC": (33.953, -118.339),
    "LA": (33.953, -118.339), "LAR": (33.953, -118.339), "MIA": (25.958, -80.239), "MIN": (44.974, -93.258),
    "NE": (42.091, -71.264), "NO": (29.951, -90.081), "NYG": (40.814, -74.074),
    "NYJ": (40.814, -74.074), "PHI": (39.901, -75.168), "PIT": (40.447, -80.016),
    "SF": (37.713, -122.386), "SEA": (47.595, -122.332), "TB": (27.976, -82.503),
    "TEN": (36.166, -86.771), "WAS": (38.908, -76.864),
}


def _cache_path(team: str) -> Path:
    return CACHE / f"weather-{team}.json"


def _fetch(lat: float, lon: float, timeout: int):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&hourly=temperature_2m,wind_speed_10m&temperature_unit=fahrenheit"
           f"&wind_speed_unit=mph&forecast_days=10&timezone=UTC")
    req = urllib.request.Request(url, headers={"User-Agent": "madden/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def forecast(team: str, kickoff, timeout: int = 12, use_cache: bool = False):
    """(temp_f, wind_mph) at the home team's stadium for that kickoff, or (None, None).

    `kickoff` is a timezone-aware datetime, or None for the next few days' average --
    which is deliberately NOT offered, because an averaged temperature is a guess
    wearing a number. No kickoff means no forecast.
    """
    coords = STADIUMS.get((team or "").upper())
    if not coords or kickoff is None:
        return None, None

    payload = None
    p = _cache_path(team)
    if use_cache and p.is_file() and (time.time() - p.stat().st_mtime) < CACHE_TTL_SECONDS:
        try:
            payload = json.loads(p.read_text())
        except ValueError:
            payload = None
    if payload is None:
        try:
            payload = _fetch(coords[0], coords[1], timeout)
        except (OSError, ValueError, http.client.HTTPException):
            # OSError covers URLError, HTTPError and timeouts; HTTPException covers a body
            # cut off mid-read (IncompleteRead) and a malformed response. A forecast that
            # cannot be fetched is a data fault: warn and carry on, never stop the run.
            return None, None
        if use_cache:          # the spec: perishable data is never written to disk
            CACHE.mkdir(exist_ok=True)
            p.write_text(json.dumps(payload))

    try:
        hourly = payload["hourly"]
        stamp = kickoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
        idx = hourly["time"].index(stamp)
        return hourly["temperature_2m"][idx], hourly["wind_speed_10m"][idx]
    except (KeyError, ValueError, IndexError):
        return None, None


def forecast_many(pairs, timeout: int = 12, use_cache: bool = False) -> tuple:
    """pairs: [(home_team, kickoff_datetime)]. Returns (temps, winds, warnings)."""
    temps, winds, warnings = {}, {}, []
    for team, kickoff in pairs:
        t, w = forecast(team, kickoff, timeout=timeout, use_cache=use_cache)
        if t is None:
            warnings.append(f"no forecast for {team}; the temperature rule cannot fire")
            continue
        temps[team] = t
        winds[team] = w
    return temps, winds, warnings
