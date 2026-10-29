# PRSWeave run Rd2094f4f

**Request:** Using the published polygenic score provided (PGS005206) and the genotype dosage file provided for 20 individuals, compute a validated polygenic score for total-body BMD for each individual and report the results with their limitations.

**Final state:** REQUIRES_HUMAN_REVIEW. PGS005206's PGS Catalog trait fields say only 'Bone mineral density' with no skeletal site. Total-body BMD comes only from its source GWAS (GCST005348), and the only evaluation is in a European pediatric cohort. The Validation Critic would not release these scores as fulfilling a total-body BMD request. Do you accept PGS005206 as a total-body BMD score on the strength of the source GWAS (with the limitations of unmeasurable predictive validity, 5 palindromic variants, 24 ambiguous other alleles and unverified weight derivation), or do you want to supply or approve a different score or target phenotype? The recomputed scores for 20 synthetic individuals (artifacts/prs_scores_2.csv, all QC PASS) are available if you accept the score.

Planner decisions: 10; tool executions: 7; Critic reviews: 1 ['FAIL']; recovery cycles: 1.

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
| S009 | calculate_prs | ok |
| S010 | request_human_review | ok |

## Fixed limitations

- Genotypes are synthetic effect-allele dosages; no ancestry, phenotype or real allele harmonization.
- PGS005206 is a total-body BMD score; nothing here is a hip-BMD result.
- Derivation of the published weights is partly unverified (DR-0002).
- Raw weighted sums only; no percentiles, risk categories or clinical meaning.
