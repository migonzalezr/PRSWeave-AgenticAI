"""Stage 3 tests: controller, specialists and Critic driven by SCRIPTED decisions.

These scripted decisions only test the machinery. They are not experiment
results and are never written under results/stage3/scenario_*.
Run:  python3 -m unittest -v tests.test_stage3
(The first run fetches about 3 small records from the PGS/GWAS Catalog APIs into results/stage3/cache.)
"""

import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from prsweave.orchestration import state as S  # noqa: E402
from prsweave.orchestration.controller import Controller  # noqa: E402
from prsweave.orchestration.event_log import EventLog, sha256_file, verify_chain  # noqa: E402

AUTH = ROOT / "data/synthetic/PGS005206_synthetic_dosages_seed20261029.tsv"
with open(ROOT / "results/stage2/prs_scores.csv") as _fh:
    REF = {r["IID"]: r["score"] for r in csv.DictReader(_fh)}
SUMMARY = ("Raw PGS005206 weighted sums were computed for 20 synthetic individuals using all 81 variants; "
           "the score measures total-body BMD. No clinical interpretation is made.")


def D(action, **args):
    return json.dumps({"observation": "scripted", "task_definition": None, "options_considered": [],
                       "selected_action": action, "action_arguments": args, "decision_justification": "scripted test"})


class Run:
    def __init__(self, phenotype="total-body BMD", permute=None, hooks=None):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "inputs").mkdir()
        dst = self.dir / "inputs/dosages.tsv"
        shutil.copy2(AUTH, dst)
        if permute:
            lines = dst.read_text().splitlines(keepends=True)
            com = [l for l in lines if l.startswith("#")]
            body = [l.rstrip("\n").split("\t") for l in lines if not l.startswith("#")]
            order = [body[0].index(c) for c in permute]
            dst.write_text("".join(com) + "".join("\t".join(r[i] for i in order) + "\n" for r in body))
        self.ctrl = Controller.create(self.dir, "RTEST", "test request", phenotype, ["PGS005206"],
                                      {"genotype_artifact": "inputs/dosages.tsv"})
        self.ctrl.hooks = hooks or {}
        self.ctrl.packet()
        self.n = 0

    def do(self, reply: str) -> dict:
        self.n += 1
        p = self.dir / "decisions" / f"reply_{self.n:03d}.txt"
        p.parent.mkdir(exist_ok=True)
        p.write_text(reply)
        return self.ctrl.apply_decision(p, {"latency_ms": 0, "planner_tool_uses": 0})

    def close(self):
        shutil.rmtree(self.dir)


GENO = "inputs/dosages.tsv"
PREFIX = [D("inspect_score_metadata", pgs_id="PGS005206"), D("assess_phenotype_compatibility", pgs_id="PGS005206"),
          D("inspect_variant_coverage", genotype_artifact=GENO, pgs_id="PGS005206"), D("verify_checksum", pgs_id="PGS005206")]


def released(run):
    with open(run.dir / "released/prs_scores.csv") as fh:
        return {r["IID"]: r["score"] for r in csv.DictReader(fh)}


class EventLogTests(unittest.TestCase):
    def test_chain_detects_tampering(self):
        d = Path(tempfile.mkdtemp())
        log = EventLog(d / "e.jsonl")
        for i in range(3):
            log.append(actor_kind="deterministic_controller", event_type="state_transition", observations={"i": i})
        self.assertTrue(verify_chain(d / "e.jsonl")[0])
        lines = (d / "e.jsonl").read_text().splitlines()
        lines[1] = lines[1].replace('"i": 1', '"i": 9')
        (d / "e.jsonl").write_text("\n".join(lines) + "\n")
        self.assertFalse(verify_chain(d / "e.jsonl")[0])
        shutil.rmtree(d)

    def test_illegal_transition(self):
        with self.assertRaises(S.IllegalTransition):
            S.check_transition(S.INITIALIZED, S.COMPLETED)
        with self.assertRaises(S.IllegalTransition):
            S.check_transition(S.ABSTAINED, S.EXECUTING)


class ScriptedPaths(unittest.TestCase):
    def tearDown(self):
        self.run.close()

    def test_compatible_path_completes_and_matches_stage2(self):
        self.run = r = Run()
        for x in PREFIX + [D("approve_plan", plan=["score"]), D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206")]:
            r.do(x)
        out = r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
                     phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        self.assertEqual(out["terminal"], S.COMPLETED, json.dumps(r.ctrl.st["critic_verdicts"], indent=1))
        self.assertEqual(released(r), REF)
        self.assertTrue(verify_chain(r.dir / "events.jsonl")[0])

    def test_permuted_columns_repair_then_complete(self):
        hdr = AUTH.read_text().splitlines()[2].split("\t")
        perm = list(reversed(hdr))
        self.run = r = Run(permute=perm)
        sha0 = sha256_file(r.dir / GENO)
        for x in PREFIX:
            r.do(x)
        cov = json.loads((r.dir / r.ctrl.ctx.assessments[f"coverage:{GENO}"]).read_text())
        self.assertIn("COLUMN_ORDER_NONCANONICAL", [i["code"] for i in cov["issues"]])
        self.assertFalse(cov["readable_by_stage2_scorer"])
        r.do(D("approve_plan", plan=["try"]))
        res = r.do(D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206"))
        self.assertEqual(r.ctrl.st["last_result"]["error_code"], "GENOTYPE_SCHEMA_ERROR")
        r.do(D("repair_column_order", genotype_artifact=GENO))
        new = r.ctrl.st["current_genotype"]
        self.assertTrue(new.startswith("derived/"))
        r.do(D("inspect_variant_coverage", genotype_artifact=new, pgs_id="PGS005206"))
        r.do(D("approve_plan", plan=["score repaired"]))
        r.do(D("calculate_prs", genotype_artifact=new, pgs_id="PGS005206"))
        out = r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
                     phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        self.assertEqual(out["terminal"], S.COMPLETED, json.dumps(r.ctrl.st["critic_verdicts"], indent=1))
        self.assertEqual(released(r), REF)
        self.assertEqual(sha256_file(r.dir / GENO), sha0)
        self.assertEqual(r.ctrl.st["recovery_cycles"], 1)

    def test_phenotype_mismatch_blocks_release(self):
        self.run = r = Run(phenotype="total-hip BMD")
        for x in PREFIX:
            r.do(x)
        self.assertEqual(r.ctrl.st["last_result"]["action"], "verify_checksum")
        pa = json.loads((r.dir / r.ctrl.ctx.assessments["phenotype:PGS005206"]).read_text())
        self.assertEqual(pa["scientific_suitability"]["site_correspondence"], "mismatch")
        r.do(D("approve_plan", plan=["x"]))
        r.do(D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206"))
        r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
               phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        v = r.ctrl.st["critic_verdicts"][-1]
        self.assertEqual(v["judgment"], "FAIL")
        self.assertIn("V6b_request_phenotype_correspondence", v["failed_criteria"])
        self.assertFalse(v["retry_allowed"])
        r.do(D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206"))
        r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_2.csv", pgs_id="PGS005206",
               phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        self.assertEqual(r.ctrl.st["last_rejection"]["action"], "submit_for_validation")
        out = r.do(D("abstain", reason="phenotype mismatch"))
        self.assertEqual(out["terminal"], S.ABSTAINED)
        self.assertFalse((r.dir / "released").exists())

    def test_corrupted_output_fail_then_recalculate(self):
        def corrupt(run_dir, res, seen=[0]):
            seen[0] += 1
            if seen[0] == 1:
                p = run_dir / res.data["scores_artifact"]
                p.write_text(p.read_text().replace("SYN11,PGS005206,-0.790", "SYN11,PGS005206,-0.709"))
        self.run = r = Run(hooks={"calculate_prs": corrupt})
        for x in PREFIX + [D("approve_plan", plan=["s"]), D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206")]:
            r.do(x)
        r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
               phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        v = r.ctrl.st["critic_verdicts"][-1]
        self.assertEqual(v["judgment"], "FAIL")
        self.assertTrue({"V4_output_integrity", "V5_independent_numerical_agreement"} <= set(v["failed_criteria"]))
        self.assertTrue(v["retry_allowed"])
        r.do(D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206"))
        out = r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_2.csv", pgs_id="PGS005206",
                     phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        self.assertEqual(out["terminal"], S.COMPLETED)
        self.assertEqual(released(r), REF)
        self.assertEqual(r.ctrl.st["recovery_cycles"], 1)


class ControllerRules(unittest.TestCase):
    def tearDown(self):
        self.run.close()

    def test_rejections_and_invalid_streak(self):
        self.run = r = Run()
        r.do(D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206"))
        self.assertIn("approved plan", r.ctrl.st["last_rejection"]["reason"])
        r.do(D("launch_rockets"))
        self.assertIn("unknown action", r.ctrl.st["last_rejection"]["reason"])
        out = r.do("not json")
        self.assertEqual(out["terminal"], S.FAILED)
        events = [json.loads(l) for l in (r.dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["event_type"] for e in events].count("tool_execution"), 0)

    def test_forbidden_claim_fails_and_can_be_revised(self):
        self.run = r = Run()
        for x in PREFIX + [D("approve_plan", plan=["s"]), D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206")]:
            r.do(x)
        r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
               phenotype_reported="total-body BMD", fulfils_request=True,
               summary=SUMMARY + " SYN05 is in the 5th percentile and at high risk."))
        v = r.ctrl.st["critic_verdicts"][-1]
        self.assertEqual(v["failed_criteria"], ["V7_claims_supported"])
        r.do(D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206"))
        out = r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_2.csv", pgs_id="PGS005206",
                     phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        self.assertEqual(out["terminal"], S.COMPLETED)

    def test_amendment2_string_boolean_rejected_by_controller(self):
        self.run = r = Run()
        for x in PREFIX + [D("approve_plan", plan=["s"]), D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206")]:
            r.do(x)
        r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
               phenotype_reported="total-body BMD", fulfils_request="true", summary=SUMMARY))
        self.assertIn("JSON boolean", r.ctrl.st["last_rejection"]["reason"])
        self.assertEqual(r.ctrl.st["critic_verdicts"], [])
        out = r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
                     phenotype_reported="total-body BMD", fulfils_request=True, summary=SUMMARY))
        self.assertEqual(out["terminal"], S.COMPLETED)

    def test_amendment2_false_claim_with_matching_sites_is_retryable(self):
        self.run = r = Run()
        for x in PREFIX + [D("approve_plan", plan=["s"]), D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206")]:
            r.do(x)
        r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
               phenotype_reported="total-body BMD", fulfils_request=False, summary=SUMMARY))
        v = r.ctrl.st["critic_verdicts"][-1]
        self.assertEqual((v["failed_criteria"], v["retry_allowed"]), (["V6b_request_phenotype_correspondence"], True))

    def test_amendment2_numbers_from_logged_evidence_allowed(self):
        self.run = r = Run()
        for x in PREFIX + [D("approve_plan", plan=["s"]), D("calculate_prs", genotype_artifact=GENO, pgs_id="PGS005206")]:
            r.do(x)
        out = r.do(D("submit_for_validation", scores_artifact="artifacts/prs_scores_1.csv", pgs_id="PGS005206",
                     phenotype_reported="total-body BMD", fulfils_request=True,
                     summary=SUMMARY + " The only evaluation cohort had mean age 9.77 years; SYN01 scored -0.320."))
        self.assertEqual(out["terminal"], S.COMPLETED, json.dumps(r.ctrl.st["critic_verdicts"]))

    def test_corrective_tools_refuse_without_precondition(self):
        self.run = r = Run()
        r.do(PREFIX[0])
        r.do(D("repair_column_order", genotype_artifact=GENO))
        self.assertEqual(r.ctrl.st["last_result"]["error_code"], "REPAIR_PRECONDITION_FAILED")
        p = r.dir / GENO
        p.write_text(p.read_text().replace("\t2\t", "\t1\t", 1))
        r.do(D("regenerate_authorized_test_input", genotype_artifact=GENO))
        self.assertEqual(r.ctrl.st["last_result"]["error_code"], "INPUT_NOT_AUTHORIZED_SET")


if __name__ == "__main__":
    unittest.main()
