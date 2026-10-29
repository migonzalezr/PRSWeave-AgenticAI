#!/usr/bin/env python3
"""Stage 2: reproducible PGS005206 calculation for 20 synthetic individuals.

A deterministic pipeline, not an agent: every step is fixed code, and every
step is written to results/stage2/execution_log.jsonl.

Usage:
    python3 scripts/stage2_run.py
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prsweave import audit, prs, synthetic  # noqa: E402
from prsweave.scoring_file import APPROVED, load_scoring_file, verify_checksum  # noqa: E402

SEED = 20261029
N_INDIVIDUALS = 20
TOLERANCE = 1e-9          # absolute; fixed in DR-0002 before the first comparison
MANUAL_IDS = ("SYN01", "SYN02")

SCORING = ROOT / "data/raw/scoring_files/PGS005206/PGS005206_hmPOS_GRCh38.txt.gz"
TABLE1 = ROOT / "data/raw/literature/medina_gomez_2018_table1.tsv"
GENO = ROOT / f"data/synthetic/PGS005206_synthetic_dosages_seed{SEED}.tsv"
GENO_META = GENO.with_suffix(".json")
OUT = ROOT / "results/stage2"


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def literature_crosscheck(variants) -> dict:
    """Compare deposited weights with GWAS Table 1 (Medina-Gomez 2018), where both list a SNP."""
    with open(TABLE1) as fh:
        lit = list(csv.DictReader((l for l in fh if not l.startswith("#")), delimiter="\t"))
    by_rs = {v.rsid: v for v in variants}
    per_snp, tally = {}, {"identical": 0, "same_allele_same_sign_diff_magnitude": 0, "conflict": 0, "absent_from_pgs": 0}
    for r in lit:
        v = by_rs.get(r["rsID"])
        if v is None:
            tally["absent_from_pgs"] += 1
            continue
        e = Decimal(r["effect"])
        if v.effect_allele == r["A1"]:
            pass
        elif v.effect_allele == r["A2"]:
            e = -e
        else:
            per_snp[v.rsid] = {"gwas_effect": r["effect"], "agreement": "conflict"}
            tally["conflict"] += 1
            continue
        pos_ok = v.orig_pos == int(r["bp"])
        if e == v.weight:
            label = "identical"
        elif (e > 0) == (v.weight > 0):
            label = "same_allele_same_sign_diff_magnitude"
        else:
            label = "conflict"
        tally[label] += 1
        per_snp[v.rsid] = {"gwas_effect_aligned": str(e), "agreement": label, "grch37_position_match": pos_ok}
    return {"source": "Medina-Gomez 2018 AJHG Table 1 (novel loci only)", "n_table1": len(lit),
            "n_in_pgs": len(lit) - tally["absent_from_pgs"], "tally": tally, "per_snp": per_snp}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log = audit.ExecutionLog(OUT / "execution_log.jsonl", ROOT)
    t_run = time.perf_counter()
    log.record(actor_type="deterministic_software", actor="stage2_run", action="record_environment",
               details={**audit.runtime_environment(), "seed": SEED, "tolerance": TOLERANCE, "approved": APPROVED})
    log.record(actor_type="claude_code_development", actor="Claude Code", action="design_decisions_in_effect",
               details={"decision_records": ["DR-0001", "DR-0002"],
                        "note": "Pipeline design, missing-data policy, tolerance and seed were chosen by Claude Code "
                                "during development (DR-0002); DR-0001 was approved by the project owner."})

    # 1. Scoring file: fetch only if absent, and always verify against the approved checksum.
    with log.step("scoring_file", "obtain_and_verify_checksum") as ctx:
        if not SCORING.exists():
            SCORING.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(APPROVED["url"], headers={"User-Agent": "PRSWeave/0.1"})
            SCORING.write_bytes(urllib.request.urlopen(req, timeout=60).read())
            ctx["details"]["downloaded"] = APPROVED["url"]
        ctx["details"]["sha256"] = verify_checksum(SCORING)
        ctx["details"]["expected"] = APPROVED["sha256"]
        ctx["outputs"].append(SCORING)

    with log.step("scoring_file", "parse_and_validate", inputs=[SCORING]) as ctx:
        header, variants = load_scoring_file(SCORING)
        ctx["details"].update({
            "pgs_id": header.get("pgs_id"), "weight_type": header.get("weight_type"),
            "genome_build_original": header.get("genome_build"), "HmPOS_build": header.get("HmPOS_build"),
            "HmPOS_date": header.get("HmPOS_date"), "n_variants": len(variants),
            "n_positive_weights": sum(v.weight > 0 for v in variants),
            "n_negative_weights": sum(v.weight < 0 for v in variants),
            "n_palindromic": sum(v.palindromic for v in variants),
            "n_other_allele_ambiguous": sum(v.other_allele_ambiguous for v in variants),
            "sum_abs_weight": str(sum(abs(v.weight) for v in variants)),
            "max_weight_decimals": max(-v.weight.as_tuple().exponent for v in variants),
        })

    xcheck = None
    if TABLE1.exists():
        with log.step("weight_verification", "crosscheck_weights_vs_source_gwas_table", inputs=[SCORING, TABLE1]) as ctx:
            xcheck = literature_crosscheck(variants)
            (OUT / "weight_crosscheck.json").write_text(json.dumps(xcheck, indent=2))
            ctx["details"].update(xcheck["tally"], n_table1=xcheck["n_table1"])
            ctx["outputs"].append(OUT / "weight_crosscheck.json")
    else:
        log.record(actor_type="deterministic_software", actor="weight_verification", action="crosscheck_weights_vs_source_gwas_table",
                   status="skipped", details={"reason": f"{TABLE1.relative_to(ROOT)} not present"})

    # 2. Synthetic genotypes, plus a regeneration check that the bytes are identical.
    with log.step("synthetic", "generate_dosages", inputs=[SCORING]) as ctx:
        ids, freqs, dosages = synthetic.generate(variants, N_INDIVIDUALS, SEED)
        synthetic.write_genotypes(GENO, variants, ids, dosages)
        meta = synthetic.write_metadata(GENO_META, GENO, seed=SEED, ids=ids, variants=variants, freqs=freqs,
                                        scoring_sha256=APPROVED["sha256"])
        with tempfile.TemporaryDirectory() as td:
            again = Path(td) / "regen.tsv"
            ids2, _, dosages2 = synthetic.generate(variants, N_INDIVIDUALS, SEED)
            synthetic.write_genotypes(again, variants, ids2, dosages2)
            regen_ok = audit.sha256_file(again) == meta["genotype_file_sha256"]
        all_d = [d for row in dosages.values() for d in row]
        ctx["details"].update({"seed": SEED, "n_individuals": len(ids), "n_variants": len(dosages),
                               "dosage_counts": {k: all_d.count(k) for k in (0, 1, 2)},
                               "regeneration_identical": regen_ok, "_status": "ok" if regen_ok else "fail"})
        ctx["outputs"] += [GENO, GENO_META]

    # 3. Primary scorer.
    with log.step("prs_primary", "score_individuals", inputs=[SCORING, GENO]) as ctx:
        gm = prs.read_genotypes(GENO)
        scores = prs.score_individuals(variants, gm)
        rows = [{"IID": s.iid, "pgs_id": APPROVED["pgs_id"], "score": "" if s.score is None else str(s.score),
                 "n_variants_total": s.n_total, "n_variants_used": s.n_used, "n_missing_dosage": s.n_missing_dosage,
                 "n_not_genotyped": s.n_not_genotyped, "coverage": f"{s.coverage:.4f}",
                 "n_dosage_0": s.n_dosage_0, "n_dosage_1": s.n_dosage_1, "n_dosage_2": s.n_dosage_2,
                 "qc_status": s.status} for s in scores]
        write_csv(OUT / "prs_scores.csv", rows)
        vals = [s.score for s in scores if s.score is not None]
        ctx["details"].update({"n_scored": len(vals), "statuses": {st: sum(s.status == st for s in scores) for st in ("PASS", "PARTIAL", "LOW_COVERAGE", "NO_DATA")},
                               "min": str(min(vals)), "max": str(max(vals)), "mean": str(sum(vals) / len(vals))})
        ctx["outputs"].append(OUT / "prs_scores.csv")

    # 4. Independent scorer in a separate, isolated interpreter.
    indep_csv = OUT / "prs_scores_independent.csv"
    indep_script = ROOT / "validation/independent_scorer.py"
    with log.step("prs_independent", "recalculate_scores", inputs=[indep_script, SCORING, GENO]) as ctx:
        cmd = [sys.executable, "-I", str(indep_script), str(SCORING), APPROVED["sha256"], str(GENO), str(indep_csv)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        ctx["details"].update({"returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()})
        if p.returncode != 0:
            raise RuntimeError(f"independent scorer failed: {p.stderr.strip()}")
        ctx["outputs"].append(indep_csv)

    with log.step("validation", "compare_primary_vs_independent", inputs=[OUT / "prs_scores.csv", indep_csv]) as ctx:
        with open(indep_csv) as fh:
            indep = {r["IID"]: r for r in csv.DictReader(fh)}
        comp = []
        for s in scores:
            r = indep[s.iid]
            diff = abs(float(s.score) - float(r["score_independent"]))
            comp.append({"IID": s.iid, "score_primary": str(s.score), "score_independent": r["score_independent"],
                         "abs_diff": diff, "n_used_primary": s.n_used, "n_used_independent": int(r["n_used"]),
                         "pass": diff <= TOLERANCE and s.n_used == int(r["n_used"])})
        ok = len(comp) == N_INDIVIDUALS and set(indep) == {s.iid for s in scores} and all(c["pass"] for c in comp)
        validation = {"tolerance_abs": TOLERANCE, "n_compared": len(comp), "n_pass": sum(c["pass"] for c in comp),
                      "max_abs_diff": max(c["abs_diff"] for c in comp), "all_pass": ok, "per_individual": comp}
        ctx["details"].update({k: validation[k] for k in ("tolerance_abs", "n_compared", "n_pass", "max_abs_diff", "all_pass")})
        ctx["details"]["_status"] = "ok" if ok else "fail"

    # 5. Per-variant breakdowns for manual checking.
    with log.step("manual_check_support", "write_contribution_tables", inputs=[SCORING, GENO]) as ctx:
        for iid in MANUAL_IDS:
            path = OUT / f"manual_check_{iid}.csv"
            write_csv(path, prs.contributions(variants, gm, iid))
            ctx["outputs"].append(path)

    # 6. Automated tests.
    with log.step("tests", "run_unittest_suite", inputs=[ROOT / "tests/test_stage2.py"]) as ctx:
        p = subprocess.run([sys.executable, "-m", "unittest", "-v", "tests.test_stage2"], cwd=ROOT,
                           capture_output=True, text=True)
        tail = p.stderr.strip().splitlines()
        ctx["details"].update({"returncode": p.returncode, "summary": tail[-3:],
                               "tests": [l for l in tail if l.endswith(("ok", "FAIL", "ERROR"))]})
        ctx["details"]["_status"] = "ok" if p.returncode == 0 else "fail"
        # Wall-clock time is kept in the log only, so this file is byte-reproducible.
        (OUT / "test_output.txt").write_text(re.sub(r"(Ran \d+ tests?) in [\d.]+s", r"\1", p.stderr))
        ctx["outputs"].append(OUT / "test_output.txt")
    validation["unit_tests"] = {"returncode": p.returncode, "summary": tail[-1] if tail else ""}
    (OUT / "validation.json").write_text(json.dumps(validation, indent=2))

    # 7. Variant QC table.
    with log.step("variant_qc", "write_variant_qc", inputs=[SCORING, GENO]) as ctx:
        ranks = {v.key: i for i, v in enumerate(sorted(variants, key=lambda v: -abs(v.weight)), start=1)}
        qc = []
        for v in variants:
            row = gm.dosage[v.key]
            obs = [d for d in row if d is not None]
            x = (xcheck or {}).get("per_snp", {}).get(v.rsid, {})
            qc.append({
                "rsID": v.rsid, "variant_id_GRCh38": v.key, "chr_GRCh37": v.orig_chrom, "pos_GRCh37": v.orig_pos,
                "chr_GRCh38": v.chrom, "pos_GRCh38": v.pos, "effect_allele": v.effect_allele,
                "other_allele_inferred_by_catalog": v.other_allele_inferred, "effect_weight": v.weight_text,
                "abs_weight_rank": ranks[v.key], "palindromic": v.palindromic,
                "other_allele_ambiguous": v.other_allele_ambiguous,
                "gwas_table1_agreement": x.get("agreement", "not_in_table1" if xcheck else "not_checked"),
                "gwas_table1_effect_aligned": x.get("gwas_effect_aligned", ""),
                "synthetic_freq": f"{freqs[v.key]:.6f}", "synthetic_mean_dosage": f"{sum(obs) / len(obs):.3f}",
                "n_missing": len(row) - len(obs), "n_dosage_0": obs.count(0), "n_dosage_1": obs.count(1),
                "n_dosage_2": obs.count(2), "included_in_score": len(obs) > 0,
            })
        write_csv(OUT / "variant_qc.csv", qc)
        ctx["outputs"].append(OUT / "variant_qc.csv")

    # 8. Manifest of all inputs and outputs.
    files = [SCORING, TABLE1, GENO, GENO_META, *sorted(OUT.glob("*.csv")), *sorted(OUT.glob("*.json")),
             OUT / "test_output.txt"]
    manifest = {"run_id": log.run_id, "generated_at": audit.utcnow(), "seed": SEED,
                "files": {str(f.relative_to(ROOT)): audit.sha256_file(f) for f in files if f.exists() and f.name != "manifest.json"}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    failed = [e for e in log.events if e["status"] in ("fail", "error")]
    log.record(actor_type="deterministic_software", actor="stage2_run", action="run_complete",
               status="ok" if not failed else "fail", duration_s=time.perf_counter() - t_run,
               outputs=[OUT / "manifest.json"],
               details={"n_events": len(log.events), "n_failed": len(failed), "n_prsweave_agent_events": 0})
    print(f"run {log.run_id}: {len(scores)} scored, validation all_pass={validation['all_pass']} "
          f"max|diff|={validation['max_abs_diff']:.3g}, tests rc={p.returncode}, failed steps={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
