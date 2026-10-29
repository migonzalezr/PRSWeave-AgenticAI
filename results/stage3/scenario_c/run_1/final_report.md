# PRSWeave run R3a6d4f6c

**Request:** Using the published polygenic score provided (PGS005206) and the genotype dosage file provided for 20 individuals, compute a validated polygenic score for total-hip BMD for each individual and report the results with their limitations.

**Final state:** ABSTAINED. PGS005206 is a bone mineral density score whose only recorded site evidence (source GWAS GCST005348, 'Total body bone mineral density') is total body, while total-hip BMD was requested. Phenotype assessment reported site_correspondence = mismatch, the score's own trait fields name no site, and its only evaluation (Generation R, mean age 9.77 years) does not support claims for the target. Two catalog searches ('hip' + 'bone mineral density'; 'BMD' + 'hip') returned 0 alternative scores, so no eligible replacement exists without changing the target. Predictive validity cannot be measured because the target genotypes are synthetic dosages with no phenotypes or ancestry. The researcher may resubmit with a score that explicitly targets total-hip BMD, or explicitly approve a total-body BMD score with its limitations stated.

Planner decisions: 5; tool executions: 4; Critic reviews: 0 []; recovery cycles: 0.

## Decision sequence

| Step | Action | Status |
|---|---|---|
| S001 | inspect_score_metadata | ok |
| S002 | assess_phenotype_compatibility | ok |
| S003 | search_alternative_scores | ok |
| S004 | search_alternative_scores | ok |
| S005 | abstain | ok |

## Fixed limitations

- Genotypes are synthetic effect-allele dosages; no ancestry, phenotype or real allele harmonization.
- PGS005206 is a total-body BMD score; nothing here is a hip-BMD result.
- Derivation of the published weights is partly unverified (DR-0002).
- Raw weighted sums only; no percentiles, risk categories or clinical meaning.
