"""Load and validate the approved PGS Catalog harmonized scoring file.

The approved file and checksum are fixed by docs/decisions/0001-select-pgs005206.md.
Loading refuses to continue if the checksum differs or if the file uses a
feature this scorer does not implement (interactions, dominant/recessive
models, dosage-specific weights).
"""

from __future__ import annotations

import csv
import gzip
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .audit import sha256_file

APPROVED = {
    "pgs_id": "PGS005206",
    "url": "https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/PGS005206/ScoringFiles/Harmonized/PGS005206_hmPOS_GRCh38.txt.gz",
    "sha256": "406045ea0a082ae6fe640d22b8e2f282cacdcdfa2536b62148fb027703b0b6d3",
    "build": "GRCh38",
    "decision_record": "DR-0001",
}

REQUIRED_COLUMNS = ("rsID", "effect_allele", "effect_weight", "hm_chr", "hm_pos")
UNSUPPORTED_COLUMNS = ("is_interaction", "is_dominant", "is_recessive", "is_haplotype", "is_diplotype",
                       "dosage_0_weight", "dosage_1_weight", "dosage_2_weight")
PALINDROMIC = ({"A", "T"}, {"C", "G"})


class ChecksumMismatch(Exception):
    pass


class ScoringFileError(Exception):
    pass


@dataclass(frozen=True)
class ScoreVariant:
    rsid: str
    chrom: str          # GRCh38 (harmonized)
    pos: int            # GRCh38 (harmonized)
    effect_allele: str
    weight: Decimal     # parsed exactly from the file text
    weight_text: str
    other_allele_inferred: str
    orig_chrom: str
    orig_pos: int

    @property
    def key(self) -> str:
        return f"{self.chrom}:{self.pos}:{self.effect_allele}"

    @property
    def other_allele_ambiguous(self) -> bool:
        return "/" in self.other_allele_inferred or not self.other_allele_inferred

    @property
    def palindromic(self) -> bool:
        return not self.other_allele_ambiguous and {self.effect_allele, self.other_allele_inferred} in PALINDROMIC


def verify_checksum(path: Path, expected: str = APPROVED["sha256"]) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise ChecksumMismatch(f"{path.name}: sha256 {actual} != approved {expected}")
    return actual


def load_scoring_file(path: Path, expected_sha256: str = APPROVED["sha256"]) -> tuple[dict, list[ScoreVariant]]:
    verify_checksum(path, expected_sha256)
    header, body = {}, []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                if "=" in line:
                    k, v = line.lstrip("#").rstrip("\n").split("=", 1)
                    header[k] = v
            else:
                body.append(line)
    rows = list(csv.DictReader(io.StringIO("".join(body)), delimiter="\t"))
    if not rows:
        raise ScoringFileError("no variant rows")
    cols = set(rows[0])
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise ScoringFileError(f"missing required columns: {missing}")
    unsupported = [c for c in UNSUPPORTED_COLUMNS if c in cols]
    if unsupported:
        raise ScoringFileError(f"scoring features not implemented: {unsupported}")
    if header.get("HmPOS_build") != APPROVED["build"]:
        raise ScoringFileError(f"expected HmPOS_build={APPROVED['build']}, got {header.get('HmPOS_build')}")

    variants = []
    for i, r in enumerate(rows, start=1):
        try:
            w = Decimal(r["effect_weight"])
        except InvalidOperation as e:
            raise ScoringFileError(f"row {i}: non-numeric effect_weight {r['effect_weight']!r}") from e
        if not r["hm_pos"]:
            raise ScoringFileError(f"row {i} ({r['rsID']}): not mapped to {APPROVED['build']}")
        variants.append(ScoreVariant(
            rsid=r["rsID"], chrom=r["hm_chr"], pos=int(r["hm_pos"]), effect_allele=r["effect_allele"].upper(),
            weight=w, weight_text=r["effect_weight"], other_allele_inferred=r.get("hm_inferOtherAllele", ""),
            orig_chrom=r["chr_name"], orig_pos=int(r["chr_position"]),
        ))
    n_declared = int(header.get("variants_number", -1))
    if n_declared != len(variants):
        raise ScoringFileError(f"header declares {n_declared} variants, file has {len(variants)}")
    if len({v.key for v in variants}) != len(variants):
        raise ScoringFileError("duplicate variant keys")
    return header, variants
