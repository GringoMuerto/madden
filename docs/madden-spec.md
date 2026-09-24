---
type: agent-spec
status: approved
created: 2026-09-10
revised: 2026-09-24
playbook_version: 2026-08-06
supersedes: the first madden.md draft written earlier on 2026-09-10, now trashed
---

# Madden — weekly NFL office-pool advisor, picking every game against the spread

> **Read the Evidence Ledger before changing any number in this spec.** Every parameter is marked either MEASURED with its source, or GUESS with what would settle it. The single most expensive mistake available here is treating a guess as a finding. It was made twice during design and caught both times only by a holdout.

---

## Job

**Trigger.** Scott drops the week's pool sheet (.xlsx) into `OW Pick Em/26-27/`, kept in the vault at `Personal/NFL/` (in `My Drive/NFL` until 2026-09-24). Sheet arrives Tuesday, occasionally Wednesday.

**Inputs.** The sheet's frozen spreads; current market consensus spreads; official injury designations and inactives; opponent-adjusted efficiency metrics; schedule/venue; temperature for outdoor games.

**Outputs.** A complete, submittable set of picks for every game on the sheet not yet kicked off, each with pick, drift, edge, confidence band, one-line driver, and a deviation-from-favorite flag. Plus blind games listed separately with leans and reasons. Plus the Monday night combined-score tiebreaker. Plus three display-only sections under the board -- quarterback exposure, starter health, injured quarterbacks by depth-chart rank -- none of which carries points. Plus run health.

**Reader.** Scott only. He submits manually.

**What it replaces.** Picking by feel, which produced 52.9%, 47.8%, 55.4% and 47.8% across four seasons — a mean of 51.0% and a range of eight points, consistent with a coin flip.

### Pool rules (all stated by Scott, all binding)

- Straight picks against the spread, every game, one point each, no confidence weighting.
- **Two prizes: weekly ($220/wk × 18 = $3,960) and season ($505/$303/$202 = $1,010).** Weekly is 78% of the pot. Scott's stated priority is the season; the money says weekly. **Neither matters, because one strategy maximises both** (see Objective).
- Field: 51-59 players across the archived seasons.
- Deadlines are **per game, before each game's own kickoff**. Complete sheets are not required.
- **Scott submits whenever it suits him (his decision, 2026-09-24)**, often Friday or Saturday when he will not be at his computer Sunday morning. So every run prices every game on the sheet not yet kicked off, with the freshest data available at that moment; a later run is better informed and may pick differently. Until 2026-09-24 he submitted in two fixed tranches (Thursday night, Sunday morning), which cost the inactives on ~6-7 games a week.
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

The drift term carries the system. The power rating is not built. If it is ever built, it ships damped, and its weight is not to be increased without a measured A/B. The situational matrix is worth roughly one pick a season, two rules survived a holdout out of thirty tested, and it is not to be expanded without the same discipline. The injury valuation was designed and cancelled on 2026-09-10 because injuries reach the picks through the market line and a separate injury number would double count it; injury data flags and counts, with no points attached, on the terms set out immediately below.

### What prints under the board

Three sections print beneath every board. The first was built on 2026-09-10; the
second and third were added on 2026-09-11 at Scott's request. **None of them is a price.** Each attaches no points and cannot move a pick, a
band, an edge or the tiebreaker; each is there because Scott often submits before every
designation has resolved (Friday, Saturday or Sunday, as suits him), which leaves games picked
with a designation open, and these say where to look before he submits.

| Section | Covers | Included when |
|---|---|---|
| Quarterback exposure | Quarterbacks whose status is unresolved | Questionable or Doubtful, or no game status yet on a team whose final report has not published and whose latest practice was DNP or limited |
| Starter health | Every team on the board, offence and defence separately, with a board total | Always. Counts listed starters with no row on this week's official report |
| Injured quarterbacks | Every quarterback carrying a row, resolved or not, at his depth-chart rank | Always. Wider than exposure: a QB1 at full participation appears here and not there |

**Starter is the depth chart's own word, not a judgment.** Offence is rank 1 at every slot
of the published three-receiver package plus receivers ranked 1-3, eleven men for most
teams. Defence is rank 1 at every slot of whichever base front the team lists, twelve: the
eleven plus the nickel back the chart lists beside them. Special teams are not starters.

**Healthy means the report says nothing about him**, which is blunt and is labelled blunt
in the output: a full-participation note counts against a team exactly like a DNP, and a
veteran rest day counts like an injury. The percentage is a pointer, not a measurement,
and pushing it toward a severity weighting would rebuild the injury valuation that was
designed and cancelled on 2026-09-10.

**This resolves a contradiction in earlier drafts of this spec**, which said in one place
that injury data flags unresolved *starters* and in another that the nflverse report feeds
*the quarterback* exposure line. Starter health covers all starters; exposure and the
injured-quarterback list stay quarterbacks only. Non-QB status adjudication remains Call
A's, which is designed and not built.

**Failure is loud, never silent.** No injury report means UNKNOWN for every team in both
sections. No depth chart means starter health is UNKNOWN for every team and quarterbacks
print without a rank. A team absent from the depth chart build prints UNKNOWN, never a
clean sheet, and raises its own run-health line.

---

## Architecture decision

**As built, 2026-09-11: rung 2, a deterministic script with no model calls inside it, operated by one Claude Code skill.** The design further down places two model calls inside the script, Call A (status adjudication) and Call B (writer). Neither is built. Drivers are generated in code from the inputs, and structural breaks are declared by hand in the week file. The only model in the loop is the operator skill, and it sits outside the script.

The weekly sequence is identical every run. Nothing about its order varies by input, so the playbook's rule applies: a known repeatable sequence belongs in code rather than in a model re-deciding the flow.

**Team rejected.** None of the five justifications holds: steps are dependent, the week fits one context, components would contend over shared state, the graph is fixed.

**Agent-driven sequence rejected.** The operator is a single agent with tools, but it does not decide the sequence and it produces no number. It runs the script and reports.

**The tradeoff this shape carries.** The operator sees everything: sheet, lines, picks and injury news. Call A's lane boundary was designed to prevent exactly that, so the independence property claimed for Call A (status signal and market signal never meet in one model) does not exist in the as-built system. The shape is acceptable only because every pick, band and driver comes out of code, and the engine refuses to produce one from anything but its own committed code and inputs. That refusal is enforced in the engine, not in prose.

**Call A and Call B remain designed, not built.** Their specification under Workers stands. Building either is a change to this section.

### Redesigned 2026-09-23: a regular agent, no sandbox

Scott, 2026-09-23: *"I want to strip Madden down to be a regular agent and have the same guardrails that they have. It's way too complex right now."* The sandbox and everything built to prove it was in force were removed that day. The plan is `Claude Tasks/madden-redesign/Plan_v4.md`, reviewed three rounds by Stevie with no Blocks. What replaced it is below. What it replaced is in the dated history at the end of this section.

### Operator skill

**Mandate:** report exactly what the engine produced. When Scott digs into a game, fetch; never reason.
**Lives at** `plugins/scott-agents/skills/madden/SKILL.md` in `GringoMuerto/claude-skills`.
**Invoked** as `/madden` by Scott, from a Claude Code session started **anywhere**, or from Cowork. `disable-model-invocation: true`: loading the skill runs the engine and spends odds-API credits, so only Scott starts it.

**The engine runs as the skill loads,** before the model reads a word. A load-time command runs `scripts/run_engine.py`, which runs `python3 -m madden.run` in the vault's `Apps/madden` with no flags (so every game not yet kicked off), prints the engine's full output and exit code, allows 100 seconds, and always exits 0 so that the engine's refusals reach the model as text. While the skill is active the model holds no shell and no editing tool (`disallowed-tools: Bash Edit Write NotebookEdit`); it reads the output and reports it. `WebFetch` stays for follow-ups. The restriction clears on Scott's next message, so follow-up turns have normal tools, and the engine's own checks below are what stop a follow-up turn producing a board.

**A non-default run** (another tranche, `--sheet-week`, `--expect`, `--week`) is Scott's own: `! python3 "<Scott's Second Brain>/Apps/madden/madden/run.py" <flags>`, and the operator reports that output.

**The claude.ai copy** is a separate short file, `skills/madden/claude_ai_upload.md`, packed as the upload's one `SKILL.md`. It runs the engine where it has a shell that reaches the repo (Cowork), and in a claude.ai chat with no shell it produces nothing. No engine, no picks.

**Where the engine runs (changed 2026-09-24).** In Claude Code on Scott's Mac and in Cowork, the same way. Until 2026-09-24 it ran only in Claude Code. Week 3's Thursday run from Cowork showed why it could not run there: Cowork's network proxy refused `api.the-odds-api.com` (403 at the tunnel, `X-Proxy-Error: blocked-by-allowlist`), and check 1 fetched over SSH, for which Cowork has no key. That run printed a board with no lines. Running the same way in both needs:

- **The same hosts reachable from both:** `github.com` and `release-assets.githubusercontent.com` (nflverse, and check 1), `api.the-odds-api.com`, `api.open-meteo.com`. Cowork reaches only hosts on its network allowlist, which is set in Cowork, not in this repo.
- **The same GitHub access from both:** check 1 takes a fresh copy of GitHub's `main` over HTTPS. The repo is public (since 2026-09-24), so neither environment needs a key, the Mac's SSH key or a saved login.
- **The same folders from both (moved 2026-09-24):** the engine lives in the vault at `Apps/madden` and the pick'em sheets at `Personal/NFL`, so a Cowork conversation needs only Scott's Second Brain connected. Consolidation had kept `~/dev/madden` outside the vault, which is what stopped Cowork. The git database lives outside the vault at `~/git-repos/madden.git`, behind a one-line `.git` pointer, because Drive sync corrupts git databases; no run needs it. `MADDEN_SHEETS_DIR` is relative to the engine's folder, so it names the same folder wherever the vault is mounted. Madden sessions skip the vault's `CLAUDE.md` and `AGENTS.md` (`claudeMdExcludes` in the repo's `.claude/settings.json`): their read-everything-then-wait gate would stop a run.
- **The network check** below, so a host either environment cannot reach stops the run by name instead of producing an empty board.

**Not yet verified in Cowork (2026-09-24).** Three protections have been confirmed only in Claude Code on the Mac: Claude's file tools asking before editing Madden's folder (set in the Mac's `~/.claude/settings.json`); `--cache` refused, which keys on `CLAUDECODE=1`; and the operator skill removing the shell while `/madden` is active. Until a Cowork session confirms each one, the engine's own checks are what stand behind a Cowork board, and these three do not.

| May not | Enforced by |
|---|---|
| Produce a pick, line, band or driver by any route but the engine | While the skill is active the model has no shell, so it cannot run anything but the wrapper. After that, the engine's checks below |
| Produce picks from code, parameters, a week file or a lines file that is not committed and on GitHub | Engine checks 1 and 2 |
| Produce picks from a sheet outside the pick'em folder | Engine check 3 |
| Produce a submittable board from cached forecasts | `--cache` refused under Claude Code (`CLAUDECODE=1`) |
| Write any engine file with Claude's file tools | `ask` on `Edit(//Users/gringomuerto/Library/CloudStorage/GoogleDrive-cseustace@gmail.com/My Drive/Scott's Second Brain/Apps/madden/**)` and its `~/` form in `~/.claude/settings.json` (the `~/dev/madden` rules until 2026-09-24), from any session. Verified live 2026-09-11 (history below) |

**Left in prose deliberately.** Presenting the engine's output unrewritten: the text of a reply cannot be permission-gated. Mitigation: every report cites the log path the engine printed, so any figure can be checked against the file. Also prose: voice and the follow-up rule that every claim traces to something fetched in that exchange. If a follow-up ever cites a betting site, that rule is what failed.

### The engine's checks

They run on **every** engine run, from any shell, not only under Claude Code. Each failure prints `GUARDRAIL, halting:` and one plain sentence naming the problem, and exits 3. Code: `madden/guard.py`.

1. **The code matches GitHub's main, file for file (rewritten 2026-09-24).** The engine takes a shallow copy of GitHub's `main` over HTTPS into a scratch folder (30 seconds at most, no key, no credential helper) and compares every file in its folder against it by git blob hash. Refused: a file changed here, missing here, or here but not on GitHub, unless GitHub's own `.gitignore` ignores it (`.env`, `logs/`, `.cache/`, `.pytest_cache/` and the rest); the refusal names the first five of each. The repo root's `.git` (a folder, or the vault's one-line pointer) is not code and is skipped. This covers what the old checks covered (behind, ahead, split, uncommitted work, a file dropped beside the engine to shadow a module; the 2026-09-10 stale-checkout failure among them) without the local git database, which Cowork cannot reach. A good check is saved to `.cache/github-main.json`. **If GitHub cannot be reached,** the same comparison runs against that saved copy, so a changed or extra file still refuses. Otherwise it runs, and RUN HEALTH says: *"CODE NOT CHECKED AGAINST GITHUB: the engine could not reach GitHub (<git's reason>), so it compared against the copy of GitHub's main saved <time> and cannot confirm GitHub has no newer work."* With no saved copy it refuses. A Sunday-morning network hiccup must not cost the board, and it must not be silent either.
2. **Input files live in the repo and are on GitHub.** `--params`, `--week` and `--offline-lines` must resolve inside the repo and be tracked on GitHub's `main`, so check 1 covers their contents. A path outside the repo is refused, and so is a file in an ignored folder, which check 1 cannot see.
3. **The sheet comes from the pick'em folder.** The sheet, chosen or passed with `--sheet`, must resolve inside `MADDEN_SHEETS_DIR`, following symlinks. A relative `MADDEN_SHEETS_DIR` is relative to the engine's folder (`../../Personal/NFL/OW Pick Em/26-27`), so one setting names the same folder on the Mac and in Cowork. An unset `MADDEN_SHEETS_DIR` is a refusal. RUN HEALTH prints `SHEET: <full path>, last changed <local time>`.

**The network check (added 2026-09-24).** After checks 1 and 2 and before anything is fetched, the engine sends a HEAD request to one URL on every host the run will use: the nflverse schedule (which redirects to GitHub's download host), the odds API unless `--offline-lines`, open-meteo unless `--no-weather`. A proxy that refuses the connection (403 at the tunnel) refuses it on every run until its allowlist changes, so the run halts with `GUARDRAIL, halting:` naming each refused host and saying to add it to the environment's network allowlist (exit 3, no log, no odds credit spent: the check sends no key). Any HTTP answer means the host was reached. A timeout or DNS failure is a hiccup, not policy: it is left to the fetch that meets it, which degrades and warns as before. Code: `blocked_hosts` in `madden/net.py`.

**Together:** only code and inputs that are committed **and** on GitHub can produce picks. The one gap is when GitHub cannot be reached, and RUN HEALTH says so on the board.

**The weekly sheet is the one input nobody guarantees.** Code, parameters, week files and lines files must be committed and on GitHub. The sheet only has to sit in the pick'em Drive folder, and nothing checks who made it. Committing sheets was considered and rejected: the sheet arrives from the league organiser through Drive, and committing it would add a weekly step. The SHEET line's last-changed time is what makes a sheet made after the league's release easy to spot.

**Also kept:** a log write that fails degrades to exit 4 and `NOT LOGGED` (see Observability).

**Which games a run prices (changed 2026-09-24).** By default every game on the sheet whose kickoff, from the nflverse schedule, is still ahead (`--tranche remaining`; `auto` means the same). RUN HEALTH prints `GAMES: every game on the sheet not yet kicked off, <n> of <total>`, names any game already under way (not priced), and gives the next kickoff. A game with no kickoff time is priced, and a warning names it. If every game has kicked off, or no kickoff times are known, it refuses with a plain sentence (exit 3) before any odds credit is spent. A run made before a batch's first kickoff covers that batch in the missed-games check. `--tranche thursday|international|sunday|all` still prices one batch for Scott's own runs. Until 2026-09-24 the default was the earliest tranche still ahead, so a Thursday run priced only Thursday night.

**Runs from anywhere.** Relative paths (`--params`, `--log`, `--week`, `--offline-lines`) resolve against the repo root, not the working directory. `python3 "<Scott's Second Brain>/Apps/madden/madden/run.py"` works from any directory. `python3 -m madden.run` works from the repo or wherever the package is importable.

### Who writes to this repo (the sole-writer rule, restated 2026-09-23)

**Old rule, 2026-09-10:** "Only the Madden session writes to this repo. Nothing else pushes to it." Written after another session pushed engine code mid-run.

**Rule now:**
- Changes to Madden's code are made in a Claude Code session started in the vault's `Apps/madden`, then committed and pushed from there, like any repo.
- The engine's in-step-with-GitHub check is what stops a run from stale code. The old rule relied on sessions not writing.
- Codex is set read-only for this folder (`.codex/config.toml`, `sandbox_mode = "read-only"`), which takes effect when Codex is started here and trusts the folder; `~/.codex/config.toml` trusts `Apps/madden` since 2026-09-24. Started elsewhere, Codex writes only inside its own starting folder.
- Claude's file tools still ask before editing Madden's files, from any session.

This does not stop another session writing into Madden's folder through Bash. Nothing did before; a vault-started session did exactly that on 2026-09-23. The checks make such a write harmless to a run: code or inputs that are uncommitted, or committed but not on GitHub, cannot produce picks.

**This file is the one copy of the spec.** Until 2026-09-23 it was a byte-identical read copy of the vault's `Knowledge/AI Systems/Agent Specs/madden.md`, and every edit went to both. The vault file is now a pointer here.

### History: the sandbox years, 2026-09-10 to 2026-09-23

Recorded so the lessons survive. None of this is a live rule.

- **2026-09-10 to 09-11: sandbox rules and an engine input guard.** The operator ran under a Claude Code sandbox (`denyWrite` over the repo, a network allowlist, `allowUnsandboxedCommands: false`). The engine refused unless `SANDBOX_RUNTIME` was set, an `Edit` rule gated the file tools, every input was unwritable by the process, and an off-list host (`example.com`) was refused. Settings newer than the session, and a probe with no verdict, warned rather than refused.
- **2026-09-11: an inert rule caught.** `ask` on `Edit(//**)` matched nothing and never fired. It was replaced by path-scoped `ask` rules on `Edit(~/dev/madden/**)` and `Edit(//Users/gringomuerto/dev/madden/**)`, **verified by a four-probe run the same day**: prompts inside the repo, none outside, from a vault-started session. `Edit(path)` rules cover `Write`. `Write(...)` path rules are rejected by Claude Code. Lesson: **a path rule is not trusted until something has said it fired.** To re-verify after any settings change: fresh session, one probe at a time, Scott reports each, no `settings.local.json` in any scope.
- **2026-09-11: the writability check stopped discriminating.** The rules moved into user settings, which made the inputs read-only in every session. The guard inferred "guardrails loaded" from "inputs are read-only", and install-check step 6 (vault session refused) became false about ninety minutes after it was recorded. It was replaced by a transcript-location check, then within the hour by the in-force checks, when Scott removed the starting directory as a gate. Lesson: **a guard must key on a positive signal of the condition itself, not a side effect, and fail closed when it cannot read one.** The four checks key on git's own answer.
- **2026-09-11: the machine-wide allowlist.** At user scope it broke Leo's crew runs (`api.anthropic.com`, `mcp-proxy.anthropic.com` blocked) and grew to sixteen hosts. It governed Bash egress only; MCP, WebSearch and WebFetch were never behind it. The WebSearch/WebFetch deny was dropped the same day for the same reason.
- **2026-09-11: known defect, now closed. No git operation worked inside the sandbox.** Not `fetch` or `push` (network and credentials), and not `add` or `commit` (`denyWrite` covered `.git/`). The standing rule that `main` equals `origin/main` before a run was therefore never checked from inside a session, and every commit went through `!`, which left work uncommitted for 10 to 12 days. **Closed 2026-09-23:** there is no sandbox. A session started here commits and pushes normally, and the engine checks `main` against `origin/main` itself on every run.
- **2026-09-12 to 09-23: the rules drifted out of force.** The sandbox block left `~/.claude/settings.json` on 2026-09-12. A "posture file" at `~/.config/madden/settings.json` was loaded by nothing. The rules bound only sessions started in `~/dev/madden`, and the engine then refused every run from anywhere else, including Scott's own `!` runs. That complexity, not any single failure, is why it was removed.
- **2026-09-23: removed.** Scott's lift script (`Claude Tasks/lifts/2026-09-23_madden_remove_sandbox.py`) reduced the repo's `.claude/settings.json` to its `$schema` line, deleted the posture file, and set Codex read-only here. The engine's sandbox guard was replaced by the four checks above the same night.

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
11. **Emit** the tranche sheet, the blind list, the three display-only sections, the tiebreaker, run health.
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

*Status: designed, not built. See Architecture decision.*

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
| Unresolved status | Any run, meaningful player still questionable on a game not yet kicked off | Which player, which way the line moved, the pick either way | Notify | Pick stands |
| Silence | A game kicks off that no run priced before its kickoff | Alert (the next run's MISSED GAMES warning) | Notify | That game reverts to the favorite |
| Engine change | Claude's `Edit` or `Write` on any file under the vault's `Apps/madden`, from any session | The file and the change | Approve or reject | The write does not happen |
| Engine check fails | Code here differs from GitHub's main (a file changed, missing or extra); an input file outside the repo or not on GitHub; GitHub unreachable and never checked; a sheet outside `MADDEN_SHEETS_DIR`; a host the run needs refused by the network; every game kicked off; or `--cache` under Claude Code | The refusal, one plain sentence naming the problem (exit 3) | Halt | No picks |
| Code not checked against GitHub | GitHub's main could not be copied within 30 seconds, and the code here matches the copy saved at the last good check | `CODE NOT CHECKED AGAINST GITHUB` with that copy's time, under run health | Notify | **Picks stand** |

**No cap on handbacks (Scott's decision, overruling a recommended cap of three).** He hands back as many games as he lacks the perspective to pick, each with an explanation and a lean. **Tradeoff recorded:** the trigger gets a defined threshold rather than being left to the model's sense of its own uncertainty, and the weekly handback count is logged. If it averages high, the threshold is miscalibrated and the threshold is what gets fixed.

**Requiring a lean on every handback is Scott's design improvement**, not the author's. It means Madden always emits a complete submittable sheet, so ignoring him costs nothing and the revert-to-favorite rule never fires — **not true as built: see Known defect below**.

**Known defect, found 2026-09-11: the sheet is not always complete, and the revert-to-favorite rule does fire.** Not fixed; no fix designed.
- A handback from a structural break carries a lean, as designed. A game with no market line does not: `make_pick` withholds the side rather than supply a number from anywhere else, which is what *Never fabricate a missing number* under State requires.
- The two rules contradict each other and the build follows the second. Which one gives way is not decided here.
- Measured on the week 1 board: 2 of 16 games had no line, so 2 games reverted to the favorite. Both had already been played, which is a second reason no line existed.
- Until 2026-09-11 the engine printed those games under a handbacks heading that promised a lean for every game beneath it. They now print under `NO PICK`, which names the consequence. The heading no longer claims a lean for a game that has none.

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
- **No copy of the repo carries `.env`.** A recursive copy of Madden's folder takes `ODDS_API_KEY` with it — `tar`, `cp -r` and `rsync` all do — and a copy in a scratch directory is outside everything that protects the original: `.gitignore` does not reach it, no permission rule stops a copy being made, and nothing sweeps it afterwards. **Seven such copies were found on 2026-09-11**, in `$TMPDIR`, the oldest over an hour old, spanning at least four sessions and two of them made that evening while fixing a different defect. The habit that prevents it: `tar --exclude=.env`, or copy the files you need rather than the tree, then `find <dir> -name '.env*'` before leaving the copy behind. This is its own rule because the one below, about where the key lives, is silent about copies and was read as covering them.
- Operator enforcement: see Architecture decision → Operator skill and The engine's checks.

---

## Observability

- Per-run log created at dispatch, human-readable, append-only.
- Instrument: run and tranche id, inference and tool-call count per model call, tokens, duration, finish reason, error type, every fetch with source and timestamp.
- **Alert on absence of output.** A game kicking off that no run priced before its kickoff must reach Scott. The playbook names the silent stop as the most common real-world agent failure and the least instrumented, and here it costs a week of automatic favorite picks.
- Weekly handback count, tracked for threshold drift.
- Deviation-from-favorite count per run.
- API quota remaining, read from `x-requests-remaining`.

**Known defect, found and fixed 2026-09-11: a log write that could not land took the whole run down.** `path.write_text` was unwrapped, so a `PermissionError` from a sandbox (since removed, 2026-09-23) that did not allow writes to `logs/` raised an unhandled traceback and exited 1 — **after** the board had printed, correct and complete, to stdout. The run therefore produced a usable board and no record of it, which is the one combination the observability section exists to prevent: every figure Madden reports in prose is checkable only against the log it cites.

Fixed by degrading like any other data fault. The log is now built and written **before** run health prints, so its own failure can appear there as a named line; a failed write exits 4 and the board prints `NOT LOGGED` in place of the log path. The log record was otherwise unchanged; since 2026-09-23 it also carries `health_notes`, the SHEET and TRANCHE lines. Its own failure is the single warning the log can never carry.

---

## Evaluation harness

The scoreboard is nearly free: every pick resolves within days against unambiguous truth.

**Baselines, graded weekly.** The primary one is **take every favorite**, because it is literally the do-nothing alternative under the revert rule. Across four archived seasons it ran 45.4%, 53.1%, 56.7%, 51.1% — combined 51.5% over 976 games, a z of 0.94, which is nothing. Also track every home team (51.0% combined) and **the market side relative to the sheet**, which is Madden's primary input stripped of all computation. If he cannot beat that third one, the model layer is decoration.

**2025 yardstick, for grading a season, not guidance to act on** (pool lines joined to nflverse, 269 games; single season, see open item 6): always take the favorite 51.3%; market-side rule alone 53.9%; situational matrix alone 50.9%; market plus matrix 56.9%. Adding a power rating was tested once and made results worse; the test is not reproducible from this repo and the figure is withheld rather than recorded.

**Track by how long before kickoff each game was priced, not only in aggregate (changed 2026-09-24, when fixed tranches ended).** A game priced two days out carries less drift and fewer resolved designations than one priced the morning of. If late-priced games grade materially better, that is direct evidence the drift thesis is what works; if they grade the same, the thesis is weaker than claimed and Scott should know by midseason. The grading code does not yet split results this way.

**Shadow qualitative test.** From week one, Madden generates a qualitative opinion on every game, tags which structural-break class he thinks applies, timestamps it before kickoff, writes it to the log, and **never touches a pick with it.** Graded at season end per class. Costs nothing this season; buys the answer for next. Honest limit: the interesting subsets are small (structural breaks perhaps 20-30 a year), so this will sit at the edge of usable.

**Third opinion.** Scott's overrides on handback games are logged distinctly. Over a season this answers whether his judgment beats the model in the exact spots where the model knows it is blind. If it does, the handback earns its place. If it does not, he should be taking the lean and should be told so.

**First three test cases (drafted, not yet reviewed by Scott):**
1. **Rigged sanity case.** Sheet line 3.5 off the market with a confirmed QB ruled out in the consistent direction. Madden must produce a high-confidence pick on the side the market moved toward, with drift named. Failure here is unmissable.
2. **Hook case.** Market parked on exactly 3, sheet at 3.5, no drift, no injury news. Madden must identify the underdog as holding the hook and band it high despite a near-zero model edge.
3. **Blindness case.** Team changed starting QB in week 6; season efficiency data describes the prior starter. Call A must flag invalidity, the regression weight must move to 90%+, the game must appear in the handback list with a lean, and Call B must not invent a narrative to fill the gap.

**Noise floor.** A single week is not a result. A single season is barely one: 272 picks carries a standard error of ~3 points, so even a full live season will not cleanly separate 54% from 50%. **Do not evaluate in October.** Expect 52-54%.

---

## Runtime

Git-backed local project, run through Claude Code on the MacBook or through Cowork (see Where the engine runs), invoked manually by Scott as `/madden` **from any directory**, or by Scott himself with `! python3 "<Scott's Second Brain>/Apps/madden/madden/run.py"` (see Operator skill; no sandbox since 2026-09-23). Not a scheduled local task pointed at the vault (prohibited by `CLAUDE.md`; **confirm the exact rule there before implementation — not yet done**).

- Repo: `Scott's Second Brain/Apps/madden` (`~/dev/madden` until 2026-09-24), public on GitHub as `GringoMuerto/madden`. Its git database is `~/git-repos/madden.git`, behind a `gitdir:` pointer.
- `ODDS_API_KEY` in `.env`, excluded by `.gitignore`. In the vault since 2026-09-24, by Scott's decision, so Cowork can read it: the key is on the free plan (500 requests a month, no billing), so a leak costs a month's quota, not money, and a copy is in 1Password. Never in a repo, never in a conversation, and **never in a copy of the repo** — see Guardrails. **Verified working 2026-09-10** — authenticated call returned `x-requests-last: 1`.
- `MADDEN_GITHUB_TOKEN`: not needed while the repo is public. If it is ever private again: read-only, this repo only, with an expiry date, in `.env`. Same rules as `ODDS_API_KEY`. The engine hands it to git through the environment, never on a command line, where the process list would show it.
- Tuning parameters in version-controlled config in the same repo.

| Run | When (Central) | Covers | Notes |
|---|---|---|---|
| Tuesday snapshot | On sheet arrival | Nothing | Captures market consensus at sheet-set time. Picks nothing, submits nothing. Establishes the true drift baseline and **finally measures whether the operator leans when he rounds** — the question four years of archives could not answer. |
| Any run | Whenever Scott runs it, Wednesday to Sunday (changed 2026-09-24) | Every game on the sheet not yet kicked off | Freshest data at that moment; a later run is better informed. Official game statuses post Friday; inactives about 90 minutes before each kickoff (7:00 a.m. Central for an 8:30 overseas game). An overnight market is thinner. |

**Known accepted cost.** Submitting before a game's inactives post means picking with some designations unresolved, more of them the earlier the run: on a Friday, most of the week's. Partial rather than total, since the market number has usually absorbed the news. Scott's decision, 2026-09-24. Madden flags these (the exposure list) rather than working around it.

---

## Data layer

| Source | Key | Cost | Use |
|---|---|---|---|
| **the-odds-api.com** (hyphens — see warning) | Free, email only | 1 credit/call, ~20/month against 500 | Current consensus spreads, `last_update` timestamps, totals for the tiebreaker |
| **ESPN unofficial API** | None | Free | **Not an injury source** (changed 2026-09-10). Its injury status is ESPN's own news summary, not the official designation, and official game statuses post Friday. On 2026-09-10 an entry marked `source: basic/manual` listed Michael Penix Jr. "Out" (Knee - ACL) while the official report had him at full participation, and that entry was the only reason ATL at PIT was flagged blind. Its comment attributed the status to the head coach, so it may prove right; that is the point. It is a summary of news, not the designation. Do not move injuries back to ESPN because it is the more convenient endpoint. |
| **nflverse** (GitHub) | None | Free | Schedules, venue, closing spreads, play-by-play for EPA. **The injury source:** the official league injury report and the daily depth chart, used only for the three display-only sections under the board (names and counts, no points). Rebuilt daily about 12:00 UTC; the build time prints with every run. |
| **open-meteo.com** | None | Free | Forecast temperature and wind at the stadium for each kickoff, with kickoff times from the nflverse schedule (from 2026-09-24; before that from the odds feed, so a failed line fetch also meant no forecast): temperature for the 75°F dome-visitor rule, wind for the tiebreaker. Added 2026-09-10, replacing temperatures taken from a sportsbook's weather page. A failed fetch means no temperature, and the rule does not fire. |

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

**MEASURED — 2025 season, re-derived 2026-09-20 by `madden/backtest.py` (272 games)**

The block above was reproduced from this repo for the first time. Until this date those figures existed only as a claim, the sandbox that produced them having been discarded. Always the favorite **51.1%**, market side only **54.1%**, matrix only **51.1%**, combined **57.0%** — each within a fraction of a point of the recorded value, on 272 games against that block's 269. Market side on gaps ≥2 points reproduced **exactly**: 28-14, 66.7%. The engine's cover side agrees with the operator's own result column on **272 of 272** games, which is what independently validates the sign convention.

**Everything below survives the full season and dies on a half-season split.** Recorded because the full-season numbers are seductive and the split is the only reason they were not acted on.

| | weeks 1-9 | weeks 10-18 | full |
|---|---|---|---|
| market side, drift 0.5 | 58.6% (n=29) | 40.7% (n=27) | 50.0% |
| market side, drift 1.0-1.5 | 47.1% (n=34) | 53.1% (n=49) | 50.6% |
| market side, drift 2.0+ | **50.0% (n=16)** | 76.9% (n=26) | 66.7% |
| high band, edge ≥ 3 | 50.0% (n=10) | 70.6% (n=17) | 63.0% |
| high band, key crossing only | 42.9% (n=28) | 58.8% (n=34) | 51.6% |
| …crossing 3 | 46.2% (n=13) | 47.4% (n=19) | 46.9% |
| …crossing 7 | 30.8% (n=13) | 66.7% (n=12) | 48.0% |

**The 66.7% on 2+ point gaps is carried entirely by the second half of the season.** In weeks 1-9 it is 8-8, exactly even. Nothing in this table may be used as a rule.

**The high band holds two populations under one label.** A pick is high either because the edge is 3+ points or because a small edge steps across 3, 7, 10 or 14. The key-crossing branch is 62 of the 89 high-band games and grades 51.6% against the magnitude branch's 63.0%. **This changes no pick and never could:** the side is the sign of the edge, and the band is computed afterwards and gates nothing. Re-banding on magnitude alone relabels 62 games and moves the record not at all — 57.0% either way. Recorded so that nobody re-derives this split expecting a gain from acting on it.

**A 2.0-point drift floor was tested and rejected, 2026-09-20.** Discarding the market line when the drift is under 2 points — on the evidence in the table above that small drifts grade near 50% as a standalone directional rule — costs three points of accuracy: **54.0% against 57.0%, worse in both halves** (48.1 vs 51.9, and 59.9 vs 62.0). On the 56 picks it changes, the engine as built went 32-24 and the floor went 24-32. Taking the favorite below the floor instead is worse again, 51.8%, and flips between halves. **The lesson generalises and is the reason this is recorded: a drift that does not predict a side ON ITS OWN is not a drift worth removing from the number.** Those are two different measurements and the bucket table invites confusing them.

**MEASURED AND UNEXPLAINED — a key-number crossing graded WORSE than no crossing**

On small edges, a number that stepped across a key number covered **51.6%** (32-30). One that crossed nothing covered **57.7%** (97-71). Both groups are small edges; the only difference between them is the geometry this spec says should make a half point near 3 worth several points from 8 to 9. That is anti-correlation, not absence of signal, and **neither Scott nor the author of this spec has an explanation for it.**

The direction holds across both halves and nearly all of the size is in the first: the gap is 12.0 points in weeks 1-9 (42.9 vs 54.9) and 2.2 points in weeks 10-18 (58.8 vs 61.0). One season, one pool's lines, and the split says most of the effect is one stretch of it.

**Not acted on, deliberately.** The key-number upgrade stays exactly as it is. This is an observation that contradicts a stated premise of the method, and the premise — Stern's margin distribution and the key-number frequencies — is externally measured on far more data than one pool season. The contradiction is worth knowing about for several seasons before it is worth doing anything about. See open item 7.

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
6. **The 56.9% rests on one season** with thresholds chosen after seeing that season. It is promising, not proven. **Partly closed 2026-09-20:** it is now re-derivable from this repo (`madden/backtest.py`, 57.0% over 272 games) and agrees with the operator's own result column on every game. Still one season, still partly in-sample, still not proven.
7. **Why does a key-number crossing grade worse than no crossing on a small edge?** 51.6% against 57.7% over 2025. Measured, replicated in direction across both halves, and unexplained — see the Evidence Ledger. It contradicts the key-number premise the banding rests on. **What would settle it:** the same split over 2022-2024.
   **BLOCKED 2026-09-20, and the reason is worth recording because it was assumed the other way first.** `OW Pick Em/Prior/` holds a season-final workbook for **2025 only** — 18 week tabs, 272 games carrying frozen lines. The 2022, 2023 and 2024 files are mid-season working copies: one unplayed board, one prior-week results tab, plus `standing` and `Teams`. That is **16 games each, a single late-season week per season, 48 in total**, of which roughly eleven would carry a key-number crossing. It settles nothing and should not be run for the look of it. Nothing else matching a pool file exists in the Drive.
   **The four-season figures elsewhere in this ledger are not evidence against this.** They come from the `standing` tab, which carries per-player weekly win counts for a whole season and no frozen lines whatsoever. Pool-level statistics and per-game line data are different things, and only the first is present for 2022-2024. **To unblock: a season-final workbook for 2022, 2023 and 2024 of the kind that exists for 2025.**
8. **The band gates nothing.** The side is the sign of the edge whatever the band says, so no re-banding can change a record, and "high" currently describes two populations that grade 63.0% and 51.6%. Whether a band should gate anything — a deviation threshold, say — is an open design question and is not answered here.

---

## Handoff

`skill-creator` takes this for authoring, test cases and evaluation. Agent-creator does not author the skill.
