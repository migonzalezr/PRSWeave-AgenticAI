# PRSWeave: Adaptive Multi-Agent Orchestration for Polygenic Risk Research

PRSWeave is a research prototype that asks a specific question: can AI-driven planning, constrained to evidence and to specialized deterministic scientific tools and checked by an independent validator, support genomic analyses that adapt to what they find while remaining auditable and reproducible?

> **Status: v0.1, research prototype (Stages 1–3 complete).** Synthetic genotypes only. Not for clinical use.
> In this version an LLM Planner (a Claude subagent mediated by Claude Code) coordinates specialized deterministic scientific tools and an independent validator.

### Research vision and current scope

| | Long-term research architecture | What v0.1 implements |
|---|---|---|
| Orchestration | Adaptive multi-agent orchestration: several model-driven agents that plan, retrieve evidence, choose methods and validate, coordinating with one another | **One** LLM-driven Planner that coordinates the workflow |
| Specialists | Model-driven specialists working through validated scientific tools | **Deterministic** specialists (evidence retrieval, population context, PRS methods) |
| Validation | Validators that stay independent of the agents they check | An **independent, deterministic** Validation Critic with veto power |
| Scope | Genomic research workflows beyond PRS | One published polygenic score on 20 synthetic individuals, in four designed scenarios |

The title names the research direction. The evidence reported here concerns only the v0.1 configuration in the right-hand column.

---

## Contents

- [Overview](#overview)
- [Scientific contribution](#scientific-contribution)
- [Architecture](#architecture)
- [What we have demonstrated](#what-we-have-demonstrated)
- [Quick start](#quick-start)
- [Limitations and roadmap](#limitations-and-roadmap)
- [Repository layout and documentation](#repository-layout-and-documentation)
- [Data and third-party sources](#data-and-third-party-sources)
- [Citing PRSWeave](#citing-prsweave)
- [License](#license)
- [Research Team and Contact](#research-team-and-contact)

---

## Overview

A polygenic score combines many genetic variants, each with a published weight, into one number per person. Computing that number is easy. Deciding whether it *should* be computed, and whether the result means what the researcher thinks it means, is harder:

- Does the score measure the phenotype the study asks about?
- Do the genotype data match the score's variants, alleles and genome build?
- Was anything corrupted between input and output?
- When should the analysis stop?

PRSWeave combines four elements to address these questions:

- an **LLM Planner** that chooses the next step from observed evidence;
- **deterministic scientific tools** that perform every calculation and check;
- a **controller** that only permits authorized actions;
- an **independent Validation Critic** that recomputes results and can reject them.

Every decision, tool call and verdict is written to a tamper-evident log.

The first application uses a published score from the [PGS Catalog](https://www.pgscatalog.org/), PGS005206 (a bone mineral density score, 81 variants), on 20 synthetic individuals.

## Scientific contribution

### What this first version provides

v0.1 turns a research question into something that can be executed and checked. It provides a working, pre-registered and fully logged test bed in which an LLM makes the workflow decisions, deterministic tools do all the science, and an independent validator decides what may be released. With it, claims about adaptive AI in genomics can be tested against recorded evidence and strong conventional baselines, instead of being argued in the abstract.

### How it differs conceptually

- **Evidence-grounded decision-making.** Conventional pipelines follow a sequence fixed in advance. General-purpose AI agents decide freely and may compute or reinterpret things themselves. In PRSWeave the Planner chooses each step from logged tool evidence, among authorized actions only, and records why. It never computes results.
- **Adaptive error recovery.** When a tool reports a problem or the validator rejects a result, the Planner must diagnose the cause and choose a corrective action, such as a value-preserving repair, a restore or a recalculation. Every correction is itself verified before the workflow continues.
- **Independent verification.** Release does not depend on the Planner's own judgment. A separately written Critic recomputes every score, checks provenance and phenotype suitability, and can veto. Abstaining is treated as a valid scientific outcome.

These are differences in design, not demonstrated advantages. In the preliminary experiments a robust deterministic baseline reached the same outcomes faster ([see below](#an-essential-finding-a-strong-deterministic-baseline-did-as-well)).

### The problem

Genomic analysis is more than running software. At each step researchers decide:
- which method is scientifically appropriate;
- what an intermediate finding implies;
- how to resolve a technical incompatibility without distorting the data;
- whether the analysis should go ahead at all.

Fixed pipelines encode these decisions in advance. They are excellent when the inputs are as expected, and they are blind to situations their authors did not anticipate. General-purpose AI agents can respond to the unexpected, but they may also improvise in ways that are hard to verify: computing numbers themselves, relabelling a phenotype to make a request "work", or presenting an unchecked result with confidence.

### The central idea

PRSWeave studies whether evidence-grounded AI reasoning, combined with specialized deterministic tools and independent verification, can make genomic workflows **adaptive** and **auditable** at the same time.

### What makes the approach distinctive

These are design commitments of the prototype. We do not claim that no other project has them.

- **Explicit, evidence-informed decisions.** At each step the Planner records what it observed, which options it considered, what it chose and why, citing tool results. It does not follow a hard-coded sequence.
- **Computation stays in tools.** The Planner cannot compute scores. Scoring uses a validated scorer with exact arithmetic, and the Critic rejects any number in the Planner's summary that cannot be traced to a logged result.
- **An independent Critic with veto power.** The Critic recomputes every score with a separately written implementation, checks file integrity and data provenance, and returns PASS, FAIL or INCONCLUSIVE. A FAIL sends the workflow back to the Planner to reconsider.
- **Running the software is not the same as answering the question.** A score can compute flawlessly yet measure the wrong phenotype. PRSWeave keeps three things apart: technical compatibility, scientific suitability (for example, the skeletal site of a BMD score) and predictive validity (which synthetic data cannot establish).
- **Everything is on the record.** Decisions, evidence, corrections, failures and limitations go into an append-only, hash-chained log that can be replayed.
- **The AI is compared, not assumed better.** Each experiment is also run with conventional deterministic pipelines and graded by the same pre-registered rubric.

### What this first version demonstrates, and what it does not

In controlled experiments with synthetic data:

| Situation | What happened | Why it matters |
|---|---|---|
| Clean input | The published score was calculated and independently verified; all 20 scores match a reference exactly | Correctness is established by recomputation, not asserted |
| Malformed input (columns in the wrong order) | The Planner diagnosed the problem from a tool report, chose a value-preserving repair, re-checked the repaired file and completed the analysis | Recovery chosen from evidence, with the repair verified cell by cell |
| Output corrupted after scoring | The Critic detected it (changed file hash; independent recomputation disagreed) and rejected it. The Planner restored a verified input, recalculated and passed review | The validator's feedback changed what the system did next |
| Request for **total-hip** BMD, with only a **total-body** BMD score available | The Planner found the mismatch, searched the catalog for an eligible alternative, found none and **abstained** | A well-justified refusal counts as a correct scientific outcome |
| A defect in our own validator | It rejected correct results; the Planners escalated to human review instead of forcing a release. We documented the defect, fixed it in the open, and reran | Failures are kept and reported, not hidden |

These are **preliminary demonstrations of controlled, evidence-grounded workflow adaptation** in four designed scenarios. They are not evidence of general autonomous scientific reasoning.

### Learning from wrong decisions, in the open

We publish our mistakes alongside our successes, because showing how a system improves after a bad decision is part of the evidence.

- **Our validator made a wrong decision.** In the pre-registered runs, the Critic rejected scientifically correct results. The Planner had sent `"true"` as text, and the Critic treated that as an uncorrectable phenotype mismatch. It also rejected a number that had been correctly copied from an evidence record.
- **The safeguards held.** The Planners did not force a release or relabel the phenotype. They noticed that the Critic's verdict contradicted its own evidence and escalated to human review. No incorrect result was released.
- **We kept the failure on the record.** The failed runs stay as the primary result, with their complete logs.
- **We fixed it openly and re-tested.** We diagnosed the defect, recorded the fix as a dated decision record ([DR-0004](docs/decisions/0004-stage3-amendment2-post-hoc.md)) with the exact code change ([diff](docs/decisions/0004-amendment2.diff)), and reran the scenarios separately as post-hoc runs. In those runs all three answerable tasks were completed and verified.
- **The Planner also corrected its own mistakes when challenged.** In the reruns it first submitted an incomplete phenotype label ("Bone mineral density" without the skeletal site). The Critic rejected it with a specific reason, and the Planner fixed the label and passed on its next submission. This is the reject → reconsider → correct loop the architecture is designed to test.
- **Anyone can check this.** Reversing the recorded fix reproduces the original failed runs exactly, and applying it reproduces the corrected ones. The improvement can be verified, not just described.

### An essential finding: a strong deterministic baseline did as well

A conventional pipeline with well-chosen fixed rules (header-name repair, a phenotype-site check, one recalculation after a failed verification) **achieved the same outcomes in all four scenarios, in milliseconds and with no model calls.** The LLM-driven runs took minutes.

We consider this a useful result, not an embarrassment. For the problems tested here, simple deterministic automation was sufficient. What the agentic version added was:
- an explicit, evidence-cited rationale at every step;
- self-initiated checks;
- more than one valid recovery strategy;
- appropriate escalation when the validator itself contradicted its own evidence.

Whether that matters in practice is exactly the question that needs testing.

**The value of this proof of concept is therefore not a claim that agents outperform conventional methods.** It is an executable, auditable and pre-registered framework for finding out *when* adaptive agentic decision-making helps genomic research and when simpler automation is enough.

### How the approaches differ (conceptually)

| | Fixed bioinformatics pipeline | General-purpose AI agent with tools | PRSWeave research approach |
|---|---|---|---|
| Who decides the next step | Pre-written logic | The model, often unconstrained | The model, restricted to authorized actions with preconditions |
| Who computes results | Deterministic code | Code or the model itself | Deterministic, validated tools only |
| Handling the unexpected | Fails or follows a rule written in advance | Improvises; may be hard to verify | Reasons from tool evidence; the correction is verified |
| Phenotype suitability | Usually implicit in pipeline design | Rarely checked explicitly | An explicit step, kept separate from technical success |
| Validation | Tests and QC defined by the author | Often self-assessed | Independent Critic with veto, plus an external evaluator |
| Record | Logs of steps run | Conversation transcripts | Hash-chained log of decisions, evidence, tools and verdicts |
| Main strength | Speed, reliability, reproducibility | Flexibility | Studying adaptation together with verification |

Each approach has merits, and this table describes design intent rather than measured superiority.

## Architecture

![PRSWeave Stage 3 architecture](docs/figures/fig1_architecture.svg)

| Component | Role | Implementation |
|---|---|---|
| **Planner** | Reads a state packet; picks one permitted action with a short justification | **LLM**: a Claude subagent, run through Claude Code |
| **Controller** | State machine. Logs each decision *before* acting, authorizes it, enforces retry and decision limits | Deterministic |
| **Evidence Retrieval** | PGS Catalog / GWAS Catalog records with provenance; catalog search | Deterministic |
| **Population Context** | Phenotype-site comparison, variant coverage, effect-allele checks, eligibility of alternative scores | Deterministic |
| **PRS Methods** | Checksum-pinned scoring with the Stage 2 scorer; value-preserving repair and restore tools that verify themselves | Deterministic |
| **Validation Critic** | Recomputes scores independently; checks weights, provenance, output integrity, phenotype labels and claims; can reject | Deterministic |
| **Event log** | Append-only, SHA-256 hash-chained JSONL | Deterministic |

The Planner runs as a Claude Code subagent. The Claude Code session relays each state packet to it and records its reply verbatim. Isolation from the hidden experiment configuration rests on instructions plus transcript audits, so it is not strong isolation. The tools, controller and Critic have no model dependency, so other model backends could be connected through the same interface; none has been tested.

Details: [`docs/stage3_architecture.md`](docs/stage3_architecture.md).

## What we have demonstrated

### Stage 1: feasibility and score selection
We queried the PGS Catalog (release 2026-10-23, 7,029 scores) for hip and bone-mineral-density scores. **No total-hip BMD score exists in the catalog.** PGS005206 (total-body BMD, 81 variants, beta weights, harmonized GRCh38 file) was chosen as the most technically feasible candidate and pinned by checksum.
→ [`docs/stage1_feasibility_report.md`](docs/stage1_feasibility_report.md)

### Stage 2: verified calculation
We built 20 synthetic individuals from a fixed seed and scored them with an exact-arithmetic scorer. A separately written scorer agreed to within 2.2 × 10⁻¹⁶, and two individuals were checked by hand. 19 tests pass, and repeated runs are byte-identical. We confirmed the weight units against the source GWAS. The PGS publication's weight derivation remains partly unverified.
→ [`docs/stage2_report.md`](docs/stage2_report.md)

### Stage 3: agentic orchestration, adaptation and independent validation
We pre-registered four scenarios, an evaluation rubric and two deterministic baselines before running anything. Results were graded by an independent evaluator that shares no code with the agents.

| Scenario | Pre-registered run (run 1) | Post-hoc rerun after documented fix (run 2) | Robust deterministic baseline |
|---|---|---|---|
| A: clean data | Escalated to human review (validator defect) | **Completed**, verified | Completed |
| B: columns permuted | Repaired, then escalated (validator defect) | **Completed**: repair; one label correction after Critic FAIL | Completed |
| C: total-hip requested | **Abstained** (no eligible score) | not rerun | Abstained |
| D: output corrupted | Critic caught corruption; escalated (validator defect) | **Completed**: Critic FAIL, input restored, recalculated, PASS | Completed |

Across all 15 graded runs, **no invalid result was released.** Every released score equals the Stage 2 reference.

- **Run 1** is the primary, pre-registered result. It exposed a defect in our validation interface: a `"true"` string was treated as a non-retryable phenotype mismatch.
- **Run 2** used the corrected code, recorded in [DR-0004](docs/decisions/0004-stage3-amendment2-post-hoc.md), and is reported separately as post hoc.

→ [`docs/stage3_scientific_report.md`](docs/stage3_scientific_report.md) · [decision traces](results/stage3/decision_traces.md) · [outcome figure](docs/figures/fig2_outcomes.svg)

## Quick start

Requirements: Python ≥ 3.10 (also tested on 3.9) and internet access to download public scoring files. **No third-party packages are needed.**

```bash
git clone https://github.com/migonzalezr/PRSWeave-AgenticAI.git
cd PRSWeave-AgenticAI

# 1. Download the public PGS Catalog scoring files (not redistributed here), verified against recorded checksums
python3 scripts/fetch_public_data.py

# 2. Score 20 synthetic individuals with PGS005206 and verify with an independent implementation
python3 examples/quickstart.py

# 3. Run the test suite (31 tests; the first run fetches a few public API records)
python3 -m unittest -v tests.test_stage2 tests.test_stage3
```

Expected output of step 2 (abridged):

```
Scored 20 synthetic individuals with 81 PGS005206 variants.
  SYN01   -0.320  (81/81 variants, PASS)
  ...
Independent implementation, max |difference|: 2.2e-16
Identical to archived Stage 2 reference: True
```

These are raw weighted sums on synthetic data, with no biological or clinical meaning.

Replaying recorded agent decisions, re-grading experiments and running new agentic experiments are covered in [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

## Limitations and roadmap

**Implemented today:**
- an LLM Planner (Claude via Claude Code) choosing among 10 executable tools, under a deterministic controller;
- deterministic specialists and an independent Critic with a working reject → replan → pass loop;
- phenotype-suitability abstention;
- a hash-chained audit log and deterministic replay;
- a pre-registered rubric with an independent evaluator and deterministic baselines.

**Not established:**
- **Synthetic data only:** no ancestry transferability, clinical validity or predictive accuracy can be inferred.
- **Not tested on real genotypes:** allele harmonization, strand resolution and imputation.
- **Small experiment:** four scenarios, seven agentic runs, one model family. The corrected runs are post hoc. There is no statistical comparison and no claim of superiority.
- **Limited model-driven role:** only the Planner is model-driven. The relay path means agent isolation is weak, and the Critic's claim checks are pattern-based.
- **Score caveats:** PGS005206 is a total-body BMD score, used here as a proxy. Its weight derivation is partly unverified.

**Future research:**
- running on dedicated computational resources (cloud or HPC). Today each Planner decision is relayed manually and a run takes minutes; more compute would allow larger, repeated and faster experiments with directly measured cost and latency;
- model-driven specialists and validators, and how to keep them independent;
- real-cohort data with harmonization and ancestry assessment;
- larger, randomized scenario sets with statistical comparison against strong deterministic baselines;
- human approval steps within a run;
- extension beyond PRS to other genomic workflows.

## Repository layout and documentation

```
src/prsweave/            Core package
  prs.py, scoring_file.py, synthetic.py     Stage 2 validated scorer, checksum-pinned loader, synthetic data
  agents/                Planner contract, deterministic specialists, Validation Critic
  orchestration/         Controller, state machine, tool registry, hash-chained event log
validation/              Independent second scoring implementation
scripts/                 Stage 1 and 2 scripts; public-data fetcher
examples/                Quick-start example
experiments/stage3/      Hidden scenario configs, harness, baselines, replay, summaries
evaluation/              Pre-registered rubric and independent evaluator
tests/                   Unit tests (Stages 2-3)
data/synthetic/          Synthetic genotypes (seeded) and metadata
results/                 Archived outputs of Stages 1-3 (event logs, verdicts, scores, checksums)
docs/                    Stage reports, architecture, decision records (DR-0001 to DR-0004), figures
```

| Document | Content |
|---|---|
| [Stage 3 scientific report](docs/stage3_scientific_report.md) | Full results, baseline comparison, failure analysis, limitations |
| [Stage 3 architecture](docs/stage3_architecture.md) | Components, message contract, states, Critic checks |
| [Reproducibility guide](docs/REPRODUCIBILITY.md) | What can be rerun, and with which data |
| [Decision records](docs/decisions/) | Score approval, scoring conventions, pre-registration, post-hoc amendment |

## Data and third-party sources

- **Not redistributed:** PGS Catalog scoring files and API records. They are fetched from the official source by `scripts/fetch_public_data.py`.
- **Included:** all genotypes in this repository are synthetic. Some archived result files include published PGS005206 weights, PGS Catalog and GWAS Catalog metadata, and effect sizes from the source GWAS, as part of the experimental record. These remain subject to their original sources' terms. Use of PGS Catalog data follows the [EMBL-EBI Terms of Use](https://www.ebi.ac.uk/about/terms-of-use/).
- **Please cite the original sources** when using these data:
  - PGS Catalog: Lambert et al., *Nat Genet* 2024, doi:10.1038/s41588-024-01937-x.
  - PGS005206: Prijatelj et al., *Bone* 2024, doi:10.1016/j.bone.2024.117070.
  - Source GWAS: Medina-Gomez et al., *Am J Hum Genet* 2018, doi:10.1016/j.ajhg.2017.12.005.

## Citing PRSWeave

Citation metadata is in [`CITATION.cff`](CITATION.cff); GitHub's "Cite this repository" button reads it. Suggested form:

> *PRSWeave: Adaptive Multi-Agent Orchestration for Polygenic Risk Research* (v0.1, research prototype). 2026. https://github.com/migonzalezr/PRSWeave-AgenticAI

## License

The PRSWeave source code and documentation are released under the [MIT License](LICENSE).

The license does not cover third-party data or metadata included in the archived results (see [Data and third-party sources](#data-and-third-party-sources)); those remain under their original terms.

## Research Team and Contact

PRSWeave is developed by researchers at the **Center for Biomedical Informatics and Genomics (CBG), Tulane University**, New Orleans, Louisiana, USA.

**Primary contact:** Martha Isabel González-Ramírez, [martha.gonzalezr@tulane.edu](mailto:martha.gonzalezr@tulane.edu)

Questions, issues and collaboration proposals are welcome through the contact above or the repository's [issue tracker](https://github.com/migonzalezr/PRSWeave-AgenticAI/issues).
