"""Current market consensus spreads.

Priced against a multi-book consensus, never one book: sub-half-point differences from a
single book are measurement noise.

Staleness is judged from the data's own last_update timestamps, never from a clock
heuristic. A line that cannot be fetched stays missing; Madden never supplies one from
anywhere else, because a model asked for a line it could not retrieve will produce a
plausible one that looks real.

The feed is a swappable component. The interface is "give me a current consensus spread
per game". Which vendor supplies it is a config line.
"""

from __future__ import annotations

import json
import os
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from .teams import abbr

# The real vendor is the-odds-api.com WITH hyphens. See params.yaml.


@dataclass
class MarketLine:
    home: str
    away: str
    home_line: float | None      # points the home team is favored by
    total: float | None
    books: int
    last_update: str | None

    def age_hours(self, now=None) -> float | None:
        if not self.last_update:
            return None
        try:
            ts = datetime.fromisoformat(self.last_update.replace("Z", "+00:00"))
        except ValueError:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - ts).total_seconds() / 3600.0


def _consensus(values: list[float], how: str) -> float | None:
    if not values:
        return None
    if how == "mean":
        return round(statistics.fmean(values), 2)
    return round(statistics.median(values), 2)


def fetch_lines(params, api_key: str | None = None, timeout: int = 20) -> dict:
    """Fetch current spreads and totals. Raises on transport failure; the caller degrades."""
    cfg = params["odds_api"]
    api_key = api_key or os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ODDS_API_KEY is not set. Put it in .env (which .gitignore excludes) and export it. "
            "The key never goes in the vault, a repo, or a conversation.")

    query = urllib.parse.urlencode({
        "apiKey": api_key, "regions": cfg["regions"], "markets": cfg["markets"],
        "oddsFormat": cfg["odds_format"],
    })
    url = f"{cfg['base_url']}/sports/{cfg['sport']}/odds?{query}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        remaining = resp.headers.get("x-requests-remaining")
        payload = json.load(resp)
    if remaining is not None:
        print(f"[market] odds api credits remaining: {remaining}")
    return parse_odds_payload(payload, params)


def parse_odds_payload(payload, params) -> dict:
    """Turn the vendor payload into consensus lines keyed by the pair of teams."""
    how = params["odds_api"]["consensus"]
    out: dict = {}
    for event in payload:
        try:
            home = abbr(event["home_team"])
            away = abbr(event["away_team"])
        except (KeyError, ValueError):
            continue
        spreads, totals, stamps = [], [], []
        for book in event.get("bookmakers", []):
            stamps.append(book.get("last_update"))
            for market in book.get("markets", []):
                if market["key"] == "spreads":
                    for o in market.get("outcomes", []):
                        try:
                            if abbr(o["name"]) == home:
                                spreads.append(-float(o["point"]))
                        except (KeyError, ValueError, TypeError):
                            continue
                elif market["key"] == "totals":
                    for o in market.get("outcomes", []):
                        if o.get("name", "").lower() == "over":
                            try:
                                totals.append(float(o["point"]))
                            except (KeyError, ValueError, TypeError):
                                continue
        stamps = [s for s in stamps if s]
        out[frozenset((home, away))] = MarketLine(
            home=home, away=away,
            home_line=_consensus(spreads, how),
            total=_consensus(totals, how),
            books=len(event.get("bookmakers", [])),
            last_update=max(stamps) if stamps else None,
        )
    return out


def load_offline(path: str) -> dict:
    """Load hand-entered lines. Use when the API is down or out of credits.

    Format:  {"KC@DEN": {"home_line": 2.5, "total": 43.5}}   key is AWAY@HOME
    """
    with open(path) as fh:
        raw = json.load(fh)
    out = {}
    for key, val in raw.items():
        if key.startswith("_"):        # comment keys
            continue
        away, home = [abbr(p.strip()) for p in key.split("@")]
        out[frozenset((home, away))] = MarketLine(
            home=home, away=away,
            home_line=val.get("home_line"), total=val.get("total"),
            books=int(val.get("books", 0)), last_update=val.get("last_update"),
        )
    return out
