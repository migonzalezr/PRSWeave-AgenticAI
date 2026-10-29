"""Population Context specialist (deterministic; no model inside).

Reports observed facts at three separate levels and does not merge them:
  1. technical_compatibility: can the weighted sum be computed on this file?
  2. scientific_suitability: does the score's phenotype correspond to the request?
  3. predictive_validity: can performance in the target population be assessed?
It flags conditions that may call for abstention, but the decision is the Planner's.
"""

from __future__ import annotations

import gzip
import json

from ..orchestration.tool_registry import ToolResult
from .common import (CANONICAL_COLUMNS, PINNED_SCORING_FILES, RunContext, parse_genotype_table, skeletal_sites)

AGENT_ID = "PopulationContextAgent"
VALID = {"0", "1", "2"}
MISSING = {"NA", "", "."}
PALINDROMIC = ({"A", "T"}, {"C", "G"})


def _evidence(ctx: RunContext, pgs_id: str) -> dict | None:
    rel = ctx.evidence.get(pgs_id)
    return json.loads(ctx.path(rel).read_text()) if rel else None


def _scoring_rows(pgs_id: str) -> list[dict]:
    with gzip.open(PINNED_SCORING_FILES[pgs_id]["path"], "rt") as fh:
        lines = [l.rstrip("\n").split("\t") for l in fh if not l.startswith("#")]
    head = lines[0]
    return [dict(zip(head, r)) for r in lines[1:]]


def assess_phenotype_compatibility(ctx: RunContext, pgs_id: str) -> ToolResult:
    ev = _evidence(ctx, pgs_id)
    if ev is None:
        return ToolResult("error", {"message": f"no evidence record for {pgs_id}; run inspect_score_metadata first"},
                          error_code="EVIDENCE_REQUIRED")
    ph = ev["phenotype"]
    sources = {"trait_reported": ph["trait_reported"], "trait_additional": ph["trait_additional"],
               **{f"trait_efo[{i}]": t for i, t in enumerate(ph["trait_efo"])},
               **{f"source_gwas[{g['accession']}]": g.get("disease_trait") for g in ph["source_gwas"]},
               **{f"evaluation_phenotype[{i}]": t for i, t in enumerate(ph["evaluation_phenotypes"])}}
    score_sites = {k: skeletal_sites(v) for k, v in sources.items() if v}
    all_sites = sorted({s for v in score_sites.values() for s in v})
    req_sites = skeletal_sites(ctx.requested_phenotype)
    if not all_sites or not req_sites:
        match = "undetermined"
    else:
        match = "exact" if set(req_sites) == set(all_sites) else "mismatch"
    conditions = []
    if match == "mismatch":
        conditions.append(f"Requested site(s) {req_sites} differ from the site(s) in the score's evidence {all_sites}.")
    if match == "undetermined":
        conditions.append("Skeletal site could not be determined from the request or the score evidence.")
    if not any(score_sites.get(k) for k in ("trait_reported", "trait_additional")):
        conditions.append("The score's own trait fields name no skeletal site; any site comes from linked records.")
    eu = (ev.get("ancestry_distribution") or {})
    data = {
        "pgs_id": pgs_id,
        "requested_phenotype": ctx.requested_phenotype,
        "scientific_suitability": {
            "requested_sites": req_sites, "score_phenotype_sources": sources, "sites_by_source": score_sites,
            "score_sites": all_sites, "site_correspondence": match,
            "note": "Site correspondence is a vocabulary comparison of recorded metadata; it is evidence, not a decision."},
        "technical_compatibility": ctx.assessments.get("coverage_summary", "not yet assessed (run inspect_variant_coverage)"),
        "predictive_validity": {
            "measurable": False,
            "reason": "Target genotypes are synthetic effect-allele dosages with no phenotypes and no ancestry; "
                      "transferability and predictive accuracy cannot be measured."},
        "ancestry_metadata": {"development_gwas": eu.get("gwas"), "evaluation": eu.get("eval"),
                              "evaluations": ev.get("evaluations"),
                              "supports_claims_for_target": False},
        "conditions_possibly_requiring_abstention": conditions,
    }
    out = ctx.run_dir / "artifacts" / f"phenotype_assessment_{pgs_id}.json"
    out.write_text(json.dumps(data, indent=2))
    ctx.assessments[f"phenotype:{pgs_id}"] = ctx.rel(out)
    return ToolResult("ok", data, artifacts=[out])


def inspect_variant_coverage(ctx: RunContext, genotype_artifact: str, pgs_id: str) -> ToolResult:
    if pgs_id not in PINNED_SCORING_FILES:
        return ToolResult("error", {"message": f"no pinned scoring file for {pgs_id}"}, error_code="NO_APPROVED_SCORING_FILE")
    t = parse_genotype_table(ctx.path(genotype_artifact))
    score = _scoring_rows(pgs_id)
    score_keys = {f"{r['hm_chr']}:{r['hm_pos']}:{r['effect_allele'].upper()}": r for r in score}
    issues = []
    if t["missing_columns"]:
        issues.append({"code": "MISSING_REQUIRED_COLUMN", "detail": t["missing_columns"]})
    if t["duplicate_columns"]:
        issues.append({"code": "DUPLICATE_COLUMN", "detail": t["duplicate_columns"]})
    if t["ragged_lines"]:
        issues.append({"code": "RAGGED_LINES", "detail": t["ragged_lines"][:10]})
    if not t["canonical_order"]:
        issues.append({"code": "COLUMN_ORDER_NONCANONICAL",
                       "detail": {"observed_first_columns": t["header"][:8], "expected_first_columns": CANONICAL_COLUMNS,
                                  "all_required_columns_present_once": not t["missing_columns"] and not t["duplicate_columns"]}})
    matched = [k for k in t["rows"] if k in score_keys]
    unmatched_score = [k for k in score_keys if k not in t["rows"]]
    rsid_consistent = sum(1 for k in matched if t["rows"][k].get("rsID") == score_keys[k]["rsID"])
    invalid, missing_cells = [], 0
    per_ind = {}
    for iid in t["ids"]:
        used = 0
        for k in matched:
            tok = t["rows"][k][iid].strip()
            if tok in VALID:
                used += 1
            elif tok in MISSING:
                missing_cells += 1
            else:
                invalid.append({"variant_id": k, "iid": iid, "value": tok})
        per_ind[iid] = round(used / len(score_keys), 4)
    if invalid:
        issues.append({"code": "INVALID_DOSAGE", "detail": invalid[:10], "n": len(invalid)})
    if unmatched_score:
        issues.append({"code": "SCORE_VARIANTS_NOT_IN_FILE", "detail": unmatched_score[:10], "n": len(unmatched_score)})
    cov = list(per_ind.values())
    summary = {"genotype_artifact": genotype_artifact, "n_individuals": len(t["ids"]), "n_score_variants": len(score_keys),
               "n_matched_by_variant_id": len(matched), "n_rsid_consistent": rsid_consistent,
               "n_missing_cells": missing_cells, "n_invalid_cells": len(invalid),
               "coverage_min": min(cov) if cov else None, "coverage_max": max(cov) if cov else None,
               "individuals_below_0.95": sorted(i for i, c in per_ind.items() if c < 0.95),
               "readable_by_stage2_scorer": t["canonical_order"] and not issues,
               "issues": issues}
    out = ctx.run_dir / "artifacts" / f"coverage_{genotype_artifact.replace('/', '_')}.json"
    out.write_text(json.dumps({**summary, "per_individual_coverage": per_ind}, indent=2))
    ctx.assessments["coverage_summary"] = {k: summary[k] for k in ("genotype_artifact", "n_matched_by_variant_id",
                                                                   "coverage_min", "readable_by_stage2_scorer")}
    ctx.assessments[f"coverage:{genotype_artifact}"] = ctx.rel(out)
    return ToolResult("ok", summary, artifacts=[out])


def validate_effect_alleles(ctx: RunContext, genotype_artifact: str, pgs_id: str) -> ToolResult:
    if pgs_id not in PINNED_SCORING_FILES:
        return ToolResult("error", {"message": f"no pinned scoring file for {pgs_id}"}, error_code="NO_APPROVED_SCORING_FILE")
    t = parse_genotype_table(ctx.path(genotype_artifact))
    if "effect_allele" not in t["header"] or "variant_id" not in t["header"]:
        return ToolResult("error", {"message": "effect_allele or variant_id column absent"}, error_code="MISSING_REQUIRED_COLUMN")
    score = {f"{r['hm_chr']}:{r['hm_pos']}:{r['effect_allele'].upper()}": r for r in _scoring_rows(pgs_id)}
    mism = [k for k, r in t["rows"].items() if k in score and r["effect_allele"].upper() != score[k]["effect_allele"].upper()]
    amb = [r["rsID"] for r in score.values() if "/" in r.get("hm_inferOtherAllele", "") or not r.get("hm_inferOtherAllele")]
    pal = [r["rsID"] for r in score.values() if r["rsID"] not in amb and {r["effect_allele"].upper(), r["hm_inferOtherAllele"].upper()} in PALINDROMIC]
    return ToolResult("ok", {"n_checked": sum(k in score for k in t["rows"]), "n_effect_allele_mismatch": len(mism),
                             "mismatches": mism[:10], "n_other_allele_ambiguous_in_score": len(amb),
                             "n_palindromic_in_score": len(pal), "palindromic_rsids": pal,
                             "note": "The file is coded as effect-allele dosage, so agreement here does not test strand "
                                     "resolution or allele harmonization of real genotypes."})


def select_alternative_eligible_score(ctx: RunContext, pgs_id: str) -> ToolResult:
    """Check whether pgs_id may replace the provided score automatically. It may not switch silently."""
    from .evidence import inspect_score_metadata
    if pgs_id not in ctx.evidence:
        r = inspect_score_metadata(ctx, pgs_id)
        if r.status != "ok":
            return ToolResult("error", {"pgs_id": pgs_id, "message": r.data.get("message")}, error_code=r.error_code)
    a = assess_phenotype_compatibility(ctx, pgs_id).data
    reasons = []
    if a["scientific_suitability"]["site_correspondence"] != "exact":
        reasons.append(f"site correspondence is '{a['scientific_suitability']['site_correspondence']}' "
                       f"(requested {a['scientific_suitability']['requested_sites']}, score {a['scientific_suitability']['score_sites']})")
    if pgs_id not in PINNED_SCORING_FILES:
        reasons.append("no approved, checksum-pinned scoring file; switching requires researcher approval and a new decision record")
    eligible = not reasons
    return ToolResult("ok" if eligible else "error",
                      {"pgs_id": pgs_id, "eligible_for_automatic_use": eligible, "reasons": reasons,
                       "requires_researcher_approval": not eligible},
                      error_code=None if eligible else "NOT_ELIGIBLE_WITHOUT_APPROVAL")
