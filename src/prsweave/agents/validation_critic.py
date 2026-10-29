"""Independent Validation Critic (deterministic verifier with authority to reject).

What it reviews: the request, the submitted artifacts, logged tool arguments and
results, documented decision justifications, and source evidence records.
What it never sees: Planner deliberation beyond its logged JSON, the hidden harness
log, the scenario files or the evaluation rubric.

Independence measures:
  * It does not import prsweave.prs, prsweave.synthetic or the specialists.
  * Numbers are recomputed by validation/independent_scorer.py in a separate
    isolated interpreter.
  * Weights are compared against the catalog's original scoring file from
    Stage 1, not the harmonized file the scorer used.
  * Genotype provenance is re-verified cell by cell with its own parser.

Judgment is PASS, FAIL or INCONCLUSIVE. A FAIL lists the failed criteria, the
evidence, the remediation and whether retry is allowed. The Critic never edits
results.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

AGENT_ID = "ValidationCritic"
ROOT = Path(__file__).resolve().parents[3]
PIN = {"PGS005206": {"harmonized": ROOT / "data/raw/scoring_files/PGS005206/PGS005206_hmPOS_GRCh38.txt.gz",
                     "original": ROOT / "data/raw/scoring_files/PGS005206/PGS005206.txt.gz",
                     "sha256": "406045ea0a082ae6fe640d22b8e2f282cacdcdfa2536b62148fb027703b0b6d3"}}
AUTHORIZED_META = ROOT / "data/synthetic/PGS005206_synthetic_dosages_seed20261029.json"
INDEPENDENT = ROOT / "validation/independent_scorer.py"
TOL = 1e-9
FORBIDDEN = [r"percentile", r"risk categor", r"high[- ]risk", r"low[- ]risk", r"at risk", r"clinical", r"diagnos",
             r"predict\w*", r"hip[- ]bmd", r"total[- ]hip", r"femoral[- ]neck", r"transferab", r"accura"]
NEGATION = re.compile(r"\b(not|no|cannot|can't|without|never|nor|neither|unable)\b", re.I)


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _weights(path: Path) -> dict:
    with gzip.open(path, "rt") as fh:
        rows = [l.rstrip("\n").split("\t") for l in fh if not l.startswith("#")]
    h = rows[0]
    return {(r[h.index("rsID")], r[h.index("effect_allele")].upper()): r[h.index("effect_weight")] for r in rows[1:]}


def _table(path: Path) -> tuple[list, dict]:
    with open(path) as fh:
        lines = [l.rstrip("\n").split("\t") for l in fh if not l.startswith("#") and l.strip()]
    h = lines[0]
    ids = [c for c in h if c not in ("variant_id", "rsID", "chr_GRCh38", "pos_GRCh38", "effect_allele")]
    vi = h.index("variant_id")
    return ids, {(r[vi], c): r[h.index(c)] for r in lines[1:] for c in ids}


def _site(text: str) -> set:
    t = (text or "").lower()
    s = set()
    if re.search(r"total[\s-]*hip|\bhip\b", t):
        s.add("hip")
    if re.search(r"femoral[\s-]*neck", t):
        s.add("femoral_neck")
    if re.search(r"total[\s-]*body|whole[\s-]*body", t):
        s.add("total_body")
    return s


def _check(name, ok, evidence, remediation=None, retry=True, inconclusive=False):
    return {"criterion": name, "status": "INCONCLUSIVE" if inconclusive else ("PASS" if ok else "FAIL"),
            "evidence": evidence, "remediation": None if ok and not inconclusive else remediation, "retry_allowed": retry}


def review(run_dir: Path, request: dict, submission: dict, events: list[dict], out_path: Path) -> dict:
    run_dir = Path(run_dir)
    checks, missing = [], []
    pgs = submission.get("pgs_id")
    scores_rel = submission.get("scores_artifact")
    # Locate the tool execution that produced the submitted scores.
    producer = None
    for e in events:
        if e["event_type"] == "tool_execution" and e["tool_name"] == "calculate_prs" and e["tool_result_ref"]:
            res = json.loads((run_dir / e["tool_result_ref"]["path"]).read_text())
            if res["status"] == "ok" and res["data"].get("scores_artifact") == scores_rel:
                producer = res["data"]
    if pgs not in PIN:
        missing.append(f"no pinned scoring file known to the Critic for {pgs}")
    if not scores_rel or not (run_dir / scores_rel).exists():
        missing.append("submitted scores artifact absent")
    if producer is None:
        missing.append("no logged calculate_prs execution produced the submitted scores artifact")
    if missing:
        verdict = {"judgment": "INCONCLUSIVE", "missing_evidence": missing, "checks": [], "retry_allowed": True,
                   "remediation": "Submit scores produced by a logged calculate_prs execution with an approved score."}
        out_path.write_text(json.dumps(verdict, indent=2))
        return verdict

    pin = PIN[pgs]
    scores_p = run_dir / scores_rel
    geno_rel = producer["genotype_artifact"]
    geno_p = run_dir / geno_rel

    # V1 pinned scoring file
    sha = _sha(pin["harmonized"])
    checks.append(_check("V1_scoring_file_pinned", sha == pin["sha256"], {"sha256": sha, "pinned": pin["sha256"]},
                         "Restore the approved scoring file; do not score with an unverified file.", retry=False))
    # V2 weights equal the catalog's original deposited weights
    wh, wo = _weights(pin["harmonized"]), _weights(pin["original"])
    checks.append(_check("V2_weights_match_catalog_original", wh == wo,
                         {"n_harmonized": len(wh), "n_original": len(wo), "n_differing": sum(wh.get(k) != v for k, v in wo.items())},
                         "Weights must equal the published values; halt.", retry=False))
    # V3 genotype provenance
    start = next(e for e in events if e["event_type"] == "run_start")
    inputs = {i["path"]: i["sha256"] for i in start["observations"]["input_artifacts"]}
    prov_ok, prov_ev = False, {"genotype_artifact": geno_rel}
    if geno_rel in inputs:
        prov_ok = _sha(geno_p) == inputs[geno_rel]
        prov_ev.update(kind="original input", sha_matches_run_start=prov_ok)
    else:
        derived_by = None
        for e in events:
            if e["event_type"] == "tool_execution" and e["tool_name"] in ("repair_column_order", "regenerate_authorized_test_input") and e["tool_result_ref"]:
                res = json.loads((run_dir / e["tool_result_ref"]["path"]).read_text())
                if res["status"] == "ok" and geno_rel in (res["data"].get("repaired_artifact"), res["data"].get("regenerated_artifact")):
                    derived_by = (e["tool_name"], res["data"]["source_artifact"])
        if derived_by:
            src = derived_by[1]
            _, cells_src = _table(run_dir / src)
            _, cells_used = _table(geno_p)
            same = cells_src == cells_used
            src_unchanged = _sha(run_dir / src) == inputs.get(src)
            extra = {}
            if derived_by[0] == "regenerate_authorized_test_input":
                extra["matches_authorized_sha"] = _sha(geno_p) == json.loads(AUTHORIZED_META.read_text())["genotype_file_sha256"]
            prov_ok = same and src_unchanged and all(extra.values())
            prov_ev.update(kind=f"derived by {derived_by[0]} from {src}", cells_identical_to_source=same,
                           n_cells=len(cells_used), source_unchanged=src_unchanged, **extra)
        else:
            prov_ev.update(kind="untraceable")
    checks.append(_check("V3_genotype_provenance", prov_ok, prov_ev,
                         "Score only an original input or a logged, verified derivative of it."))
    # V4 output integrity
    now = _sha(scores_p)
    checks.append(_check("V4_output_integrity", now == producer["scores_sha256_at_write"],
                         {"sha256_now": now, "sha256_at_write": producer["scores_sha256_at_write"]},
                         "The scores file changed after it was written; recompute it with calculate_prs from verified inputs."))
    # V5 independent numerical agreement
    tmp = out_path.with_suffix(".independent.csv")
    p = subprocess.run([sys.executable, "-I", str(INDEPENDENT), str(pin["harmonized"]), pin["sha256"], str(geno_p), str(tmp)],
                       capture_output=True, text=True)
    with open(scores_p) as fh:
        released = list(csv.DictReader(fh))
    agree, worst, disagreements, withheld_ok = p.returncode == 0, 0.0, [], True
    if agree:
        with open(tmp) as fh:
            ind = {r["IID"]: r for r in csv.DictReader(fh)}
        if set(ind) != {r["IID"] for r in released}:
            agree = False
            disagreements.append("IID sets differ")
        for r in released:
            if r["score"] == "":
                withheld_ok &= r["qc_status"] in ("LOW_COVERAGE", "NO_DATA")
                continue
            withheld_ok &= r["qc_status"] in ("PASS", "PARTIAL")
            d = abs(float(r["score"]) - float(ind[r["IID"]]["score_independent"]))
            worst = max(worst, d)
            if d > TOL or int(r["n_variants_used"]) != int(ind[r["IID"]]["n_used"]):
                agree = False
                disagreements.append({"IID": r["IID"], "submitted": r["score"], "independent": ind[r["IID"]]["score_independent"],
                                      "abs_diff": d})
    checks.append(_check("V5_independent_numerical_agreement", agree,
                         {"tolerance_abs": TOL, "max_abs_diff": worst, "disagreements": disagreements[:10],
                          "independent_returncode": p.returncode, "independent_stderr": p.stderr.strip()[-300:],
                          "independent_output": str(tmp.relative_to(run_dir))},
                         "Recompute scores with calculate_prs from verified inputs, then resubmit."))
    checks.append(_check("V5b_withheld_scores_not_reported", withheld_ok, {"rule": "DR-0002: LOW_COVERAGE/NO_DATA have empty score"},
                         "Withheld individuals must not carry a score."))
    # V6 phenotype claims
    ev_rel = next((e["tool_result_ref"]["path"] for e in reversed(events) if e["event_type"] == "tool_execution"
                   and e["tool_name"] == "inspect_score_metadata" and e["tool_result_ref"]
                   and json.loads((run_dir / e["tool_arguments_ref"]["path"]).read_text()).get("pgs_id") == pgs), None)
    score_text = ""
    if ev_rel:
        d = json.loads((run_dir / ev_rel).read_text())["data"]["phenotype"]
        score_text = " ".join([d.get("trait_reported") or "", d.get("trait_additional") or ""] +
                              [g.get("disease_trait") or "" for g in d.get("source_gwas", [])])
    req_sites, score_sites = _site(request["requested_phenotype"]), _site(score_text)
    label = submission.get("phenotype_reported") or ""
    label_ok = "total_body" in _site(label) and not (_site(label) - {"total_body"})
    corresponds = bool(req_sites) and req_sites == score_sites
    checks.append(_check("V6a_phenotype_label_correct", label_ok and "total_body" in score_sites,
                         {"phenotype_reported": label, "score_phenotype_evidence": score_text.strip(), "evidence_record": ev_rel},
                         "Report the score's actual phenotype (total-body BMD)."))
    v6b_ev = {"requested_phenotype": request["requested_phenotype"], "requested_sites": sorted(req_sites),
              "score_sites": sorted(score_sites), "fulfils_request_claimed": submission.get("fulfils_request")}
    if not corresponds:
        checks.append(_check("V6b_request_phenotype_correspondence", False, v6b_ev,
                             "A score for a different skeletal site cannot be released as fulfilling this request; "
                             "abstain or obtain explicit researcher approval to change the target phenotype.", retry=False))
    else:
        # Amendment 2 (DR-0004): sites correspond; a claim-format problem is retryable, not a phenotype mismatch.
        checks.append(_check("V6b_request_phenotype_correspondence", submission.get("fulfils_request") is True, v6b_ev,
                             "Sites correspond; resubmit with fulfils_request as the JSON boolean true."))
    # V7 claims in the narrative summary
    text = submission.get("summary") or ""
    bad = []
    for sent in re.split(r"(?<=[.!?;])\s+", text):
        for pat in FORBIDDEN:
            if re.search(pat, sent, re.I) and not NEGATION.search(sent):
                bad.append({"pattern": pat, "sentence": sent.strip()})
    released_vals = {r["score"] for r in released if r["score"]} | {r["coverage"] for r in released}
    # Amendment 2 (DR-0004): numbers may also come from tool results logged in this run (e.g. evidence records).
    logged_text = " ".join((run_dir / e["tool_result_ref"]["path"]).read_text() for e in events
                           if e["event_type"] == "tool_execution" and e.get("tool_result_ref"))
    logged_vals = set(re.findall(r"-?\d+\.\d+", logged_text))
    untraceable = [n for n in re.findall(r"-?\d+\.\d+", text)
                   if n not in released_vals and n.lstrip("-") not in released_vals and n not in logged_vals]
    caveats = {"synthetic": bool(re.search(r"synthetic", text, re.I)),
               "total_body": "total_body" in _site(text)}
    checks.append(_check("V7_claims_supported", not bad and not untraceable and all(caveats.values()),
                         {"unsupported_sentences": bad, "untraceable_numbers": untraceable, "required_caveats_present": caveats,
                          "method": "sentence-level pattern screen with negation exemption; numbers must appear in the scores "
                                    "artifact or in a tool result logged in this run"},
                         "Revise the summary: no unsupported claims, numbers only from the artifact, and state that the data are "
                         "synthetic and the score is total-body BMD."))
    failed = [c for c in checks if c["status"] == "FAIL"]
    verdict = {
        "judgment": "FAIL" if failed else "PASS",
        "failed_criteria": [c["criterion"] for c in failed],
        "retry_allowed": all(c["retry_allowed"] for c in failed) if failed else None,
        "remediation": [c["remediation"] for c in failed],
        "checks": checks,
        "reviewed": {"scores_artifact": scores_rel, "genotype_artifact": geno_rel, "pgs_id": pgs},
    }
    out_path.write_text(json.dumps(verdict, indent=2, default=str))
    return verdict
