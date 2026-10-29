# PRSWeave v0.1: Stage 1 Feasibility Report

**Date:** 2026-10-29. **PGS Catalog release:** 2026-10-23 (7,029 scores; REST API v1.8.6; Ensembl 105).
**Evidence:** `results/stage1/stage1_summary.json`, which holds all API responses, file SHA-256 checksums and retrieval timestamps. Re-run it with `python3 scripts/stage1_feasibility.py`.

## 1. Environment

| Item | Finding |
|---|---|
| OS | macOS 15.7.3, Apple Silicon (arm64) |
| Python | 3.14.6 (Homebrew, `python3`); system 3.9.6 also present |
| Third-party libs | **None installed** (no numpy/pandas/requests/pytest) |
| Tools | git 2.39.5, pip 26.1.2; no conda/uv |
| Disk | **19 GiB free (96% used)** |
| Project dir | Empty at start; on OneDrive sync |

## 2. PGS Catalog connectivity

The API is reachable (HTTP 200, about 0.4 s). The REST docs and OpenAPI schema were read. The documented rate limit is **100 queries/min**. The Stage 1 client stays under it and handles `429 availableIn`. One full run makes 52 requests.

## 3. Search results

* **No score in the catalog targets total-hip or hip BMD.** No trait for hip, total-hip or femoral-neck BMD exists in the catalog's ontology. The free-text trait search for "bone density" also returns nothing.
* The relevant trait is **`OBA_1000110` bone tissue density** (11 scores). There is also `EFO_0009270` heel BMD (22 scores), most of them UK Biobank ultrasound eBMD.
* A full scan of the score index found 73 bone-related scores.
* The closest to the hip is the femoral-neck score from Ho-Le 2016 (`trait_additional` = "Femoral neck BMD (g/cm2)").

## 4. Candidates (all values from the API and file headers)

| | **PGS005206** `BMD_PRS` | **PGS000121** `2018_BMD62_GRS.FN` | **PGS002583** `bmd_HEEL_TSCOREz.P+T.5e-08` |
|---|---|---|---|
| Phenotype | Bone mineral density; source GWAS is **total-body BMD** (GCST005348, Medina-Gomez 2018) | **Femoral-neck BMD** | Heel BMD T-score (UKB ultrasound) |
| Publication | Prijatelj V, *Bone* 2024, PMID 38460828 | Ho-Le TP, *JBMR* 2016, PMID 27649491 | Weissbrod O, *Nat Genet* 2022, PMID 35393596 |
| Variants | 81 | 62 | 7,908 |
| Build (as submitted) | NR | NCBI36 (hg18) | GRCh37 |
| Harmonized files | GRCh37 and GRCh38 | GRCh37 and GRCh38 | GRCh37 and GRCh38 |
| Weight type | beta (64 distinct values) | **NR; every `effect_weight` = 1**. Sex-specific betas appear only as free text in `variant_description` (62/62 parseable) | beta |
| `other_allele` | Absent; inferred by harmonization (24 multi-allelic) | Absent (11 missing, 7 multi-allelic) | Present |
| Palindromic SNVs | 5 | 5 | 1,362 |
| Other QC | 0 unmapped, 0 duplicates | 0 unmapped, 0 duplicates | 5 unmapped, 4 duplicate positions |
| GWAS ancestry | 84% EUR, 2% AFR, 14% NR | 100% EUR | 100% EUR |
| Catalog evaluation | Generation R, EUR children (mean age 9.8 y), n=3,470, β=0.04 | Dubbo (DOES), EUR, n=902. FN-BMD β=−0.019; fracture HR 1.13 to 1.20 | UKB EUR R²=0.133; SAS 0.084; EAS 0.043; AFR 0.020 |

Scoring file URLs follow the pattern `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/<ID>/ScoringFiles/<ID>.txt.gz`. Harmonized files are under `Harmonized/<ID>_hmPOS_GRCh38.txt.gz`. The exact URLs and checksums are in the summary JSON.

## 5. Recommendation

**PGS005206 is the most technically feasible.** It has 81 numeric beta weights spread across 20 chromosomes, harmonized GRCh38 coordinates, and no unmapped or duplicate variants. Synthetic genotypes for 81 sites are trivial to generate, and the weighted sum can be checked by hand. It runs with the standard library alone.

**Caveat:** it measures total-body BMD, not total-hip BMD.
**Alternative for site specificity:** PGS000121 (femoral neck, the nearest site to the hip). It needs one decision first: whether to use the female or male betas parsed from the free text. The deposited weights are placeholders.

## 6. Limitations to resolve before Stage 2

1. **Trait mismatch.** No published total-hip BMD score is in the catalog. Any hip-BMD framing would rely on a proxy (total-body or femoral-neck), and the report must say so.
2. **Allele orientation.** PGS005206 has no deposited `other_allele`, and harmonization lists several possible alleles for 24 of its 81 variants. Synthetic genotypes must be defined against the effect allele. They are never matched to a reference panel, so this only matters for realism.
3. **Palindromic SNVs** (5 in PGS005206) cannot be strand-resolved without allele frequencies. With synthetic genotypes the stated strand can be taken as given, but this should be logged.
4. **Build.** PGS005206 is "NR" as submitted. Use the catalog's harmonized GRCh38 file and record the harmonization date (2025-05-18).
5. **Scale and interpretation.** Raw scores for 20 synthetic people have no reference distribution. Do not report percentiles or risk categories. Ancestry normalization (as in pgsc_calc) needs a real reference panel and is out of scope.
6. **Unverified points.** The units of the beta values (likely SD of TB-BMD) and the negative femoral-neck β of PGS000121 should be checked against the source papers. I have not read them.
7. **Environment.** No numeric libraries are installed and disk space is tight (19 GiB). The stdlib suffices for Stage 2. Any additions (for example numpy or pytest) need your approval and a venv. Note that `.git` inside a OneDrive folder can sync badly, so `git init` has not been run.

**Stage 1 complete. Awaiting approval to proceed to Stage 2.**
