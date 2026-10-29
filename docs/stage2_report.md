# PRSWeave v0.1: Stage 2 Scientific Report

**Date:** 2026-10-29. **Score:** PGS005206 (DR-0001). **Conventions:** DR-0002.
**Reproduce:** `python3 scripts/stage2_run.py` (standard library only, Python ≥ 3.9; about 0.1 s).

> All genotypes are synthetic. The scores below are arithmetic outputs on made-up data. They carry no information about any person, population, BMD, hip BMD or fracture risk.

## 1. Method verification (Requirement A)

| Question | Answer | Basis |
|---|---|---|
| Scoring rule | Additive Σ dosage(effect allele) × effect_weight | PGS Catalog scoring-file spec; the file has no dominant, recessive or interaction columns |
| Weight type | beta | File header and API |
| Units | Per-allele effect in **SD of inverse-normal-transformed TB(LH)-BMD residuals** (adjusted for age, weight, height and PCs, computed per sex) | Medina-Gomez 2018 Methods (PMC5777980) |
| Phenotype | Total-body (less head) BMD. **Not hip** | GWAS Catalog GCST005348; Prijatelj 2024 abstract |
| Catalog evaluation | Generation R, European-ancestry children (mean age 9.8 y), n = 3,470, β = 0.04 | PGS Catalog PPM022584 |
| Original build | Declared "NR". Its 81/81 positions match GRCh37 | Compared against the catalog's harmonized GRCh37 file |
| Approved file integrity | SHA-256 `406045ea…0b6d3` matches DR-0001. Both scorers check it independently | Execution log, events 3 and 8 |

**Cross-check against the source GWAS.**
- 12 of the 36 Table 1 lead SNPs (Medina-Gomez 2018) are in PGS005206.
- All 12 agree on effect allele, sign and GRCh37 position.
- Only 4 have identical weights. The other 8 differ by 0.002 to 0.007 (for example rs1548607: 0.041 deposited vs 0.036 published).

So the deposited weights are **not a verbatim copy** of the published overall-meta-analysis effects. One possible reason is re-estimation without Generation R to avoid sample overlap, but I could not confirm this. **The Prijatelj 2024 full text was not accessible:** ScienceDirect blocked the request, and the open-access repository copy sits behind a Cloudflare challenge, which I did not bypass. The weights were used exactly as deposited, as DR-0001 approved.

## 2. Synthetic genotypes (Requirement B)

- **Individuals and coding:** 20 (`SYN01` to `SYN20`), 81 variants, effect-allele dosage {0, 1, 2}, no missing values.
- **Seed:** 20261029.
- **Model:** arbitrary per-variant frequency ~ U(0.05, 0.95), with two independent Bernoulli draws per person.
- **File:** `data/synthetic/PGS005206_synthetic_dosages_seed20261029.tsv`, SHA-256 `ac0ea060…b9f5ffd`. Python 3.9.6 and 3.14.6 produce byte-identical files.
- **Overall dosage counts** (1,620 genotypes): 0 = 490, 1 = 562, 2 = 568.

These dosages do **not** represent a realistic population, ancestry, allele-frequency spectrum or LD structure. Because they are effect-allele-coded by construction, this stage **does not test allele harmonization or strand resolution**. The 24 variants with an ambiguous other allele and the 5 palindromic SNVs remain unresolved for any real data.

## 3. Results (Requirement C)

All 20 individuals: 81/81 variants used, coverage 1.0000, status PASS.

| IID | Score | IID | Score | IID | Score | IID | Score |
|---|---|---|---|---|---|---|---|
| SYN01 | −0.320 | SYN06 | −0.687 | SYN11 | −0.790 | SYN16 | −1.051 |
| SYN02 | −1.195 | SYN07 | −0.680 | SYN12 | −0.025 | SYN17 | −0.563 |
| SYN03 | −0.173 | SYN08 | −0.521 | SYN13 | −0.832 | SYN18 | −0.069 |
| SYN04 | −0.974 | SYN09 | −0.135 | SYN14 | 0.049 | SYN19 | −1.539 |
| SYN05 | −1.865 | SYN10 | −0.340 | SYN15 | −0.512 | SYN20 | −0.373 |

- **Summary:** range −1.865 to 0.049; mean −0.630; median −0.542.
- **Possible range** for this score: −5.594 (all negative-weight alleles at dosage 2) to +4.828.
- **Expected mean** under the synthetic frequencies: −0.702.

The scores are mostly negative because of the arbitrary synthetic frequencies combined with Σw = −0.383. This has no biological meaning, and the values are not centred or standardized.

## 4. Independent verification (Requirement D)

| Check | Result |
|---|---|
| Primary (exact `Decimal`, chr:pos join) vs independent (separate file, no shared imports, float + `fsum`, rsID join, separate `python -I` process) | **20/20 pass.** Max \|diff\| = 2.2 × 10⁻¹⁶; tolerance 1 × 10⁻⁹, fixed before the run; n_used identical |
| Manual check, SYN01 | 21×0, 28×1, 32×2. Σw(d=1) = 0.730; Σw(d=2) = −0.525; 0.730 + 2(−0.525) = **−0.320**. `awk` gives −0.320000 ✓ |
| Manual check, SYN02 | 26×0, 22×1, 33×2. Σw(d=1) = −0.225; Σw(d=2) = −0.485; −0.225 + 2(−0.485) = **−1.195**. `awk` gives −1.195000 ✓ |
| Unit tests (19, `unittest`) | **All pass** on Python 3.14.6 and 3.9.6 |
| Repeat run | All 12 manifest files byte-identical across two consecutive runs |

The tests cover:
- **Dosage boundaries:** all-0 gives 0, all-2 gives 2Σw, a single copy, a negative weight at dosage 2.
- **Invalid dosages:** 3, −1, 1.5, x, 01, 2.0 and nan are all rejected.
- **Missing data:** the NA, empty and "." tokens are excluded and not imputed. LOW_COVERAGE and NO_DATA withhold the score, and NO_DATA is never shown as 0. The PARTIAL threshold works, and variants absent from the file are counted.
- **Input checks:** effect-allele mismatches, tampered-checksum files and unsupported dominant models are rejected.
- **Generator:** the same seed gives identical output and a different seed changes it.
- **Agreement:** primary and independent scorers agree on a random 30 × 81 matrix with about 25% missing.

## 5. Execution tracking (Requirement E)

`results/stage2/execution_log.jsonl` has 13 events per run. Each records the actor type, the action, input and output SHA-256s, timestamps, duration, status and errors. Three actor types are kept apart:

- **deterministic_software:** 12 events (checksum, parsing, cross-check, generation, both scorers, comparison, tests, QC).
- **claude_code_development:** 1 event, pointing to DR-0002 (design choices made by Claude Code while building).
- **prsweave_agent:** **0 events.** No agent exists yet.

The project owner's decision is DR-0001. Claude Code's decisions are in DR-0002.

## 6. Problems encountered

1. The Prijatelj 2024 full text was not retrievable: the publisher blocked it, a Cloudflare challenge guarded the repository copy, and the scite connector needs a paid plan. The weight derivation is unverified.
2. The deposited weights differ from GWAS Table 1 for 8 of 12 overlapping SNPs (same direction). This is recorded, not corrected.
3. **Bugs found and fixed during development:**
   - A test asserted a score at 67% coverage, but policy withholds it. The test was wrong, not the code.
   - The independent scorer left files open. The resulting ResourceWarnings, which contain random temp paths, made `test_output.txt` differ between runs.
   - The test log's wall-clock time broke byte-reproducibility. It is now kept in the log only.
   - Zero contributions printed as "-0.000".

## 7. Limitations

- **Phenotype:** this is a total-body BMD proxy. **No hip-BMD prediction is claimed.**
- **No claims** of predictive accuracy, clinical utility or ancestry transferability. The only catalog evaluation is in European-ancestry children.
- **Scale:** raw weighted sums in GWAS effect units. There is no reference distribution, so no percentiles or risk categories.
- **Data:** synthetic data exercises arithmetic and QC logic only. It does not exercise harmonization, strand flips, imputation or real missingness patterns.
- **Data inputs:** the literature cross-check uses a manually extracted Table 1, which covers novel loci only (36 of about 80).

## 8. Files

| File | Content |
|---|---|
| `data/synthetic/PGS005206_synthetic_dosages_seed20261029.{tsv,json}` | Genotypes plus seed, model, checksums and caveats |
| `results/stage2/prs_scores.csv` | 20 scores with coverage, dosage counts and QC status |
| `results/stage2/prs_scores_independent.csv` | Independent recalculation |
| `results/stage2/variant_qc.csv` | 81 variants: both builds, alleles, palindromic/ambiguous flags, GWAS agreement, synthetic frequency and dosage counts |
| `results/stage2/validation.json` | Per-individual comparison, tolerance, test summary |
| `results/stage2/manual_check_SYN0{1,2}.csv` | Per-variant contributions |
| `results/stage2/weight_crosscheck.json` | Deposited vs published weights |
| `results/stage2/execution_log.jsonl`, `manifest.json`, `test_output.txt` | Execution trail and checksums |
