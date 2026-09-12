"""Starter health and the injured-quarterback list: display only, and never a price."""

import gzip
import json as _json
import pathlib

INJ_HEADER = ("season,season_type,game_type,team,week,gsis_id,position,full_name,first_name,"
              "last_name,report_primary_injury,report_status,practice_primary_injury,"
              "practice_secondary_injury,practice_status")
DEPTH_HEADER = ("dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,pos_name,"
                "pos_abb,pos_slot,pos_rank")
DT = "2026-09-11T12:21:50Z"


def _get(inj_rows, depth_rows, broken=()):
    """inj: (team, gsis, pos, name, report_status, practice_status, injury, secondary).
       depth: (team, group, pos_abb, rank, gsis, name)."""
    from madden.injuries import RELEASE_API, RELEASES
    lines = [INJ_HEADER] + [
        f"2026,REG,REG,{t},1,{g},{pos},{n},,,{inj},{rs},,{sec},{ps}"
        for t, g, pos, n, rs, ps, inj, sec in inj_rows]
    dlines = [DEPTH_HEADER] + [
        f"{DT},{t},{n},,{g},1,{grp},1,{pos},{pos},1,{rank}"
        for t, grp, pos, rank, g, n in depth_rows]
    table = {
        f"{RELEASES}/injuries/injuries_2026.csv": "\n".join(lines).encode(),
        f"{RELEASE_API}/injuries": _json.dumps({"assets": [
            {"name": "injuries_2026.csv", "updated_at": "2026-09-11T12:12:00Z"}]}).encode(),
        f"{RELEASES}/depth_charts/depth_charts_2026.csv.gz":
            gzip.compress("\n".join(dlines).encode()),
    }

    def get(url):
        if any(b in url for b in broken) or url not in table:
            raise RuntimeError(f"HTTP Error 404 for {url}")
        return table[url]
    return get


OFF = "3WR 1TE"
DEF = "Base 4-3 D"
# Two men a side, which is enough to count: the arithmetic does not care how many.
KC_DEPTH = [("KC", OFF, "QB", 1, "g-mah", "Patrick Mahomes"),
            ("KC", OFF, "LT", 1, "g-sim", "Josh Simmons"),
            ("KC", DEF, "LCB", 1, "g-sne", "L'Jarius Sneed"),
            ("KC", DEF, "SS", 1, "g-con", "Chamarri Conner"),
            ("KC", OFF, "QB", 2, "g-fie", "Justin Fields")]


def test_health_counts_starters_with_no_row_as_healthy():
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-sim", "OT", "Josh Simmons", "", "Did Not Participate In Practice", "Back", ""),
    ], KC_DEPTH))
    assert health.health(rep, ["KC"]) == [("KC", 1, 2, 2, 2)]


def test_a_full_participation_note_still_counts_against_the_team():
    """The blunt instrument, pinned deliberately: the chart counts rows, not severity."""
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-mah", "QB", "Patrick Mahomes", "", "Full Participation in Practice", "Knee", ""),
        ("KC", "g-sne", "CB", "L'Jarius Sneed", "", "Full Participation in Practice", "Knee", ""),
    ], KC_DEPTH))
    assert health.health(rep, ["KC"]) == [("KC", 1, 2, 1, 2)]


def test_a_backup_on_the_report_does_not_move_starter_health():
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-fie", "QB", "Justin Fields", "", "Did Not Participate In Practice", "Rib", ""),
    ], KC_DEPTH))
    assert health.health(rep, ["KC"]) == [("KC", 2, 2, 2, 2)]


def test_a_team_absent_from_the_depth_chart_is_unknown_not_clean():
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([], KC_DEPTH))
    assert health.health(rep, ["DEN"]) == [("DEN", 0, 0, 0, 0)]


def test_receivers_ranked_one_to_three_are_all_starters():
    from madden import health, injuries
    depth = [("KC", OFF, "WR", r, f"g-wr{r}", f"Receiver {r}") for r in (1, 2, 3, 4)]
    rep, _ = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-wr3", "WR", "Receiver 3", "", "Limited Participation in Practice", "Calf", ""),
        ("KC", "g-wr4", "WR", "Receiver 4", "", "Did Not Participate In Practice", "Calf", ""),
    ], depth))
    # Three starters at receiver, one of them listed. The fourth is not a starter.
    assert health.health(rep, ["KC"]) == [("KC", 2, 3, 0, 0)]


def test_injured_quarterbacks_include_resolved_ones_and_carry_their_rank():
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-fie", "QB", "Justin Fields", "Out", "", "Rib", ""),
        ("KC", "g-mah", "QB", "Patrick Mahomes", "", "Full Participation in Practice", "Knee", ""),
    ], KC_DEPTH))
    assert health.quarterbacks(rep, ["KC"]) == [("KC", [
        ("QB1", "Patrick Mahomes", "no game status yet, full participation (Knee)"),
        ("QB2", "Justin Fields", "Out (Rib)"),
    ])]
    # Exposure stays narrower: Out is resolved, full participation is resolved.
    assert injuries.exposure(rep, "KC", "DEN")[0] == []


def test_a_secondary_injury_is_named_and_a_rest_day_says_rest():
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-mah", "QB", "Patrick Mahomes", "", "Limited Participation in Practice",
         "Not injury related - resting player", "Knee"),
    ], KC_DEPTH))
    assert health.quarterbacks(rep, ["KC"])[0][1] == [
        ("QB1", "Patrick Mahomes", "no game status yet, limited in practice (rest / Knee)")]


def test_depth_chart_failure_leaves_health_unknown_and_ranks_unavailable():
    from madden import health, injuries
    rep, warns = injuries.fetch(2026, 1, get=_get([
        ("KC", "g-mah", "QB", "Patrick Mahomes", "Questionable", "", "Knee", ""),
    ], KC_DEPTH, broken=("depth_charts",)))
    assert health.health(rep, ["KC"]) == [("KC", 0, 0, 0, 0)]
    assert health.quarterbacks(rep, ["KC"])[0][1] == [
        ("QB?", "Patrick Mahomes", "Questionable (Knee)")]
    assert any("starter health is UNKNOWN" in w for w in warns)


def test_report_failure_is_unknown_for_every_team():
    from madden import health, injuries
    rep, _ = injuries.fetch(2026, 1, get=_get([], KC_DEPTH, broken=("injuries_2026.csv",)))
    assert rep.error
    assert health.health(rep, ["KC"]) == [("KC", 0, 0, 0, 0)]
    assert health.quarterbacks(rep, ["KC"]) == [("KC", [])]


def test_health_never_reaches_the_pick_arithmetic():
    """The layer is display only, and that is enforced here rather than in prose."""
    core = (pathlib.Path(__file__).resolve().parents[1] / "madden" / "core.py").read_text()
    assert "health" not in core
    assert "injur" not in core.lower()


def test_a_blocked_log_write_is_a_run_health_line_not_a_traceback(tmp_path):
    """2026-09-11: an unhandled PermissionError took the run down after the board had
    printed, exiting 1 with a traceback and leaving no log. A write that cannot land
    degrades and warns like any other data fault."""
    import argparse
    from madden import run as run_mod

    blocked = tmp_path / "logs"
    blocked.mkdir()
    blocked.chmod(0o555)
    args = argparse.Namespace(log=str(blocked), tranche="sunday", cache=False)
    resolved = run_mod.schedule.Resolution(season=2026, week=1, matched=16, total=16,
                                           source="nflverse")
    path, problem = run_mod.write_log(
        args, {"spec_version": "2026-09-11"}, tmp_path / "sheet.xlsx", resolved,
        None, {}, {}, {}, {}, [], [], ["an earlier warning"])
    assert path is None
    assert problem is not None
    assert "could not be written" in problem
    blocked.chmod(0o755)


def test_a_log_write_that_lands_returns_its_path(tmp_path):
    import argparse, json
    from madden import run as run_mod

    args = argparse.Namespace(log=str(tmp_path / "logs"), tranche="sunday", cache=False)
    resolved = run_mod.schedule.Resolution(season=2026, week=1, matched=16, total=16,
                                           source="nflverse")
    path, problem = run_mod.write_log(
        args, {"spec_version": "2026-09-11"}, tmp_path / "sheet.xlsx", resolved,
        None, {}, {}, {}, {}, [], [], ["an earlier warning"])
    assert problem is None
    assert json.loads(path.read_text())["warnings"] == ["an earlier warning"]
