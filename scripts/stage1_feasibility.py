#!/usr/bin/env python3
"""Stage 1: environment and PGS Catalog feasibility check.

Re-runnable, standard library only. It:
  1. records the runtime environment,
  2. queries the PGS Catalog API (info, trait search, full score index),
  3. shortlists bone-density-related scores from the live index,
  4. fetches full metadata and performance records for the chosen candidates,
  5. downloads their original and harmonized scoring files and runs QC on them.

All raw API responses and files are written under data/raw/ with SHA-256
checksums, and a machine-readable summary goes to results/stage1/.

Usage:
    python3 scripts/stage1_feasibility.py [PGS_ID ...]
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import platform
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prsweave.pgs_catalog import FTP_BASE, PGSCatalogClient, _utcnow  # noqa: E402

DEFAULT_CANDIDATES = ["PGS005206", "PGS000121", "PGS002583"]
TRAIT_TERMS = ["bone mineral density", "bone density", "hip", "total hip", "femoral neck", "BMD", "osteoporosis"]
BONE_RE = re.compile(r"bone|BMD|\bhip\b|femoral|femur|osteopor|fractur", re.I)
EXCLUDE_RE = re.compile(r"arthroplasty|osteoarthritis|marrow|malignan|waist|circumference|adipose", re.I)
PALINDROMIC = {frozenset("AT"), frozenset("CG")}

RAW_API = ROOT / "data/raw/pgs_catalog_api"
RAW_FILES = ROOT / "data/raw/scoring_files"
OUT = ROOT / "results/stage1"


def environment() -> dict:
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def read_scoring_file(path: Path) -> tuple[dict, list[dict]]:
    header, lines = {}, []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                if "=" in line:
                    k, v = line.lstrip("#").rstrip("\n").split("=", 1)
                    header[k] = v
            else:
                lines.append(line)
    return header, list(csv.DictReader(io.StringIO("".join(lines)), delimiter="\t"))


def qc_scoring_rows(rows: list[dict]) -> dict:
    cols = list(rows[0].keys()) if rows else []
    weights = [r["effect_weight"] for r in rows]
    other = [r.get("other_allele") or r.get("hm_inferOtherAllele") or "" for r in rows]
    keys = Counter((r.get("hm_chr") or r.get("chr_name"), r.get("hm_pos") or r.get("chr_position"), r["effect_allele"]) for r in rows)
    return {
        "n_variants": len(rows),
        "columns": cols,
        "has_rsID": "rsID" in cols,
        "has_other_allele_column": "other_allele" in cols,
        "n_unique_effect_weights": len(set(weights)),
        "all_weights_identical": len(set(weights)) == 1,
        "n_other_allele_missing": sum(a == "" for a in other),
        "n_other_allele_ambiguous_multiallelic": sum("/" in a for a in other),
        "n_palindromic_snvs": sum(1 for r, a in zip(rows, other) if a and "/" not in a and frozenset(r["effect_allele"] + a) in PALINDROMIC),
        "n_unmapped_in_harmonization": sum(1 for r in rows if "hm_pos" in r and not r.get("hm_pos")),
        "n_duplicate_positions": sum(v > 1 for v in keys.values()),
        "n_non_snv_alleles": sum(1 for r in rows if len(r["effect_allele"]) != 1),
        "chromosomes": sorted({r.get("hm_chr") or r.get("chr_name") for r in rows} - {""}, key=lambda c: (len(c), c)),
        "free_text_weights_in_variant_description": sum(1 for r in rows if re.search(r"Female\s*=.*Male\s*=", r.get("variant_description") or "")),
    }


def summarize_score(s: dict) -> dict:
    p = s["publication"]
    return {
        "id": s["id"],
        "name": s["name"],
        "trait_reported": s["trait_reported"],
        "trait_additional": s.get("trait_additional"),
        "trait_efo": [f"{t['label']} ({t['id']})" for t in s["trait_efo"]],
        "method_name": s.get("method_name"),
        "method_params": s.get("method_params"),
        "variants_number": s["variants_number"],
        "variants_genomebuild": s["variants_genomebuild"],
        "weight_type": s.get("weight_type"),
        "ancestry_distribution": s.get("ancestry_distribution"),
        "ftp_scoring_file": s["ftp_scoring_file"],
        "ftp_harmonized_scoring_files": s.get("ftp_harmonized_scoring_files"),
        "date_release": s.get("date_release"),
        "license": s.get("license"),
        "publication": {k: p.get(k) for k in ("id", "firstauthor", "title", "journal", "date_publication", "doi", "PMID")},
        "samples_variants": [
            {k: x.get(k) for k in ("sample_number", "ancestry_broad", "source_GWAS_catalog", "source_PMID")}
            for x in s.get("samples_variants") or []
        ],
    }


def summarize_performance(perf: dict) -> list[dict]:
    out = []
    for r in perf.get("results", []):
        smp = r["sampleset"]["samples"][0] if r["sampleset"]["samples"] else {}
        m = r["performance_metrics"]
        out.append({
            "ppm_id": r["id"],
            "phenotype": r.get("phenotyping_reported"),
            "covariates": r.get("covariates"),
            "sample_number": smp.get("sample_number"),
            "ancestry": smp.get("ancestry_broad"),
            "cohorts": [c["name_short"] for c in smp.get("cohorts", [])],
            "sample_age": smp.get("sample_age"),
            "metrics": [
                {"name": x["name_short"] or x["name_long"], "estimate": x["estimate"], "ci_lower": x.get("ci_lower"), "ci_upper": x.get("ci_upper")}
                for x in m["effect_sizes"] + m["class_acc"] + m["othermetrics"]
            ],
        })
    return out


def main(candidates: list[str]) -> None:
    client = PGSCatalogClient(cache_dir=RAW_API)
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_started": _utcnow(), "environment": environment()}

    info = client.info()
    report["catalog"] = {
        "rest_api_version": info["rest_api"]["version"],
        "latest_release": info["latest_release"],
        "ensembl_version": info.get("ensembl_version"),
    }

    report["trait_search"] = {
        term: [{"id": t["id"], "label": t["label"], "n_pgs": len(t.get("associated_pgs_ids", []))} for t in client.trait_search(term).get("results", [])]
        for term in TRAIT_TERMS
    }

    # Full index scan: the trait search does not reach every relevant score
    # (e.g. "bone tissue density" scores are not returned for "bone density").
    scores = client.all_scores()
    (RAW_API / "score_all.json").write_text(json.dumps(scores))
    shortlist = []
    for s in scores:
        text = " ".join([s["trait_reported"], s.get("trait_additional") or "", s["name"] or ""] + [t["label"] for t in s["trait_efo"]])
        if BONE_RE.search(text) and not EXCLUDE_RE.search(text):
            shortlist.append({
                "id": s["id"], "name": s["name"], "trait_reported": s["trait_reported"],
                "trait_additional": s.get("trait_additional"),
                "trait_efo": [t["id"] for t in s["trait_efo"]],
                "variants_number": s["variants_number"], "genome_build": s["variants_genomebuild"],
                "weight_type": s.get("weight_type"), "method": s.get("method_name"),
                "pmid": s["publication"].get("PMID"),
            })
    report["index_scan"] = {"n_scores_in_index": len(scores), "n_bone_related": len(shortlist)}
    (OUT / "bone_related_scores.json").write_text(json.dumps(shortlist, indent=2))

    report["candidates"] = []
    for pid in candidates:
        entry = {"score": summarize_score(client.score(pid)), "performance": summarize_performance(client.performance(pid)), "files": {}}
        urls = {"original": entry["score"]["ftp_scoring_file"]}
        for build, d in (entry["score"]["ftp_harmonized_scoring_files"] or {}).items():
            urls[f"hmPOS_{build}"] = d["positions"]
        for label, url in urls.items():
            dest = RAW_FILES / pid / Path(url).name
            r = client.download(url, dest)
            header, rows = read_scoring_file(dest)
            entry["files"][label] = {
                "url": url, "path": str(dest.relative_to(ROOT)), "sha256": r.sha256, "bytes": r.nbytes,
                "retrieved_at": r.retrieved_at, "header": header, "qc": qc_scoring_rows(rows),
            }
        report["candidates"].append(entry)

    report["run_finished"] = _utcnow()
    report["requests"] = [vars(r) for r in client.log]
    (OUT / "stage1_summary.json").write_text(json.dumps(report, indent=2))
    print(f"Catalog release {info['latest_release']['date']}: {len(scores)} scores, {len(shortlist)} bone-related.")
    for c in report["candidates"]:
        s, qc = c["score"], c["files"].get("hmPOS_GRCh38", c["files"]["original"])["qc"]
        print(f"  {s['id']} {s['name']}: n={s['variants_number']} build={s['variants_genomebuild']} "
              f"weights={s['weight_type']} identical_weights={qc['all_weights_identical']} "
              f"palindromic={qc['n_palindromic_snvs']} multiallelic_other={qc['n_other_allele_ambiguous_multiallelic']}")
    print(f"Wrote {OUT / 'stage1_summary.json'} ({len(client.log)} requests)")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_CANDIDATES)
