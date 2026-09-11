"""The algorithm.

    MADDEN'S NUMBER = current market consensus line
                    + situational adjustments (applied AFTER regression)
                    + w x (power rating - market line)     [w=0 until a rating exists]

    EDGE = MADDEN'S NUMBER - the sheet's frozen line
    PICK = the side the edge points to

Every line in this module is expressed as HOME LINE: the points the home team is favored
by, negative when the home team is the underdog. Situational adjustments are POINTS ADDED
TO THE HOME TEAM, which is the sign convention of the spec's table. Get this backwards and
every pick inverts, so it is asserted in the tests.

Drift and the hook are not separate terms. Both fall out of one subtraction: anchor on the
current number, compare to the frozen one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .teams import is_divisional, is_dome_based, is_outdoors


@dataclass
class Adjustment:
    rule: str
    points: float
    detail: str


@dataclass
class Pick:
    game: object
    market_home_line: float | None
    sheet_home_line: float
    adjustments: list[Adjustment]
    madden_number: float | None
    edge: float | None
    side: str | None                 # team abbreviation
    band: str
    drivers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blind: bool = False

    @property
    def adjustment_total(self) -> float:
        return round(sum(a.points for a in self.adjustments), 3)

    @property
    def deviates_from_favorite(self) -> bool:
        return self.side is not None and self.side != self.game.favorite


def situational_adjustments(game, params, temp_f: float | None = None,
                            retractable_open: bool = False) -> tuple[list[Adjustment], list[str]]:
    """Apply the four measured rules. Returns (adjustments, warnings)."""
    s = params["situational"]
    v = params["venues"]
    adjustments: list[Adjustment] = []
    warnings: list[str] = []

    home, away = game.home, game.away

    if game.neutral_site:
        warnings.append(
            "neutral site: the global home baseline and the dome-visitor rule are void here, "
            "and the divisional rule is being applied to a nominal home team that is not at home")
    else:
        adjustments.append(Adjustment(
            "global_home_baseline", s["global_home_baseline"]["points"],
            "home teams cover 49.0% over 6,712 games"))

    if is_divisional(home, away):
        adjustments.append(Adjustment(
            "divisional", s["divisional"]["points"], f"{home} and {away} share a division"))

    if not game.neutral_site:
        outdoors = is_outdoors(home, canopy_is_outdoors=v["canopy_is_outdoors"],
                               retractable_open=retractable_open)
        dome_visitor = is_dome_based(away, canopy_counts=v["canopy_is_dome_based"])
        rule = s["dome_visitor_outdoors_75f"]
        if outdoors and dome_visitor:
            if temp_f is None:
                warnings.append(
                    f"{away} is dome-based and this game is outdoors, but no temperature was "
                    f"supplied, so the {rule['points']} rule could not be evaluated")
            elif temp_f >= rule["temp_threshold_f"]:
                adjustments.append(Adjustment(
                    "dome_visitor_outdoors_75f", rule["points"],
                    f"{away} is dome-based, outdoors at {temp_f:.0f}F"))
        elif outdoors and temp_f is None:
            warnings.append("outdoor game with no temperature supplied")

        dog_rule = s["home_underdog_7plus"]
        if game.sheet_home_line <= -dog_rule["threshold"]:
            adjustments.append(Adjustment(
                "home_underdog_7plus", dog_rule["points"],
                f"{home} is a home underdog of {abs(game.sheet_home_line)}"))

    return adjustments, warnings


def crosses_key_number(a: float, b: float, key_numbers) -> int | None:
    """Return the key number strictly between a and b, if any."""
    lo, hi = (a, b) if a <= b else (b, a)
    for k in key_numbers:
        for cand in (k, -k):
            if lo < cand < hi:
                return k
    return None


def band_for(edge: float, madden_number: float, sheet_home_line: float, params) -> tuple[str, int | None]:
    b = params["bands"]
    key = crosses_key_number(madden_number, sheet_home_line, b["key_numbers"])
    if abs(edge) >= b["high_points"]:
        return "high", key
    if key is not None and b["key_number_upgrades_to_high"]:
        return "high", key
    if abs(edge) >= b["medium_points"]:
        return "medium", key
    return "coin flip", key


def make_pick(game, market_home_line: float | None, params, temp_f: float | None = None,
              retractable_open: bool = False, model_term: float = 0.0,
              blind: bool = False) -> Pick:
    """Price one game. Never fabricates a missing line."""
    adjustments, warnings = situational_adjustments(
        game, params, temp_f=temp_f, retractable_open=retractable_open)
    warnings = list(warnings) + list(game.notes)

    if market_home_line is None:
        warnings.append(
            "no market line could be fetched for this game; missing stays missing. "
            "Pick withheld and the game is flagged.")
        return Pick(game=game, market_home_line=None, sheet_home_line=game.sheet_home_line,
                    adjustments=adjustments, madden_number=None, edge=None, side=None,
                    band="blind", warnings=warnings, blind=True)

    adj_total = sum(a.points for a in adjustments)
    madden_number = market_home_line + adj_total + model_term
    edge = madden_number - game.sheet_home_line
    side = game.home if edge > 0 else game.away
    band, key = band_for(edge, madden_number, game.sheet_home_line, params)
    if blind:
        band = "blind"

    drivers = []
    drift = market_home_line - game.sheet_home_line
    if abs(drift) >= 0.5:
        toward = game.home if drift > 0 else game.away
        drivers.append(f"line moved {abs(drift):.1f} toward {toward} since the sheet was set")
    for a in adjustments:
        if a.rule != "global_home_baseline":
            drivers.append(f"{a.rule.replace('_', ' ')} {a.points:+.1f} ({a.detail})")
    if key is not None:
        drivers.append(f"edge crosses the key number {key}")
    if not drivers:
        drivers.append("no drift and no situational rule beyond the home baseline")

    return Pick(game=game, market_home_line=market_home_line,
                sheet_home_line=game.sheet_home_line, adjustments=adjustments,
                madden_number=round(madden_number, 2), edge=round(edge, 2), side=side,
                band=band, drivers=drivers, warnings=warnings, blind=blind)


def tiebreaker(market_total: float | None, params, wind_mph: float | None = None) -> dict:
    """Monday night combined score. Offset off the total deliberately, never sit on it."""
    t = params["tiebreaker"]
    if market_total is None:
        return {"guess": None, "reason": "no market total fetched; no number supplied"}
    offset = t["offset_points"]
    direction = -1 if t["offset_direction"] == "down" else 1
    guess = market_total + direction * offset
    notes = [f"market total {market_total}, offset {offset} {t['offset_direction']} "
             f"because the field clusters on the total itself"]
    if wind_mph is not None and wind_mph >= t["wind_strong_mph"]:
        guess -= 2.7
        notes.append(f"wind {wind_mph} mph is 20+, worth about 2.7 fewer points")
    elif wind_mph is not None and wind_mph >= t["wind_mph_threshold"]:
        notes.append(f"wind {wind_mph} mph is above 10, under hits about 54% here")
    if t["offset_direction"] == "down" and t.get("offset_direction_resolved") is not True:
        notes.append("offset DIRECTION is unresolved in the spec (open item 3)")
    return {"guess": round(guess), "reason": "; ".join(notes)}
