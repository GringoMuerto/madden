---
type: agent-spec
status: approved
created: 2026-09-10
revised: 2026-09-10
playbook_version: 2026-08-06
supersedes: the first madden.md draft written earlier on 2026-09-10, now trashed
---

# Madden — weekly NFL office-pool advisor, picking every game against the spread

> **Read the Evidence Ledger before changing any number in this spec.** Every parameter is marked either MEASURED with its source, or GUESS with what would settle it. The single most expensive mistake available here is treating a guess as a finding. It was made twice during design and caught both times only by a holdout.

---

## Job

**Trigger.** Scott drops the week's pool sheet (.xlsx) into `OW Pick Em/26-27/` in Google Drive. Sheet arrives Tuesday, occasionally Wednesday.

**Inputs.** The sheet's frozen spreads; current market consensus spreads; official injury designations and inactives; opponent-adjusted efficiency metrics; schedule/venue; temperature for outdoor games.

**Outputs.** A complete, submittable set of picks for the tranche being run, each with pick, drift, edge, confidence band, one-line driver, and a deviation-from-favorite flag. Plus blind games listed separately with leans and reasons. Plus the Monday night combined-score tiebreaker. Plus run health.

**Reader.** Scott only. He submits manually.

**What it replaces.** Picking by feel, which produced 52.9%, 47.8%, 55.4% and 47.8% across four seasons — a mean of 51.0% and a range of eight points, consistent with a coin flip.

### Pool rules (all stated by Scott, all binding)

- Straight picks against the spread, every game, one point each, no confidence weighting.
- **Two prizes: weekly ($220/wk × 18 = $3,960) and season ($505/$303/$202 = $1,010).** Weekly is 78% of the pot. Scott's stated priority is the season; the money says weekly. **Neither matters, because one strategy maximises both** (see Objective).
- Field: 51-59 players across the archived seasons.
- Deadlines are **per game, before each game's own kickoff**. Complete sheets are not required.
- Scott submits in **two tranches by choice**: Thursday (TNF) and Sunday morning (everything else). A third early tranche only when an international game kicks before the Sunday window. **This is his fairness decision regarding the league operator and is not to be re-argued**, even though it costs the inactives on ~6-7 games a week.
- **The operator always publishes half-point spreads**, never whole numbers, to prevent pushes.
- **Unpicked games revert to the favorite.** So the do-nothing baseline is "take every favorite," not "no pick."
- Sheet layout: col E favorite, col G favorite W-L, col J spread, col M underdog W-L, col O underdog; headers on row 10; picks marked with an "X"; **home team in ALL CAPS**; games grouped under day headings that vary week to week (Wednesday/Thursday/Saturday/Sunday/Monday).
- Weekly tie-breaker: closest to the **Monday Night Football combined score**.

---

## Objective

**Maximise expected correct picks. Every week. All season. No exceptions, no modes, no switches.**

This was contested during design and the data settled it. The standard advice — that weekly prizes need differentiation while season prizes need accuracy — depends on the field clustering. **Scott's field does not cluster.** Two randomly chosen entries agree on only 57.6% of picks, differing on nearly seven of sixteen games a week. Differentiation is therefore free, and deliberately taking a worse side to manufacture it costs expected wins while buying separation already in hand.

Simulated on the actual pool structure (51 players, 18 weeks, $220/wk, $505/$303/$202, ties split):

| True skill | Expected $/season | Weekly wins | P(title) |
|---|---|---|---|
| 50.0% | $96 | 0.65 | 2.2% |
| 52.0% | $171 | 0.88 | 8.2% |
| 54.0% | $300 | 1.19 | 22.1% |
| 56.0% | $471 | 1.57 | 43.8% |

The 50% row returning $96 against a $100 entry is the sanity check. Returns are **convex**: each additional point buys more than the one before, which is the argument for the market edges over the situational ones.

**The bar.** Winning percentages across four archived seasons: 55.0%, 58.0%, 58.8%, 54.4%. The winner averages **~56.5%**. Madden's realistic 52-54% is a top-ten finish, not a title. Do not let anyone, including the author of this spec, describe 54% as a winning number.

---

## What actually carries this system

The drift term carries the system. The power rating is not built. If it is ever built, it ships damped, and its weight is not to be increased without a measured A/B. The situational matrix is worth roughly one pick a season, two rules survived a holdout out of thirty tested, and it is not to be expanded without the same discipline. The injury valuation was designed and cancelled on 2026-09-10 because injuries reach the picks through the market line and a separate injury number would double count it; injury data flags unresolved starters only, with no points attached.

---

## Architecture decision

**Rung 2: a deterministic script with two model calls inside it.** Not a single call, not an agent with tools, not a team.

The weekly sequence is identical every run. Nothing about its order varies by input, so the playbook's rule applies: a known repeatable sequence belongs in code rather than in a model re-deciding the flow.

**Team rejected.** None of the five justifications holds — steps are dependent, the week fits one context, components would contend over shared state, the graph is fixed. The independent-coverage argument is satisfied instead by lane isolation between the two model calls (see Connections).

**Single agent with tools rejected.** It would let a model re-decide a fixed sequence weekly, adding cost and variance for nothing.

---

## The algorithm

### Core equation

```
MADDEN'S NUMBER = current market consensus line
                + situational adjustments          (applied AFTER regression)
                + w × (power rating − market line)  (w ≈ 0.35, season-scaled)

EDGE            = MADDEN'S NUMBER − the sheet's frozen line
PICK            = the side the edge points to
```

**Drift and the hook are not separate terms.** Both fall out of one subtraction: anchor on the current number, compare to the frozen one. Drift is the difference; the hook is the half-point positioning inside it. Earlier drafts treated these as two mechanisms and two components. They are one.

### Pipeline

1. **Parse the sheet.** Locate the header row by finding the labels "Favorite", "Spread", "Underdog" rather than hardcoding row 10 — day blocks resize weekly and the operator edits his own template. Hard-stop if the game count does not match the slate.
2. **Resolve venue** from the schedule and actual stadium. **Never from the operator's capitalisation.** Use the ALL CAPS convention only as a cross-check that his sheet matches the real slate; a mismatch means a flexed game, a relocation, or his typo. In international games he capitalises a nominal home team that is not at home.
3. **Fetch** current consensus spreads (multi-book average), official designations and inactives, efficiency inputs, temperature for outdoor games.
4. **Call A** — status adjudication and model-validity verdicts.
5. **Compute the power rating** per game.
6. **Regress toward the market** at a per-game weight.
7. **Apply the situational matrix** — after regression, never before.
8. **Compute the edge** against the frozen line; convert to cover probability.
9. **Band** and assign picks. Every game gets a pick.
10. **Call B** — write the drivers.
11. **Emit** the tranche sheet, the blind list, the tiebreaker, run health.
12. **Log** everything; grade completed games against the baselines.

### Power rating

A blend, never a single metric — every source examined agrees a blend outpredicts any component.

- Opponent-adjusted EPA per play differential, **offence weighted 1.6 to defence 1.0** (published optimum for predicting future net EPA).
- Point differential.
- Success rate as a consistency check.
- Recency-weighted within season.
- **Carries a preseason prior that shrinks as games accumulate but never decays to zero.** TeamRankings' documented methodology evolution found that retaining preseason weight improved predictions *even in the final weeks*, not just early ones. Without this, Madden contributes nothing of his own in weeks 1-3.

### Market regression — two components, not one

Blending a model with the market produces a prediction more accurate than either alone; published optimum ≈ **65% market / 35% model**. That is the base. The weight then moves on two independent things, and **collapsing them into one number is an error made in an earlier draft**:

- **Strength trust** decays with season maturity. Team data through three weeks rests on ~180 plays and does not stabilise until ~week 8. Schedule: 85% market weeks 1-4, 75% weeks 5-8, 65% thereafter.
- **News trust** is driven by drift and **overrides** strength trust. Drift is news, not an opinion about team strength, and must not be damped by a maturity schedule. Material news-driven movement pushes the weight toward total regardless of week.

Blindness flags from Call A push the weight to 90%+ for that game specifically.

**Attribution happens in code**, by joining Call A's status verdicts to movement size — never by letting a model see both:
- Material status change + consistent-direction movement = **news-driven**. Trust the new number hard.
- Movement with no corresponding status change = **unexplained**. Trust partially.
- Movement much larger than the status change justifies = **log only, do not act**. Evidence too thin.

**Reprice, never follow.** Madden does not pick a team because money came in on them. He prices a stale number against a better one. The literature on whether movement predicts outcomes is genuinely mixed and none of it matters for this use: the only claim being made is that the current number is a better estimate than the frozen one.

### Situational matrix — applied AFTER regression

These are **measured market errors**, not estimates of team strength. Regressing them toward the market would erase the very thing being corrected. This is the single most important architectural detail in the spec.

Fitted on 1999-2012, tested untouched on 2013-2025. Benchmarked against the **49.0% home base rate**, not 50% — an error in the first draft that overstated every value.

| Rule | Points to the HOME team | n | Evidence |
|---|---|---|---|
| Dome-based visitor, outdoors, 75°F+ | **−2.8** | 271 | z = −3.10; replicates 40.2% / 41.0% across eras; not a warm-climate confound (warm-city dome visitors 40.6%, cold-city 40.5%) |
| Home underdog of 7+ | **+2.3** | 493 | z = +2.57; replicates 57.3% / 54.4% |
| Divisional game | **−0.8** | 2,608 | Survives a temperature control (48.1% vs 50.5% non-div) |
| Global home baseline | **−0.3** | 6,712 | Home teams cover 49.0% |

Combined holdout on 2013-2025: 52.5% across 1,767 games, rising to 55.9% where the adjustment exceeds 2 points and 59.0% above 3. In-sample was 54.0%; the 1.5-point degradation is what honest fitting looks like. Triggers on ~140 of 272 games a season.

### Edge, key numbers and banding

Edge is the blended number minus the frozen line, **converted to change in cover probability** rather than thresholded in raw points. Margins are lumpy: ~15% of games land on exactly 3, ~9% on 7, 5-6% on 10, 4-5% on 14; 4, 5, 8 and 9 are low-frequency. A half point across 3 is worth several times a full point from 8 to 9. Stern's 1986 result — margin minus spread ≈ normal, mean 0, SD ~13.4-13.9 — holds and supplies the conversion away from key numbers.

Sub-half-point differences from a single book are measurement noise. **Price against a multi-book consensus.**

| Band | Trigger | Behaviour |
|---|---|---|
| High | Edge 3+ pts, or any edge crossing a key number, no blindness flag | Pick, driver named |
| Medium | Edge 1.5-3 pts | Pick, driver named |
| Coin flip | Edge under 1.5 pts (~2pp cover probability) | Pick the model side, labelled a coin flip, no narrative |
| Blind | Structural break flagged by Call A | Pick with lean, listed separately |

### Deviation accounting

Because unpicked games revert to the favorite, **Madden's value exists only where he deviates from the favorite.** Every run reports the deviation count; the scoreboard grades deviations separately. A 9-7 week with fifteen favorite picks produced almost nothing.

### Tiebreaker (Monday night combined score)

Anchor on the market total, then **offset deliberately rather than sitting on it**. Actual scores scatter around the total with SD 13.4 while the total's average error is ~0.7 with a median of zero — it nails the average and misses almost every game. The field will cluster on the one obvious public number, so the total is the most crowded and least likely square on the board.

Offset **3-5 points**, held constant all season so the log means something. Direction is **unresolved**: under hits 49.8% against over's 48.7%, which is noise; right-skewed scoring argues the other way. If the pool has a sub-tie rule favouring the lower guess, offset down and that is a rule rather than a theory.

Wind is the only weather variable that reliably moves totals (20+ mph ≈ 2.7 fewer points; under hits ~54% above 10 mph). Temperature evidence conflicts — apply wind, flag temperature, adjust for neither until tested.

**Honest scope:** this pays only in a weekly tie and is close to a lottery even played well. Worth doing because it is cheap.

---

## Workers

### Call A — status adjudicator and model-validity check

**Mandate.** Convert fetched injury reports, designations, inactives and personnel news into (a) a starter-status verdict per team, (b) tier-2 absence flags, (c) a model-validity verdict per game.

**Method.** Read what was fetched. Decide starter in / out / limited with a confidence and the supporting source line. Separately decide whether the season data still describes the team that will take the field.

**Where it looks first.** Official league and team designations and the inactives list — not aggregator commentary about them.

**What it hunts.** Status changes after the sheet was set, and four structural-break classes: personnel or scheme change invalidating history; a non-QB injury not yet reflected in efficiency metrics; teams not competing; insufficient data.

**Definition of good.** Every team receives a verdict with a citation. No team unresolved. Never asserts a designation absent from the fetched text.

**Output.** Structured per team and per game, in **plain text, not rigid JSON envelopes** — a controlled study found a five-role pipeline fell from 75% to 45% accuracy under JSON inter-agent messaging and recovered to 82% on plain text.

**Lane boundary.** Does **not** see the spreads, the drift, or Madden's number, and does not know which side is favored. If it can see the line it will reason toward it, and the status signal and the market signal stop being independent. **This isolation is what supplies the independent-coverage property that would otherwise argue for a team.**

**Powers.** Exactly one beyond reporting: it may lower confidence in Madden's number for a named game, shifting that game's regression weight toward the market. **It cannot flip a pick.**

**Budget.** 12 fetches, hard cap.

**Context slice.** The games in this tranche, the teams, the fetched status text. Never the sheet, never the lines.

### Call B — writer

**Mandate.** Turn the finished pick table into per-game drivers in Scott's voice.

**Method.** State the driver of each edge in the vocabulary of the method file and nothing else.

**Definition of good.** Every explanation traces to a specific input value. Coin flips are labelled as coin flips rather than dressed up. No criterion outside the method file appears anywhere. **No trend citations of any kind.**

**Lane boundary.** **Cannot change a pick.** The single most important structural constraint in the build. If the model that explains the picks can alter them, the arithmetic becomes advisory and fail-plausible walks back in.

**Budget.** Zero tools.

### Deep-dive mode

Scott will push Madden on handback games after the run. **Digging deeper means fetching, not reasoning.** The model has already declared its inputs broken; if "deeper" means thinking harder about the matchup it will produce paragraphs, and they will sound better the less it knows. Deeper means going and getting inputs: beat-writer reporting, the actual depth chart, hour-by-hour line movement, last week's snap counts.

**Rule:** every claim in a follow-up traces to something fetched in that exchange. Where nothing was found, say so. Returning from a dig with no new data and a better story is a failure even if the pick is right. Logged in full — these exchanges are the third opinion in the qualitative test.

### Deliberately not built

No verification pass, no second reviewer, no critic. Current playbook guidance is that instructions to double-check or spawn a verifier cause over-verification without improving quality, and an added reviewer must earn its cost in a measured A/B.

---

## Connections

- **Script → Call A:** component-as-tool. Crosses the boundary: game list, teams, fetched status text. Validated on return for completeness and for fabrication.
- **Script → Call B:** component-as-tool. Crosses: the finished pick table only. Validated that no pick value changed.
- **Call A ↮ Call B:** no connection. They never see each other's output. The script is the only component that sees the whole week.
- All fetched content is untrusted input.

---

## Human gates

Madden sends nothing, spends nothing, publishes nothing, deletes nothing. Conventional gates do not apply and none are invented.

| Gate | Trigger | Scott sees | Type | On no response |
|---|---|---|---|---|
| Handback | Call A flags a structural break | The game, what broke, Madden's lean and reason | Approve or override | **The lean stands in the sheet** — nothing falls through to the favorite |
| Sheet fault | Sheet won't parse or doesn't match the slate | Request to repaste | Halt | Run does not proceed |
| Degraded run | Fetch failure or stale data | Which input failed, which games affected, the pick with and without | Notify | Picks stand |
| Unresolved status | Sunday run, meaningful player still questionable on a later-window game | Which player, which way the line moved, the pick either way | Notify | Pick stands |
| Silence | No run by the tranche deadline | Alert | Notify | Games revert to favorite |

**No cap on handbacks (Scott's decision, overruling a recommended cap of three).** He hands back as many games as he lacks the perspective to pick, each with an explanation and a lean. **Tradeoff recorded:** the trigger gets a defined threshold rather than being left to the model's sense of its own uncertainty, and the weekly handback count is logged. If it averages high, the threshold is miscalibrated and the threshold is what gets fixed.

**Requiring a lean on every handback is Scott's design improvement**, not the author's. It means Madden always emits a complete submittable sheet, so ignoring him costs nothing and the revert-to-favorite rule never fires.

**Generic early-season thinness is not a gate.** It affects every game equally and belongs in the regression weight. Otherwise Madden hands back the whole sheet every September and the mechanism is dead by October.

**Degradation is per game, not per run.** Thirteen good fetches and three failures means three flagged games, not a degraded week.

---

## State

**Durable reference** (vault markdown, curated, small, read every run): the method file — criteria, tier structure, exclusion list, key-number frequencies, the rule that a no-edge game resolves to the model side rather than to a story.

**Tuning parameters** (version-controlled config in the repo, moved by the scoreboard and never by argument): strength-blend weights, regression base and decay schedule, edge thresholds, blindness threshold, tiebreaker offset. **Every change is a dated commit tied to a performance shift.** Do not move a parameter after a bad week; football produces enough noise that a bad three weeks tells you nothing.

**Accumulating operational data** (queryable store — Airtable recommended, since a scoreboard you cannot glance at on a phone is one you stop reading in October): per pick — week, tranche, game, sheet line, Tuesday market snapshot, current line, drift, hook side and number, power rating, regression weight applied, situational adjustments, edge, band, pick, deviation flag, blindness flag, Scott's override, shadow qualitative opinion, outcome. Plus the baselines.

**Perishable, fetched fresh, never written to disk:** lines, designations, inactives, weather, efficiency metrics. Absolute. A cached Wednesday line would make Madden report no drift on exactly the game where drift was the point.

**Staleness — use the data's own timestamps, not a clock heuristic.** The odds API returns `last_update` per bookmaker *and* per market. Read it. This replaces the six-hour rule in the first draft and is strictly better. For efficiency data the test is whether it includes last week's games, not how many hours old the file is — sources refresh on different weekly schedules and an hours rule would fire every week on current data. For the tranche about to kick off, the real test is whether **inactives have published** for those specific games.

**Never fabricate a missing number.** If a line cannot be fetched, Madden does not supply one from anywhere else. A model asked for a line it could not retrieve will produce a plausible one that looks real. Missing stays missing and the game gets flagged. **Enforced in code**, per the playbook's rule that an unenforceable rule is a suggestion.

---

## Guardrails

- Call A: 12 tool calls hard cap. Call B: zero.
- Source allowlist. Official league and team injury data, named books for lines, named efficiency sources. Not left to the model's judgment — this domain is among the most aggressively SEO-optimised on the internet and drift toward SEO content over authoritative sources is a named failure mode.
- No halting spend ceiling. Two model calls against sixteen games is not a cost story.
- Degrade and warn, never stop, on data faults. Halt only on sheet fault.
- Madden never submits, never contacts, never publishes.

---

## Observability

- Per-run log created at dispatch, human-readable, append-only.
- Instrument: run and tranche id, inference and tool-call count per model call, tokens, duration, finish reason, error type, every fetch with source and timestamp.
- **Alert on absence of output.** A tranche deadline passing with no run must reach Scott. The playbook names the silent stop as the most common real-world agent failure and the least instrumented, and here it costs a week of automatic favorite picks.
- Weekly handback count, tracked for threshold drift.
- Deviation-from-favorite count per run.
- API quota remaining, read from `x-requests-remaining`.

---

## Evaluation harness

The scoreboard is nearly free: every pick resolves within days against unambiguous truth.

**Baselines, graded weekly.** The primary one is **take every favorite**, because it is literally the do-nothing alternative under the revert rule. Across four archived seasons it ran 45.4%, 53.1%, 56.7%, 51.1% — combined 51.5% over 976 games, a z of 0.94, which is nothing. Also track every home team (51.0% combined) and **the market side relative to the sheet**, which is Madden's primary input stripped of all computation. If he cannot beat that third one, the model layer is decoration.

**2025 yardstick, for grading a season, not guidance to act on** (pool lines joined to nflverse, 269 games; single season, see open item 6): always take the favorite 51.3%; market-side rule alone 53.9%; situational matrix alone 50.9%; market plus matrix 56.9%. Adding a power rating was tested once and made results worse; the test is not reproducible from this repo and the figure is withheld rather than recorded.

**Track by tranche, not only in aggregate.** Thursday games carry ~2 days of drift; Sunday games ~5 plus inactives. If Madden performs materially better on Sunday games, that is direct evidence the drift thesis is what works. If the tranches perform identically, the thesis is weaker than claimed and Scott should know by midseason.

**Shadow qualitative test.** From week one, Madden generates a qualitative opinion on every game, tags which structural-break class he thinks applies, timestamps it before kickoff, writes it to the log, and **never touches a pick with it.** Graded at season end per class. Costs nothing this season; buys the answer for next. Honest limit: the interesting subsets are small (structural breaks perhaps 20-30 a year), so this will sit at the edge of usable.

**Third opinion.** Scott's overrides on handback games are logged distinctly. Over a season this answers whether his judgment beats the model in the exact spots where the model knows it is blind. If it does, the handback earns its place. If it does not, he should be taking the lean and should be told so.

**First three test cases (drafted, not yet reviewed by Scott):**
1. **Rigged sanity case.** Sheet line 3.5 off the market with a confirmed QB ruled out in the consistent direction. Madden must produce a high-confidence pick on the side the market moved toward, with drift named. Failure here is unmissable.
2. **Hook case.** Market parked on exactly 3, sheet at 3.5, no drift, no injury news. Madden must identify the underdog as holding the hook and band it high despite a near-zero model edge.
3. **Blindness case.** Team changed starting QB in week 6; season efficiency data describes the prior starter. Call A must flag invalidity, the regression weight must move to 90%+, the game must appear in the handback list with a lean, and Call B must not invent a narrative to fill the gap.

**Noise floor.** A single week is not a result. A single season is barely one: 272 picks carries a standard error of ~3 points, so even a full live season will not cleanly separate 54% from 50%. **Do not evaluate in October.** Expect 52-54%.

---

## Runtime

Git-backed local project, run through Claude Code on the MacBook, invoked manually by Scott. Not a scheduled local task pointed at the vault (prohibited by `CLAUDE.md`; **confirm the exact rule there before implementation — not yet done**).

- Repo: `~/dev/madden`, git-initialised.
- `ODDS_API_KEY` in `.env`, excluded by `.gitignore`. Never in the vault, never in a repo, never in a conversation. **Verified working 2026-09-10** — authenticated call returned `x-requests-last: 1`.
- Tuning parameters in version-controlled config in the same repo.

| Run | When (Central) | Covers | Notes |
|---|---|---|---|
| Tuesday snapshot | On sheet arrival | Nothing | Captures market consensus at sheet-set time. Picks nothing, submits nothing. Establishes the true drift baseline and **finally measures whether the operator leans when he rounds** — the question four years of archives could not answer. |
| Thursday | Thursday morning | TNF only | ~2 days of drift. Weakest-informed tranche. |
| International | ~7:15 a.m. Sunday, only in weeks with an overseas kickoff | That game only | Inactives post 7:00 a.m. Central for an 8:30 kickoff. Overnight market is thinner; Madden should say so. |
| Sunday main | 10:30-11:30 a.m. | Everything else, incl. late afternoon, SNF, MNF | Inactives confirmed for the noon slate only. |

**Known accepted cost.** Submitting everything Sunday morning means ~6-7 games a week are picked with a questionable designation unresolved (3:25 games resolve 1:55 p.m., SNF 5:50 p.m.). Partial rather than total, since the market number has usually absorbed the news. **Scott's fairness decision; not to be re-argued.** Madden flags these rather than working around it.

---

## Data layer

| Source | Key | Cost | Use |
|---|---|---|---|
| **the-odds-api.com** (hyphens — see warning) | Free, email only | 1 credit/call, ~20/month against 500 | Current consensus spreads, `last_update` timestamps, totals for the tiebreaker |
| **ESPN unofficial API** | None | Free | **Not an injury source** (changed 2026-09-10). Its injury status is ESPN's own news summary, not the official designation, and official game statuses post Friday. On 2026-09-10 an entry marked `source: basic/manual` listed Michael Penix Jr. "Out" (Knee - ACL) while the official report had him at full participation, and that entry was the only reason ATL at PIT was flagged blind. Its comment attributed the status to the head coach, so it may prove right; that is the point. It is a summary of news, not the designation. Do not move injuries back to ESPN because it is the more convenient endpoint. |
| **nflverse** (GitHub) | None | Free | Schedules, venue, closing spreads, play-by-play for EPA. **The injury source:** the official league injury report and the daily depth chart, used only for the quarterback exposure line (names, no points). Rebuilt daily about 12:00 UTC; the build time prints with every run. |
| **open-meteo.com** | None | Free | Forecast temperature and wind at the stadium for each kickoff: temperature for the 75°F dome-visitor rule, wind for the tiebreaker. Added 2026-09-10, replacing temperatures taken from a sportsbook's weather page. A failed fetch means no temperature, and the rule does not fire. |

⚠️ **The vendor publishes an impersonator warning about itself.** The real domain is **the-odds-api.com** (hyphens). An unaffiliated site at **theoddsapi.com** (no hyphens, registered 2024) resells their data without authorisation. A third similarly-named business, odds-api.io, is a separate company and was accidentally cited during design.

**Independently verified:** GitHub account `the-odds-api` created 2019-11-28 with 319 followers; community Python wrappers built against their v3 and v4 APIs; competitors publish "alternative to The Odds API" comparison pages naming it as the incumbent. Not verified: their Australian Business Register entry (fetch blocked), and the free plan's exact monthly allowance from their own pages.

**Historical endpoints are paid-only** (explicit in their docs, cost 10× standard). The multi-season validation path is therefore closed on the free tier.

**Spec the odds feed as a swappable component.** The interface is "give me a current consensus spread per game." Which vendor supplies it is a config line, not an architectural commitment.

---

## Evidence ledger

**MEASURED — from Scott's four-season pool archive (2022-2025)**
- No skill exists in the pool. Split-half correlation of player performance **r = −0.17**; first-half vs second-half **r = −0.07**. Observed SD of season totals 6.86 picks against 8.25 for pure chance. The entire 26-pick spread from first to last is noise.
- Winner takes it with ~56.5% (55.0 / 58.0 / 58.8 / 54.4).
- Field takes the favorite 62.5% of the time; two entries agree on 57.6% of picks.
- No simple strategy persists: favorites 45.4 / 53.1 / 56.7 / 51.1, home 51.3 / 50.0 / 50.0 / 52.6, underdogs 54.6 / 46.9 / 43.3 / 48.9.
- Scott: 52.9 / 47.8 / 55.4 / 47.8, mean 51.0%.

**MEASURED — 2025 season, pool lines joined to nflverse (269 games, score-verified)**
- The operator's line differs from the market close in **67% of games**, mean absolute gap **0.86 points**; market lays more on the favorite in 116 games vs 63.
- Always the favorite: 51.3%. Market side only: 53.9%. Matrix only: 50.9%. **Combined: 56.9% (153-116).**
- Market side on gaps ≥2 points: **66.7% (28-14)**.
- ⚠️ **Single season. The matrix half is partly in-sample. Thresholds chosen after seeing the data. Closing lines are later than Scott's decision point. Not proven.**

**MEASURED — nflverse 1999-2025**
- Home teams cover **49.0%** (6,902 games). Stable at 49.0% across the last 10, 15 and 27 seasons. Home favorites 48.2% (CI excludes 50); home underdogs 50.2%.
- Resolving a 2-point effect needs ~4,900 games ≈ **18 seasons**. Three years cannot do it.
- The situational matrix and its era holdout, as tabled above.

**MEASURED — external**
- Market regression optimum ~65/35; offensive EPA weight 1.6:1.0; key-number frequencies; Stern's margin distribution; bye/rest effects absent post-2011 CBA; wind thresholds; efficiency stabilisation ~180 plays / week 8; nfelo's 17-year record (55.90% ATS vs opening line, 55.06% vs closing, MAE 0.13 better than opening and 0.01 worse than closing, CLV 5.86%) — **note these are on ~100-145 selected bets a season, not all 272 games.**

**GUESS — starting values, to be moved only by the scoreboard**
- The 50/50 split between point differential and the efficiency composite.
- The 85/75/65 regression schedule.
- The 90% blindness weight.
- Edge thresholds of 3 and 1.5 points, ~2pp.
- 12-fetch budget for Call A.
- Tiebreaker offset magnitude and direction.

**ASSUMPTION — load-bearing and unverified**
- That Scott's coworkers submit early and do not track line movement. This is the basis for claiming drift gives an edge **against the field** rather than only against his own stale sheet. Supported only by a vendor's marketing example. The Tuesday snapshot plus this season's returned sheets will test it.

---

## Tested and dead — Madden must be structurally incapable of invoking these

Revenge games · momentum · hot and cold streaks · primetime · rookie coaches · blowout hangovers · travel spots · scheduling quirks · bye weeks · rest advantages of any size · short weeks · wind on sides · home favorites of 10+ · week-of-season effects · marquee-team public bias · West Coast circadian angles · new-starting-QB splits · surface changes · second divisional meetings · Denver altitude · total-line extremes · spreads pinned at 3 or 7 · fading the public · team-specific home field · PFF grades as a paid input (redundant with the QB adjustment) · international game history (too small to distinguish pattern from noise) · narrative matchup reasoning as a pick driver · weekly variance chasing · opponent modelling during the regular season.

Thirty-plus hypotheses tested against 27 seasons with an era holdout on each. **Two survived.** Formulations like "since 1989, road teams off a close road loss are 62-22 ATS in revenge spots excluding small favorites and late-season games" are data mining with filters chosen after seeing the data, and a language model asked to justify a pick finds them irresistible.

---

## Open items

1. **`CLAUDE.md` runtime rule** not yet read and confirmed.
2. **Scoreboard store** — Airtable recommended, not confirmed.
3. **Tiebreaker sub-tie rule** — does a tie in distance favour the lower guess? Would settle the offset direction.
4. **Monday night deadline** — "on the sheet but due earlier." Unresolved.
5. **The first three test cases** are drafted but not reviewed by Scott.
6. **The 56.9% rests on one season** with thresholds chosen after seeing that season. It is promising, not proven.

---

## Handoff

`skill-creator` takes this for authoring, test cases and evaluation. Agent-creator does not author the skill.
