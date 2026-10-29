"""Stage 2 tests (standard library unittest).

Run:  python3 -m unittest -v tests.test_stage2
"""

import gzip
import importlib.util
import random
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prsweave import prs, synthetic  # noqa: E402
from prsweave.audit import sha256_file  # noqa: E402
from prsweave.scoring_file import (APPROVED, ChecksumMismatch, ScoreVariant, ScoringFileError,  # noqa: E402
                                   load_scoring_file)

APPROVED_FILE = ROOT / "data/raw/scoring_files/PGS005206/PGS005206_hmPOS_GRCh38.txt.gz"

_spec = importlib.util.spec_from_file_location("independent_scorer", ROOT / "validation/independent_scorer.py")
independent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(independent)


def toy_variants():
    spec = [("rs1", "1", 100, "A", "0.069"), ("rs2", "2", 200, "T", "-0.101"), ("rs3", "3", 300, "C", "0.312")]
    return [ScoreVariant(rsid=r, chrom=c, pos=p, effect_allele=a, weight=Decimal(w), weight_text=w,
                         other_allele_inferred="G", orig_chrom=c, orig_pos=p) for r, c, p, a, w in spec]


def write_geno(path, variants, ids, cells):
    """cells[variant_index][individual_index] as raw text tokens."""
    with open(path, "w") as fh:
        fh.write("\t".join(["variant_id", "rsID", "chr_GRCh38", "pos_GRCh38", "effect_allele", *ids]) + "\n")
        for v, row in zip(variants, cells):
            fh.write("\t".join([v.key, v.rsid, v.chrom, str(v.pos), v.effect_allele, *row]) + "\n")


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def score(self, cells, ids=("I1",), variants=None, **kw):
        variants = variants or toy_variants()
        write_geno(self.tmp / "g.tsv", variants, list(ids), cells)
        return prs.score_individuals(variants, prs.read_genotypes(self.tmp / "g.tsv"), **kw)


class DosageBoundaries(TmpDirCase):
    def test_all_zero_scores_zero(self):
        (s,) = self.score([["0"], ["0"], ["0"]])
        self.assertEqual(s.score, Decimal("0"))
        self.assertEqual((s.n_dosage_0, s.status), (3, "PASS"))

    def test_all_two_is_twice_weight_sum(self):
        (s,) = self.score([["2"], ["2"], ["2"]])
        self.assertEqual(s.score, 2 * (Decimal("0.069") + Decimal("-0.101") + Decimal("0.312")))
        self.assertEqual(s.score, Decimal("0.560"))

    def test_single_copy_adds_weight_once(self):
        (s,) = self.score([["1"], ["0"], ["0"]])
        self.assertEqual(s.score, Decimal("0.069"))

    def test_negative_weight_dosage_two(self):
        (s,) = self.score([["0"], ["2"], ["0"]])
        self.assertEqual(s.score, Decimal("-0.202"))

    def test_invalid_dosages_rejected(self):
        for bad in ["3", "-1", "1.5", "x", "01", "2.0", "nan"]:
            with self.subTest(bad=bad), self.assertRaises(prs.GenotypeError):
                self.score([[bad], ["0"], ["0"]])


class MissingData(TmpDirCase):
    def test_missing_tokens_excluded_not_imputed(self):
        for tok in ["NA", "", "."]:
            with self.subTest(tok=tok):
                (s,) = self.score([[tok], ["2"], ["1"]], min_coverage=Decimal("0"))
                self.assertEqual(s.score, Decimal("-0.202") + Decimal("0.312"))
                self.assertEqual((s.n_used, s.n_missing_dosage), (2, 1))

    def test_low_coverage_withholds_score(self):
        (s,) = self.score([["NA"], ["2"], ["1"]])     # 2/3 < 0.95
        self.assertEqual(s.status, "LOW_COVERAGE")
        self.assertIsNone(s.score)

    def test_partial_coverage_threshold(self):
        (s,) = self.score([["NA"], ["2"], ["1"]], min_coverage=Decimal("0.5"))
        self.assertEqual(s.status, "PARTIAL")
        self.assertEqual(s.coverage, Decimal(2) / Decimal(3))

    def test_all_missing_is_no_data_not_zero(self):
        (s,) = self.score([["NA"], ["NA"], ["NA"]], min_coverage=Decimal("0"))
        self.assertEqual((s.n_used, s.score, s.status), (0, None, "NO_DATA"))

    def test_variant_absent_from_genotype_file(self):
        v = toy_variants()
        write_geno(self.tmp / "g.tsv", v[:2], ["I1"], [["1"], ["1"]])
        (s,) = prs.score_individuals(v, prs.read_genotypes(self.tmp / "g.tsv"), min_coverage=Decimal("0.5"))
        self.assertEqual((s.n_not_genotyped, s.n_used, s.score), (1, 2, Decimal("-0.032")))

    def test_effect_allele_mismatch_rejected(self):
        v = toy_variants()
        write_geno(self.tmp / "g.tsv", v, ["I1"], [["1"], ["1"], ["1"]])
        text = (self.tmp / "g.tsv").read_text().replace("\tA\t1", "\tG\t1", 1)
        (self.tmp / "g.tsv").write_text(text)
        with self.assertRaises(prs.GenotypeError):
            prs.score_individuals(v, prs.read_genotypes(self.tmp / "g.tsv"))


class ScoringFileChecks(TmpDirCase):
    @unittest.skipUnless(APPROVED_FILE.exists(), "approved scoring file not downloaded")
    def test_approved_file_loads(self):
        header, variants = load_scoring_file(APPROVED_FILE)
        self.assertEqual((header["pgs_id"], len(variants)), ("PGS005206", 81))

    @unittest.skipUnless(APPROVED_FILE.exists(), "approved scoring file not downloaded")
    def test_tampered_file_rejected(self):
        bad = self.tmp / "bad.gz"
        with gzip.open(APPROVED_FILE, "rt") as fh:
            rows = fh.read().replace("0.069", "0.070", 1)
        with gzip.open(bad, "wt") as fh:
            fh.write(rows)
        with self.assertRaises(ChecksumMismatch):
            load_scoring_file(bad)

    def test_unsupported_model_rejected(self):
        f = self.tmp / "dom.gz"
        with gzip.open(f, "wt") as fh:
            fh.write("#variants_number=1\n#HmPOS_build=GRCh38\n"
                     "rsID\tchr_name\tchr_position\teffect_allele\teffect_weight\tis_dominant\thm_chr\thm_pos\n"
                     "rs1\t1\t100\tA\t0.1\tTRUE\t1\t100\n")
        with self.assertRaises(ScoringFileError):
            load_scoring_file(f, expected_sha256=sha256_file(f))


class SyntheticGenerator(unittest.TestCase):
    def test_same_seed_identical(self):
        v = toy_variants()
        self.assertEqual(synthetic.generate(v, 20, 7), synthetic.generate(v, 20, 7))

    def test_different_seed_differs(self):
        v = toy_variants()
        self.assertNotEqual(synthetic.generate(v, 20, 7)[2], synthetic.generate(v, 20, 8)[2])

    def test_dosages_in_range(self):
        _, _, d = synthetic.generate(toy_variants(), 200, 1)
        self.assertTrue(all(x in (0, 1, 2) for row in d.values() for x in row))


@unittest.skipUnless(APPROVED_FILE.exists(), "approved scoring file not downloaded")
class PrimaryVsIndependent(TmpDirCase):
    """Random dosage matrices with missing values: both implementations must agree."""

    def test_agreement_with_missing(self):
        _, variants = load_scoring_file(APPROVED_FILE)
        rng = random.Random(12345)
        ids = [f"T{i}" for i in range(30)]
        cells = [[rng.choice(["0", "1", "2", "NA"]) for _ in ids] for _ in variants]
        write_geno(self.tmp / "g.tsv", variants, ids, cells)
        primary = prs.score_individuals(variants, prs.read_genotypes(self.tmp / "g.tsv"), min_coverage=Decimal(0))
        indep, _ = independent.recalc(str(APPROVED_FILE), APPROVED["sha256"], str(self.tmp / "g.tsv"))
        for p, (iid, s, n, _) in zip(primary, indep):
            self.assertEqual((p.iid, p.n_used), (iid, n))
            self.assertLessEqual(abs(float(p.score) - s), 1e-9)

    def test_independent_rejects_bad_dosage(self):
        _, variants = load_scoring_file(APPROVED_FILE)
        write_geno(self.tmp / "g.tsv", variants, ["I1"], [["3"]] + [["0"]] * (len(variants) - 1))
        with self.assertRaises(SystemExit):
            independent.recalc(str(APPROVED_FILE), APPROVED["sha256"], str(self.tmp / "g.tsv"))


if __name__ == "__main__":
    unittest.main()
