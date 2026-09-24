"""The engine's four input checks, against real git repos with a local bare "origin".

Nothing here touches the real remote: every repo and every origin is made under tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden import guard
from madden.guard import Refusal
from madden.run import NoTrancheLeft, choose_tranche
from madden.schedule import kickoff_at
from madden.sheet import Game

REPO_ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def commit(repo, name, text):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"change {name}")


@pytest.fixture
def repo(tmp_path):
    """A checkout on main, in step with a bare origin, with an engine file and params."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "madden"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    git(work, "remote", "add", "origin", str(origin))
    (work / ".gitignore").write_text(".env\nlogs/\n.cache/\n.codex/\n")
    (work / "madden").mkdir()
    (work / "madden" / "core.py").write_text("X = 1\n")
    (work / "params.yaml").write_text("a: 1\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "init")
    git(work, "push", "-q", "-u", "origin", "main")
    return work


def other_clone(repo, tmp_path):
    """A second clone of the same origin, standing in for work pushed from elsewhere."""
    origin = git(repo, "remote", "get-url", "origin").strip()
    clone = tmp_path / "elsewhere"
    subprocess.run(["git", "clone", "-q", origin, str(clone)], check=True)
    return clone


def unreachable(repo, tmp_path):
    git(repo, "remote", "set-url", "origin", str(tmp_path / "no-such-origin.git"))


# ---- check 1: in step with GitHub ----------------------------------------------------

def test_in_step_passes_silently(repo):
    assert guard.in_step_with_github(repo) is None


def test_behind_origin_refuses(repo, tmp_path):
    clone = other_clone(repo, tmp_path)
    commit(clone, "madden/core.py", "X = 2\n")
    git(clone, "push", "-q", "origin", "main")
    with pytest.raises(Refusal, match="behind GitHub"):
        guard.in_step_with_github(repo)


def test_ahead_of_origin_refuses(repo):
    commit(repo, "madden/core.py", "X = 2\n")
    with pytest.raises(Refusal, match="ahead of GitHub"):
        guard.in_step_with_github(repo)


def test_split_from_origin_refuses(repo, tmp_path):
    clone = other_clone(repo, tmp_path)
    commit(clone, "madden/core.py", "X = 2\n")
    git(clone, "push", "-q", "origin", "main")
    commit(repo, "params.yaml", "a: 2\n")
    with pytest.raises(Refusal, match="split"):
        guard.in_step_with_github(repo)


def test_not_on_main_refuses(repo):
    git(repo, "checkout", "-q", "-b", "experiment")
    with pytest.raises(Refusal, match="not main"):
        guard.in_step_with_github(repo)


def test_unreachable_origin_with_nothing_local_warns(repo, tmp_path):
    unreachable(repo, tmp_path)
    warning = guard.in_step_with_github(repo)
    assert warning.startswith("CODE NOT CHECKED AGAINST GITHUB: the engine could not "
                              "reach GitHub")
    assert "cannot confirm GitHub has no newer work" in warning
    assert "last successful check" in warning


def test_unreachable_origin_with_local_only_commits_refuses(repo, tmp_path):
    commit(repo, "madden/core.py", "X = 2\n")
    unreachable(repo, tmp_path)
    with pytest.raises(Refusal, match="last downloaded copy of GitHub lacks"):
        guard.in_step_with_github(repo)


def test_a_fetch_that_hangs_is_cut_off_and_warns(repo, monkeypatch):
    real = guard._git

    def slow(r, *args, timeout=None):
        if args[:1] == ("fetch",):
            raise subprocess.TimeoutExpired("git fetch", timeout)
        return real(r, *args, timeout=timeout)

    monkeypatch.setattr(guard, "_git", slow)
    warning = guard.in_step_with_github(repo, timeout=15)
    assert "no answer within 15 seconds" in warning


# ---- check 2: nothing uncommitted ----------------------------------------------------

def test_a_clean_repo_passes(repo):
    guard.nothing_uncommitted(repo)


def test_a_modified_engine_file_refuses_and_names_it(repo):
    (repo / "madden" / "core.py").write_text("X = 99\n")
    with pytest.raises(Refusal, match=r"madden/core\.py"):
        guard.nothing_uncommitted(repo)


def test_modified_params_refuses(repo):
    (repo / "params.yaml").write_text("a: 99\n")
    with pytest.raises(Refusal, match=r"params\.yaml"):
        guard.nothing_uncommitted(repo)


def test_a_staged_change_refuses(repo):
    (repo / "params.yaml").write_text("a: 99\n")
    git(repo, "add", "params.yaml")
    with pytest.raises(Refusal, match=r"params\.yaml"):
        guard.nothing_uncommitted(repo)


def test_an_untracked_file_anywhere_refuses(repo):
    """A new file beside the engine could shadow a module it imports."""
    (repo / "madden" / "json.py").write_text("")
    with pytest.raises(Refusal, match=r"madden/json\.py"):
        guard.nothing_uncommitted(repo)


def test_ignored_files_do_not_trip_it(repo):
    (repo / ".env").write_text("ODDS_API_KEY=x\n")
    (repo / "logs").mkdir()
    (repo / "logs" / "run.json").write_text("{}")
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text("")
    guard.nothing_uncommitted(repo)


def test_a_long_list_is_cut_short(repo):
    for i in range(8):
        (repo / f"stray{i}.txt").write_text("")
    with pytest.raises(Refusal, match="and 3 more"):
        guard.nothing_uncommitted(repo)


# ---- check 3: input files live in the repo and are committed ------------------------

def test_a_week_file_outside_the_repo_refuses(repo, tmp_path):
    outside = tmp_path / "week.yaml"
    outside.write_text("blind: []\n")
    with pytest.raises(Refusal, match="--week file .* is outside the repo"):
        guard.committed_input(outside, "--week", repo)


def test_an_untracked_week_file_refuses(repo):
    f = repo / "examples" / "week9.yaml"
    f.parent.mkdir()
    f.write_text("blind: []\n")
    with pytest.raises(Refusal, match="not committed"):
        guard.committed_input(f, "--week", repo)


def test_an_untracked_offline_lines_file_in_an_ignored_folder_refuses(repo):
    """Check 2 cannot see an ignored file, so check 3 has to."""
    f = repo / "logs" / "lines.json"
    f.parent.mkdir()
    f.write_text("{}")
    with pytest.raises(Refusal, match="--offline-lines file .* not committed"):
        guard.committed_input(f, "--offline-lines", repo)


def test_a_committed_input_passes(repo):
    commit(repo, "examples/week9.yaml", "blind: []\n")
    guard.committed_input(repo / "examples" / "week9.yaml", "--week", repo)


def test_check_repo_runs_all_three(repo, tmp_path):
    assert guard.check_repo({"--params": repo / "params.yaml", "--week": None}, repo) is None
    with pytest.raises(Refusal, match="outside the repo"):
        guard.check_repo({"--offline-lines": tmp_path / "x.json"}, repo)


# ---- check 4: the sheet comes from the pick'em folder --------------------------------

def test_a_sheet_outside_the_folder_refuses(tmp_path, monkeypatch):
    folder = tmp_path / "OW Pick Em" / "26-27"
    folder.mkdir(parents=True)
    monkeypatch.setenv("MADDEN_SHEETS_DIR", str(folder))
    handmade = tmp_path / "NFL2026w03.xlsx"
    handmade.write_text("")
    with pytest.raises(Refusal, match="not in the pick'em folder"):
        guard.sheet_from_folder(handmade)


def test_a_symlink_into_the_folder_from_outside_still_refuses(tmp_path, monkeypatch):
    folder = tmp_path / "sheets"
    folder.mkdir()
    monkeypatch.setenv("MADDEN_SHEETS_DIR", str(folder))
    handmade = tmp_path / "made.xlsx"
    handmade.write_text("")
    (folder / "NFL2026w03.xlsx").symlink_to(handmade)
    with pytest.raises(Refusal, match="not in the pick'em folder"):
        guard.sheet_from_folder(folder / "NFL2026w03.xlsx")


def test_the_sheet_line_names_the_full_path_and_when_it_changed(tmp_path, monkeypatch):
    folder = tmp_path / "sheets"
    folder.mkdir()
    monkeypatch.setenv("MADDEN_SHEETS_DIR", str(folder))
    sheet = folder / "Eustace - NFL2026w03.xlsx"
    sheet.write_text("")
    when = datetime(2026, 9, 22, 9, 27).timestamp()
    os.utime(sheet, (when, when))
    line = guard.sheet_from_folder(sheet)
    assert line.startswith(f"SHEET: {sheet.resolve()}, last changed 2026-09-22 09:27")


def test_no_sheets_folder_set_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("MADDEN_SHEETS_DIR", raising=False)
    with pytest.raises(Refusal, match="MADDEN_SHEETS_DIR is not set"):
        guard.sheet_from_folder(tmp_path / "x.xlsx")


# ---- --tranche auto ---------------------------------------------------------------------

def game(fav, dog, home, day):
    return Game(favorite=fav, underdog=dog, spread=3.5, day=day, nominal_home=home, row=0)


WEEK = [game("SEA", "NE", "SEA", "Thursday"), game("JAX", "CLE", "JAX", "Sunday"),
        game("KC", "DEN", "KC", "Monday")]
KICKOFFS = {frozenset(("SEA", "NE")): kickoff_at("2026-09-24", "20:15"),
            frozenset(("JAX", "CLE")): kickoff_at("2026-09-27", "13:00"),
            frozenset(("KC", "DEN")): kickoff_at("2026-09-28", "20:15")}


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def test_auto_picks_thursday_before_thursday_kicks_off():
    name, why = choose_tranche(WEEK, KICKOFFS, now=utc("2026-09-23 12:00"))
    assert name == "thursday"
    assert why.startswith("TRANCHE: auto chose thursday")
    assert "already kicked off" not in why


def test_auto_moves_on_to_sunday_once_thursday_has_kicked_off():
    name, why = choose_tranche(WEEK, KICKOFFS, now=utc("2026-09-25 12:00"))
    assert name == "sunday"
    assert "already kicked off: thursday" in why


def test_auto_refuses_when_every_tranche_has_kicked_off():
    """Monday night is still ahead, but the sunday tranche's deadline was Sunday's
    first kickoff, so nothing on this sheet can still be submitted on time."""
    with pytest.raises(NoTrancheLeft, match="every tranche on this sheet has already"):
        choose_tranche(WEEK, KICKOFFS, now=utc("2026-09-27 18:00"))


def test_auto_refuses_without_kickoff_times():
    with pytest.raises(NoTrancheLeft, match="no kickoff times"):
        choose_tranche(WEEK, {}, now=utc("2026-09-23 12:00"))


# ---- runs from anywhere ---------------------------------------------------------------

def test_the_module_runs_from_a_directory_that_is_not_the_repo(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    r = subprocess.run([sys.executable, "-m", "madden.run", "--help"], cwd=tmp_path,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "--tranche" in r.stdout


def test_the_script_path_form_runs_from_anywhere(tmp_path):
    r = subprocess.run([sys.executable, str(REPO_ROOT / "madden" / "run.py"), "--help"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---- the checks inside a real main() run ----------------------------------------------
# Everything that would reach the network is stubbed; the run itself is the engine's.

from madden import run as run_mod
from madden import schedule


@pytest.fixture
def a_run(tmp_path, monkeypatch):
    """A main() run from a directory that is not the repo, with a sheet in the folder."""
    folder = tmp_path / "OW Pick Em" / "26-27"
    folder.mkdir(parents=True)
    sheet = folder / "Eustace - NFL2026w03.xlsx"
    sheet.write_text("")
    monkeypatch.setenv("MADDEN_SHEETS_DIR", str(folder))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_mod.guard, "check_repo", lambda inputs: None)
    monkeypatch.setattr(run_mod, "parse_sheet", lambda *a, **k: list(WEEK))
    monkeypatch.setattr(schedule, "resolve", lambda games, get=None: schedule.Resolution(
        season=2026, week=4, matched=3, total=3, kickoffs=dict(KICKOFFS)))
    monkeypatch.setattr(run_mod, "fetch_lines", lambda params: {})
    monkeypatch.setattr(run_mod, "fetch_scores", lambda params: {})
    monkeypatch.setattr(run_mod, "datetime", _Frozen)
    return sheet, tmp_path / "logs"


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return utc("2026-09-25 12:00").astimezone(tz)


def run_main(log, *flags):
    return run_mod.main(["--no-injuries", "--no-weather", "--log", str(log), *flags])


def health_of(out):
    return out.split("RUN HEALTH", 1)[1]


def test_run_health_names_the_sheet_and_the_tranche_auto_chose(a_run, capsys):
    sheet, log = a_run
    assert run_main(log) == 0
    health = health_of(capsys.readouterr().out)
    assert f"SHEET: {sheet.resolve()}, last changed" in health
    assert "TRANCHE: auto chose sunday" in health and "already kicked off: thursday" in health
    record = json.loads(next(log.glob("run-*-sunday.json")).read_text())
    assert record["tranche"] == "sunday"
    assert any(n.startswith("SHEET: ") for n in record["health_notes"])


def test_an_unreachable_github_is_said_in_run_health(a_run, monkeypatch, capsys):
    _, log = a_run
    monkeypatch.setattr(run_mod.guard, "check_repo", lambda inputs: (
        "CODE NOT CHECKED AGAINST GITHUB: the engine could not reach GitHub"))
    assert run_main(log) == 0
    assert "! CODE NOT CHECKED AGAINST GITHUB" in health_of(capsys.readouterr().out)


def test_a_repo_refusal_halts_with_exit_3_before_anything_is_read(a_run, monkeypatch, capsys):
    _, log = a_run

    def refuse(inputs):
        raise Refusal("this Mac is 1 commit(s) behind GitHub")

    monkeypatch.setattr(run_mod.guard, "check_repo", refuse)
    monkeypatch.setattr(run_mod, "fetch_lines", lambda p: pytest.fail("fetched lines"))
    assert run_main(log) == 3
    assert "GUARDRAIL, halting: this Mac is 1 commit(s) behind" in capsys.readouterr().err


def test_a_sheet_from_elsewhere_halts_with_exit_3(a_run, tmp_path, capsys):
    _, log = a_run
    handmade = tmp_path / "NFL2026w03.xlsx"
    handmade.write_text("")
    assert run_main(log, "--sheet", str(handmade)) == 3
    assert "not in the pick'em folder" in capsys.readouterr().err


def test_every_tranche_kicked_off_halts_with_exit_3(a_run, monkeypatch, capsys):
    _, log = a_run

    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc("2026-09-27 18:00").astimezone(tz)

    monkeypatch.setattr(run_mod, "datetime", Late)
    monkeypatch.setattr(run_mod, "fetch_lines", lambda p: pytest.fail("spent a credit"))
    assert run_main(log) == 3
    assert "every tranche on this sheet has already kicked off" in capsys.readouterr().err


def test_a_named_tranche_still_works(a_run, capsys):
    _, log = a_run
    assert run_main(log, "--tranche", "all") == 0
    assert "TRANCHE: auto" not in capsys.readouterr().out


def test_the_check_is_handed_repo_root_paths_from_another_directory(a_run, monkeypatch):
    """Run from tmp_path; params.yaml and a relative --week still mean the repo's."""
    _, log = a_run
    seen = {}
    monkeypatch.setattr(run_mod.guard, "check_repo", lambda inputs: seen.update(inputs))
    assert run_main(log, "--week", "examples/week1-2026.yaml", "--tranche", "all") == 0
    assert seen["--params"] == str(REPO_ROOT / "params.yaml")
    assert seen["--week"] == str(REPO_ROOT / "examples" / "week1-2026.yaml")


def test_cache_is_still_refused_under_claude_code(a_run, monkeypatch, capsys):
    _, log = a_run
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run_main(log, "--cache") == 3
    assert "--cache" in capsys.readouterr().err
