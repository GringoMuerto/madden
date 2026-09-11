"""Tests that pin the things which silently invert the whole system.

The sign convention is the dangerous one. Situational points are added to the HOME team,
so a negative adjustment favours the visitor. A previous reconstruction had this rule at
-3.3 with an invented 70F companion rule, and it flipped picks in six games.
"""

import sys
from datetime import datetime, timezone
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


def _event(home, away, home_spread, kickoff):
    """One odds-api event with a single book quoting the home team at `home_spread`."""
    return {
        "home_team": home, "away_team": away, "commence_time": kickoff,
        "bookmakers": [{"last_update": kickoff, "markets": [{"key": "spreads", "outcomes": [
            {"name": home, "point": home_spread}, {"name": away, "point": -home_spread}]}]}],
    }


# Market tests run at a fixed moment, never the wall clock: soonest() drops a game once it
# has kicked off, so a test pinned to real kickoffs breaks the day those games are played.
WEEK1_TUESDAY = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def test_divisional_rematch_does_not_overwrite_this_weeks_line():
    # Week 1 at the Giants, NYG -2.5. The week 17 rematch in Dallas, DAL -4.5, comes back
    # in the same payload. The run must price week 1, oriented to the sheet's home team.
    # A rematch months away is a different game, not an ambiguity, so it must NOT warn:
    # warning on the normal case trains the reader to skip run health (commit 0fcb959).
    from madden.market import parse_odds_payload, soonest
    payload = [
        _event("Dallas Cowboys", "New York Giants", -4.5, "2026-12-27T18:00:00Z"),
        _event("New York Giants", "Dallas Cowboys", -2.5, "2026-09-13T17:00:00Z"),
    ]
    lines = parse_odds_payload(payload, PARAMS)
    ml, warnings = soonest(lines, "NYG", "DAL", now=WEEK1_TUESDAY)
    assert ml.commence_time.startswith("2026-09-13")
    assert ml.line_for("NYG") == 2.5
    assert not any("meetings" in w for w in warnings)


def test_two_meetings_inside_the_window_do_warn():
    from madden.market import parse_odds_payload, soonest
    payload = [
        _event("New York Giants", "Dallas Cowboys", -2.5, "2026-09-13T17:00:00Z"),
        _event("Dallas Cowboys", "New York Giants", -4.5, "2026-09-17T00:15:00Z"),
    ]
    ml, warnings = soonest(parse_odds_payload(payload, PARAMS), "NYG", "DAL",
                           now=WEEK1_TUESDAY)
    assert ml.commence_time.startswith("2026-09-13")
    assert any("2 meetings" in w for w in warnings)


def test_a_game_already_kicked_off_has_no_line():
    from madden.market import parse_odds_payload, soonest
    payload = [_event("New York Giants", "Dallas Cowboys", -2.5, "2026-09-13T17:00:00Z")]
    after = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
    ml, warnings = soonest(parse_odds_payload(payload, PARAMS), "NYG", "DAL", now=after)
    assert ml is None and any("already kicked off" in w for w in warnings)


def test_line_is_reoriented_when_the_feed_disagrees_about_home():
    from madden.market import parse_odds_payload, soonest
    payload = [_event("San Francisco 49ers", "Los Angeles Rams", -1.5, "2026-09-11T10:35:00Z")]
    ml, warnings = soonest(parse_odds_payload(payload, PARAMS), "LAR", "SF",
                           now=WEEK1_TUESDAY)
    assert ml.line_for("LAR") == -1.5
    assert any("re-oriented" in w for w in warnings)


# Quarterback exposure, against a canned nflverse. Names only: nothing here may carry a
# number, and a team with no data is UNKNOWN, never clean.

INJ_HEADER = ("season,season_type,game_type,team,week,gsis_id,position,full_name,first_name,"
              "last_name,report_primary_injury,report_status,practice_primary_injury,"
              "practice_secondary_injury,practice_status")


def _nflverse(rows, depth=(), broken=()):
    """A fake GET. rows: (team, week, gsis, pos, name, report_status, practice_status, injury)."""
    import gzip
    import json as _json
    from madden.injuries import RELEASE_API, RELEASES
    lines = [INJ_HEADER] + [
        f"2026,REG,REG,{t},{w},{g},{pos},{n},,,{inj},{rs},,,{ps}"
        for t, w, g, pos, n, rs, ps, inj in rows]
    dlines = ["dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,pos_name,"
              "pos_abb,pos_slot,pos_rank"] + [
        f"2026-09-10T12:01:46Z,{t},{n},,{g},21,3WR 1TE,8,Quarterback,QB,8,{rank}"
        for t, g, n, rank in depth]
    table = {
        f"{RELEASES}/injuries/injuries_2026.csv": "\n".join(lines).encode(),
        f"{RELEASE_API}/injuries": _json.dumps({"assets": [
            {"name": "injuries_2026.csv", "updated_at": "2026-09-13T12:03:24Z"}]}).encode(),
        f"{RELEASES}/depth_charts/depth_charts_2026.csv.gz":
            gzip.compress("\n".join(dlines).encode()),
    }

    def get(url):
        if any(b in url for b in broken) or url not in table:
            raise RuntimeError(f"HTTP Error 404 for {url}")
        return table[url]
    return get


ATL_DEPTH = [("ATL", "g-tua", "Tua Tagovailoa", 1), ("ATL", "g-penix", "Michael Penix Jr.", 2)]


def test_exposure_names_an_unresolved_quarterback_with_rank_and_no_points():
    from madden import injuries
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([
        ("ATL", 1, "g-tua", "QB", "Tua Tagovailoa", "Questionable",
         "Limited Participation in Practice", "Oblique"),
        ("PIT", 1, "g-x", "CB", "Donte Kent", "Out", "", "Knee"),
    ], depth=ATL_DEPTH))
    names, unknown = injuries.exposure(rep, "PIT", "ATL")
    assert names == ["ATL QB Tua Tagovailoa (QB1), Questionable (Oblique)"]
    assert unknown == []
    assert rep.built == "2026-09-13T12:03:24Z"


def test_out_and_full_participation_are_resolved():
    from madden import injuries
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([
        ("ATL", 1, "g-penix", "QB", "Michael Penix Jr.", "Out", "", "Knee"),
        ("WAS", 1, "g-mar", "QB", "Marcus Mariota", "", "Full Participation in Practice", "Knee"),
    ], depth=ATL_DEPTH))
    assert injuries.exposure(rep, "PIT", "ATL") == ([], ["PIT"])
    assert injuries.exposure(rep, "PHI", "WAS") == ([], ["PHI"])


def test_no_game_status_counts_only_until_the_final_report():
    from madden import injuries
    dnp = ("CHI", 1, "g-bag", "QB", "Tyson Bagent", "", "Did Not Participate In Practice", "Back")
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([dnp, ("CAR", 1, "g-c", "OT", "X", "", "", "")]))
    names, _ = injuries.exposure(rep, "CAR", "CHI")
    assert names == ["CHI QB Tyson Bagent (not on the depth chart), no game status yet, "
                     "did not practice (Back)"]
    # Once any Chicago player carries a game status, the final report is out and a blank
    # status means no designation.
    final = ("CHI", 1, "g-g", "CB", "Kyler Gordon", "Out", "", "Hamstring")
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([dnp, final, ("CAR", 1, "g-c", "OT", "X", "", "", "")]))
    assert injuries.exposure(rep, "CAR", "CHI") == ([], [])


def test_team_missing_from_the_report_is_unknown_not_clean():
    from madden import injuries
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([("DEN", 2, "g-n", "QB", "Bo Nix", "", "", "")]))
    assert injuries.exposure(rep, "KC", "DEN") == ([], ["DEN", "KC"])


def test_report_fetch_failure_is_unknown_for_every_game():
    from madden import injuries
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([], broken=("injuries_2026.csv",)))
    assert rep.error and "404" in rep.error
    assert injuries.exposure(rep, "PIT", "ATL") == ([], ["ATL", "PIT"])
    assert injuries.header(rep).startswith("INJURY REPORT FETCH FAILED")


def test_depth_chart_failure_names_without_rank_and_warns():
    from madden import injuries
    rep, warns = injuries.fetch(2026, 1, get=_nflverse([
        ("ATL", 1, "g-tua", "QB", "Tua Tagovailoa", "Doubtful", "", "Oblique"),
    ], broken=("depth_charts",)))
    assert injuries.exposure(rep, "PIT", "ATL")[0] == ["ATL QB Tua Tagovailoa, Doubtful (Oblique)"]
    assert any("depth chart unavailable" in w for w in warns)


def test_nflverse_rams_are_lar():
    from madden import injuries
    rep, _ = injuries.fetch(2026, 1, get=_nflverse([
        ("LA", 1, "g-s", "QB", "Matthew Stafford", "Questionable", "", "Back")]))
    assert injuries.exposure(rep, "LAR", "SF")[0] == [
        "LAR QB Matthew Stafford (not on the depth chart), Questionable (Back)"]


def test_forecast_is_not_written_to_disk_without_the_cache_flag(tmp_path, monkeypatch):
    from madden import weather
    monkeypatch.setattr(weather, "CACHE", tmp_path / ".cache")
    monkeypatch.setattr(weather, "_fetch", lambda lat, lon, timeout: {"hourly": {
        "time": ["2026-09-13T17:00"], "temperature_2m": [80.4], "wind_speed_10m": [5.0]}})
    kickoff = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
    assert weather.forecast("PIT", kickoff) == (80.4, 5.0)
    assert not (tmp_path / ".cache").exists()
