#!/usr/bin/env python3
"""Quick start: score 20 synthetic individuals with PGS005206 and verify the result two ways.

Steps:
  1. Load the published scoring file, refusing it unless its SHA-256 matches the approved pin.
  2. Score the synthetic effect-allele dosages with the validated scorer (exact Decimal arithmetic).
  3. Recompute independently with validation/independent_scorer.py (float, separate code).
  4. Compare both with the archived Stage 2 reference in results/stage2/prs_scores.csv.

Writes only to examples/output/. Archived results are never modified.
Prerequisite: python3 scripts/fetch_public_data.py --only PGS005206

The scores are raw weighted sums on synthetic data, with no biological or clinical meaning.
"""

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prsweave import prs  # noqa: E402
from prsweave.scoring_file import APPROVED, load_scoring_file  # noqa: E402

SCORING = ROOT / "data/raw/scoring_files/PGS005206/PGS005206_hmPOS_GRCh38.txt.gz"
GENOTYPES = ROOT / "data/synthetic/PGS005206_synthetic_dosages_seed20261029.tsv"
OUT = ROOT / "examples/output"

if not SCORING.exists():
    sys.exit("Scoring file missing. Run: python3 scripts/fetch_public_data.py --only PGS005206")

OUT.mkdir(parents=True, exist_ok=True)
_, variants = load_scoring_file(SCORING)  # raises ChecksumMismatch unless the file matches the approved pin
scores = prs.score_individuals(variants, prs.read_genotypes(GENOTYPES))
primary = {s.iid: str(s.score) for s in scores}

indep_csv = OUT / "independent_scores.csv"
subprocess.run([sys.executable, "-I", str(ROOT / "validation/independent_scorer.py"), str(SCORING),
                APPROVED["sha256"], str(GENOTYPES), str(indep_csv)], check=True, capture_output=True)
with open(indep_csv) as fh:
    indep = {r["IID"]: float(r["score_independent"]) for r in csv.DictReader(fh)}
with open(ROOT / "results/stage2/prs_scores.csv") as fh:
    reference = {r["IID"]: r["score"] for r in csv.DictReader(fh)}

with open(OUT / "quickstart_scores.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["IID", "score", "variants_used", "qc_status"])
    for s in scores:
        w.writerow([s.iid, s.score, s.n_used, s.status])

max_diff = max(abs(float(primary[i]) - indep[i]) for i in primary)
print(f"Scored {len(scores)} synthetic individuals with {len(variants)} PGS005206 variants.")
for s in scores[:5]:
    print(f"  {s.iid}  {s.score:>7}  ({s.n_used}/{s.n_total} variants, {s.status})")
print("  ...")
print(f"Independent implementation, max |difference|: {max_diff:.1e}")
print(f"Identical to archived Stage 2 reference: {primary == reference}")
print(f"Wrote {OUT.relative_to(ROOT)}/quickstart_scores.csv")
