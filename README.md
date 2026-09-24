# Madden

Weekly ATS picks for Scott's office pick'em pool. Every game on the sheet, one point each,
no confidence weighting.

**The spec is the source of truth, and there is one copy of it: `docs/madden-spec.md`.**
The vault's `Knowledge/AI Systems/Agent Specs/madden.md` is a pointer here (since
2026-09-23). This repo implements the spec: where the code and the spec disagree, the spec
wins and the code is wrong.

**Nothing here is edited from memory.** Every parameter in `params.yaml` is tagged MEASURED
with its evidence, or GUESS with what would settle it. A reconstruction from memory in
September 2026 had the dome rule at -3.3, the divisional rule at -1.1, an invented "70F
outdoor" rule that does not exist, and no global home baseline at all. It flipped picks in
six of fifteen games. That is the failure this file exists to prevent.

## Run it

```bash
pip install -r requirements.txt               # once
python3 ~/Library/CloudStorage/GoogleDrive-cseustace@gmail.com/My\ Drive/Scott\'s\ Second\ Brain/Apps/madden/madden/run.py
```

The engine lives in the vault at `Scott's Second Brain/Apps/madden` (moved from
`~/dev/madden` on 2026-09-24 so Cowork can run it with only the vault connected). Its git
database lives outside the vault at `~/git-repos/madden.git`, and `.git` here is a one-line
pointer to it, because Drive sync corrupts git databases.

That is the whole command. `.env` (`ODDS_API_KEY`, and `MADDEN_SHEETS_DIR` relative to this
folder, `../../Personal/NFL/OW Pick Em/26-27`, so it means the same folder on the Mac and in
Cowork) is read from the repo
automatically. **Every run prices every game on the sheet that has not kicked off yet**,
whenever it runs (changed 2026-09-24: Scott submits Friday, Saturday or Sunday as suits him).
Each run fetches lines, injuries and forecasts fresh, so the board reflects that moment and
sharpens as kickoff nears. Run health says how many games it priced, names any already under
way (not priced), and gives the next kickoff. Once every game has kicked off it refuses.
`--tranche thursday|international|sunday|all` still picks one batch by hand. The sheet is chosen by the highest week number in its
filename, and the season and week are worked out from the games on it, so neither needs a
flag.

**Runs from anywhere.** Relative paths (`--params`, `--log`, `--week`, `--offline-lines`)
mean paths in this repo, whatever directory you run from. `python3 -m madden.run` also works
from inside the repo, or anywhere the package is importable. From `~` it is not, so use the
path form above.

### Checks before every run

The engine refuses to run, exit 3, with one plain sentence saying why, unless all hold:

1. **It matches GitHub's main, file for file.** It takes a fresh copy of GitHub's `main`
   over HTTPS (30 seconds at most; the repo is public, so no key) into a scratch folder and
   compares every file here against it. A file changed here, missing here, or here but not
   on GitHub refuses, naming the first few. Files GitHub's `.gitignore` ignores (`.env`,
   `logs/`, `.cache/` and the rest) don't count, and neither does `.git`. It never uses the
   local git database, so it works the same on the Mac and in Cowork, where that database
   is out of reach. If GitHub can't be reached, it compares against the copy saved at the
   last good check (`.cache/github-main.json`) and says `CODE NOT CHECKED AGAINST GITHUB`
   in run health; with no saved copy it refuses.
2. **Settings, week and lines files are on GitHub.** A `--params`, `--week` or
   `--offline-lines` file from outside the repo, or not on GitHub, refuses.
3. **The sheet is from the pick'em folder.** It must be inside `MADDEN_SHEETS_DIR`. Run
   health prints `SHEET: <full path>, last changed <time>`. The sheet is the one input
   nobody checks the origin of, so look at that time.

So after any change: commit and push, then run. `--cache` is also refused under Claude
Code, because cached forecasts are not a submittable board.

**Then the network.** Before fetching anything it checks every host the run will use:
`github.com` and `release-assets.githubusercontent.com` (nflverse), `api.the-odds-api.com`
unless `--offline-lines`, `api.open-meteo.com` unless `--no-weather`. A host the network's
proxy refuses stops the run, exit 3, naming the host to add to that environment's
allowlist. This is what a Cowork run without the allowlist entries hits. A timeout is not a
refusal: that fetch degrades and warns as before.

**Claude Code and Cowork run it the same way** once the hosts above are reachable (Cowork's
allowlist is set in Cowork) and the Cowork conversation has Scott's Second Brain connected.

`--week examples/week1-2026.yaml` is optional: neutral sites, blind flags and manual
overrides. It may also declare `season:` and `week:`, which overrides the schedule lookup —
the escape hatch for a run when nflverse cannot be reached. A declared week that disagrees
with the schedule still wins, and says so in run health, because a leftover week file would
otherwise reintroduce by hand the dark exposure layer this mechanism exists to prevent.

Add `--offline-lines examples/week1-2026-lines.json` to run on hand-entered lines when the
API is down or out of credits. Both files must be on GitHub (check 2).

Every run writes a JSON log to `logs/`.

## Grade it

```bash
python -m madden.grade logs/run-20260913T164534Z-sunday.json
```

Joins a run log to nflverse final scores. Reports Madden's record over the picks he made,
the record **as submitted** (a withheld pick reverts to the favorite and is scored that
way, because the pool scores it that way), take-every-favorite, the deviation record, the
market side relative to the sheet, and the record by band. Reads a log the engine already
wrote; it never prices a game.

```bash
python -m madden.backtest --archive "<season-final>.xlsx" --season 2025
```

Prices a whole archived season with the real engine — `make_pick`, the real `params.yaml`
— and grades it against every baseline. Three caveats travel with every number it prints,
and they are in the module docstring: the market line is the **closing** line rather than
the Sunday-morning one, the band thresholds were chosen after seeing seasons that include
the one being tested, and one season carries a standard error near 3 points. Compare two
rules on the games where they **differ**, which is what its head-to-head section prints.

## The arithmetic

```
MADDEN'S NUMBER = current market consensus line
                + situational adjustments
                + w x (power rating - market line)      [w = 0, no rating built yet]

EDGE  = MADDEN'S NUMBER - the sheet's frozen line
PICK  = the side the edge points to
```

Every line is a **home line**: points the home team is favored by, negative for a home dog.
Situational adjustments are **points added to the home team**, so a negative adjustment
favours the visitor. Invert that sign and every pick inverts with it, which is why
`tests/test_core.py` pins it.

The situational matrix is applied **after** market regression, never before. These are
measured market errors, not estimates of team strength; regressing them toward the market
erases the thing being corrected.

## What is built

- Sheet parser. Finds the header by its labels, never by row number. Reads the ALL CAPS
  convention as a cross-check only. Hard stops on a game-count mismatch.
- Week resolution (`madden/schedule.py`). Season and week come from matching the sheet's
  pairings against nflverse's published schedule — not from the filename, which the
  operator numbers from zero (`NFL2026w0.xlsx` is NFL week 1, and the sheet's own tab says
  `Week01`), and not from the clock, which is wrong at the week boundary. The filename week
  is demoted to a cross-check, like ALL CAPS. A sheet matching no week, or matching two
  equally well, is a sheet fault and halts. Nothing downstream may run on an unresolved
  week: the injury report is keyed on it, and a wrong week fetches cleanly, returns an
  empty slice, and reports every team UNKNOWN. That was silent until 2026-09-11.
- Situational matrix, all four rules, with the neutral-site carve-out.
- Market consensus from the-odds-api.com (**with hyphens**), median across books, with
  staleness read from each book's own `last_update`.
- Edge, key-number crossing, banding, deviation-from-favorite accounting.
- Tiebreaker with the deliberate offset off the market total.
- Three display-only sections under the board, from the official injury report and the
  daily depth chart via nflverse. **Quarterback exposure**: quarterbacks whose status is
  unresolved. **Starter health**: the share of each team's listed starters with no row on
  the report, offence and defence separately, with a board total. **Injured quarterbacks**:
  every quarterback carrying a row, resolved or not, at his depth-chart rank. Names and
  counts only, no points, no effect on any pick or band. The
  injury valuation was designed and cancelled; see the spec's *What actually carries
  this system*. Exposure needs no flag and cannot go dark quietly: a failed fetch, an
  empty week, and individual teams missing from the build each raise their own run-health
  line, and only an explicit `--no-injuries` turns the layer off.
- **Drift sanity check** (`odds_api.max_drift_points`, GUESS). A fetched line further from
  the sheet than the threshold is not believed: the pick is withheld and the game is
  flagged, checked before any arithmetic runs. Added 2026-09-20 after the week 1 Thursday
  board priced SF at LAR off a recorded market line of -19.0 against a sheet of +3.5 and
  banded it high on the size of the error. The band is computed from the edge, so a broken
  line does not degrade a pick, it manufactures a confident one.
- **Grading harness** (`python -m madden.grade <log>`). Joins a run log to nflverse final
  scores and reports Madden's record, the same record as actually submitted (reverts
  included), take-every-favorite, deviations, the market side, and the record by band.
- **Backtest** (`python -m madden.backtest --archive <season-final.xlsx> --season 2025`).
  Prices a whole archived season with the real engine and grades it against the baselines.
  It reproduces the spec's 2025 figures to within a fraction of a point, so that
  measurement is no longer a claim that cannot be re-derived from this repo.
- **Deadline ledger and after-kickoff warning.** A tranche's deadline is its earliest
  kickoff, from the nflverse schedule. At the start of every run the engine reports any
  tranche whose deadline has passed with no run that beat it — so the Sunday run names the
  Thursday miss while the rest of the week can still be submitted. **A run written after
  the deadline does not count as covering it**: week 1's Thursday tranche ran two and a
  half hours after its own kickoff, wrote a log, exited 0, and satisfied any check that
  only asks whether a log exists. Separately, a game in this tranche that has already
  kicked off is named in run health, because a line fetched then is a live in-play price
  and an edge computed from one is read off the scoreboard.
- Run log, run health, degrade-and-warn on every data fault.

## What is not built

- **Power rating.** `power_rating.enabled: false`. The model term is zero, so the number is
  the market plus the matrix and nothing else. A run says nothing about this: it is a
  recorded design decision, not a run-health event, and a warning that fires every single
  week trains the reader to skim the section that carries the real ones. Run health speaks
  only when the flag and the fact disagree — `enabled: true` with no rating built, which is
  a config claiming a layer the engine does not have. The check keys on whether a rating
  module exists (`run.rating_module`), never on the flag, because flipping the flag alone
  moves no number: `make_pick`'s `model_term` defaults to 0.0 and `run.py` passes nothing.
- **Call A**, status adjudication and model-validity verdicts. Until it exists, structural
  breaks are declared by hand in the week file's `blind:` list.
- **Call B**, the writer. Drivers are currently generated in code from the actual inputs.
- **Schedule feed** for venue and roof state. The week file stands in. Temperature and
  wind now come from open-meteo (`madden/weather.py`); the week file only overrides them.
  The schedule *is* now fetched (`madden/schedule.py`), but only to resolve the week —
  venue and roof still come from `teams.py` and the week file.
- **A watcher for a week with no run at all.** The deadline ledger above speaks at the
  start of the *next* run, so it catches a skipped tranche and cannot catch a skipped
  week. That needs something outside the engine on a timer — the spec names absence of
  output as the most common real-world agent failure and the least instrumented.
- **Scoreboard writer** (Airtable recommended, not confirmed).

## Rules that are not negotiable

- Never fabricate a missing line. Missing stays missing and the game gets flagged.
- Degrade and warn on a data fault. Halt only on a sheet fault.
- Madden never submits, never contacts, never publishes.
- `ODDS_API_KEY` lives in `.env`, which `.gitignore` excludes: never in a repo, never in a
  conversation. Since 2026-09-24 that `.env` is in the vault, by Scott's decision, so Cowork
  can read it. That is acceptable because the key is on the free plan (500 requests a month,
  no billing): a leak costs a month's quota, not money. A copy is in 1Password.
  `MADDEN_GITHUB_TOKEN` is needed only if the repo is ever private again; the engine hands
  it to git through the environment, never on a command line.
- **No copy of the repo carries `.env`.** A recursive copy takes the key with it and lands it
  somewhere nothing protects. Use `tar --exclude=.env`, or copy the files you need rather
  than the tree, then `find <dir> -name '.env*'` before you leave the copy behind. Seven
  copies were found sitting in scratch directories on 2026-09-11.
- Move a GUESS only when the scoreboard moves it, in a dated commit tied to a performance
  shift. Never after a bad week.

## Tested and dead

Revenge games, momentum, streaks, primetime, rookie coaches, blowout hangovers, travel
spots, bye weeks, rest advantages, short weeks, wind on sides, big home favorites,
week-of-season effects, public bias, West Coast circadian angles, new-QB splits, surface
changes, second divisional meetings, altitude, fading the public, and about fifteen more.
Thirty-plus hypotheses against 27 seasons with an era holdout on each. Two survived.

Madden must be structurally incapable of invoking any of them. If a driver string ever
cites one, that is a bug.
