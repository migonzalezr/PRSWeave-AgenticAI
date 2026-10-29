# PRSWeave run R8a5bf58f

**Request:** Using the published polygenic score provided (PGS005206) and the genotype dosage file provided for 20 individuals, compute a validated polygenic score for total-body BMD for each individual and report the results with their limitations.

**Final state:** COMPLETED. validated

Planner decisions: 8; tool executions: 6; Critic reviews: 1 ['PASS']; recovery cycles: 0.

## Decision sequence

| Step | Action | Status |
|---|---|---|
| S001 | inspect_score_metadata | ok |
| S002 | assess_phenotype_compatibility | ok |
| S003 | inspect_variant_coverage | ok |
| S004 | validate_effect_alleles | ok |
| S005 | approve_plan | ok |
| S006 | verify_checksum | ok |
| S007 | calculate_prs | ok |
| S008 | submit_for_validation | PASS |

## Planner summary (verified by the Critic)

Raw polygenic scores for PGS005206 (Bone mineral density; source GWAS GCST005348, Total body bone mineral density) were computed for 20 individuals from a synthetic effect-allele dosage file. All 81 score variants were matched, no effect-allele mismatches were found, and all 20 individuals passed QC (20 PASS, 0 PARTIAL, 0 LOW_COVERAGE, 0 NO_DATA). The scoring file matched its approved SHA-256 pin. The input data are synthetic and contain no phenotypes or ancestry, so predictive validity and transferability could not be assessed. The only catalog evaluation is in European children (Generation R, n=3470, mean age 9.77 years). The original genome build is not reported, the derivation of the weights is unverified (8 of 12 weights overlapping the GWAS table differ in magnitude), 24 variants have an ambiguous other allele and 5 are palindromic, and the dosage coding does not test strand resolution. The scores are raw values with no percentiles, risk categories or clinical interpretation.

## Released scores

| IID | Score | Variants used | QC |
|---|---|---|---|
| SYN01 | -0.320 | 81/81 | PASS |
| SYN02 | -1.195 | 81/81 | PASS |
| SYN03 | -0.173 | 81/81 | PASS |
| SYN04 | -0.974 | 81/81 | PASS |
| SYN05 | -1.865 | 81/81 | PASS |
| SYN06 | -0.687 | 81/81 | PASS |
| SYN07 | -0.680 | 81/81 | PASS |
| SYN08 | -0.521 | 81/81 | PASS |
| SYN09 | -0.135 | 81/81 | PASS |
| SYN10 | -0.340 | 81/81 | PASS |
| SYN11 | -0.790 | 81/81 | PASS |
| SYN12 | -0.025 | 81/81 | PASS |
| SYN13 | -0.832 | 81/81 | PASS |
| SYN14 | 0.049 | 81/81 | PASS |
| SYN15 | -0.512 | 81/81 | PASS |
| SYN16 | -1.051 | 81/81 | PASS |
| SYN17 | -0.563 | 81/81 | PASS |
| SYN18 | -0.069 | 81/81 | PASS |
| SYN19 | -1.539 | 81/81 | PASS |
| SYN20 | -0.373 | 81/81 | PASS |

## Fixed limitations

- Genotypes are synthetic effect-allele dosages; no ancestry, phenotype or real allele harmonization.
- PGS005206 is a total-body BMD score; nothing here is a hip-BMD result.
- Derivation of the published weights is partly unverified (DR-0002).
- Raw weighted sums only; no percentiles, risk categories or clinical meaning.
