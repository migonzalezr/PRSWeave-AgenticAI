#!/usr/bin/env python3
"""Conventional baselines (pre-registered in baseline_spec.json). No model involved.

Both variants use the same tool functions, registry, event log, Critic and
inputs as PRSWeave runs, so the evaluator applies identical criteria. The only
difference is that a fixed rule sequence replaces the Planner.

Usage:
    python3 experiments/stage3/baseline.py            # all scenarios, both variants
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_experiments import REQUEST, build_inputs, harness_log, hooks_for, load_scenario  # noqa: E402
from prsweave.agents import validation_critic  # noqa: E402
from prsweave.agents.common import RunContext  # noqa: E402
from prsweave.orchestration.controller import build_registry  # noqa: E402
from prsweave.orchestration.event_log import EventLog, read_events, sha256_file, utcnow  # noqa: E402

OUT = ROOT / "results/stage3/baseline"
SUMMARY = ("Raw PGS005206 weighted sums for synthetic individuals; the score measures total-body BMD. "
           "No clinical interpretation is made.")


def run_variant(variant: str, sid: str) -> dict:
    sc = load_scenario(sid)
    run_dir = OUT / variant / f"scenario_{sid.lower()}"
    if run_dir.exists():
        shutil.rmtree(run_dir)        # baselines are deterministic; a rerun replaces only the baseline's own output
    for d in ("artifacts", "critic"):
        (run_dir / d).mkdir(parents=True)
    harness_log(run_dir, action="prepare", scenario_id=sid, variant=variant)
    inputs = build_inputs(sc, run_dir)
    run_id = f"BL-{variant}-{sid}"
    request = REQUEST.format(scores=", ".join(sc["provided_scores"]), phenotype=sc["requested_phenotype"])
    ctx = RunContext(run_dir, request, sc["requested_phenotype"], sc["provided_scores"], inputs)
    log = EventLog(run_dir / "events.jsonl")
    reg, hooks = build_registry(), hooks_for(sc, run_dir)
    pgs, geno = sc["provided_scores"][0], inputs["genotype_artifact"]
    log.append(run_id=run_id, step_id="S000", agent_id=variant, actor_kind="deterministic_controller", event_type="run_start",
               current_task=request, observations={"input_artifacts": [{"path": geno, "sha256": sha256_file(run_dir / geno)}]})
    t0, step, seq = time.perf_counter(), [0], []

    def tool(name, **args):
        step[0] += 1
        seq.append(name)
        r = reg.execute(name, args, ctx=ctx, log=log, run_id=run_id, task_id=run_id, step_id=f"S{step[0]:03d}",
                        artifacts_dir=run_dir / "artifacts", retry_count=0, invoked_by=variant)
        if r.status == "ok" and name in hooks:
            hooks[name](run_dir, r)
        return r

    def rule(text, outcome):
        log.append(run_id=run_id, step_id=f"S{step[0]:03d}", agent_id=variant, actor_kind="deterministic_controller",
                   event_type="deterministic_rule", decision_justification=text, validation_status=outcome)

    def review():
        step[0] += 1
        seq.append("submit_for_validation")
        sub = {"scores_artifact": last["scores_artifact"], "pgs_id": pgs, "phenotype_reported": "total-body BMD",
               "fulfils_request": True, "summary": SUMMARY}
        vp = run_dir / "critic" / f"S{step[0]:03d}_verdict.json"
        v = validation_critic.review(run_dir, {"requested_phenotype": sc["requested_phenotype"], "request": request}, sub,
                                     read_events(run_dir / "events.jsonl"), vp)
        log.append(run_id=run_id, step_id=f"S{step[0]:03d}", agent_id="ValidationCritic", actor_kind="deterministic_specialist",
                   event_type="verification_judgment", tool_name="independently_verify_prs", validation_status=v["judgment"],
                   tool_result_ref={"path": str(vp.relative_to(run_dir)), "sha256": sha256_file(vp)},
                   observations={"failed_criteria": v.get("failed_criteria")})
        return v

    final, reason, verdicts, last = None, "", [], None
    if tool("inspect_score_metadata", pgs_id=pgs).status != "ok":
        final, reason = "FAILED", "metadata unavailable"
    if not final:
        pa = tool("assess_phenotype_compatibility", pgs_id=pgs)
        if pa.data["scientific_suitability"]["site_correspondence"] != "exact":
            rule("fixed rule: requested skeletal site must equal the score's site", "ABSTAINED")
            final, reason = "ABSTAINED", f"site correspondence {pa.data['scientific_suitability']['site_correspondence']}"
    if not final and tool("verify_checksum", pgs_id=pgs).status != "ok":
        final, reason = "FAILED", "checksum mismatch"
    if not final and variant == "baseline_robust":
        cov = tool("inspect_variant_coverage", genotype_artifact=geno, pgs_id=pgs)
        codes = [i["code"] for i in cov.data["issues"]]
        if codes == ["COLUMN_ORDER_NONCANONICAL"]:
            rule("fixed rule: column order is the only issue and every required column is present once -> reorder by name", "repair")
            rep = tool("repair_column_order", genotype_artifact=geno)
            if rep.status == "ok":
                geno = rep.data["repaired_artifact"]
            else:
                final, reason = "FAILED", "repair failed"
    if not final:
        r = tool("calculate_prs", genotype_artifact=geno, pgs_id=pgs)
        if r.status != "ok":
            rule(f"fixed rule: scoring error {r.error_code} -> stop", "FAILED")
            final, reason = "FAILED", f"calculate_prs {r.error_code}"
        else:
            last = r.data
    if not final:
        v = review()
        verdicts.append(v["judgment"])
        if v["judgment"] != "PASS" and v.get("retry_allowed"):
            rule("fixed rule: one recomputation after a retryable verification failure", "retry")
            r = tool("calculate_prs", genotype_artifact=geno, pgs_id=pgs)
            last = r.data if r.status == "ok" else None
            v = review() if last else v
            verdicts.append(v["judgment"])
        final, reason = ("COMPLETED", "validated") if v["judgment"] == "PASS" else ("FAILED", f"verification {v['failed_criteria']}")
        if final == "COMPLETED":
            (run_dir / "released").mkdir()
            shutil.copy2(run_dir / last["scores_artifact"], run_dir / "released/prs_scores.csv")
            (run_dir / "released/summary.json").write_text(json.dumps({"summary": SUMMARY, "phenotype_reported": "total-body BMD"}))
    events = read_events(run_dir / "events.jsonl")
    outcome = {"run_id": run_id, "variant": variant, "scenario_id": sid, "final_state": final, "reason": reason,
               "released": final == "COMPLETED", "n_planner_decisions": 0, "n_model_calls": 0,
               "n_tool_executions": sum(e["event_type"] == "tool_execution" for e in events),
               "critic_judgments": verdicts, "action_sequence": seq, "runtime_s": round(time.perf_counter() - t0, 4),
               "finished_at": utcnow()}
    log.append(run_id=run_id, step_id=f"S{step[0]:03d}", agent_id=variant, actor_kind="deterministic_controller",
               event_type="run_end", observations=outcome, validation_status=final)
    (run_dir / "outcome.json").write_text(json.dumps(outcome, indent=2))
    return outcome


if __name__ == "__main__":
    for variant in ("baseline_strict", "baseline_robust"):
        for sid in "ABCD":
            o = run_variant(variant, sid)
            print(f"{variant:16s} {sid}: {o['final_state']:10s} tools={o['n_tool_executions']} critic={o['critic_judgments']} "
                  f"t={o['runtime_s']}s  {o['reason']}")
