"""The engine's own input checks. Four of them, run on every engine run.

REWRITTEN 2026-09-23, when Madden stopped depending on a sandbox. The old guard asked
whether a Claude Code sandbox was running and whether its rules were declared, and it
refused every run that was not inside one. What it protected is the same thing these
four checks protect: a board that came from something other than the engine's own
committed code and inputs. They ask that question of git, which answers it directly,
instead of asking a sandbox that might not be there.

1. In step with GitHub. On main, and neither behind, ahead of, nor split from
   origin/main after a fresh fetch. When GitHub cannot be reached, the run is still
   refused if this Mac holds commits the last downloaded copy lacks; otherwise it
   warns, and run health says the code was not checked against GitHub.
2. Nothing uncommitted. `git status --porcelain` must be empty. Ignored files are
   exempt: .env, logs/, .cache/, .codex/.
3. Every input file the run reads from the repo (--params, --week, --offline-lines)
   lives inside the repo and is tracked, so check 2 covers it.
4. The sheet sits in the pick'em folder, MADDEN_SHEETS_DIR. It is the one input nobody
   guarantees: nothing checks who made it, so run health prints its path and when it
   last changed.

Each check that fails raises Refusal with one plain sentence. The engine prints it and
exits 3.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FETCH_TIMEOUT = 15          # seconds; a Sunday-morning hiccup must not hang the board
SHOW_PATHS = 5              # how many uncommitted paths a refusal names


class Refusal(Exception):
    """A check failed. The message is the one sentence the engine prints."""


def _git(repo: Path, *args, timeout: float | None = None) -> subprocess.CompletedProcess:
    # No optional locks: plain `git status` refreshes the index under index.lock, and a
    # run killed partway would leave that lock behind to block every later git command.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C", GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args],
                          capture_output=True,
                          text=True, timeout=timeout, env=env)


def _out(repo: Path, *args) -> str:
    r = _git(repo, *args)
    if r.returncode != 0:
        raise Refusal(f"git could not answer 'git {' '.join(args)}' in {repo} "
                      f"({(r.stderr or r.stdout).strip() or 'no output'}), so the engine "
                      f"cannot confirm what code it is running")
    return r.stdout.strip()


def local_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def last_fetch(repo: Path) -> str:
    """When this checkout last downloaded from GitHub successfully, or 'never'.

    git rewrites FETCH_HEAD on every fetch that succeeds and leaves it alone on one
    that fails, so its timestamp is the last successful check.
    """
    try:
        p = Path(_out(repo, "rev-parse", "--git-path", "FETCH_HEAD"))
        p = p if p.is_absolute() else repo / p
        return local_time(p.stat().st_mtime)
    except (Refusal, OSError):
        return "never"


def in_step_with_github(repo: Path = REPO, timeout: float = FETCH_TIMEOUT) -> str | None:
    """Check 1. Returns a run-health warning when GitHub was unreachable, else None."""
    branch = _out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise Refusal(f"this checkout is on '{branch}', not main, so these would not be "
                      f"the picks from the code on GitHub's main branch")

    try:
        r = _git(repo, "fetch", "--quiet", "origin", timeout=timeout)
        reached, why = r.returncode == 0, (r.stderr.strip().splitlines() or ["no reason"])[-1]
    except subprocess.TimeoutExpired:
        reached, why = False, f"no answer within {timeout:g} seconds"

    if _git(repo, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main").returncode:
        raise Refusal("this checkout holds no copy of GitHub's main branch at all, so "
                      "nothing can confirm the code matches GitHub")
    ahead, behind = (int(n) for n in
                     _out(repo, "rev-list", "--left-right", "--count",
                          "main...origin/main").split())

    if reached:
        if ahead and behind:
            raise Refusal(f"this Mac and GitHub have split: this Mac has {ahead} commit(s) "
                          f"GitHub lacks and GitHub has {behind} this Mac lacks")
        if behind:
            raise Refusal(f"this Mac is {behind} commit(s) behind GitHub, so the engine "
                          f"would run stale code; pull first")
        if ahead:
            raise Refusal(f"this Mac is {ahead} commit(s) ahead of GitHub, so the picks "
                          f"would come from code that is not on GitHub; push first")
        return None

    # GitHub could not be reached. The saved copy of origin/main still says whether this
    # Mac holds work GitHub lacks, and whether it is known to be behind.
    if ahead:
        raise Refusal(f"GitHub could not be reached ({why}), and this Mac holds {ahead} "
                      f"commit(s) that the last downloaded copy of GitHub lacks, so the "
                      f"picks would come from code that may not be on GitHub")
    if behind:
        raise Refusal(f"GitHub could not be reached ({why}), and even the last downloaded "
                      f"copy of GitHub is {behind} commit(s) ahead of this Mac, so the "
                      f"engine would run stale code; pull first")
    return (f"CODE NOT CHECKED AGAINST GITHUB: the engine could not reach GitHub ({why}), "
            f"so it cannot confirm GitHub has no newer work; last successful check "
            f"{last_fetch(repo)}")


def nothing_uncommitted(repo: Path = REPO) -> None:
    """Check 2. Modified, staged, deleted or untracked-and-not-ignored: all refuse."""
    lines = [ln for ln in _git_status(repo) if ln.strip()]
    if not lines:
        return
    paths = [ln[3:] for ln in lines]
    shown = ", ".join(paths[:SHOW_PATHS])
    more = f" and {len(paths) - SHOW_PATHS} more" if len(paths) > SHOW_PATHS else ""
    raise Refusal(f"the repo has uncommitted changes ({shown}{more}), so the picks would "
                  f"not come from committed code and inputs; commit and push them, or "
                  f"remove them")


def _git_status(repo: Path) -> list[str]:
    # Not _out: its strip() would eat the leading space of " M path" on the first line.
    r = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if r.returncode != 0:
        raise Refusal(f"git could not report the repo's status ({r.stderr.strip()}), so "
                      f"the engine cannot confirm nothing uncommitted feeds the run")
    return r.stdout.splitlines()


def committed_input(path: Path, flag: str, repo: Path = REPO) -> None:
    """Check 3. An input file must sit inside the repo and be tracked by git."""
    real, root = path.resolve(), repo.resolve()
    if not real.is_relative_to(root):
        raise Refusal(f"the {flag} file {path} is outside the repo, so nothing proves it "
                      f"is committed; put it in {repo} and commit it")
    rel = real.relative_to(root)
    if _git(repo, "ls-files", "--error-unmatch", "--", str(rel)).returncode:
        raise Refusal(f"the {flag} file {rel} is not committed to the repo; commit and "
                      f"push it first")


def sheets_folder() -> Path:
    """The pick'em folder, MADDEN_SHEETS_DIR, required and absolute."""
    raw = os.environ.get("MADDEN_SHEETS_DIR")
    if not raw:
        raise Refusal("MADDEN_SHEETS_DIR is not set, so there is no pick'em folder to "
                      "check the sheet against; set it in .env")
    return Path(raw).expanduser()


def sheet_from_folder(sheet: Path) -> str:
    """Check 4. Returns the SHEET line for run health."""
    folder = sheets_folder()
    real = sheet.resolve()
    if not real.is_relative_to(folder.resolve()):
        raise Refusal(f"the sheet {sheet} is not in the pick'em folder {folder}, so it is "
                      f"not the league's sheet")
    try:
        changed = local_time(real.stat().st_mtime)
    except OSError as exc:
        raise Refusal(f"the sheet {sheet} cannot be read ({exc.strerror})") from None
    return f"SHEET: {real}, last changed {changed}"


def check_repo(inputs: dict, repo: Path = REPO) -> str | None:
    """Checks 3, 2 and 1: the local ones first, the one that needs the network last.
    Returns the unreachable-GitHub warning, if any.

    `inputs` maps a flag name to the path it names; None values are skipped.
    """
    for flag, path in inputs.items():
        if path is not None:
            committed_input(Path(path), flag, repo)
    nothing_uncommitted(repo)
    return in_step_with_github(repo)
