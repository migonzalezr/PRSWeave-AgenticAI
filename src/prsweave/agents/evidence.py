"""Evidence Retrieval specialist (deterministic; no model inside).

Retrieves real PGS Catalog and GWAS Catalog records through a provenance cache
and returns structured evidence records. It proposes options but never judges
whether a score is scientifically appropriate.
"""

from __future__ import annotations

import gzip
import json

from ..orchestration.event_log import sha256_file, utcnow
from ..orchestration.tool_registry import ToolResult
from ..scoring_file import UNSUPPORTED_COLUMNS
from .common import (PINNED_SCORING_FILES, ROOT, STAGE1_SCORE_INDEX, STAGE1_SUMMARY, RunContext, cached_get_json,
                     skeletal_sites)

AGENT_ID = "EvidenceRetrievalAgent"
PGS_REST = "https://www.pgscatalog.org/rest"
GWAS_REST = "https://www.ebi.ac.uk/gwas/rest/api/v2/studies"
KNOWN_GAPS = {
    "PGS005206": [{"gap": "Full text of Prijatelj et al. 2024 (PGS publication) not reviewed; derivation of the 81 weights unverified. "
                          "8 of 12 weights that overlap GWAS Table 1 differ in magnitude (same allele and sign).",
                   "source": "docs/decisions/0002-stage2-scoring-conventions.md"}],
}


def _scoring_file_header(path) -> tuple[dict, list[str]]:
    header, cols = {}, []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                if "=" in line:
                    k, v = line.lstrip("#").rstrip("\n").split("=", 1)
                    header[k] = v
            else:
                cols = line.rstrip("\n").split("\t")
                break
    return header, cols


def inspect_score_metadata(ctx: RunContext, pgs_id: str) -> ToolResult:
    hosts, provenance = set(), []
    try:
        score, p1 = cached_get_json(f"{PGS_REST}/score/{pgs_id}", f"score_{pgs_id}")
        perf, p2 = cached_get_json(f"{PGS_REST}/performance/search?pgs_id={pgs_id}&limit=250", f"performance_{pgs_id}")
    except Exception as e:
        return ToolResult("error", {"message": f"catalog metadata unavailable: {e}"}, error_code="METADATA_UNAVAILABLE")
    if not score:
        return ToolResult("error", {"message": f"{pgs_id} not found in PGS Catalog"}, error_code="SCORE_NOT_FOUND")
    provenance += [p1, p2]
    gwas = []
    for s in score.get("samples_variants") or []:
        gcst = s.get("source_GWAS_catalog")
        if gcst and gcst not in {g["accession"] for g in gwas}:
            try:
                g, pg = cached_get_json(f"{GWAS_REST}/{gcst}", f"gwas_{gcst}")
                provenance.append(pg)
                gwas.append({"accession": gcst, "disease_trait": g.get("disease_trait"), "pubmed_id": g.get("pubmed_id"),
                             "initial_sample_size": g.get("initial_sample_size"), "url": pg["url"]})
            except Exception as e:
                gwas.append({"accession": gcst, "error": str(e)})
    hosts |= {p["host"] for p in provenance if p.get("served_from") == "live"}

    pinned = PINNED_SCORING_FILES.get(pgs_id)
    scoring = {"ftp_scoring_file": score.get("ftp_scoring_file"),
               "harmonized": {b: d.get("positions") for b, d in (score.get("ftp_harmonized_scoring_files") or {}).items()}}
    effect_allele_spec = None
    if pinned and pinned["path"].exists():
        hdr, cols = _scoring_file_header(pinned["path"])
        actual = sha256_file(pinned["path"])
        scoring.update({"local_path": str(pinned["path"].relative_to(ROOT)), "sha256": actual, "pinned_sha256": pinned["sha256"],
                        "matches_pin": actual == pinned["sha256"], "approval": pinned["approval"],
                        "harmonized_build_used": hdr.get("HmPOS_build"), "harmonization_date": hdr.get("HmPOS_date"),
                        "columns": cols})
        effect_allele_spec = {"effect_allele_column": "effect_allele" in cols, "other_allele_column": "other_allele" in cols,
                              "other_allele_inferred_by_catalog": "hm_inferOtherAllele" in cols,
                              "non_additive_columns": [c for c in UNSUPPORTED_COLUMNS if c in cols]}
    else:
        scoring.update({"local_path": None, "pinned_sha256": None, "matches_pin": None,
                        "note": "No locally pinned, approved scoring file for this score."})

    evaluations = []
    for r in perf.get("results", []):
        smp = (r["sampleset"]["samples"] or [{}])[0]
        evaluations.append({"ppm_id": r["id"], "phenotype": r.get("phenotyping_reported"), "ancestry": smp.get("ancestry_broad"),
                            "n": smp.get("sample_number"), "cohorts": [c["name_short"] for c in smp.get("cohorts", [])],
                            "age": smp.get("sample_age")})
    pub = score.get("publication") or {}
    phenotype_text = [score.get("trait_reported"), score.get("trait_additional")] + [t["label"] for t in score.get("trait_efo", [])]
    missing = []
    if not any(skeletal_sites(t) for t in phenotype_text if t):
        missing.append("PGS Catalog trait fields do not state a skeletal site.")
    if score.get("variants_genomebuild") in (None, "NR"):
        missing.append("Original genome build not reported (NR).")
    if effect_allele_spec and not effect_allele_spec["other_allele_column"]:
        missing.append("No author-supplied other_allele; catalog-inferred only.")
    if not pinned:
        missing.append("No approved, checksum-pinned scoring file for this score.")
    record = {
        "score_id": pgs_id, "name": score.get("name"),
        "phenotype": {"trait_reported": score.get("trait_reported"), "trait_additional": score.get("trait_additional"),
                      "trait_efo": [f"{t['label']} ({t['id']})" for t in score.get("trait_efo", [])],
                      "source_gwas": gwas, "evaluation_phenotypes": sorted({e["phenotype"] for e in evaluations if e["phenotype"]})},
        "genome_build": {"original": score.get("variants_genomebuild"), "harmonized_available": sorted(scoring["harmonized"])},
        "variants_number": score.get("variants_number"), "weight_type": score.get("weight_type"),
        "method": score.get("method_name"), "effect_allele_specification": effect_allele_spec, "scoring_file": scoring,
        "ancestry_distribution": score.get("ancestry_distribution"), "evaluations": evaluations,
        "publication": {k: pub.get(k) for k in ("firstauthor", "title", "journal", "date_publication", "doi", "PMID")},
        "verified_metadata": [p["url"] for p in provenance],
        "missing_information": missing + [g["gap"] for g in KNOWN_GAPS.get(pgs_id, [])],
        "source_citations": [p["url"] for p in provenance] + [g["source"] for g in KNOWN_GAPS.get(pgs_id, [])]
                             + ([f"https://doi.org/{pub['doi']}"] if pub.get("doi") else []),
        "retrieval": [{"url": p["url"], "retrieved_at": p["retrieved_at"], "sha256": p["sha256"], "served_from": p["served_from"]} for p in provenance],
        "retrieval_time": utcnow(),
        "candidate_corrective_actions": (["search_alternative_scores"] if missing else []),
    }
    out = ctx.run_dir / "artifacts" / f"evidence_{pgs_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2))
    ctx.evidence[pgs_id] = ctx.rel(out)
    return ToolResult("ok", record, artifacts=[out], network_hosts=sorted(hosts))


def search_alternative_scores(ctx: RunContext, terms: list) -> ToolResult:
    """Search the full PGS Catalog score index retrieved in Stage 1 (release recorded below)."""
    if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and t.strip() for t in terms):
        return ToolResult("error", {"message": "terms must be a non-empty list of strings"}, error_code="BAD_ARGUMENTS")
    index = json.loads(STAGE1_SCORE_INDEX.read_text())
    release = json.loads(STAGE1_SUMMARY.read_text())["catalog"]["latest_release"]
    hits = []
    for s in index:
        text = " ".join([s.get("trait_reported") or "", s.get("trait_additional") or "", s.get("name") or ""]
                        + [t["label"] for t in s.get("trait_efo", [])]).lower()
        if all(t.lower() in text for t in terms):
            hits.append({"pgs_id": s["id"], "name": s["name"], "trait_reported": s["trait_reported"],
                         "trait_additional": s.get("trait_additional"), "trait_efo": [t["label"] for t in s["trait_efo"]],
                         "sites_in_metadata": skeletal_sites(" ".join([s["trait_reported"] or "", s.get("trait_additional") or ""])),
                         "variants_number": s["variants_number"], "weight_type": s.get("weight_type"),
                         "genome_build": s["variants_genomebuild"]})
    return ToolResult("ok", {"terms": terms, "n_hits": len(hits), "hits": hits[:30], "truncated": len(hits) > 30,
                             "index": {"path": str(STAGE1_SCORE_INDEX.relative_to(ROOT)), "sha256": sha256_file(STAGE1_SCORE_INDEX),
                                       "catalog_release": release, "n_scores": len(index)},
                             "note": "Matches are text matches on catalog metadata, not eligibility judgements."})
