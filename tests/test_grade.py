"""The grading harness. No network: every test supplies its own score table.

What these pin is the arithmetic that turns a log plus a scoreboard into a record. The
sign convention is pinned here as well as in test_core, deliberately: test_core proves the
engine picks the side the edge points to, and this proves the grader agrees about which
side actually covered. Get either backwards and the scoreboard quietly reports the
complement of the truth, which is the one failure that would never look like a bug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden.grade import GradeFault, grade_log, resolve_week


def log(picks, season=2026, week=1, tranche="sunday"):
    return {"run": "TEST", "tranche": tranche, "season": season, "week": week,
            "picks": picks}


def pick(game, sheet_line, side, band="coin flip", deviation=False, market_line=None):
    return {"game": game, "sheet_line": sheet_line, "pick": side, "band": band,
            "deviation": deviation, "market_line": market_line}


def test_home_favorite_covering_is_graded_to_the_home_team():
    # JAX favored by 7.5 at home, wins by 24. The favorite covers.
    results = {(2026, 1, "CLE", "JAX"): (10, 34)}
    g = grade_log(log([pick("CLE@JAX", 7.5, "JAX")]), results)
    r = g["rows"][0]
    assert r["favorite"] == "JAX" and r["covered"] == "JAX"
    assert r["pick_hit"] and g["madden"] == (1, 1) and g["favorite"] == (1, 1)


def test_a_home_underdog_line_is_read_the_right_way_round():
    """Sheet line -2.5 means the HOME team is a 2.5 dog, so the away team is the favorite.

    CHI won at CAR by 22. The away favorite covered, and a grader that read the negative
    line as a home favorite would score this exactly backwards.
    """
    results = {(2026, 1, "CHI", "CAR"): (59, 37)}
    g = grade_log(log([pick("CHI@CAR", -2.5, "CHI")]), results)
    r = g["rows"][0]
    assert r["favorite"] == "CHI" and r["covered"] == "CHI" and r["margin"] == -22
    assert r["pick_hit"]


def test_the_favorite_can_win_and_still_not_cover():
    # DET favored by 6.5 at home, wins by 1. The dog covers.
    results = {(2026, 1, "NO", "DET"): (30, 31)}
    g = grade_log(log([pick("NO@DET", 6.5, "DET")]), results)
    assert g["rows"][0]["covered"] == "NO"
    assert g["madden"] == (0, 1) and g["favorite"] == (0, 1)


def test_a_withheld_pick_reverts_to_the_favorite_and_is_counted_apart():
    """The pool scores a blank as the favorite, so it lands in submitted, never in made."""
    results = {(2026, 1, "NE", "SEA"): (10, 13)}
    g = grade_log(log([pick("NE@SEA", 3.5, None, band="blind")]), results)
    r = g["rows"][0]
    assert r["reverted"] and r["submitted"] == "SEA" and r["covered"] == "NE"
    assert g["madden"] == (0, 0), "a game with no pick is not one of Madden's picks"
    assert g["submitted"] == (0, 1), "but it is one of Scott's, and it lost"
    assert len(g["reverts"]) == 1


def test_deviation_and_band_records_split_out():
    results = {(2026, 1, "ARI", "LAC"): (26, 14),     # dev, high, win
               (2026, 1, "GB", "MIN"): (22, 39),      # dev, coin flip, loss
               (2026, 1, "ATL", "PIT"): (13, 20)}     # not a dev, high, win
    g = grade_log(log([
        pick("ARI@LAC", 10.5, "ARI", band="high", deviation=True),
        pick("GB@MIN", 1.5, "GB", band="coin flip", deviation=True),
        pick("ATL@PIT", 2.5, "PIT", band="high", deviation=False)]), results)
    assert g["madden"] == (2, 3)
    assert g["favorite"] == (2, 3)
    assert g["deviations"] == (1, 2)
    assert g["bands"] == {"high": (2, 2), "coin flip": (0, 1)}


def test_market_side_skips_a_game_with_no_drift():
    """No drift is no market side. Scoring it as one would invent a baseline pick."""
    results = {(2026, 1, "TB", "CIN"): (27, 33), (2026, 1, "CLE", "JAX"): (10, 34)}
    g = grade_log(log([
        pick("TB@CIN", 3.5, "TB", market_line=3.5),        # no drift: excluded
        pick("CLE@JAX", 7.5, "JAX", market_line=8.5)]),    # drift to JAX, JAX covered
        results)
    assert g["market_side"] == (1, 1)


def test_a_push_is_reported_rather_than_scored():
    """The operator sets half points so this cannot happen. If it does, it is said."""
    results = {(2026, 1, "NE", "SEA"): (10, 13)}
    g = grade_log(log([pick("NE@SEA", 3.0, "SEA")]), results)
    assert g["rows"] == [] and g["madden"] == (0, 0)
    assert any("push" in u for u in g["ungraded"])


def test_a_game_with_no_final_score_is_left_ungraded_not_scored_zero():
    g = grade_log(log([pick("CLE@JAX", 7.5, "JAX")]), {})
    assert g["rows"] == [] and g["madden"] == (0, 0)
    assert any("no final score" in u for u in g["ungraded"])


def test_a_log_with_no_week_is_resolved_from_its_pairings():
    """The week 1 thursday log carries season: null. It is still gradeable."""
    results = {(2026, 1, "SF", "LAR"): (27, 7), (2026, 1, "NE", "SEA"): (10, 13)}
    assert resolve_week({"picks": [{"game": "SF@LAR"}]}, results) == (2026, 1)


def test_a_log_whose_games_match_nothing_refuses_to_guess():
    with pytest.raises(GradeFault):
        resolve_week({"picks": [{"game": "SF@LAR"}]}, {})
