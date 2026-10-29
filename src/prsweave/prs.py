"""Primary deterministic PRS calculator.

    score_i = sum over variants j with an observed dosage of  dosage_ij * effect_weight_j

This is the additive convention the PGS Catalog defines for ``effect_weight``.
Arithmetic uses ``decimal.Decimal`` on the weights' text values, so results are
exact and do not depend on summation order.

Missing-data policy (DR-0002):
  * A missing dosage ('NA', '', '.') is excluded from the sum. It is NOT imputed,
    and it is counted.
  * A scoring variant absent from the genotype file counts as missing for everyone.
  * coverage = used / total scoring variants. Status is PASS at 100%,
    PARTIAL if >= MIN_COVERAGE, and LOW_COVERAGE below that (score withheld).
    NO_DATA (score withheld) if no variant is usable, so a missing score is never shown as 0.
  * Any dosage other than 0, 1, 2 or a missing token is an error, never coerced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .scoring_file import ScoreVariant

MISSING_TOKENS = frozenset({"NA", "", "."})
VALID_DOSAGES = {"0": 0, "1": 1, "2": 2}
MIN_COVERAGE = Decimal("0.95")


class GenotypeError(Exception):
    pass


@dataclass
class GenotypeMatrix:
    ids: list[str]
    effect_allele: dict[str, str]                       # variant_id -> effect allele as written
    dosage: dict[str, list[int | None]] = field(default_factory=dict)


@dataclass
class IndividualScore:
    iid: str
    score: Decimal | None
    n_total: int
    n_used: int
    n_missing_dosage: int
    n_not_genotyped: int
    coverage: Decimal
    status: str
    n_dosage_0: int
    n_dosage_1: int
    n_dosage_2: int


def parse_dosage(token: str, where: str) -> int | None:
    t = token.strip()
    if t in MISSING_TOKENS:
        return None
    if t in VALID_DOSAGES:
        return VALID_DOSAGES[t]
    raise GenotypeError(f"invalid dosage {token!r} at {where}; expected 0, 1, 2 or NA")


def read_genotypes(path: Path) -> GenotypeMatrix:
    with open(path) as fh:
        lines = [l.rstrip("\n") for l in fh if not l.startswith("#")]
    head = lines[0].split("\t")
    if head[:5] != ["variant_id", "rsID", "chr_GRCh38", "pos_GRCh38", "effect_allele"]:
        raise GenotypeError(f"unexpected genotype header: {head[:5]}")
    ids = head[5:]
    if len(set(ids)) != len(ids):
        raise GenotypeError("duplicate individual IDs")
    gm = GenotypeMatrix(ids=ids, effect_allele={})
    for n, line in enumerate(lines[1:], start=2):
        f = line.split("\t")
        if len(f) != len(head):
            raise GenotypeError(f"line {n}: {len(f)} fields, expected {len(head)}")
        vid = f[0]
        if vid in gm.dosage:
            raise GenotypeError(f"duplicate variant {vid}")
        gm.effect_allele[vid] = f[4].upper()
        gm.dosage[vid] = [parse_dosage(tok, f"{vid}/{iid}") for tok, iid in zip(f[5:], ids)]
    return gm


def score_individuals(variants: list[ScoreVariant], gm: GenotypeMatrix,
                      min_coverage: Decimal = MIN_COVERAGE) -> list[IndividualScore]:
    for v in variants:
        if v.key in gm.dosage and gm.effect_allele[v.key] != v.effect_allele:
            raise GenotypeError(f"{v.key}: genotype effect allele {gm.effect_allele[v.key]} != scoring file {v.effect_allele}")
    n_total = len(variants)
    results = []
    for col, iid in enumerate(gm.ids):
        total, used, missing, absent = Decimal(0), 0, 0, 0
        counts = [0, 0, 0]
        for v in variants:
            row = gm.dosage.get(v.key)
            if row is None:
                absent += 1
                continue
            d = row[col]
            if d is None:
                missing += 1
                continue
            total += v.weight * d
            used += 1
            counts[d] += 1
        coverage = Decimal(used) / Decimal(n_total)
        if used == 0:
            status = "NO_DATA"
        elif used == n_total:
            status = "PASS"
        elif coverage >= min_coverage:
            status = "PARTIAL"
        else:
            status = "LOW_COVERAGE"
        results.append(IndividualScore(
            iid=iid, score=None if status in ("LOW_COVERAGE", "NO_DATA") else total, n_total=n_total, n_used=used,
            n_missing_dosage=missing, n_not_genotyped=absent, coverage=coverage, status=status,
            n_dosage_0=counts[0], n_dosage_1=counts[1], n_dosage_2=counts[2],
        ))
    return results


def contributions(variants: list[ScoreVariant], gm: GenotypeMatrix, iid: str) -> list[dict]:
    """Per-variant breakdown for one individual, for manual checking."""
    col = gm.ids.index(iid)
    out = []
    for v in variants:
        d = gm.dosage.get(v.key, [None] * len(gm.ids))[col]
        out.append({"rsID": v.rsid, "variant_id": v.key, "effect_allele": v.effect_allele, "effect_weight": v.weight_text,
                    "dosage": "NA" if d is None else d,
                    "contribution": "" if d is None else "0" if d == 0 else str(v.weight * d)})
    return out
