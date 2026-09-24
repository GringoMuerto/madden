"""Deadlines, missed tranches and games already under way.

The failure these exist for is week 1: the thursday tranche ran at 03:03 UTC on
2026-09-11, after BOTH its games had kicked off -- NE at SEA the previous evening and
SF at LAR two and a half hours earlier. It produced a log, exited 0, and said nothing.
Any check that only asks "is there a log for this tranche" passes that run.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden.run import (already_started, logged_runs, missed_tranches, owning_tranche,
                        tranche_deadlines)
from madden.schedule import kickoff_at
from madden.sheet import Game


def game(fav, dog, home, day, spread=3.5):
    return Game(favorite=fav, underdog=dog, spread=spread, day=day,
                nominal_home=home, row=0)


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


# Week 1 for real, from the nflverse schedule.
NE_SEA = kickoff_at("2026-09-09", "20:20")        # Wednesday night
SF_LAR = kickoff_at("2026-09-10", "20:35")        # Thursday night
CLE_JAX = kickoff_at("2026-09-13", "13:00")       # Sunday early
DEN_KC = kickoff_at("2026-09-14", "20:15")        # Monday night

WEEK1 = [game("SEA", "NE", "SEA", "Wednesday"), game("LAR", "SF", "LAR", "Thursday"),
         game("JAX", "CLE", "JAX", "Sunday"), game("KC", "DEN", "KC", "Monday")]
KICKOFFS = {frozenset(("SEA", "NE")): NE_SEA, frozenset(("LAR", "SF")): SF_LAR,
            frozenset(("JAX", "CLE")): CLE_JAX, frozenset(("KC", "DEN")): DEN_KC}


def test_saturday_belongs_to_the_international_tranche():
    """Saturday is in both day-sets. The overseas kickoff is why that tranche exists."""
    assert owning_tranche("Saturday") == "international"
    assert owning_tranche("Wednesday") == "thursday"
    assert owning_tranche("Thursday") == "thursday"
    assert owning_tranche("Sunday") == "sunday"
    assert owning_tranche("Monday") == "sunday"
    assert owning_tranche("Tuesday") is None


def test_a_deadline_is_the_tranches_earliest_kickoff():
    d = tranche_deadlines(WEEK1, KICKOFFS)
    assert d["thursday"][0] == NE_SEA, "the Wednesday game sets it, not the Thursday one"
    assert d["sunday"][0] == CLE_JAX, "the early Sunday game, not Monday night"
    assert sorted(d) == ["sunday", "thursday"]


def test_a_game_with_no_kickoff_counts_toward_no_deadline():
    d = tranche_deadlines(WEEK1, {frozenset(("JAX", "CLE")): CLE_JAX})
    assert "thursday" not in d and d["sunday"][0] == CLE_JAX


def test_a_tranche_not_yet_due_is_silent():
    d = tranche_deadlines(WEEK1, KICKOFFS)
    assert missed_tranches(d, [], now=utc("2026-09-08 12:00")) == []


def test_a_tranche_that_never_ran_is_reported_with_the_revert_named():
    d = tranche_deadlines(WEEK1, KICKOFFS)
    # After the thursday deadline, before the sunday one, so only one tranche is due.
    out = missed_tranches(d, [], now=utc("2026-09-12 12:00"))
    assert len(out) == 1 and "thursday" in out[0]
    assert "no run covers it" in out[0]
    assert "reverted to the favorite" in out[0]


def test_a_run_that_beat_the_deadline_covers_it():
    d = tranche_deadlines(WEEK1, KICKOFFS)
    runs = [("thursday", utc("2026-09-09 14:00"))]
    assert missed_tranches(d, runs, now=utc("2026-09-12 12:00")) == []


def test_an_all_tranche_run_covers_a_named_tranche():
    d = tranche_deadlines(WEEK1, KICKOFFS)
    runs = [("all", utc("2026-09-09 14:00"))]
    assert missed_tranches(d, runs, now=utc("2026-09-12 12:00")) == []


def test_a_run_written_after_the_deadline_does_not_cover_it():
    """Week 1 exactly. A log exists; it is not a covering run."""
    d = tranche_deadlines(WEEK1, KICKOFFS)
    runs = [("thursday", utc("2026-09-11 03:03"))]          # the real run stamp
    out = missed_tranches(d, runs, now=utc("2026-09-12 12:00"))
    assert len(out) == 1
    assert "after the deadline" in out[0]
    assert "already under way" in out[0]


def test_a_sunday_run_reports_the_thursday_miss_while_it_still_matters():
    d = tranche_deadlines(WEEK1, KICKOFFS)
    out = missed_tranches(d, [("thursday", utc("2026-09-11 03:03"))],
                          now=utc("2026-09-13 11:00"))      # before the Sunday deadline
    assert any("thursday" in line for line in out)
    assert not any("sunday" in line for line in out), "the sunday tranche is not due yet"


def test_already_started_flags_a_game_in_progress():
    late = already_started([game("LAR", "SF", "LAR", "Thursday")], KICKOFFS,
                           now=utc("2026-09-11 03:03"))
    assert late and "already kicked off" in late[0]
    assert any("SF at LAR" in line for line in late)


def test_already_started_is_silent_before_kickoff():
    assert already_started([game("LAR", "SF", "LAR", "Thursday")], KICKOFFS,
                           now=utc("2026-09-10 12:00")) == []


def test_logged_runs_reads_only_this_week(tmp_path):
    (tmp_path / "run-20260909T140000Z-thursday.json").write_text(json.dumps(
        {"run": "20260909T140000Z", "tranche": "thursday", "season": 2026, "week": 1}))
    (tmp_path / "run-20260916T140000Z-thursday.json").write_text(json.dumps(
        {"run": "20260916T140000Z", "tranche": "thursday", "season": 2026, "week": 2}))
    (tmp_path / "run-bad.json").write_text("not json at all")
    runs = logged_runs(tmp_path, 2026, 1)
    assert runs == [("thursday", utc("2026-09-09 14:00"))]


def test_logged_runs_survives_a_log_with_no_stamp(tmp_path):
    (tmp_path / "run-20260909T140000Z-thursday.json").write_text(json.dumps(
        {"tranche": "thursday", "season": 2026, "week": 1}))
    assert logged_runs(tmp_path, 2026, 1) == []


# ---- forecasts: kickoff times come from the schedule ------------------------------

from madden.run import forecast_needs

GB_ATL = kickoff_at("2026-09-24", "20:15")        # week 3, Thursday night


def test_a_forecast_uses_the_schedule_kickoff():
    """Week 3: the odds fetch failed, and ATL at GB went without a forecast."""
    atl_gb = game("GB", "ATL", "GB", "Thursday")
    need, warnings = forecast_needs([atl_gb], {}, {frozenset(("GB", "ATL")): GB_ATL})
    assert need == [("GB", GB_ATL)]
    assert warnings == []


def test_a_game_missing_from_the_schedule_says_so():
    atl_gb = game("GB", "ATL", "GB", "Thursday")
    need, warnings = forecast_needs([atl_gb], {}, {})
    assert need == []
    assert len(warnings) == 1 and "ATL at GB" in warnings[0]


def test_a_supplied_temperature_or_neutral_site_needs_no_forecast():
    atl_gb = game("GB", "ATL", "GB", "Thursday")
    london = Game(favorite="MIN", underdog="CLE", spread=3.0, day="Sunday",
                  nominal_home="CLE", row=0, neutral_site=True)
    kickoffs = {frozenset(("GB", "ATL")): GB_ATL, frozenset(("CLE", "MIN")): GB_ATL}
    need, warnings = forecast_needs([atl_gb, london], {"GB": 58.0}, kickoffs)
    assert need == [] and warnings == []
