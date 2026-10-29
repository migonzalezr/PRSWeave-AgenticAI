# DR-0002: Stage 2 scoring, synthetic data and validation conventions

- **Decided by:** Claude Code, during development (not a PRSWeave agent). Pending review by the project owner.
- **Date:** 2026-10-29
- **Applies to:** `scripts/stage2_run.py`, `src/prsweave/{scoring_file,synthetic,prs,audit}.py`, `validation/independent_scorer.py`

These choices were fixed **before** the first scoring run, so validation can't be tuned to the results.

## 1. Scoring method (verified, not assumed)

| Item | Evidence | Status |
|---|---|---|
| Formula: Σ dosage(effect_allele) × effect_weight, additive | PGS Catalog scoring-file docs (`/downloads/`): effect_weight is "multiplied by the dosage of the effect allele" | Verified |
| No dominant, recessive, interaction or dosage-specific weights | No such columns in the file; the loader rejects them if present | Verified |
| `weight_type=beta` | File header and API | Verified |
| Weight units: SD of TB(LH)-BMD residual | Source GWAS (Medina-Gomez 2018, PMC5777980, Methods): TB-BMD corrected for age, weight, height and PCs, residuals computed by sex, then **inverse-normal transformed** | Verified for the GWAS; see the limitation below |
| Phenotype: total-body (less head) BMD, not hip | GWAS Catalog GCST005348 `disease_trait` = "Total body bone mineral density"; Prijatelj 2024 abstract | Verified |
| Weights = GWAS Table 1 effects? | Of the 36 Table 1 SNPs, 12 are in PGS005206. All 12 have the same effect allele, sign and GRCh37 position; 4/12 identical, 8/12 differ by 0.002 to 0.007 | **No: not an exact copy** |
| How Prijatelj et al. derived the 81 weights | Full text not accessible (ScienceDirect blocked; repository copy behind a Cloudflare challenge, which was not bypassed) | **Unverified** |
| Original build | Declared "NR", but 81/81 original positions equal the catalog's GRCh37 harmonized positions | Inferred GRCh37 |

## 2. Inputs

- Scoring file: the DR-0001 GRCh38 harmonized file. SHA-256 is verified by both implementations before use.
- Variant key: GRCh38 `chr:pos:effect_allele` for the primary scorer, `rsID + effect_allele` for the independent one.

## 3. Synthetic genotypes

- Seed **20261029**, 20 individuals (`SYN01` to `SYN20`), `random.Random`, `random()` only.
- Per variant, an arbitrary frequency f ~ U(0.05, 0.95). Dosage = Bernoulli(f) + Bernoulli(f), independent across variants and individuals.
- The main dataset has no missing values. Missing-data behaviour is exercised in the tests.
- These dosages do **not** represent any population or ancestry. Because they are coded as effect-allele counts, they do **not** test allele harmonization or strand resolution.

## 4. Missing data and invalid input

- `NA`, empty or `.` means missing. It is excluded from the sum, never imputed, and counted.
- Coverage = used / 81. Status: `PASS` (100%), `PARTIAL` (≥ 95%), `LOW_COVERAGE` (< 95%, score withheld), `NO_DATA` (0 used, score withheld).
- Any dosage outside {0, 1, 2} (for example 3, −1, 1.5, "2.0") is an error and is never coerced.
- A genotype effect allele that differs from the scoring file's is an error.

## 5. Numerical validation

- Primary: exact `Decimal` arithmetic on the weights' text values, looping per individual.
- Independent: a separate file with no shared imports, its own parser, float weights and `math.fsum`, column-wise. It runs in a separate isolated interpreter (`python -I`).
- **Tolerance: absolute 1e-9.** Weights have 3 decimal places and |score| < 10, so a true discrepancy would be ≥ 0.001. Float error is about 1e-15.
- Also: n_used must match exactly, and both outputs must have the same set of individuals.
- Manual check: per-variant contribution tables for SYN01 and SYN02, summed by a third tool (`awk`) and spot-checked by hand.

## 6. What the score may and may not be used to claim

The score may only be reported as a raw weighted sum in GWAS effect units. It must not be reported as a percentile, a risk category, a hip-BMD prediction, evidence of predictive accuracy, or evidence of ancestry transferability.
