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


# Injury fetch, against a canned ESPN. Every earlier version failed silently, so these
# pin the one property that matters: a team is read in full or reported FAILED.

def _espn(pages, entries, athletes, broken=()):
    """A fake GET. pages: {page_no: [entry ids]} for team 1 (ATL)."""
    from madden.injuries import CORE
    count = sum(len(v) for v in pages.values())
    table = {}
    for n, ids in pages.items():
        table[f"{CORE}/teams/1/injuries?page={n}"] = {
            "count": count, "pageCount": len(pages), "items": [{"$ref": f"e/{i}"} for i in ids]}
    for i, (status, date, who) in entries.items():
        table[f"e/{i}"] = {"status": status, "date": date, "athlete": {"$ref": f"a/{who}"}}
    for who, (name, pos) in athletes.items():
        table[f"a/{who}"] = {"displayName": name, "position": {"abbreviation": pos}}

    def get(url):
        if url in broken or url not in table:
            raise RuntimeError(f"HTTPError: 403 Forbidden for {url}")
        return table[url]
    return get


def test_injuries_read_every_page_and_keep_each_players_latest_entry():
    from madden.injuries import fetch_all
    get = _espn(
        pages={1: [1, 2], 2: [3]},
        entries={1: ("Questionable", "2026-09-10T20:00Z", 10),
                 2: ("Out", "2026-08-04T15:00Z", 11),
                 3: ("Active", "2026-09-01T15:00Z", 11)},      # supersedes the old Out
        athletes={10: ("Tua Tagovailoa", "QB"), 11: ("DeAngelo Malone", "LB")})
    r = fetch_all(["ATL"], get=get)["ATL"]
    assert r.fetched and not r.error
    assert [(d.player, d.status) for d in r.quarterbacks(PARAMS["injuries"])] == [
        ("Tua Tagovailoa", "questionable")]
    assert len(r.designations) == 2                       # one per player, not per entry
    assert "out" not in {d.status for d in r.designations}


def test_injury_page_failure_is_failed_not_clean():
    from madden.injuries import CORE, fetch_all, summarise
    get = _espn(pages={1: [1]}, entries={1: ("Out", "2026-09-07T15:00Z", 10)},
                athletes={10: ("Michael Penix Jr.", "QB")},
                broken={f"{CORE}/teams/1/injuries?page=1"})
    reports = fetch_all(["ATL"], get=get)
    assert not reports["ATL"].fetched and "403" in reports["ATL"].error
    health = summarise(reports, PARAMS["injuries"])
    assert any(h.startswith("INJURY FETCH FAILED") and "403" in h for h in health)
    assert not any("no quarterback" in h for h in health)


def test_unreadable_entries_fail_the_team():
    # The exact failure of the previous version: pointers listed, contents never read.
    from madden.injuries import fetch_all
    get = _espn(pages={1: [1, 2]},
                entries={1: ("Out", "2026-09-07T15:00Z", 10),
                         2: ("Questionable", "2026-09-10T20:00Z", 11)},
                athletes={10: ("A", "QB"), 11: ("B", "QB")}, broken={"e/2"})
    r = fetch_all(["ATL"], get=get)["ATL"]
    assert not r.fetched and "1 of 2 entries unreadable" in r.error


def test_zero_injury_entries_is_failed():
    from madden.injuries import fetch_all
    r = fetch_all(["ATL"], get=_espn(pages={1: []}, entries={}, athletes={}))["ATL"]
    assert not r.fetched and "no injury entries" in r.error


def test_unreadable_athlete_behind_a_live_designation_fails_the_team():
    from madden.injuries import fetch_all
    get = _espn(pages={1: [1]}, entries={1: ("Out", "2026-09-07T15:00Z", 10)},
                athletes={}, broken={"a/10"})
    r = fetch_all(["ATL"], get=get)["ATL"]
    assert not r.fetched and "athlete" in r.error


def test_nothing_is_written_to_disk_without_the_cache_flag(tmp_path, monkeypatch):
    from madden import injuries
    monkeypatch.setattr(injuries, "CACHE", tmp_path / ".cache")
    get = _espn(pages={1: [1]}, entries={1: ("Questionable", "2026-09-10T20:00Z", 10)},
                athletes={10: ("Tua Tagovailoa", "QB")})
    injuries.fetch_all(["ATL"], get=get)
    assert not (tmp_path / ".cache").exists()
