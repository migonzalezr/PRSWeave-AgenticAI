# DR-0003: Stage 3 pre-registration and runtime architecture

- **Runtime choice:** approved by the project owner, 2026-10-29: a Claude Code subagent acts as the Planner, with Claude Code relaying its decisions.
- **Everything else:** decided by Claude Code during development.
- **Pre-registered at:** 2026-10-29T14:34:16Z, before any Stage 3 agent, controller or evaluator code existed and before any experiment ran.

## Pre-registered files (SHA-256)

| File | SHA-256 |
|---|---|
| `experiments/stage3/scenario_a.json` | `9e325c9d0f3eead14096ac5e7c10857d123edfa94e9bd012eac85522dc9acb00` |
| `experiments/stage3/scenario_b.json` | `8580e0bcb378d3fa7fec15c1e2aeb5cd083b400c6f309ea5d6b47f2a5d864262` |
| `experiments/stage3/scenario_c.json` | `6ecff8a0cd108c8a775770884bba496f3d11caaf208584c3ecf10a9aa442963b` |
| `experiments/stage3/scenario_d.json` | `50bf21477ab1bd7b3819e252ce17decf28ee66da787407452f801c2a4e0e25f3` |
| `experiments/stage3/baseline_spec.json` | `7a632a90619cad9cda541a060ac17155bf8b41ea94d0dcafd0162fc8affbaa21` |
| `evaluation/acceptance_criteria.json` | `c6ac945af18fac150d122577666aeb75e2cfa17e2039c67df90631dc72902641` |

The evaluator checks these hashes before grading. If any file has changed, it reports that.

### Amendment 1 (2026-10-29T14:45:19Z, before any experiment or baseline run)

AD2 in `evaluation/acceptance_criteria.json` was reworded. As first written, it required an action "not previously executed". In Experiment D the correct remedy is recalculation, which repeats an earlier action, so the original wording would have failed every correct D run. When the amendment was made, `results/stage3/` held only the API cache.

| File | SHA-256 after amendment |
|---|---|
| `evaluation/acceptance_criteria.json` | `d6ad1cb3e2d49eabc76be5b64f6bad213afc2b5fe6d4f005953c0b9a03bd1853` |

Disclosure: in D, AD2 is largely guaranteed by the controller, which accepts a resubmission only after a fresh `calculate_prs`. So AD2 is weak evidence of adaptation in D.

## Runtime facts established in Phase 1

- The Claude Code CLI 2.1.309 has a headless `-p` mode, but a nested call from project code fails: "OAuth session expired and could not be refreshed". Direct model calls from Python are therefore unavailable without separate credentials, which were not requested.
- The model-driven Planner is a **Claude Code subagent**: a fresh one per run, continued across steps of that run with SendMessage.
- **The relay:** Claude Code (the main session) does the following:
  1. pastes the controller's packet verbatim into the subagent's message;
  2. saves the subagent's reply verbatim to a file;
  3. runs the controller's `step` command.

  The controller logs the reply before validating or executing anything.
- **What the relay means:** the main session knows the scenarios. The isolation between the Planner and the hidden scenario files rests on instructions only, plus the subagent's logged tool-use count. This is not strong isolation.

## Fixed definitions

- A **recovery cycle** starts with the first corrective action after a tool error or Critic FAIL, and ends at the next validation. At most 2 per run. At most 14 Planner decisions per run.
- Harness fault injection is recorded only in `harness_log.jsonl`. Neither the Planner nor the Critic reads it. The evaluator does.
