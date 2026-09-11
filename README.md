# Madden

Weekly ATS picks for Scott's office pick'em pool. Every game on the sheet, one point each,
no confidence weighting.

**The spec is the source of truth.** It is authored in the vault, at `Knowledge/AI Systems/
Agent Specs/madden.md`. `docs/madden-spec.md` here is the **read copy**, kept byte-identical,
because a path into the vault is unfollowable from a session started in this project. An edit
goes to both, identically, in the same commit. This repo implements the spec: where the code
and the spec disagree, the spec wins and the code is wrong.

**Nothing here is edited from memory.** Every parameter in `params.yaml` is tagged MEASURED
with its evidence, or GUESS with what would settle it. A reconstruction from memory in
September 2026 had the dome rule at -3.3, the divisional rule at -1.1, an invented "70F
outdoor" rule that does not exist, and no global home baseline at all. It flipped picks in
six of fifteen games. That is the failure this file exists to prevent.

## Run it

```bash
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)          # ODDS_API_KEY

python -m madden.run --tranche sunday
```

That is the whole command. The sheet is chosen by the highest week number in its filename,
and the season and week are worked out from the games on it, so neither needs a flag.

`--week examples/week1-2026.yaml` is optional: neutral sites, blind flags and manual
overrides. It may also declare `season:` and `week:`, which overrides the schedule lookup —
the escape hatch for a run when nflverse cannot be reached. A declared week that disagrees
with the schedule still wins, and says so in run health, because a leftover week file would
otherwise reintroduce by hand the dark exposure layer this mechanism exists to prevent.

Add `--offline-lines examples/week1-2026-lines.json` to run on hand-entered lines when the
API is down or out of credits. Tranches are `thursday`, `international`, `sunday`, `all`.

Every run writes a JSON log to `logs/`.

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
- **Backtest harness.** Needs nflverse ingest plus the pool archive. This is what would
  re-establish the 56.9% measurement, which currently exists only as a claim in the spec
  because the sandbox that produced it was discarded.
- **Scoreboard writer** (Airtable recommended, not confirmed).

## Rules that are not negotiable

- Never fabricate a missing line. Missing stays missing and the game gets flagged.
- Degrade and warn on a data fault. Halt only on a sheet fault.
- Madden never submits, never contacts, never publishes.
- `ODDS_API_KEY` lives in `.env`, which `.gitignore` excludes. Never in the vault, never in
  a repo, never in a conversation.
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
