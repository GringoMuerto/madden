"""The engine's input checks, against real git repos with a local bare "origin".

Nothing here touches the real remote: every repo and every origin is made under tmp_path,
and the engine is pointed at the origin by URL, as it is pointed at GitHub in a real run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden import guard
from madden.guard import Refusal
from madden.run import NoTrancheLeft, choose_remaining
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
def origin(tmp_path):
    """A bare origin standing in for GitHub, holding an engine file, params and a
    .gitignore, pushed from a first checkout."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / ".gitignore").write_text(".env\nlogs/\n.cache/\n.codex/\n.pytest_cache/\n")
    (seed / "madden").mkdir()
    (seed / "madden" / "core.py").write_text("X = 1\n")
    (seed / "params.yaml").write_text("a: 1\n")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "init")
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "-u", "origin", "main")
    return bare


@pytest.fixture
def url(origin):
    return "file://" + str(origin)


@pytest.fixture
def repo(tmp_path, origin):
    """A checkout in step with the origin."""
    work = tmp_path / "madden"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    return work


def pushed_from_elsewhere(tmp_path, origin, name, text):
    other = tmp_path / "elsewhere"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    commit(other, name, text)
    git(other, "push", "-q", "origin", "main")


def check(repo, url, **inputs):
    return guard.check_repo(inputs, repo, url=url)


# ---- check 1: the code here matches GitHub's main -------------------------------------

def test_in_step_passes_silently(repo, url):
    assert check(repo, url) is None


def test_a_changed_engine_file_refuses_and_names_it(repo, url):
    (repo / "madden" / "core.py").write_text("X = 99\n")
    with pytest.raises(Refusal, match=r"changed here: madden/core\.py"):
        check(repo, url)


def test_a_local_commit_not_yet_pushed_refuses(repo, url):
    commit(repo, "madden/core.py", "X = 2\n")
    with pytest.raises(Refusal, match="commit and push, or pull"):
        check(repo, url)


def test_newer_work_on_github_refuses(repo, url, origin, tmp_path):
    """The 2026-09-10 stale-checkout failure: GitHub moved on and this copy did not."""
    pushed_from_elsewhere(tmp_path, origin, "madden/core.py", "X = 2\n")
    with pytest.raises(Refusal, match=r"changed here: madden/core\.py"):
        check(repo, url)


def test_a_file_github_added_is_missing_here(repo, url, origin, tmp_path):
    pushed_from_elsewhere(tmp_path, origin, "madden/new.py", "Y = 1\n")
    with pytest.raises(Refusal, match=r"missing here: madden/new\.py"):
        check(repo, url)


def test_an_extra_file_anywhere_refuses(repo, url):
    """A new file beside the engine could shadow a module it imports."""
    (repo / "madden" / "json.py").write_text("")
    with pytest.raises(Refusal, match=r"here but not on GitHub: madden/json\.py"):
        check(repo, url)


def test_ignored_files_do_not_trip_it(repo, url):
    (repo / ".env").write_text("ODDS_API_KEY=x\n")
    (repo / "logs").mkdir()
    (repo / "logs" / "run.json").write_text("{}")
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text("")
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "README.md").write_text("")
    assert check(repo, url) is None


def test_a_long_list_is_cut_short(repo, url):
    for i in range(8):
        (repo / f"stray{i}.txt").write_text("")
    with pytest.raises(Refusal, match="and 3 more"):
        check(repo, url)


def test_a_plain_folder_with_no_git_database_is_checked_the_same(repo, url, tmp_path):
    """Cowork: the vault copy's git database lives outside the vault, out of reach."""
    plain = tmp_path / "plain"
    shutil.copytree(repo, plain, ignore=shutil.ignore_patterns(".git"))
    assert check(plain, url) is None
    (plain / "params.yaml").write_text("a: 9\n")
    with pytest.raises(Refusal, match=r"params\.yaml"):
        check(plain, url)


def test_the_vaults_one_line_git_pointer_is_not_part_of_the_code(repo, url, tmp_path):
    plain = tmp_path / "vault-copy"
    shutil.copytree(repo, plain, ignore=shutil.ignore_patterns(".git"))
    (plain / ".git").write_text("gitdir: /Users/someone/git-repos/madden.git\n")
    assert check(plain, url) is None


def test_a_nested_git_file_is_still_code(repo, url):
    """Only the repo root's .git is skipped; a .git file anywhere else is a stray file."""
    (repo / "madden" / ".git").write_text("")
    with pytest.raises(Refusal, match=r"madden/\.git"):
        check(repo, url)


# ---- when GitHub cannot be reached ----------------------------------------------------

def test_unreachable_after_a_good_check_warns_and_says_when(repo, url, tmp_path):
    check(repo, url)                                   # saves the copy of main
    warning = check(repo, "file://" + str(tmp_path / "no-such-origin.git"))
    assert warning.startswith("CODE NOT CHECKED AGAINST GITHUB: the engine could not "
                              "reach GitHub")
    assert "compared against the copy of GitHub's main saved" in warning
    assert "cannot confirm GitHub has no newer work" in warning


def test_unreachable_still_refuses_a_changed_file(repo, url, tmp_path):
    check(repo, url)
    (repo / "madden" / "core.py").write_text("X = 99\n")
    with pytest.raises(Refusal, match="differs from the copy of GitHub's main saved"):
        check(repo, "file://" + str(tmp_path / "no-such-origin.git"))


def test_unreachable_with_no_saved_copy_refuses(repo, tmp_path):
    with pytest.raises(Refusal, match="never been checked against GitHub"):
        check(repo, "file://" + str(tmp_path / "no-such-origin.git"))


def test_a_clone_that_hangs_is_cut_off(repo, url, monkeypatch):
    check(repo, url)
    real = guard._git

    def slow(cwd, *args, timeout=None, env=None):
        if args[:1] == ("clone",):
            raise subprocess.TimeoutExpired("git clone", timeout)
        return real(cwd, *args, timeout=timeout, env=env)

    monkeypatch.setattr(guard, "_git", slow)
    warning = guard.check_repo({}, repo, url=url, timeout=15)
    assert "no answer within 15 seconds" in warning


def test_the_saved_copy_lives_in_the_ignored_cache(repo, url):
    check(repo, url)
    saved = json.loads((repo / ".cache" / "github-main.json").read_text())
    assert "madden/core.py" in saved["files"] and saved["gitignore"].startswith(".env")


# ---- git hygiene and GitHub access ------------------------------------------------------

def test_no_git_command_touches_this_repos_git_database(repo, url, monkeypatch):
    """Every git command runs in a scratch folder, never in the repo, and takes no
    optional locks, so nothing here can leave an index.lock behind."""
    calls = []
    real = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append((cmd, kwargs.get("env") or {}))
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(guard.subprocess, "run", spy)
    check(repo, url, **{"--params": repo / "params.yaml"})
    assert calls
    for cmd, env in calls:
        assert cmd[0] == "git" and "--no-optional-locks" in cmd, cmd
        assert env.get("GIT_OPTIONAL_LOCKS") == "0", cmd
        assert str(repo) not in cmd[cmd.index("-C") + 1], cmd


def test_the_token_goes_to_github_only_and_no_saved_login_is_used(monkeypatch):
    monkeypatch.setenv(guard.TOKEN_VAR, "tok123")
    env = guard._auth_env()
    pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
             for i in range(int(env["GIT_CONFIG_COUNT"]))}
    assert pairs["credential.helper"] == ""
    header = pairs["http.https://github.com/.extraheader"]
    assert header.startswith("Authorization: Basic ")
    assert "tok123" not in header                  # encoded, never sent in the clear


def test_without_a_token_no_header_is_sent(monkeypatch):
    monkeypatch.delenv(guard.TOKEN_VAR, raising=False)
    assert guard._auth_env()["GIT_CONFIG_COUNT"] == "1"


def test_the_token_never_reaches_the_command_line(repo, url, monkeypatch):
    monkeypatch.setenv(guard.TOKEN_VAR, "tok123")
    calls = []
    real = subprocess.run

    def spy(cmd, *args, **kwargs):
        calls.append(cmd)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(guard.subprocess, "run", spy)
    check(repo, url)
    assert calls and not any("tok123" in part for cmd in calls for part in cmd)


def test_the_reason_is_gits_fatal_line_not_the_last_line():
    """Week 3's warning quoted "and the repository exists.", the tail of the message."""
    stderr = ("git@github.com: Permission denied (publickey).\n"
              "fatal: Could not read from remote repository.\n\n"
              "Please make sure you have the correct access rights\n"
              "and the repository exists.\n")
    assert guard._reason(stderr) == "Could not read from remote repository."


def test_the_blob_hash_is_gits_own():
    assert guard.blob_hash(b"X = 1\n") == subprocess.run(
        ["git", "hash-object", "--stdin"], input=b"X = 1\n",
        capture_output=True).stdout.decode().strip()


# ---- check 2: input files live in the repo and are on GitHub -----------------------------

def test_a_week_file_outside_the_repo_refuses(repo, url, tmp_path):
    outside = tmp_path / "week.yaml"
    outside.write_text("blind: []\n")
    with pytest.raises(Refusal, match="--week file .* is outside the repo"):
        check(repo, url, **{"--week": outside})


def test_an_untracked_week_file_refuses(repo, url):
    f = repo / "examples" / "week9.yaml"
    f.parent.mkdir()
    f.write_text("blind: []\n")
    with pytest.raises(Refusal, match="--week file examples/week9.yaml is not on GitHub"):
        check(repo, url, **{"--week": f})


def test_an_offline_lines_file_in_an_ignored_folder_refuses(repo, url):
    """Check 1 cannot see an ignored file, so check 2 has to."""
    f = repo / "logs" / "lines.json"
    f.parent.mkdir()
    f.write_text("{}")
    with pytest.raises(Refusal, match="--offline-lines file .* not on GitHub"):
        check(repo, url, **{"--offline-lines": f})


def test_an_input_on_github_passes(repo, url, origin, tmp_path):
    pushed_from_elsewhere(tmp_path, origin, "examples/week9.yaml", "blind: []\n")
    git(repo, "pull", "-q")
    assert check(repo, url, **{"--week": repo / "examples" / "week9.yaml",
                               "--params": repo / "params.yaml"}) is None


# ---- check 3: the sheet comes from the pick'em folder --------------------------------

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


def test_a_relative_sheets_folder_means_relative_to_the_repo(tmp_path, monkeypatch):
    """The vault is mounted at different paths on the Mac and in Cowork; a path
    relative to the repo finds the same folder in both."""
    vault = tmp_path / "vault"
    repo = vault / "Apps" / "madden"
    folder = vault / "Personal" / "NFL" / "OW Pick Em" / "26-27"
    repo.mkdir(parents=True)
    folder.mkdir(parents=True)
    sheet = folder / "Eustace - NFL2026w03.xlsx"
    sheet.write_text("")
    monkeypatch.setenv("MADDEN_SHEETS_DIR", "../../Personal/NFL/OW Pick Em/26-27")
    assert guard.sheet_from_folder(sheet, repo).startswith(f"SHEET: {sheet.resolve()}")
    monkeypatch.chdir(tmp_path)                    # the working directory is irrelevant
    assert guard.sheet_from_folder(sheet, repo).startswith("SHEET:")


def test_no_sheets_folder_set_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("MADDEN_SHEETS_DIR", raising=False)
    with pytest.raises(Refusal, match="MADDEN_SHEETS_DIR is not set"):
        guard.sheet_from_folder(tmp_path / "x.xlsx")


# ---- the default run: every game not yet kicked off ------------------------------------

def game(fav, dog, home, day):
    return Game(favorite=fav, underdog=dog, spread=3.5, day=day, nominal_home=home, row=0)


WEEK = [game("SEA", "NE", "SEA", "Thursday"), game("JAX", "CLE", "JAX", "Sunday"),
        game("KC", "DEN", "KC", "Monday")]
KICKOFFS = {frozenset(("SEA", "NE")): kickoff_at("2026-09-24", "20:15"),
            frozenset(("JAX", "CLE")): kickoff_at("2026-09-27", "13:00"),
            frozenset(("KC", "DEN")): kickoff_at("2026-09-28", "20:15")}


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def names(games):
    return [f"{g.away} at {g.home}" for g in games]


def test_on_thursday_every_game_is_priced_not_just_thursday_night():
    """Scott, 2026-09-24: every game needs to run regardless of when I run it."""
    ahead, started, why = choose_remaining(WEEK, KICKOFFS, now=utc("2026-09-23 12:00"))
    assert names(ahead) == ["NE at SEA", "CLE at JAX", "DEN at KC"]
    assert started == []
    assert why.startswith("GAMES: every game on the sheet not yet kicked off, 3 of 3")


def test_on_friday_the_games_already_played_are_left_out_and_named():
    ahead, started, why = choose_remaining(WEEK, KICKOFFS, now=utc("2026-09-25 12:00"))
    assert names(ahead) == ["CLE at JAX", "DEN at KC"]
    assert names(started) == ["NE at SEA"]
    assert "already kicked off, not priced: NE at SEA" in why


def test_on_sunday_afternoon_monday_night_is_still_priced():
    """The old default refused here: the sunday tranche's deadline had passed."""
    ahead, _, _ = choose_remaining(WEEK, KICKOFFS, now=utc("2026-09-27 18:00"))
    assert names(ahead) == ["DEN at KC"]


def test_a_game_with_no_kickoff_time_is_priced_not_dropped():
    kickoffs = {k: v for k, v in KICKOFFS.items() if k != frozenset(("JAX", "CLE"))}
    ahead, _, _ = choose_remaining(WEEK, kickoffs, now=utc("2026-09-25 12:00"))
    assert "CLE at JAX" in names(ahead)


def test_refuses_once_every_game_has_kicked_off():
    with pytest.raises(NoTrancheLeft, match="every game on this sheet has already"):
        choose_remaining(WEEK, KICKOFFS, now=utc("2026-09-29 12:00"))


def test_refuses_without_kickoff_times():
    with pytest.raises(NoTrancheLeft, match="no kickoff times"):
        choose_remaining(WEEK, {}, now=utc("2026-09-23 12:00"))


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
    monkeypatch.setattr(run_mod, "blocked_hosts", lambda urls: [])
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


def test_a_default_run_prices_every_open_game_and_says_so(a_run, capsys):
    """Friday: Thursday night is over; Sunday and Monday night are both priced."""
    sheet, log = a_run
    assert run_main(log) == 0
    out = capsys.readouterr().out
    health = health_of(out)
    assert f"SHEET: {sheet.resolve()}, last changed" in health
    assert "GAMES: every game on the sheet not yet kicked off, 2 of 3" in health
    assert "already kicked off, not priced: NE at SEA" in health
    board = out.split("RUN HEALTH", 1)[0]
    assert "CLE at JAX" in board and "DEN at KC" in board and "NE at SEA" not in board
    record = json.loads(next(log.glob("run-*-remaining.json")).read_text())
    assert record["tranche"] == "remaining"
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


def test_every_game_kicked_off_halts_with_exit_3(a_run, monkeypatch, capsys):
    _, log = a_run

    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc("2026-09-29 12:00").astimezone(tz)

    monkeypatch.setattr(run_mod, "datetime", Late)
    monkeypatch.setattr(run_mod, "fetch_lines", lambda p: pytest.fail("spent a credit"))
    assert run_main(log) == 3
    assert "every game on this sheet has already kicked off" in capsys.readouterr().err


def test_a_named_tranche_still_works(a_run, capsys):
    _, log = a_run
    assert run_main(log, "--tranche", "all") == 0
    assert "GAMES: every game" not in capsys.readouterr().out


def test_the_check_is_handed_repo_root_paths_from_another_directory(a_run, monkeypatch):
    """Run from tmp_path; params.yaml and a relative --week still mean the repo's."""
    _, log = a_run
    seen = {}
    monkeypatch.setattr(run_mod.guard, "check_repo", lambda inputs: seen.update(inputs))
    assert run_main(log, "--week", "examples/week1-2026.yaml", "--tranche", "all") == 0
    assert seen["--params"] == str(REPO_ROOT / "params.yaml")
    assert seen["--week"] == str(REPO_ROOT / "examples" / "week1-2026.yaml")


@pytest.mark.parametrize("claudecode", ["1", None])
def test_cache_is_refused_in_claude_code_and_cowork_alike(a_run, monkeypatch, capsys,
                                                          claudecode):
    """Cowork may not set CLAUDECODE; the refusal must not depend on it."""
    _, log = a_run
    monkeypatch.delenv("MADDEN_DEBUG_CACHE", raising=False)
    if claudecode:
        monkeypatch.setenv("CLAUDECODE", claudecode)
    else:
        monkeypatch.delenv("CLAUDECODE", raising=False)
    assert run_main(log, "--cache") == 3
    assert "MADDEN_DEBUG_CACHE" in capsys.readouterr().err


def test_cache_runs_only_when_deliberately_switched_on(a_run, monkeypatch, capsys):
    _, log = a_run
    monkeypatch.setenv("MADDEN_DEBUG_CACHE", "1")
    assert run_main(log, "--cache") == 0
    assert "CACHE IN USE" in capsys.readouterr().out


# ---- the network: every host the run needs, checked before anything is fetched -------

def test_a_host_the_network_refuses_halts_the_run_and_names_it(a_run, monkeypatch, capsys):
    """Week 3 from Cowork: the proxy refused the odds API, and the run printed a board
    with no lines instead of saying the run could not work from there."""
    _, log = a_run
    monkeypatch.setattr(run_mod, "blocked_hosts", lambda urls: ["api.the-odds-api.com"])
    monkeypatch.setattr(run_mod, "fetch_lines", lambda p: pytest.fail("fetched lines"))
    assert run_main(log) == 3
    err = capsys.readouterr().err
    assert "GUARDRAIL, halting" in err
    assert "add api.the-odds-api.com to this environment's network allowlist" in err
    assert not list(log.glob("run-*.json"))


def test_the_hosts_checked_are_the_hosts_the_run_will_use(a_run, monkeypatch):
    _, log = a_run
    seen = []
    monkeypatch.setattr(run_mod, "blocked_hosts", lambda urls: seen.extend(urls) or [])
    assert run_mod.main(["--no-injuries", "--log", str(log)]) == 0
    assert seen == [schedule.SCHEDULE_URL, "https://api.the-odds-api.com/v4",
                    run_mod.FORECAST_URL]


def test_hosts_a_run_will_not_use_are_not_checked(a_run, monkeypatch):
    _, log = a_run
    seen = []
    monkeypatch.setattr(run_mod, "blocked_hosts", lambda urls: seen.extend(urls) or [])
    assert run_main(log, "--offline-lines", "examples/week1-2026-lines.json",
                    "--tranche", "all") == 0
    assert seen == [schedule.SCHEDULE_URL]
