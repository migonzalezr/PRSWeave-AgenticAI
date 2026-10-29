#!/usr/bin/env python3
"""Independent PRS recalculation, used to validate src/prsweave/prs.py.

This file deliberately shares no code with the ``prsweave`` package. It:
  * re-reads the raw scoring file with its own parser and re-checks the SHA-256,
  * joins variants on rsID + effect allele (the primary scorer joins on
    GRCh38 chr:pos:allele),
  * stores weights as floats and sums with ``math.fsum`` column by column
    (the primary scorer uses exact Decimal arithmetic, looping per individual),
  * applies the same documented missing-data rule: missing dosages are skipped.

Usage:
    python3 validation/independent_scorer.py SCORING.gz SHA256 GENOTYPES.tsv OUT.csv
"""

import gzip
import hashlib
import math
import sys


def file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def weights_by_rsid(scoring_path):
    with gzip.open(scoring_path, "rt") as fh:
        lines = fh.read().splitlines()
    table = [l.split("\t") for l in lines if l and l[0] != "#"]
    head, rows = table[0], table[1:]
    i_rs, i_ea, i_w = head.index("rsID"), head.index("effect_allele"), head.index("effect_weight")
    w = {}
    for r in rows:
        key = (r[i_rs], r[i_ea].upper())
        if key in w:
            raise SystemExit(f"duplicate {key}")
        w[key] = float(r[i_w])
    return w


def dosage_columns(genotype_path):
    with open(genotype_path) as fh:
        lines = [l for l in fh.read().splitlines() if l and l[0] != "#"]
    head = lines[0].split("\t")
    ids = head[5:]
    keys, cols = [], [[] for _ in ids]
    for line in lines[1:]:
        f = line.split("\t")
        keys.append((f[1], f[4].upper()))
        for j, tok in enumerate(f[5:]):
            tok = tok.strip()
            if tok in ("NA", "", "."):
                cols[j].append(None)
            elif tok in ("0", "1", "2"):
                cols[j].append(float(tok))
            else:
                raise SystemExit(f"bad dosage {tok!r} for {f[1]} / {ids[j]}")
    return ids, keys, cols


def recalc(scoring_path, expected_sha, genotype_path):
    got = file_sha256(scoring_path)
    if got != expected_sha:
        raise SystemExit(f"checksum mismatch: {got}")
    w = weights_by_rsid(scoring_path)
    ids, keys, cols = dosage_columns(genotype_path)
    unknown = [k for k in keys if k not in w]
    if unknown:
        raise SystemExit(f"genotype variants not in scoring file: {unknown[:5]}")
    wvec = [w[k] for k in keys]
    n_absent = len(w) - len(set(keys))
    out = []
    for iid, col in zip(ids, cols):
        terms = [wi * d for wi, d in zip(wvec, col) if d is not None]
        out.append((iid, math.fsum(terms), len(terms), len(w)))
    return out, n_absent


if __name__ == "__main__":
    scoring, sha, geno, dest = sys.argv[1:5]
    rows, n_absent = recalc(scoring, sha, geno)
    with open(dest, "w") as fh:
        fh.write("IID,score_independent,n_used,n_total\n")
        for iid, s, n, t in rows:
            fh.write(f"{iid},{s!r},{n},{t}\n")
    print(f"independent: {len(rows)} individuals, {n_absent} scoring variants absent from genotype file")
