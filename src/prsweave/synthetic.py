"""Seeded synthetic effect-allele dosages.

These dosages are NOT a realistic population. Each variant gets an arbitrary
"synthetic frequency" drawn uniformly from [0.05, 0.95], independent of any
real allele frequency, ancestry or linkage. Each individual's dosage is the
sum of two independent Bernoulli draws at that frequency.

Dosages count copies of the scoring file's effect allele directly. The file
therefore says nothing about allele harmonization or strand resolution:
there is no other allele, reference panel or strand to reconcile.

Only ``random.Random.random()`` is used, whose output for an integer seed
is stable across CPython versions.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .audit import sha256_file
from .scoring_file import ScoreVariant

GENERATOR_VERSION = "prsweave.synthetic/1"
FREQ_LOW, FREQ_HIGH = 0.05, 0.95
MISSING = "NA"


def generate(variants: list[ScoreVariant], n_individuals: int, seed: int) -> tuple[list[str], dict[str, float], dict[str, list[int]]]:
    rng = random.Random(seed)
    ids = [f"SYN{i:02d}" for i in range(1, n_individuals + 1)]
    # Frequencies first (in file order), then dosages variant by variant.
    freqs = {v.key: FREQ_LOW + (FREQ_HIGH - FREQ_LOW) * rng.random() for v in variants}
    dosages = {v.key: [(rng.random() < freqs[v.key]) + (rng.random() < freqs[v.key]) for _ in ids] for v in variants}
    return ids, freqs, dosages


def write_genotypes(path: Path, variants: list[ScoreVariant], ids: list[str], dosages: dict[str, list[int]]) -> None:
    """Variant-by-individual matrix. One row per scoring-file variant, GRCh38 coordinates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        fh.write("# PRSWeave synthetic effect-allele dosages. NOT real data and NOT a realistic population.\n")
        fh.write("# dosage = copies (0/1/2) of effect_allele; 'NA' = missing\n")
        fh.write("\t".join(["variant_id", "rsID", "chr_GRCh38", "pos_GRCh38", "effect_allele", *ids]) + "\n")
        for v in variants:
            fh.write("\t".join([v.key, v.rsid, v.chrom, str(v.pos), v.effect_allele, *map(str, dosages[v.key])]) + "\n")


def write_metadata(path: Path, genotype_path: Path, *, seed: int, ids: list[str], variants: list[ScoreVariant],
                   freqs: dict[str, float], scoring_sha256: str) -> dict:
    meta = {
        "description": "Synthetic effect-allele dosages for PGS005206 variants. Not real data; "
                       "not representative of any population or ancestry.",
        "generator": GENERATOR_VERSION,
        "seed": seed,
        "rng": "python random.Random (Mersenne Twister), random() only",
        "model": f"synthetic_freq ~ Uniform({FREQ_LOW}, {FREQ_HIGH}) per variant; dosage = Bernoulli(f) + Bernoulli(f), "
                 "independent across variants and individuals (no LD, no structure)",
        "n_individuals": len(ids),
        "n_variants": len(variants),
        "individual_ids": ids,
        "coding": "effect-allele dosage {0,1,2}; missing = 'NA'",
        "scoring_file_sha256": scoring_sha256,
        "genotype_file": genotype_path.name,
        "genotype_file_sha256": sha256_file(genotype_path),
        "synthetic_frequencies": {k: round(f, 6) for k, f in freqs.items()},
        "limitations": [
            "Frequencies are arbitrary, not real allele frequencies.",
            "Effect-allele coding means no allele harmonization or strand resolution is exercised.",
            "Variants are independent; real LD and population structure are absent.",
        ],
    }
    path.write_text(json.dumps(meta, indent=2))
    return meta
