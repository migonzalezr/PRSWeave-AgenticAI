# Reproducibility guide

Everything below uses the Python standard library only (Python ≥ 3.10; also tested on 3.9).

## 1. From a fresh clone (verified)

```bash
python3 scripts/fetch_public_data.py                          # 9 PGS Catalog scoring files, checksum-verified against Stage 1
python3 examples/quickstart.py                                # score 20 synthetic individuals; compare with Stage 2 reference
python3 -m unittest -v tests.test_stage2 tests.test_stage3    # 31 tests; fetches a few public API records on first run
python3 experiments/stage3/replay.py                          # replay recorded Planner decisions (no model calls)
```

**What the replay shows.** `replay.py` feeds each run's recorded Planner replies (`results/stage3/scenario_*/run_*/decisions/`) through a fresh controller with the same injected faults. It then compares every tool result and Critic verdict with the archived run, and writes `results/stage3/replay_check.json`.

| Runs | Code | Replay result |
|---|---|---|
| Post-hoc runs (A2, B2, D2) | Current | Identical |
| Pre-registered runs (A1, B1, D1) | Pre-amendment code, recorded exactly in [`decisions/0004-amendment2.diff`](decisions/0004-amendment2.diff) | Identical |
| Scenario C | Current | Needs the Stage 1 PGS Catalog score index (24 MB; release 2026-10-23), which is not redistributed. With a newer catalog release its search step will differ |

To replay the pre-registered runs:

```bash
patch -p1 -R < docs/decisions/0004-amendment2.diff     # restore the pre-registered code
python3 experiments/stage3/replay.py                   # runs A1, B1, D1 now replay identically
patch -p1 < docs/decisions/0004-amendment2.diff        # return to the current code
```

A matching replay shows that the recorded decisions determine every tool output. It does **not** show that a new model call would make the same decisions.

## 2. Commands that need files not redistributed here

| Command | Needs | Note |
|---|---|---|
| `python3 evaluation/independent_evaluator.py` | Stage 1 score index; the GWAS Table 1 extract used in Stage 2 (`data/raw/literature/`, derived from a copyrighted article) | Its integrity check covers all Stage 2 manifest files. The archived `results/stage3/evaluation.json` is the graded record |
| `python3 scripts/stage2_run.py` | As above, for the weight cross-check | **Overwrites** `results/stage2/`. Scores are byte-identical, but logs get new timestamps |
| `python3 experiments/stage3/baseline.py` | Fetched scoring files; public API access | **Overwrites** `results/stage3/baseline/`. Pre-amendment baseline outputs are kept in `baseline_preamendment/` |
| `python3 scripts/stage1_feasibility.py` | Public API access | Queries the *current* catalog release, so results can differ from the 2026-10-23 record |

## 3. New agentic runs

The model-driven Planner runs as a Claude Code subagent, and a Claude Code session acts as the relay:

```bash
python3 experiments/stage3/run_experiments.py prepare --scenario a --rep 3
#   -> paste packets/message_001.txt to a fresh subagent; save its reply verbatim to decisions/reply_001.txt
python3 experiments/stage3/run_experiments.py step --run-dir results/stage3/scenario_a/run_3 \
    --reply results/stage3/scenario_a/run_3/decisions/reply_001.txt --latency-ms <ms> --total-tokens <n> --tool-uses <n>
#   -> repeat with the next message (experiments/stage3/render_relay.py renders a checked relay text)
```

Model outputs are not deterministic, so new runs may make different decisions.

## 4. What is archived

`results/stage3/scenario_*/run_*/` holds the following for each agentic run:
- the hash-chained `events.jsonl`;
- every packet and reply;
- tool argument and result artifacts;
- Critic verdicts;
- released scores (if any);
- the hidden `harness_log.jsonl` (fault injection);
- the final report.

`results/stage3/relay_corrections.json` records known relay-logging issues. Logs are never edited.
