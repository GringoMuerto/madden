"""The engine's own input checks, run on every engine run.

REWRITTEN 2026-09-23, when Madden stopped depending on a sandbox, and again 2026-09-24,
when it moved into Scott's Second Brain so that Cowork can run it with only the vault
connected. What they protect: a board that came from something other than the engine's
own code and inputs as they stand on GitHub.

They no longer ask the local git database. In the vault that database lives outside the
vault (Drive sync corrupts git databases), so Cowork cannot reach it. Instead the engine
takes a fresh copy of GitHub's main over HTTPS and compares every file here against it,
the same way on the Mac and in Cowork.

1. Matches GitHub. Every file GitHub's main tracks is here, byte for byte, and nothing
   is here that GitHub lacks unless GitHub's own .gitignore ignores it (.env, logs/,
   .cache/ and the rest). Any difference refuses: commit and push, or pull.
   When GitHub cannot be reached, the same comparison runs against the copy saved at
   the last successful check (.cache/github-main.json), and run health says the code
   was not checked against GitHub. With no saved copy at all, it refuses.
2. Every input file the run reads from the repo (--params, --week, --offline-lines)
   lives inside the repo and is tracked on GitHub, so check 1 covers it.
3. The sheet sits in the pick'em folder, MADDEN_SHEETS_DIR, which may be relative to
   the repo so that it means the same folder wherever the vault is mounted. It is the
   one input nobody guarantees: run health prints its path and when it last changed.

Each check that fails raises Refusal with one plain sentence. The engine prints it and
exits 3.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GITHUB_URL = "https://github.com/GringoMuerto/madden.git"
FETCH_TIMEOUT = 30          # seconds; a Sunday-morning hiccup must not hang the board
SHOW_PATHS = 5              # how many paths a refusal names
CACHE = Path(".cache") / "github-main.json"
TOKEN_VAR = "MADDEN_GITHUB_TOKEN"


class Refusal(Exception):
    """A check failed. The message is the one sentence the engine prints."""


class Unreachable(Exception):
    """GitHub could not be asked. The message says why."""


@dataclass
class Snapshot:
    """GitHub's main: every tracked path with its git blob hash, and its .gitignore."""
    commit: str
    files: dict
    gitignore: str
    checked_at: float


def _git(cwd: Path, *args, timeout: float | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    # No optional locks: a run killed partway must never leave an index.lock behind.
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C", GIT_OPTIONAL_LOCKS="0",
               **(env or {}))
    return subprocess.run(["git", "--no-optional-locks", "-C", str(cwd), *args],
                          capture_output=True, text=True, timeout=timeout, env=env)


def _auth_env() -> dict:
    """git config, through the environment, that sends MADDEN_GITHUB_TOKEN (if set) to
    GitHub and nothing else, with no credential helper: the Mac's keychain must not make
    a check pass here that would fail in Cowork. The environment keeps a token out of
    the process list, where a command-line argument would show it. The repo is public,
    so no token is needed; this stays for a private one."""
    config = [("credential.helper", "")]
    token = os.environ.get(TOKEN_VAR, "").strip()
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        config.append(("http.https://github.com/.extraheader",
                       f"Authorization: Basic {basic}"))
    env = {"GIT_CONFIG_COUNT": str(len(config))}
    for i, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return env


def _reason(stderr: str) -> str:
    """git's own statement of what failed: the fatal: line, not whatever came last.
    Week 3's warning quoted "and the repository exists.", the tail of a longer message."""
    lines = [ln.strip() for ln in stderr.strip().splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("fatal:"):
            return ln[len("fatal:"):].strip()
    return lines[-1] if lines else "no reason given"


def blob_hash(data: bytes) -> str:
    """git's own hash of a file's contents, so a local file compares against GitHub's
    tree without a local git database."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def local_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M %Z")


class _Ignores:
    """Answers "does GitHub's .gitignore ignore this path?" with git's own rules, in a
    scratch repository holding only that .gitignore."""

    def __init__(self, gitignore: str):
        self._dir = tempfile.TemporaryDirectory(prefix="madden-ignore-")
        root = Path(self._dir.name)
        _git(root, "init", "-q")
        (root / ".gitignore").write_text(gitignore)
        self._root = root

    def which(self, paths: list[str]) -> set[str]:
        if not paths:
            return set()
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(self._root),
                            "check-ignore", "--no-index", "-z", "--stdin"],
                           input="\0".join(paths) + "\0",
                           capture_output=True, text=True,
                           env=dict(os.environ, LC_ALL="C", GIT_OPTIONAL_LOCKS="0"))
        if r.returncode not in (0, 1):
            raise Refusal(f"git could not apply GitHub's .gitignore ({_reason(r.stderr)}), "
                          f"so the engine cannot tell which local files matter")
        return {p for p in r.stdout.split("\0") if p}

    def close(self):
        self._dir.cleanup()


def fetch_snapshot(url: str = GITHUB_URL, timeout: float = FETCH_TIMEOUT) -> Snapshot:
    """A fresh copy of GitHub's main: a shallow clone into a scratch folder, read, and
    thrown away. Raises Unreachable with git's own reason."""
    with tempfile.TemporaryDirectory(prefix="madden-github-") as tmp:
        clone = Path(tmp) / "main"
        try:
            r = _git(Path(tmp), "clone", "--quiet", "--depth", "1", "--branch", "main",
                     "--no-tags", url, str(clone), timeout=timeout, env=_auth_env())
        except subprocess.TimeoutExpired:
            raise Unreachable(f"no answer within {timeout:g} seconds") from None
        except FileNotFoundError:
            raise Unreachable("git is not installed here") from None
        if r.returncode != 0:
            raise Unreachable(_reason(r.stderr))
        head = _git(clone, "rev-parse", "HEAD").stdout.strip()
        listing = _git(clone, "ls-tree", "-r", "-z", "HEAD").stdout
        files = {}
        for entry in listing.split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            mode, kind, sha = meta.split()
            if kind == "blob":
                files[path] = sha
        gi = clone / ".gitignore"
        return Snapshot(commit=head, files=files,
                        gitignore=gi.read_text() if gi.is_file() else "",
                        checked_at=time.time())


def save_snapshot(snap: Snapshot, repo: Path) -> None:
    p = repo / CACHE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snap.__dict__, indent=1, sort_keys=True))
    except OSError:
        pass                     # a cache that cannot be written only weakens a later offline run


def load_snapshot(repo: Path) -> Snapshot | None:
    try:
        return Snapshot(**json.loads((repo / CACHE).read_text()))
    except (OSError, ValueError, TypeError):
        return None


def local_files(repo: Path, ignores: _Ignores) -> dict:
    """Every file here that GitHub's .gitignore does not ignore: path -> blob hash.
    The repo root's .git (a folder, or in the vault a one-line pointer file) is never
    part of the code and is skipped. Ignored folders are not walked into."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        here = Path(dirpath)
        rel_dir = here.relative_to(repo).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        if not prefix:
            dirnames[:] = [d for d in dirnames if d != ".git"]
            filenames = [f for f in filenames if f != ".git"]
        skip = ignores.which([prefix + d + "/" for d in dirnames])
        dirnames[:] = sorted(d for d in dirnames if prefix + d + "/" not in skip)
        paths = [prefix + f for f in filenames]
        ignored = ignores.which(paths)
        for rel in paths:
            if rel not in ignored:
                out[rel] = blob_hash((repo / rel).read_bytes())
    return out


def _listed(paths: list[str]) -> str:
    shown = ", ".join(sorted(paths)[:SHOW_PATHS])
    more = f" and {len(paths) - SHOW_PATHS} more" if len(paths) > SHOW_PATHS else ""
    return shown + more


def compare(snap: Snapshot, repo: Path, against: str) -> None:
    """Check 1. Refuses on any difference between this folder and the snapshot."""
    ignores = _Ignores(snap.gitignore)
    try:
        here = local_files(repo, ignores)
    finally:
        ignores.close()
    changed = [p for p, h in snap.files.items() if p in here and here[p] != h]
    missing = [p for p in snap.files if p not in here]
    extra = [p for p in here if p not in snap.files]
    problems = []
    if changed:
        problems.append(f"changed here: {_listed(changed)}")
    if missing:
        problems.append(f"missing here: {_listed(missing)}")
    if extra:
        problems.append(f"here but not on GitHub: {_listed(extra)}")
    if problems:
        raise Refusal(f"the code here differs from {against} ({'; '.join(problems)}), so "
                      f"the picks would not come from the code on GitHub; commit and push, "
                      f"or pull")


def committed_input(path: Path, flag: str, snap: Snapshot, repo: Path = REPO) -> None:
    """Check 2. An input file must sit inside the repo and be tracked on GitHub."""
    real, root = path.resolve(), repo.resolve()
    if not real.is_relative_to(root):
        raise Refusal(f"the {flag} file {path} is outside the repo, so nothing proves it "
                      f"is on GitHub; put it in {repo}, commit and push it")
    rel = real.relative_to(root).as_posix()
    if rel not in snap.files:
        raise Refusal(f"the {flag} file {rel} is not on GitHub; commit and push it first")


def sheets_folder(repo: Path = REPO) -> Path:
    """The pick'em folder, MADDEN_SHEETS_DIR. A relative path means relative to the repo,
    so the same setting finds the same folder on the Mac and in Cowork."""
    raw = os.environ.get("MADDEN_SHEETS_DIR")
    if not raw:
        raise Refusal("MADDEN_SHEETS_DIR is not set, so there is no pick'em folder to "
                      "check the sheet against; set it in .env")
    folder = Path(raw).expanduser()
    return folder if folder.is_absolute() else repo / folder


def sheet_from_folder(sheet: Path, repo: Path = REPO) -> str:
    """Check 3. Returns the SHEET line for run health."""
    folder = sheets_folder(repo)
    real = sheet.resolve()
    if not real.is_relative_to(folder.resolve()):
        raise Refusal(f"the sheet {sheet} is not in the pick'em folder {folder}, so it is "
                      f"not the league's sheet")
    try:
        changed = local_time(real.stat().st_mtime)
    except OSError as exc:
        raise Refusal(f"the sheet {sheet} cannot be read ({exc.strerror})") from None
    return f"SHEET: {real}, last changed {changed}"


def check_repo(inputs: dict, repo: Path = REPO, url: str = GITHUB_URL,
               timeout: float = FETCH_TIMEOUT) -> str | None:
    """Checks 1 and 2. Returns the unreachable-GitHub warning, if any.

    `inputs` maps a flag name to the path it names; None values are skipped.
    """
    warning = None
    try:
        snap = fetch_snapshot(url, timeout)
        save_snapshot(snap, repo)
        against = "GitHub's main"
    except Unreachable as exc:
        snap = load_snapshot(repo)
        if snap is None:
            raise Refusal(f"GitHub could not be reached ({exc}), and this copy has never "
                          f"been checked against GitHub, so nothing confirms what code "
                          f"it is running") from None
        against = f"the copy of GitHub's main saved {local_time(snap.checked_at)}"
        warning = (f"CODE NOT CHECKED AGAINST GITHUB: the engine could not reach GitHub "
                   f"({exc}), so it compared against {against} and cannot confirm GitHub "
                   f"has no newer work")
    for flag, path in inputs.items():
        if path is not None:
            committed_input(Path(path), flag, snap, repo)
    compare(snap, repo, against)
    return warning
