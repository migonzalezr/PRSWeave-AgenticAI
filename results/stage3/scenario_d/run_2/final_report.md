# PRSWeave run R5576ba54

**Request:** Using the published polygenic score provided (PGS005206) and the genotype dosage file provided for 20 individuals, compute a validated polygenic score for total-body BMD for each individual and report the results with their limitations.

**Final state:** COMPLETED. validated

Planner decisions: 13; tool executions: 9; Critic reviews: 2 ['FAIL', 'PASS']; recovery cycles: 1.

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
| S008 | submit_for_validation | FAIL |
| S009 | regenerate_authorized_test_input | ok |
| S010 | inspect_variant_coverage | ok |
| S011 | approve_plan | ok |
| S012 | calculate_prs | ok |
| S013 | submit_for_validation | PASS |

## Planner summary (verified by the Critic)

PGS005206 (BMD_PRS, 81 variants, GRCh38 harmonized scoring file matching its approved SHA-256 pin) was applied with the Stage 2 scorer to a synthetic effect-allele dosage file for 20 individuals (sha256 ac0ea0601f4750b69b902044a63fd7799a1de97006a902f08d625de69b9f5ffd, matching the authorized synthetic file). All 20 individuals were scored with QC status PASS (0 PARTIAL, 0 LOW_COVERAGE, 0 NO_DATA), with variant coverage of 1.0 and no effect-allele mismatches in the 81 checked variants. The score's phenotype is bone mineral density, and the linked source GWAS (GCST005348) is total body bone mineral density; the score's own PGS Catalog trait fields name no skeletal site. The scores were recomputed after an earlier scores file was found altered after writing. The input data are synthetic. The target data contain no phenotypes or ancestry, so predictive validity and transferability could not be measured. The only recorded evaluation is in European children (n=3470, Generation R). In the scoring file, 24 variants have an ambiguous other allele and 5 are palindromic. The original genome build is not reported, the derivation of the 81 weights is unverified, and allele agreement does not test strand harmonization of real genotypes. Per-individual scores are in artifacts/prs_scores_2.csv. No percentiles, risk categories or clinical interpretation are provided.

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
