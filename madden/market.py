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

# The feed returns every upcoming event for the season, so divisional opponents show up
# twice. Only meetings inside this window are candidates for the week being run.
NEAR_TERM_DAYS = 10


@dataclass
class MarketLine:
    home: str                    # the API's home team, which is not always the sheet's
    away: str
    home_line: float | None      # points THIS object's home team is favored by
    total: float | None
    books: int
    last_update: str | None
    commence_time: str | None = None

    def line_for(self, home: str) -> float | None:
        """Re-orient the line to the given home team.

        The API's notion of home and the sheet's can disagree, most obviously at a
        neutral site. Returning the number without checking silently inverts the game.
        """
        if self.home_line is None:
            return None
        if home == self.home:
            return self.home_line
        if home == self.away:
            return -self.home_line
        raise ValueError(f"{home} is not in this event ({self.away} at {self.home})")

    def starts_at(self):
        if not self.commence_time:
            return None
        try:
            return datetime.fromisoformat(self.commence_time.replace("Z", "+00:00"))
        except ValueError:
            return None

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
            "ODDS_API_KEY is not set. Put it in .env (which .gitignore excludes). "
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
    """Turn the vendor payload into consensus lines, keyed by the pair of teams.

    The value is a LIST of events sorted by kickoff, not a single line. Divisional
    opponents meet twice a season and the feed returns every upcoming event, so a pair of
    teams can have more than one. Keying on the pair alone would let a week 14 rematch
    overwrite week 1, which is exactly the kind of silent wrong answer that looks like a
    plausible line. `soonest()` picks the right one.
    """
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
        line = MarketLine(
            home=home, away=away,
            home_line=_consensus(spreads, how),
            total=_consensus(totals, how),
            books=len(event.get("bookmakers", [])),
            last_update=max(stamps) if stamps else None,
            commence_time=event.get("commence_time"),
        )
        out.setdefault(frozenset((home, away)), []).append(line)
    for events in out.values():
        events.sort(key=lambda e: e.commence_time or "")
    return out


def soonest(lines: dict, home: str, away: str, now=None,
            within_days: int = NEAR_TERM_DAYS) -> tuple[MarketLine | None, list[str]]:
    """Return this week's meeting of these two teams, plus any warnings.

    Two filters, in order:

      already kicked off  -- dropped. A live or finished game's line is not a price you
                             can pick against, and the feed does return them.
      months away         -- dropped. A November rematch between divisional opponents is
                             not an ambiguity to warn about, it is a different game.

    Only a genuine ambiguity -- more than one meeting still inside the window -- produces
    a warning. Warning on the normal case trains the reader to ignore the warnings, which
    is worse than not having them.
    """
    events = lines.get(frozenset((home, away))) or []
    warnings: list[str] = []
    if not events:
        return None, warnings

    now = now or datetime.now(timezone.utc)
    upcoming, started = [], []
    for e in events:
        ts = e.starts_at()
        if ts is None:
            upcoming.append(e)
            continue
        days = (ts - now).total_seconds() / 86400.0
        if days < 0:
            started.append(e)
        elif days <= within_days:
            upcoming.append(e)

    if not upcoming and started:
        warnings.append(
            f"{away} at {home}: every meeting the feed returned has already kicked off "
            f"(most recent {started[-1].commence_time}). No line to pick against.")
        return None, warnings

    if not upcoming:
        warnings.append(
            f"{away} at {home}: the feed has no meeting within {within_days} days. "
            f"Next listed is {events[0].commence_time}.")
        return None, warnings

    chosen = upcoming[0]
    if len(upcoming) > 1:
        others = ", ".join(e.commence_time or "?" for e in upcoming[1:])
        warnings.append(
            f"{away} at {home}: {len(upcoming)} meetings inside {within_days} days; "
            f"using {chosen.commence_time}, ignoring {others}. This is unexpected -- "
            f"check the sheet is the week you think it is.")
    if chosen.home != home:
        warnings.append(
            f"{away} at {home}: the feed calls {chosen.home} the home team, the sheet "
            f"calls {home}. The line has been re-oriented to the sheet.")
    return chosen, warnings


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
        out[frozenset((home, away))] = [MarketLine(
            home=home, away=away,
            home_line=val.get("home_line"), total=val.get("total"),
            books=int(val.get("books", 0)), last_update=val.get("last_update"),
        )]
    return out
