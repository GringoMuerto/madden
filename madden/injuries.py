"""Injury designations from ESPN, per team, every page, in parallel, under a deadline.

History of this module, because both earlier versions failed silently:

  * The first resolved every entry one request at a time. It took five minutes and
    printed nothing, which is indistinguishable from hung. It also read only the first
    page of each team's list (25 of 54-61 entries).
  * The second switched to ESPN's league-wide endpoint, which returns 403 Access Denied.
    Its fallback read `status` off index entries that are bare $ref pointers, found
    nothing, marked every team fetched, and dropped the error. Run health then reported
    "no quarterback or high-impact designations" for a team with two QBs listed.

What this version guarantees:

  * A team is either FAILED, with the error that failed it, or it was read completely.
    Zero readable designations is FAILED, never clean. A missing page, an unreadable
    entry, an unreadable athlete behind a live designation, or the deadline expiring all
    make the team FAILED. There is no partial success, because a partial list with the
    quarterback missing looks exactly like a clean one.
  * Each player counts once, at his most recent entry. The list is a history, so an old
    "Out" superseded by a later "Active" must not count.
  * Nothing is written to disk unless the caller asks for the cache. The spec: perishable
    data is fetched fresh, never written to disk.

It never infers a designation and it never flips a pick. It never reads a betting site
or a search result.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from pathlib import Path

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"

ESPN_TEAM_IDS = {
    "ARI": 22, "ATL": 1, "BAL": 33, "BUF": 2, "CAR": 29, "CHI": 3, "CIN": 4,
    "CLE": 5, "DAL": 6, "DEN": 7, "DET": 8, "GB": 9, "HOU": 34, "IND": 11,
    "JAX": 30, "KC": 12, "LV": 13, "LAC": 24, "LA": 14, "MIA": 15, "MIN": 16,
    "NE": 17, "NO": 18, "NYG": 19, "NYJ": 20, "PHI": 21, "PIT": 23, "SF": 25,
    "SEA": 26, "TB": 27, "TEN": 10, "WAS": 28,
}
ESPN_ABBR = {
    "WSH": "WAS", "LAR": "LA", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA",
}

# Operational limits, not tuning. A request that fails is retried once.
WORKERS = 24
REQUEST_TIMEOUT = 12
DEADLINE_SECONDS = 90
RETRIES = 1

# Severity weights, tier-2 positions and the blind threshold live in params.yaml under
# `injuries`, each tagged GUESS. They are not in the spec. Every function that scores a
# designation takes that block as `cfg`, so there is no second copy of a number here.

CACHE = Path(".cache")
CACHE_TTL_SECONDS = 3600


@dataclass
class Designation:
    team: str
    player: str
    position: str
    status: str          # lowercased, verbatim from the feed
    detail: str = ""
    date: str = ""       # the entry's own timestamp, as ESPN writes it

    def severity(self, cfg) -> float:
        return float(cfg["severity"].get(self.status, 0.0))

    @property
    def is_qb(self) -> bool:
        return self.position.upper() == "QB"


@dataclass
class TeamReport:
    team: str
    designations: list = field(default_factory=list)
    fetched: bool = False
    error: str = ""

    def quarterbacks(self, cfg) -> list:
        return [d for d in self.designations if d.is_qb and d.severity(cfg) > 0]

    def tier2(self, cfg) -> list:
        floor = cfg["severity"][cfg["tier2_min_status"]]
        positions = {p.upper() for p in cfg["tier2_positions"]}
        return [d for d in self.designations if not d.is_qb
                and d.position.upper() in positions and d.severity(cfg) >= floor]

    def confidence_penalty(self, cfg) -> float:
        if not self.fetched:
            return 0.0
        qb = max((d.severity(cfg) for d in self.quarterbacks(cfg)), default=0.0)
        others = min(cfg["tier2_cap"], cfg["tier2_per_player"] * len(self.tier2(cfg)))
        return min(1.0, qb + others)


def _norm(abbr: str) -> str:
    a = (abbr or "").upper()
    return ESPN_ABBR.get(a, a)


def _http_get(url: str):
    url = url.replace("http://", "https://")
    last = None
    for _ in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "madden/1.0"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.load(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
            last = exc
    raise RuntimeError(f"{type(last).__name__}: {last}") from last


def _athlete_key(ref: str) -> str:
    return (ref or "").split("?")[0]


class _Run:
    """One fetch across many teams: a shared pool, a shared deadline, per-team errors."""

    def __init__(self, get, deadline_seconds):
        self.get = get
        self.ends = time.monotonic() + deadline_seconds
        self.deadline_seconds = deadline_seconds
        self.pool = ThreadPoolExecutor(max_workers=WORKERS)

    def map(self, jobs):
        """jobs: {key: url}. Returns ({key: payload}, {key: error string})."""
        futures = {self.pool.submit(self.get, url): key for key, url in jobs.items()}
        done, pending = wait(futures, timeout=max(0.0, self.ends - time.monotonic()))
        results, errors = {}, {}
        for f in done:
            key = futures[f]
            try:
                results[key] = f.result()
            except Exception as exc:                                  # noqa: BLE001
                errors[key] = str(exc)
        for f in pending:
            f.cancel()
            errors[futures[f]] = f"deadline of {self.deadline_seconds}s reached"
        return results, errors

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def _fail(report: TeamReport, message: str) -> None:
    if not report.error:
        report.error = message
    report.fetched = False
    report.designations = []


def fetch_all(teams, use_cache: bool = False, get=None,
              deadline_seconds: int = DEADLINE_SECONDS) -> dict:
    """Every team in `teams`, read completely or marked FAILED with its reason."""
    wanted = sorted({_norm(t) for t in teams})
    reports = {t: TeamReport(team=t) for t in wanted}

    cached = _load_cache() if use_cache else {}
    for t in wanted:
        if t in cached:
            reports[t] = cached[t]
    todo = [t for t in wanted if not reports[t].fetched]
    for t in todo:
        if t not in ESPN_TEAM_IDS:
            _fail(reports[t], f"no ESPN team id for {t}")
    todo = [t for t in todo if t in ESPN_TEAM_IDS]
    if not todo:
        return reports

    run = _Run(get or _http_get, deadline_seconds)
    try:
        _fetch(run, todo, reports)
    finally:
        run.close()

    if use_cache:
        _store_cache({t: r for t, r in reports.items() if r.fetched})
    return reports


def _fetch(run: _Run, todo: list, reports: dict) -> None:
    index_url = lambda t, page: f"{CORE}/teams/{ESPN_TEAM_IDS[t]}/injuries?page={page}"

    # 1. First page of every team's list, which also says how many pages there are.
    first, errs = run.map({t: index_url(t, 1) for t in todo})
    for t, e in errs.items():
        _fail(reports[t], f"injury list page 1: {e}")
    live = [t for t in todo if t in first]

    # 2. Every remaining page.
    jobs = {}
    for t in live:
        for page in range(2, int(first[t].get("pageCount") or 1) + 1):
            jobs[(t, page)] = index_url(t, page)
    pages, errs = run.map(jobs)
    for (t, page), e in errs.items():
        _fail(reports[t], f"injury list page {page}: {e}")

    refs: dict = {}
    for t in live:
        if reports[t].error:
            continue
        items = list(first[t].get("items") or [])
        for (pt, _), payload in sorted(pages.items()):
            if pt == t:
                items.extend(payload.get("items") or [])
        expected = first[t].get("count")
        if expected is not None and len(items) != int(expected):
            _fail(reports[t], f"ESPN reports {expected} entries, {len(items)} were listed")
            continue
        if not items:
            _fail(reports[t], "ESPN returned no injury entries, so there is nothing to read")
            continue
        refs[t] = [i.get("$ref", "") for i in items]

    # 3. Every entry. The index holds only pointers; status and date live here.
    jobs = {(t, n): ref for t, rs in refs.items() for n, ref in enumerate(rs) if ref}
    entries, errs = run.map(jobs)
    unreadable: dict = {}
    for (t, _), e in errs.items():
        unreadable.setdefault(t, []).append(e)
    for t, es in unreadable.items():
        _fail(reports[t], f"{len(es)} of {len(refs[t])} entries unreadable ({es[0]})")

    # 4. Latest entry per player. The list is a history.
    latest: dict = {}
    for (t, _), e in entries.items():
        if reports[t].error:
            continue
        status = str(e.get("status") or "").strip().lower()
        who = _athlete_key((e.get("athlete") or {}).get("$ref", ""))
        if not status or not who:
            continue
        prev = latest.get((t, who))
        if prev is None or str(e.get("date") or "") > str(prev.get("date") or ""):
            latest[(t, who)] = e

    for t in refs:
        if not reports[t].error and not any(k[0] == t for k in latest):
            _fail(reports[t], f"none of {len(refs[t])} entries carried a readable status")

    # 5. Name and position, only for players whose latest status is not "active". An
    # unreadable athlete behind a live designation could be the quarterback, so it fails
    # the team rather than being dropped.
    need = {k: (e.get("athlete") or {}).get("$ref", "") for k, e in latest.items()
            if not reports[k[0]].error
            and str(e.get("status") or "").strip().lower() != "active"}
    athletes, errs = run.map(need)
    for (t, _), e in errs.items():
        _fail(reports[t], f"athlete behind a live designation unreadable ({e})")

    for (t, who), e in sorted(latest.items()):
        r = reports[t]
        if r.error:
            continue
        a = athletes.get((t, who), {})
        r.designations.append(Designation(
            team=t,
            player=a.get("displayName") or a.get("fullName") or "",
            position=((a.get("position") or {}).get("abbreviation") or ""),
            status=str(e.get("status") or "").strip().lower(),
            detail=str((e.get("details") or {}).get("type") or ""),
            date=str(e.get("date") or ""),
        ))
    for t in refs:
        if not reports[t].error:
            reports[t].fetched = True


def _load_cache() -> dict:
    p = CACHE / "injuries.json"
    if not p.is_file() or (time.time() - p.stat().st_mtime) >= CACHE_TTL_SECONDS:
        return {}
    try:
        raw = json.loads(p.read_text())
    except ValueError:
        return {}
    out = {}
    for t, r in raw.items():
        out[t] = TeamReport(team=t, fetched=True,
                            designations=[Designation(**d) for d in r["designations"]])
    return out


def _store_cache(reports: dict) -> None:
    CACHE.mkdir(exist_ok=True)
    (CACHE / "injuries.json").write_text(json.dumps(
        {t: {"designations": [asdict(d) for d in r.designations]}
         for t, r in reports.items()}))


def summarise(reports: dict, cfg) -> list:
    """Run-health lines. A failure is named with its reason; it is never reported clean."""
    out = []
    failed = {t: r.error or "no reason recorded" for t, r in reports.items() if not r.fetched}
    by_reason: dict = {}
    for t, why in sorted(failed.items()):
        by_reason.setdefault(why, []).append(t)
    for why, teams in by_reason.items():
        who = "every team" if len(teams) == len(reports) else ", ".join(teams)
        out.append(f"INJURY FETCH FAILED for {who}: {why}. No availability data for "
                   f"{'them' if len(teams) > 1 else 'that team'} except through the market line")
    for team, r in sorted(reports.items()):
        if not r.fetched:
            continue
        for d in r.quarterbacks(cfg):
            out.append(f"{team}: QB {d.player} listed {d.status}"
                       + (f" ({d.detail})" if d.detail else "") + f" [{d.date}]")
        tier2 = r.tier2(cfg)
        if tier2:
            names = ", ".join(f"{d.player} {d.position} {d.status}" for d in tier2[:4])
            out.append(f"{team}: {names}")
    ok = [t for t, r in reports.items() if r.fetched]
    if ok and not any(r.quarterbacks(cfg) or r.tier2(cfg)
                      for r in reports.values() if r.fetched):
        out.append(f"injury reports read in full for {len(ok)} teams: no quarterback or "
                   f"high-impact designations")
    return out


def game_confidence(reports: dict, home: str, away: str, cfg) -> tuple:
    reasons, worst = [], 0.0
    for team in (_norm(home), _norm(away)):
        r = reports.get(team)
        if r is None or not r.fetched:
            continue
        p = r.confidence_penalty(cfg)
        if p <= 0:
            continue
        worst = max(worst, p)
        for d in r.quarterbacks(cfg):
            reasons.append(f"{team} QB {d.player} {d.status}")
    return worst, reasons
