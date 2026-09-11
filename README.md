# Madden

Weekly ATS picks for Scott's office pick'em pool. Every game on the sheet, one point each,
no confidence weighting.

**The source of truth is the spec**, at `Knowledge/AI Systems/Agent Specs/madden.md` in the
vault (also synced to Google Drive as `madden.md`). This repo implements it. Where the code
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

python -m madden.run \
  --sheet "~/Downloads/Eustace - NFL2026w1.xlsx" \
  --week examples/week1-2026.yaml \
  --tranche sunday \
  --expect 16
```

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
- Situational matrix, all four rules, with the neutral-site carve-out.
- Market consensus from the-odds-api.com (**with hyphens**), median across books, with
  staleness read from each book's own `last_update`.
- Edge, key-number crossing, banding, deviation-from-favorite accounting.
- Tiebreaker with the deliberate offset off the market total.
- Run log, run health, degrade-and-warn on every data fault.

## What is not built

- **Power rating.** `power_rating.enabled: false`. The model term is zero. Until a rating
  exists the number is the market plus the matrix and nothing else, and every run says so.
- **Call A**, status adjudication and model-validity verdicts. Until it exists, structural
  breaks are declared by hand in the week file's `blind:` list.
- **Call B**, the writer. Drivers are currently generated in code from the actual inputs.
- **Schedule feed** for venue and roof state. The week file stands in. Temperature and
  wind now come from open-meteo (`madden/weather.py`); the week file only overrides them.
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
