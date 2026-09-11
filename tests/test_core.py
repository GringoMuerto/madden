"""Tests that pin the things which silently invert the whole system.

The sign convention is the dangerous one. Situational points are added to the HOME team,
so a negative adjustment favours the visitor. A previous reconstruction had this rule at
-3.3 with an invented 70F companion rule, and it flipped picks in six games.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden.core import band_for, crosses_key_number, make_pick, situational_adjustments
from madden.sheet import Game, SheetFault, parse_sheet

PARAMS = yaml.safe_load((Path(__file__).resolve().parents[1] / "params.yaml").read_text())


def game(fav, dog, spread, home, day="Sunday", neutral=False):
    g = Game(favorite=fav, underdog=dog, spread=spread, day=day, nominal_home=home, row=0)
    g.neutral_site = neutral
    return g


def test_spec_values_are_exact():
    s = PARAMS["situational"]
    assert s["dome_visitor_outdoors_75f"]["points"] == -2.8
    assert s["home_underdog_7plus"]["points"] == 2.3
    assert s["divisional"]["points"] == -0.8
    assert s["global_home_baseline"]["points"] == -0.3
    assert "outdoor_70f" not in s, "there is no 70F rule in the spec"


def test_global_baseline_applies_to_every_game():
    g = game("BAL", "IND", 3.5, home="IND")          # no other rule fires
    adj, _ = situational_adjustments(g, PARAMS)
    assert [a.rule for a in adj] == ["global_home_baseline"]


def test_baseline_alone_takes_the_road_team():
    g = game("BAL", "IND", 3.5, home="IND")
    p = make_pick(g, market_home_line=-3.5, params=PARAMS)
    assert p.edge == -0.3 and p.side == "BAL" and p.band == "coin flip"


def test_dome_visitor_outdoors_favours_the_visitor():
    # Atlanta is dome-based, Pittsburgh is outdoors at 79F.
    g = game("PIT", "ATL", 2.5, home="PIT")
    adj, _ = situational_adjustments(g, PARAMS, temp_f=79)
    assert {a.rule for a in adj} == {"global_home_baseline", "dome_visitor_outdoors_75f"}
    p = make_pick(g, market_home_line=3.5, params=PARAMS, temp_f=79)
    assert p.adjustment_total == -3.1
    assert p.side == "ATL" and p.band == "medium"


def test_rule_does_not_fire_below_75f():
    g = game("PIT", "ATL", 2.5, home="PIT")
    adj, _ = situational_adjustments(g, PARAMS, temp_f=74)
    assert all(a.rule != "dome_visitor_outdoors_75f" for a in adj)


def test_rule_does_not_fire_indoors():
    # New Orleans is dome-based but Detroit plays under a fixed roof.
    g = game("DET", "NO", 6.5, home="DET")
    adj, _ = situational_adjustments(g, PARAMS, temp_f=90)
    assert all(a.rule != "dome_visitor_outdoors_75f" for a in adj)


def test_divisional_and_dome_visitor_stack():
    # Dallas is dome-based, MetLife is outdoors at 77F, and it is an NFC East game.
    g = game("DAL", "NYG", 2.5, home="NYG")
    p = make_pick(g, market_home_line=-2.5, params=PARAMS, temp_f=77)
    assert p.adjustment_total == -3.9
    assert p.madden_number == -6.4 and p.edge == -3.9
    assert p.side == "DAL" and p.band == "high"


def test_home_underdog_of_seven_plus():
    g = game("KC", "CAR", 8.5, home="CAR")
    adj, _ = situational_adjustments(g, PARAMS, temp_f=60)
    assert any(a.rule == "home_underdog_7plus" and a.points == 2.3 for a in adj)


def test_neutral_site_voids_home_rules():
    g = game("LAR", "SF", 3.5, home="LAR", day="Thursday", neutral=True)
    adj, warn = situational_adjustments(g, PARAMS, temp_f=60)
    assert [a.rule for a in adj] == ["divisional"]
    assert any("neutral site" in w for w in warn)


def test_key_number_upgrades_to_high():
    # Chargers 10.5 on the sheet, 9.5 in the market: the edge steps across 10.
    g = game("LAC", "ARI", 10.5, home="LAC")
    p = make_pick(g, market_home_line=9.5, params=PARAMS, temp_f=70)
    assert p.edge == -1.3
    assert p.band == "high" and p.side == "ARI"


def test_crossing_detection_handles_home_dogs():
    assert crosses_key_number(-6.4, -2.5, [3, 7, 10, 14]) == 3
    assert crosses_key_number(3.2, 3.5, [3, 7, 10, 14]) is None


def test_missing_line_is_never_fabricated():
    g = game("BAL", "IND", 3.5, home="IND")
    p = make_pick(g, market_home_line=None, params=PARAMS)
    assert p.side is None and p.blind and p.madden_number is None


def test_band_thresholds():
    assert band_for(3.0, 0, 3.0, PARAMS)[0] == "high"
    assert band_for(1.5, 20.0, 18.5, PARAMS)[0] == "medium"
    assert band_for(0.4, 20.0, 19.6, PARAMS)[0] == "coin flip"


def _write_sheet(path, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws["C1"] = "2026-2027 NFL Picks"
    ws["C5"] = "HOME TEAM IN CAPITAL LETTERS."
    ws["E6"], ws["G6"], ws["J6"], ws["M6"], ws["O6"] = (
        "Favorite", "W-L", "Spread", "W-L", "Underdog")
    r = 8
    for day, fav, spread, dog in rows:
        if day:
            ws.cell(row=r, column=10, value=f"{day} Games")
            r += 2
        ws.cell(row=r, column=5, value=fav)
        ws.cell(row=r, column=10, value=spread)
        ws.cell(row=r, column=15, value=dog)
        r += 2
    wb.save(path)


def test_parser_reads_layout_and_home_capitalisation(tmp_path):
    p = tmp_path / "sheet.xlsx"
    _write_sheet(p, [
        ("Thursday", "LOS ANGELES RAMS", 3.5, "San Francisco 49ers"),
        ("Sunday", "Baltimore Ravens", 3.5, "INDIANAPOLIS COLTS"),
        (None, "KANSAS CITY CHIEFS", 2.5, "Denver Broncos"),
    ])
    games = parse_sheet(str(p), expected_games=3)
    assert [g.day for g in games] == ["Thursday", "Sunday", "Sunday"]
    assert games[0].home == "LAR" and games[0].sheet_home_line == 3.5
    assert games[1].home == "IND" and games[1].sheet_home_line == -3.5
    assert games[2].favorite == "KC"


def test_game_count_mismatch_is_a_hard_stop(tmp_path):
    p = tmp_path / "sheet.xlsx"
    _write_sheet(p, [("Sunday", "KANSAS CITY CHIEFS", 2.5, "Denver Broncos")])
    with pytest.raises(SheetFault):
        parse_sheet(str(p), expected_games=16)


def test_neutral_site_declaration_flows_through_the_parser(tmp_path):
    p = tmp_path / "sheet.xlsx"
    _write_sheet(p, [("Thursday", "LOS ANGELES RAMS", 3.5, "San Francisco 49ers")])
    games = parse_sheet(str(p), neutral_sites=[("LAR", "SF")])
    assert games[0].neutral_site
