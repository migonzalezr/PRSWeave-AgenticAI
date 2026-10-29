"""PRS Methods specialist (deterministic; no model inside).

Runs the validated Stage 2 functions without modification:
  prsweave.scoring_file.load_scoring_file  (checksum-verified loader)
  prsweave.prs.read_genotypes / score_individuals  (strict reader, exact Decimal scorer, DR-0002 QC)
It never lowers QC thresholds, alters weights or invents genotypes. The two
corrective tools only rearrange or restore an authorized file, and each one
verifies its output cell-for-cell or by checksum before returning it.
"""

from __future__ import annotations

import csv
import json

from .. import prs, synthetic
from ..orchestration.event_log import sha256_file
from ..orchestration.tool_registry import ToolResult
from ..scoring_file import ChecksumMismatch, ScoringFileError, load_scoring_file
from .common import (AUTHORIZED_GENOTYPES, AUTHORIZED_GENOTYPES_META, CANONICAL_COLUMNS, PINNED_SCORING_FILES, ROOT,
                     RunContext, parse_genotype_table)

AGENT_ID = "PRSMethodsAgent"


def verify_checksum(ctx: RunContext, pgs_id: str) -> ToolResult:
    pin = PINNED_SCORING_FILES.get(pgs_id)
    if pin is None:
        return ToolResult("error", {"pgs_id": pgs_id, "message": "no approved checksum on record for this score"},
                          error_code="NO_APPROVED_CHECKSUM")
    actual = sha256_file(pin["path"])
    ok = actual == pin["sha256"]
    return ToolResult("ok" if ok else "error",
                      {"pgs_id": pgs_id, "path": str(pin["path"].relative_to(ROOT)), "sha256": actual,
                       "pinned_sha256": pin["sha256"], "match": ok, "approval": pin["approval"]},
                      error_code=None if ok else "CHECKSUM_MISMATCH")


def calculate_prs(ctx: RunContext, genotype_artifact: str, pgs_id: str) -> ToolResult:
    pin = PINNED_SCORING_FILES.get(pgs_id)
    if pin is None:
        return ToolResult("error", {"message": f"no approved scoring file for {pgs_id}"}, error_code="NO_APPROVED_SCORING_FILE")
    try:
        _, variants = load_scoring_file(pin["path"], pin["sha256"])
    except ChecksumMismatch as e:
        return ToolResult("error", {"message": str(e)}, error_code="CHECKSUM_MISMATCH")
    except ScoringFileError as e:
        return ToolResult("error", {"message": str(e)}, error_code="SCORING_FILE_INVALID")
    try:
        gm = prs.read_genotypes(ctx.path(genotype_artifact))
        scores = prs.score_individuals(variants, gm)
    except prs.GenotypeError as e:
        msg = str(e)
        code = ("GENOTYPE_SCHEMA_ERROR" if "header" in msg else "INVALID_DOSAGE" if "invalid dosage" in msg
                else "EFFECT_ALLELE_MISMATCH" if "effect allele" in msg else "GENOTYPE_FILE_ERROR")
        return ToolResult("error", {"message": msg, "genotype_artifact": genotype_artifact}, error_code=code)
    out = ctx.run_dir / "artifacts" / f"prs_scores_{len(list((ctx.run_dir / 'artifacts').glob('prs_scores_*.csv'))) + 1}.csv"
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["IID", "pgs_id", "score", "n_variants_total", "n_variants_used", "n_missing_dosage", "n_not_genotyped",
                    "coverage", "qc_status"])
        for s in scores:
            w.writerow([s.iid, pgs_id, "" if s.score is None else str(s.score), s.n_total, s.n_used, s.n_missing_dosage,
                        s.n_not_genotyped, f"{s.coverage:.4f}", s.status])
    statuses = {st: sum(s.status == st for s in scores) for st in ("PASS", "PARTIAL", "LOW_COVERAGE", "NO_DATA")}
    return ToolResult("ok", {"scores_artifact": ctx.rel(out), "scores_sha256_at_write": sha256_file(out),
                             "genotype_artifact": genotype_artifact, "genotype_sha256": sha256_file(ctx.path(genotype_artifact)),
                             "pgs_id": pgs_id, "n_individuals": len(scores), "n_scored": sum(s.score is not None for s in scores),
                             "qc_status_counts": statuses, "n_variants_total": scores[0].n_total if scores else 0,
                             "scorer": "prsweave.prs.score_individuals (Stage 2, Decimal, min_coverage 0.95)"},
                      artifacts=[out])


def _cells(t: dict) -> dict:
    return {(vid, iid): rec[iid] for vid, rec in t["rows"].items() for iid in t["ids"]}


def repair_column_order(ctx: RunContext, genotype_artifact: str) -> ToolResult:
    """Rewrite a table into the canonical column order, using header names only."""
    src = ctx.path(genotype_artifact)
    sha_before = sha256_file(src)
    t = parse_genotype_table(src)
    problems = []
    if t["missing_columns"]:
        problems.append(f"missing required columns {t['missing_columns']}")
    if t["duplicate_columns"]:
        problems.append(f"duplicate columns {t['duplicate_columns']}")
    if t["ragged_lines"]:
        problems.append(f"ragged lines {t['ragged_lines'][:5]}")
    if not t["ids"]:
        problems.append("no individual columns")
    if t["canonical_order"]:
        problems.append("columns are already in canonical order; nothing to repair")
    if problems:
        return ToolResult("error", {"message": "; ".join(problems)}, error_code="REPAIR_PRECONDITION_FAILED")
    ids = sorted(t["ids"])
    out = ctx.run_dir / "derived" / (src.stem + "_canonical_columns.tsv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(src) as fh:
        comments = [l for l in fh if l.startswith("#")]
    with open(out, "w") as fh:
        fh.writelines(comments)
        fh.write(f"# derived by repair_column_order from {genotype_artifact} (sha256 {sha_before}); values unchanged\n")
        fh.write("\t".join(CANONICAL_COLUMNS + ids) + "\n")
        for vid, rec in t["rows"].items():
            fh.write("\t".join([rec[c] for c in CANONICAL_COLUMNS] + [rec[i] for i in ids]) + "\n")
    t2 = parse_genotype_table(out)
    identical = _cells(t) == _cells(t2) and all(t["rows"][v][c] == t2["rows"][v][c] for v in t["rows"] for c in CANONICAL_COLUMNS)
    unchanged = sha256_file(src) == sha_before
    if not (identical and unchanged and t2["canonical_order"]):
        return ToolResult("error", {"message": "verification of repaired artifact failed", "cells_identical": identical,
                                    "source_unchanged": unchanged}, error_code="REPAIR_VERIFICATION_FAILED")
    return ToolResult("ok", {"source_artifact": genotype_artifact, "source_sha256": sha_before, "source_unchanged": unchanged,
                             "repaired_artifact": ctx.rel(out), "repaired_sha256": sha256_file(out),
                             "n_cells_compared": len(_cells(t)), "cells_identical": identical,
                             "column_order_applied": CANONICAL_COLUMNS + ["individual IDs sorted"],
                             "method": "reorder by header name; no value changed"}, artifacts=[out])


def regenerate_authorized_test_input(ctx: RunContext, genotype_artifact: str) -> ToolResult:
    """Restore the authorized synthetic test file, but only if the given file has exactly its contents."""
    meta = json.loads(AUTHORIZED_GENOTYPES_META.read_text())
    given = parse_genotype_table(ctx.path(genotype_artifact))
    auth = parse_genotype_table(AUTHORIZED_GENOTYPES)
    if _cells(given) != _cells(auth):
        diff = sum(1 for k, v in _cells(auth).items() if _cells(given).get(k) != v)
        return ToolResult("error", {"message": "given artifact is not cell-identical to the authorized synthetic set; "
                                               "regeneration would substitute data", "n_cells_differing_or_absent": diff},
                          error_code="INPUT_NOT_AUTHORIZED_SET")
    _, variants = load_scoring_file(PINNED_SCORING_FILES["PGS005206"]["path"])
    ids, _, dosages = synthetic.generate(variants, meta["n_individuals"], meta["seed"])
    out = ctx.run_dir / "derived" / "regenerated_authorized_dosages.tsv"
    out.parent.mkdir(parents=True, exist_ok=True)
    synthetic.write_genotypes(out, variants, ids, dosages)
    ok = sha256_file(out) == meta["genotype_file_sha256"]
    if not ok:
        return ToolResult("error", {"message": "regenerated file does not match the authorized checksum"},
                          error_code="REGENERATION_CHECKSUM_MISMATCH")
    return ToolResult("ok", {"source_artifact": genotype_artifact, "regenerated_artifact": ctx.rel(out),
                             "sha256": sha256_file(out), "authorized_sha256": meta["genotype_file_sha256"], "match": ok,
                             "seed": meta["seed"], "generator": meta["generator"]}, artifacts=[out])
