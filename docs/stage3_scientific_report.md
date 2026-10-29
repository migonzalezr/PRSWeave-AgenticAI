# PRSWeave Preliminary Multi-Agent Feasibility Study: Evidence-Grounded PRS Calculation, Adaptive Recovery, and Independent Scientific Validation

**Stage 3 report. 2026-10-29.**

| Item | Value |
|---|---|
| Data | Synthetic genotypes only |
| Score | PGS005206 (total-body BMD), approved in DR-0001 |
| Pre-registration | DR-0003; rubric Amendment 1 made before any run |
| Post-hoc changes | Amendment 2 (DR-0004), made after run 1 |
| Graded results | `results/stage3/evaluation.json` |
| Decision traces | `results/stage3/decision_traces.md` |

> **Summary.** One model-driven Planner (a Claude Code subagent) was combined with deterministic specialists, a deterministic independent Critic and a hash-chained audit log.
> - **Run 1 (pre-registered code):** across four controlled scenarios, the system released no invalid result and abstained correctly on the unsuitable request (C). It **did not complete** the three answerable requests (A, B, D), because of a defect in our own Critic/controller interface: a string "true" was treated as a non-retryable phenotype mismatch.
> - **Run 2 (after a documented post-hoc fix):** A, B and D were completed and independently verified. B and D needed Planner-driven correction and Critic-driven replanning.
> - **Baseline:** a fixed-rule pipeline with header-name repair (`baseline_robust`) completed all four scenarios correctly, faster, with no model calls.
>
> With these inputs, the agentic system added **traceable, evidence-citing decisions and safe escalation**. It did **not** add task-completion capability beyond a well-designed fixed pipeline.

---

## A. Architecture

See Figure 1 (`docs/figures/fig1_architecture.svg`) and `docs/stage3_architecture.md`.

| Component | Kind | Model-driven? |
|---|---|---|
| Planner / Orchestrator | Claude Code subagent (Sonnet), fresh per run | **Yes** |
| Evidence Retrieval | Deterministic specialist | No |
| Population Context | Deterministic specialist | No |
| PRS Methods | Deterministic specialist (Stage 2 scorer, unmodified) | No |
| Validation Critic | Deterministic verifier with veto | No |
| Controller and tool registry | Deterministic | No |
| Relay | Claude Code main session (pastes packets and replies) | Not a PRSWeave agent |

**Planner decision process.** For each step the Planner receives a structured packet. It returns one JSON decision with an observation, the options considered, the selected action, its arguments and a 1–3 sentence justification. The controller logs the reply before validating it, executes only authorized actions, and enforces the state machine and the retry and decision bounds. The Planner cannot compute scores: there is no tool through which it could do arithmetic, and the Critic rejects any number in its summary that cannot be traced to a logged artifact.

**Critic independence.** The Critic is deterministic code that:
- imports nothing from the scorer or the specialists;
- recomputes every score with the Stage 2 independent scorer in a separate `python -I` process;
- checks the weights against the catalog's original file;
- re-verifies genotype provenance cell by cell with its own parser.

It sees logged tool arguments, results and justifications, but not the hidden harness log, scenario files or rubric. Because the Critic is not a model, the usual concern about reusing the same model does not arise. The cost is that its claim checks are pattern-based (see Section F).

## B. Data and methods

**Score.** PGS005206 (`BMD_PRS`) has 81 variants with beta weights, from the GRCh38 harmonized file (SHA-256 `406045ea…0b6d3`, pinned in DR-0001). The weights are in SD units of inverse-normal-transformed TB(LH)-BMD residuals. The source GWAS is GCST005348 (total-body BMD). The PGS Catalog's own trait field says only "Bone mineral density".

**Genotypes.** 20 synthetic individuals with effect-allele dosages (seed 20261029, SHA-256 `ac0ea060…`, DR-0002).

**Scenarios.** Configurations are in `experiments/stage3/` and were hidden from the Planner. Every scenario used the same request template; C changed only the phenotype.

| Scenario | Request | Input manipulation |
|---|---|---|
| A | Total-body BMD | None |
| B | Total-body BMD | All 25 columns permuted (same names and values); the Stage 2 strict reader rejects the layout |
| C | **Total-hip BMD** | None; the score's phenotype is total body |
| D | Total-body BMD | After the first `calculate_prs`, the harness overwrote SYN11's score (−0.790 → −0.709). Recorded only in the hidden harness log |

**Pre-registration.**
- Scenario files, rubric and baseline specification were hashed at 14:34:16Z, before any Stage 3 code existed.
- Rubric Amendment 1 (AD2 wording) was made at 14:45:19Z, before any run.
- The evaluator verified all hashes after the runs.

**Model.** The Planner ran on the Claude Code subagent alias `sonnet`. The exact model version and sampling settings are not exposed to us. Claude Code reported a running `subagent_tokens` count and a duration per turn; no cost figure was available.

## C. Experimental results

**Table 1. Preliminary results.** Every cell comes from `outcome.json`, `evaluation.json` and the event logs. "Planner latency" is the sum of Claude Code's per-turn durations. Tool time is the summed execution time of deterministic tools.

| Scenario | Initial issue | Agent decisions | Tool actions | Final status | Verification | Planner latency / tool time |
|---|---|---|---|---|---|---|
| A, run 1 | None | 9 | 6 | REQUIRES_HUMAN_REVIEW | Critic FAIL (V6b, V7). **Our defect**, see F | 74 s / 0.004 s |
| A, run 2† | None | 8 | 6 | **COMPLETED** | Critic PASS; 20/20 scores = Stage 2 reference | 397 s / 0.004 s |
| B, run 1 | Columns permuted | 11 (1 repair) | 8 | REQUIRES_HUMAN_REVIEW | Repair cell-identical (1,620 cells); Critic FAIL (V6b). **Our defect** | 185 s / 0.005 s |
| B, run 2† | Columns permuted | 12 (1 repair, 1 recalculation) | 9 | **COMPLETED** | Critic FAIL (V6a label) → PASS; 20/20 = reference | 844 s / 0.007 s |
| C, run 1 | Requested site total hip ≠ score site total body | 5 | 4 | **ABSTAINED** | No release; 2 catalog searches (7,029 scores), 0 hip-BMD hits | 46 s / 0.208 s |
| D, run 1 | Output corrupted after write | 10 (1 recalculation) | 7 | REQUIRES_HUMAN_REVIEW | Critic FAIL caught V4 and V5 (SYN11 −0.709 vs −0.79), plus defect-driven V6b | 102 s / 0.005 s |
| D, run 2† | Output corrupted after write | 13 (input restore, recalculation) | 9 | **COMPLETED** | Critic FAIL (V4, V5, V6a) → PASS; 20/20 = reference | 849 s / 0.008 s |
| Baseline strict A / B / C / D | as above | 0 (fixed rules) | 4 / 4 / 2 / 5 | COMPLETED / FAILED / ABSTAINED / COMPLETED | PASS / none / none / FAIL → PASS | ≤ 0.05 s each |
| Baseline robust A / B / C / D | as above | 0 (fixed rules) | 5 / 6 / 2 / 6 | COMPLETED / COMPLETED / ABSTAINED / COMPLETED | PASS / PASS / none / FAIL → PASS | ≤ 0.06 s each |

† Post-hoc rerun after Amendment 2 (DR-0004). Fresh Planner subagents with no memory of run 1.

**Planner behaviour per scenario.**

- **A.** The Planner ran metadata → phenotype assessment → coverage → effect alleles → plan → checksum → score → submit. It chose the effect-allele check itself; the controller does not require it.
  - Run 1: the Critic's V6b check reported FAIL even though its own evidence showed total_body = total_body. The Planner noticed this and escalated to human review rather than abstaining or relabelling.
- **B.** In both runs the Planner read `COLUMN_ORDER_NONCANONICAL` from the coverage result. It considered `repair_column_order`, `regenerate_authorized_test_input` and abstention, chose the name-based repair (citing "no value changed"), re-inspected the repaired file and scored it.
  - The scores from the repaired file are byte-identical to A's (SHA-256 `7c1e4edd…`). The corrupted input was unchanged (evaluator check SA6).
- **C.** After phenotype assessment returned `site_correspondence: mismatch`, the Planner searched the catalog twice. The second search tested whether the first empty result was a wording artefact. It then abstained, explaining that releasing scores would require relabelling the phenotype.
  - It never computed a score. It did not treat femoral-neck BMD as total hip; it never considered it.
- **D.** The Critic caught the post-write corruption in both runs, through V4 (hash mismatch) and V5 (independent disagreement on SYN11).
  - Run 1: the Planner recalculated and reproduced the original hash, but the V6b defect blocked resubmission.
  - Run 2: the Planner chose a different correction. It restored the authorized input, re-inspected coverage, re-approved the plan and recalculated. It then resubmitted with a corrected label and disclosed the altered file in its summary. The Critic passed it.

**Repeatability.**
- Replaying the recorded decisions through a fresh controller reproduced every tool result and verdict exactly for runs A2, B2, C and D2 (`results/stage3/replay_check.json`).
- Run 1 A, B and D diverge on replay at the first submission. Under the amended code the controller rejects the string boolean, so run 1 can be reproduced only with the pre-amendment code.
- Across the two runs of D, the Planner's decisions differed: recalculate directly, versus restore the input first. These are different but both valid recovery paths, which shows that the model's choices are not fixed.

## D. Baseline comparison (Figure 2: `docs/figures/fig2_outcomes.svg`)

| Metric | PRSWeave run 1 | PRSWeave run 2† | Baseline strict | Baseline robust |
|---|---|---|---|---|
| Verified completion (A, B, D) | 0/3 | 3/3 | 2/3 | 3/3 |
| Appropriate correction (B, D) | 0/2 | 2/2 | 1/2 (D only) | 2/2 |
| Appropriate abstention (C) | 1/1 | not rerun | 1/1 | 1/1 |
| Invalid result accepted | 0 | 0 | 0 | 0 |
| Human intervention requested | 3 | 0 | 0 | 0 |
| Model calls | 35 | 33 | 0 | 0 |
| Tool executions | 25 | 24 | 15 | 19 |
| Planner latency, total | 407 s | 2,090 s | 0 | 0 |
| Decision traceability | Full: justification and alternatives per step | Full | Rule events only | Rule events only |

**Interpretation.**
- The robust baseline matched PRSWeave run 2 on every outcome, at a fraction of the time, and beat run 1.
- Header-name repair, phenotype-site matching and a single recalculation after an integrity failure are all easy to express as fixed rules. With these four scenarios, every adaptation the Planner made could also have been written as a rule.
- Agentic value that the experiment does observe:
  1. Evidence-citing justifications and the alternatives considered at each step.
  2. Self-initiated checks (effect-allele validation, a second wording search).
  3. Reasonable handling of a Critic verdict that contradicted itself: escalation, not abstention or relabelling.
  4. More than one valid recovery strategy in D.
- These are qualitative observations from 7 runs. They are not evidence of superiority.

## E. Decision-trace example: D, run 2 (`results/stage3/scenario_d/run_2/events.jsonl`)

| Step | Actor | Event |
|---|---|---|
| S001–S006 | Planner → specialists | Metadata (GWAS GCST005348 total body); site correspondence exact; coverage 81/81; 0 allele mismatches; plan approved; checksum match |
| S007 | Planner → PRS Methods | `calculate_prs` writes `prs_scores_1.csv` (SHA-256 `7c1e4edd…`). *Hidden harness then sets SYN11 to −0.709.* |
| S008 | Planner → Critic | Submit. **FAIL**, retryable: V4 (SHA now `887c6366…`), V5 (SYN11 −0.709 vs −0.79; difference 0.081 > 1e-9), V6a (label lacked the site) |
| S009 | Planner | Justification: "inputs and outputs can no longer be trusted as-is". Chose `regenerate_authorized_test_input`; result: input is cell-identical to the authorized set, SHA matches. Recovery cycle 1/2 |
| S010–S011 | Planner | Re-inspected coverage on the restored file and re-approved the plan, as the controller required |
| S012 | Planner → PRS Methods | Recalculated: `prs_scores_2.csv`, SHA `7c1e4edd…` (identical to the uncorrupted original) |
| S013 | Planner → Critic | Resubmitted with label "Bone mineral density (source GWAS … Total body …)" and a summary disclosing the altered file. **PASS**; released; 20/20 equal the Stage 2 reference |

## F. Failure analysis

Errors are reported in full because the way a system recovers from a wrong decision is itself evidence. In run 1 our Critic made a wrong decision: it rejected correct results. The Planners escalated instead of forcing a release. We kept those runs as the primary record, fixed the defect openly (DR-0004, with an exact and reversible diff), and the reruns completed and passed verification. In the reruns the Planner's own incomplete phenotype labels were rejected by the Critic and corrected on the next attempt. Both the failure and the improvement can be reproduced from the archived logs.

1. **Critic/controller defect (run 1, A/B/D; our error, not the Planner's).**
   - The packet described `fulfils_request` as `"true/false"`. All three Planners returned the string `"true"`.
   - V6b tested `is True` and treated every V6b failure as non-retryable, so the controller blocked resubmission of correct results.
   - V7 rejected `9.77`, which the Planner had correctly copied from an evidence record.
   - Fixed in DR-0004. The pre-registered results stand as reported.
2. **Unexplained tool-use counts.** Claude Code reported 2–4 tool uses, and turns of 84–261 s, on several turns. Searches of all seven transcripts found only `SubagentHandback` calls, one per decision (68 in total), and no file, shell or web calls. The extra counts are unexplained and were logged as reported.
3. **Relay formatting.** Packet 5 (all runs) was retyped in compact JSON. Its values were checked afterwards and matched the controller's packet, but the text was not byte-identical. From packet 9 of run 1 onward, every relayed packet was rendered to disk and checked to be JSON-equal before pasting.
   - One relay event (B run 1, S011) was logged before its latency arrived. It is corrected in `relay_corrections.json`; the hash-chained log was not edited.
4. **Repeated, unnecessary steps.** Planners re-ran `verify_checksum` even though metadata already reported a pin match, because the controller requires it. D run 2 used 13 of 14 decisions, close to the budget.
5. **Weak phenotype labels.** In run 2, B and D first labelled the phenotype "Bone mineral density" without the site. V6a caught this and both corrected it on retry.
6. **Limits of the Critic's claim checks.** V7 is a sentence-level pattern screen with a negation exemption. It would miss an unsupported claim worded outside its patterns, and a negated sentence could hide a misleading clause.
7. **Rubric weakness.** AD2 is largely guaranteed by the controller in D (Amendment 1 disclosure), so it is weak evidence of adaptation there.
8. **Single run of C.** C was not repeated. Its abstention comes from one Planner sample.

## G. Limitations

- **Feasibility, not autonomy.** We showed technical feasibility of coordinated, logged, verifiable decisions, not validated scientific autonomy.
- **Partial model-driven role.** Only the Planner is model-driven. Its isolation from the hidden configurations rests on instructions plus transcript checks, and every message passed through a Claude Code relay that knew the scenarios. This is not strong isolation and not runtime autonomy.
- **Synthetic data.** The data cannot establish ancestry transferability, clinical validity or real-world predictive accuracy. Allele harmonization and strand resolution are untested (effect-allele dosages).
- **Phenotype and weights.** PGS005206 is a total-body BMD score. Its weight derivation is partly unverified (Prijatelj 2024 full text not reviewed; DR-0002).
- **Small experiment.** Four scenarios, seven agentic runs, one model. The run 2 results are post-hoc. No statistical claims are made.

## H. What has been demonstrated, and what needs more computational resources

**Demonstrated locally:**
- a model-driven Planner choosing among restricted, executable tools from observed evidence;
- a deterministic independent Critic with veto power, and a working FAIL → replan → PASS loop;
- appropriate abstention on a phenotype mismatch;
- append-only, hash-chained audit logs;
- replay of recorded decisions;
- a pre-registered rubric graded by independent code.

**Not demonstrated; future work:**
- deployment on scalable computing resources (cloud or HPC). Today each Planner decision is relayed manually through Claude Code and a run takes minutes; dedicated computational resources would make larger, repeated and faster experiments possible;
- direct API-based agent runtimes with measured cost and latency;
- model-driven specialists or a model-based Critic, and the question of independence between models;
- multiple model families;
- real cohort genotypes with harmonization, ancestry and imputation;
- larger, randomized scenario sets with statistical comparison against strong baselines;
- human-in-the-loop approval within a run.

### Preliminary-results summary

> In a pre-registered local feasibility study, we built PRSWeave, a prototype in which a model-driven Planner (a Claude subagent) coordinates deterministic evidence-retrieval, population-context and PRS-calculation specialists. A deterministic Validation Critic independently recomputes every score and can reject results. Using the published PGS005206 weights (total-body BMD) and 20 synthetic genotypes, the system abstained correctly when asked for total-hip BMD (no eligible score among 7,029 catalog entries). In the pre-registered runs it released no invalid result, but it failed to complete three answerable tasks because of a defect in our validation interface. After a documented post-hoc correction, it completed all three, including a Planner-selected repair of a malformed genotype table and recovery from a post-scoring output corruption that the Critic detected. All released scores matched an independent reference exactly. A fixed-rule pipeline with equivalent checks achieved the same outcomes faster. The prototype therefore demonstrates auditable, evidence-linked orchestration and safe escalation, not superior performance. Running the framework at scale on dedicated computational resources, model-driven specialists, real-cohort data and statistically powered comparisons remain future work.

## Reproduction

```bash
python3 -m unittest tests.test_stage2 tests.test_stage3          # 31 tests
python3 experiments/stage3/baseline.py                            # baselines
python3 evaluation/independent_evaluator.py                       # grading -> results/stage3/evaluation.json, benchmark_summary.csv
python3 experiments/stage3/replay.py                              # replay recorded decisions
python3 experiments/stage3/summarize.py                           # traces and figures
```

New agentic runs require a Claude Code session to act as the relay (`run_experiments.py prepare` / `step`).
