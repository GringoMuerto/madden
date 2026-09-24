"""The backtest's variant logic. No network, no workbook: hand-built rows.

Only the pure parts are tested here. Fetching a schedule and reading the operator's
archive workbook are covered by running the thing, and by its own cross-check against the
operator's result column, which is a stronger test than any fixture: 272 of 272 in 2025.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden.backtest import (as_built, coin_flip_takes_the_favorite, head_to_head,
                             high_band_split, market_side, needs_temperature, score)

PARAMS = {"bands": {"high_points": 3.0, "key_numbers": [3, 7, 10, 14]}}


def row(band, side, favorite, covered):
    return {"band": band, "side": side, "favorite": favorite, "covered": covered}


def test_the_variant_only_touches_coin_flips():
    banded = row("high", "ARI", "LAC", "ARI")
    assert coin_flip_takes_the_favorite(banded) == "ARI", "a banded pick is left alone"
    flip = row("coin flip", "GB", "MIN", "MIN")
    assert as_built(flip) == "GB"
    assert coin_flip_takes_the_favorite(flip) == "MIN"


def test_the_variant_leaves_a_withheld_pick_withheld():
    """A game with no pick has no favorite substitution to make here either."""
    withheld = row("blind", None, "SEA", "NE")
    assert coin_flip_takes_the_favorite(withheld) is None
    assert score([withheld], coin_flip_takes_the_favorite) == (0, 0)


def test_score_counts_only_games_the_rule_picks():
    rows = [row("coin flip", "GB", "MIN", "MIN"),      # variant takes MIN: right
            row("coin flip", "TB", "CIN", "TB"),       # variant takes CIN: wrong
            row("blind", None, "SEA", "NE")]           # variant picks nothing
    assert score(rows, coin_flip_takes_the_favorite) == (1, 2)
    assert score(rows, as_built) == (1, 2)


def test_head_to_head_uses_only_the_games_that_differ():
    rows = [row("high", "ARI", "LAC", "ARI"),          # agree: excluded
            row("coin flip", "GB", "MIN", "MIN"),      # differ: favorite right
            row("coin flip", "TB", "CIN", "TB"),       # differ: as built right
            row("coin flip", "DEN", "KC", "KC")]       # differ: favorite right
    h = head_to_head(rows, as_built, coin_flip_takes_the_favorite)
    assert h["n"] == 3 and h["a"] == 1 and h["b"] == 2


def test_head_to_head_on_no_disagreement_is_not_a_division_by_zero():
    rows = [row("high", "ARI", "LAC", "ARI")]
    h = head_to_head(rows, as_built, coin_flip_takes_the_favorite)
    assert h == {"n": 0, "a": 0, "b": 0, "se": 0.0, "z": 0.0}


def banded(edge, key, band="high"):
    return {"band": band, "edge": edge, "key": key, "side": "A", "covered": "A"}


def test_the_high_band_splits_on_why_it_is_high():
    """Edge past the threshold is one population; a small edge over a key number another."""
    rows = [banded(4.0, None),          # magnitude
            banded(3.5, 3),             # magnitude, and happens to cross 3
            banded(0.8, 7),             # key crossing only
            banded(1.0, None, "coin flip")]   # not high at all
    by_magnitude, by_key = high_band_split(rows, PARAMS)
    assert [r["edge"] for r in by_magnitude] == [4.0, 3.5]
    assert [r["edge"] for r in by_key] == [0.8]


def test_a_game_with_no_edge_is_not_counted_in_either_high_group():
    """A withheld pick carries band 'blind' and edge None. It must not reach the split."""
    rows = [{"band": "high", "edge": None, "key": 3, "side": None, "covered": "A"}]
    by_magnitude, by_key = high_band_split(rows, PARAMS)
    assert by_magnitude == [] and by_key == []


def test_market_side_follows_the_direction_of_the_drift():
    to_home = {"home": "PIT", "away": "ATL", "market_line": 6.5, "sheet_line": 2.5}
    to_away = {"home": "LAC", "away": "ARI", "market_line": 9.5, "sheet_line": 10.5}
    assert market_side(to_home) == "PIT"
    assert market_side(to_away) == "ARI"


def test_only_dome_visitors_at_outdoor_venues_are_worth_a_forecast():
    assert needs_temperature("CHI", "DAL", neutral=False), "dome-based visitor, open air"
    assert not needs_temperature("DET", "DAL", neutral=False), "indoors: rule cannot fire"
    assert not needs_temperature("CHI", "GB", neutral=False), "visitor is not dome-based"
    assert not needs_temperature("CHI", "DAL", neutral=True), "neutral site voids the rule"
