"""Stateful controller connecting the model-driven Planner to deterministic specialists.

Each Planner turn, in this order:
  1. relay event: Claude Code delivered packet N and received the reply (verbatim file + SHA-256)
  2. llm_decision event: the reply as recorded, before anything runs
  3. deterministic_rule event: parse and authorization check (accept or reject, with reason)
  4. tool_execution / verification_judgment events: only for an accepted action
  5. state_transition events
  6. the next packet (or a terminal report)

The controller holds no scientific judgment. It enforces the state machine,
preconditions, retry bounds and the Critic's authority.
"""

from __future__ import annotations

import csv
import json
import shutil
import time
from pathlib import Path
from typing import Callable

from ..agents import evidence, planner, population_context, prs_methods, validation_critic
from ..agents.common import RunContext
from . import state as S
from .event_log import EventLog, read_events, sha256_file, utcnow
from .tool_registry import ToolRegistry, ToolResult, ToolSpec

MAX_DECISIONS = 14
MAX_RECOVERY_CYCLES = 2
MAX_INVALID_STREAK = 3
PLANNER_ID = "Planner"


def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    E, P, M = evidence.AGENT_ID, population_context.AGENT_ID, prs_methods.AGENT_ID
    for spec in [
        ToolSpec("inspect_score_metadata", E, "Retrieve PGS Catalog score, performance and source-GWAS records with provenance.",
                 {"pgs_id": "PGS Catalog score ID"}, evidence.inspect_score_metadata),
        ToolSpec("search_alternative_scores", E, "Text search of the full PGS Catalog score index (all terms must match).",
                 {"terms": "list of search terms"}, evidence.search_alternative_scores),
        ToolSpec("assess_phenotype_compatibility", P, "Compare requested phenotype with the score's phenotype evidence; "
                 "report technical compatibility, scientific suitability evidence and predictive-validity status separately.",
                 {"pgs_id": "score ID with an evidence record"}, population_context.assess_phenotype_compatibility),
        ToolSpec("inspect_variant_coverage", P, "Inspect a genotype file by header names: layout, variant matching, coverage, invalid values.",
                 {"genotype_artifact": "run-relative path", "pgs_id": "score ID"}, population_context.inspect_variant_coverage),
        ToolSpec("validate_effect_alleles", P, "Check effect alleles in a genotype file against the scoring file.",
                 {"genotype_artifact": "run-relative path", "pgs_id": "score ID"}, population_context.validate_effect_alleles),
        ToolSpec("select_alternative_eligible_score", P, "Check whether another score may replace the provided one without "
                 "researcher approval (requires exact phenotype correspondence and an approved pinned file).",
                 {"pgs_id": "candidate score ID"}, population_context.select_alternative_eligible_score),
        ToolSpec("verify_checksum", M, "Verify the scoring file against its approved SHA-256 pin.",
                 {"pgs_id": "score ID"}, prs_methods.verify_checksum),
        ToolSpec("calculate_prs", M, "Run the validated Stage 2 scorer (strict reader, exact arithmetic, DR-0002 QC).",
                 {"genotype_artifact": "run-relative path", "pgs_id": "score ID"}, prs_methods.calculate_prs),
        ToolSpec("repair_column_order", M, "Rewrite a genotype table into canonical column order using header names only; "
                 "verifies every cell is unchanged; original left untouched.",
                 {"genotype_artifact": "run-relative path"}, prs_methods.repair_column_order, corrective=True),
        ToolSpec("regenerate_authorized_test_input", M, "Restore the authorized synthetic test file from its seed, only if the "
                 "given file is cell-identical to it; verifies the authorized checksum.",
                 {"genotype_artifact": "run-relative path"}, prs_methods.regenerate_authorized_test_input, corrective=True),
    ]:
        r.register(spec)
    return r


CONTROL_ACTIONS = {
    "approve_plan": ("Commit to a scoring plan once eligibility checks for the current score and genotype file are complete.",
                     {"plan": "list of planned steps"}),
    "submit_for_validation": ("Submit scores for independent review by the Validation Critic (PASS releases them).",
                              {"scores_artifact": "run-relative path from calculate_prs", "pgs_id": "score ID",
                               "phenotype_reported": "the score's actual phenotype",
                               "fulfils_request": "JSON boolean true or false (not a string)",
                               "summary": "short factual paragraph"}),
    "request_human_review": ("Stop and ask the researcher to decide (terminal).", {"question": "what the researcher must decide"}),
    "abstain": ("Stop without releasing results (terminal).", {"reason": "evidence-based reason"}),
}


class Controller:
    def __init__(self, run_dir: Path, post_tool_hooks: dict[str, Callable] | None = None):
        self.run_dir = Path(run_dir)
        self.st = json.loads((self.run_dir / "state.json").read_text())
        self.log = EventLog(self.run_dir / "events.jsonl")
        self.registry = build_registry()
        self.hooks = post_tool_hooks or {}
        self.ctx = RunContext(self.run_dir, self.st["request"], self.st["requested_phenotype"], self.st["provided_scores"],
                              self.st["inputs"], evidence=self.st["evidence"], assessments=self.st["assessments"])

    # ---------------------------------------------------------------- creation
    @classmethod
    def create(cls, run_dir: Path, run_id: str, request: str, requested_phenotype: str, provided_scores: list[str],
               inputs: dict[str, str]) -> "Controller":
        run_dir = Path(run_dir)
        for d in ("artifacts", "packets", "decisions", "critic"):
            (run_dir / d).mkdir(parents=True, exist_ok=True)
        st = {"run_id": run_id, "task_id": f"{run_id}-T1", "request": request, "requested_phenotype": requested_phenotype,
              "provided_scores": provided_scores, "inputs": inputs, "state": S.INITIALIZED, "step": 0, "packet": 0,
              "decisions": 0, "invalid_streak": 0, "recovery_cycles": 0, "in_recovery": False, "pending_problem": False,
              "plan_approved": False, "checksum_verified": {}, "current_genotype": inputs["genotype_artifact"],
              "current_score": provided_scores[0], "last_scores": None, "blocked_submissions": [], "critic_verdicts": [],
              "history": [], "last_result": None, "last_rejection": None, "task_definition": None,
              "evidence": {}, "assessments": {}, "terminal": None, "started_at": utcnow(), "t0": time.time()}
        (run_dir / "state.json").write_text(json.dumps(st, indent=2))
        c = cls(run_dir)
        c.log.append(run_id=run_id, task_id=st["task_id"], step_id="S000", agent_id="Controller",
                     actor_kind="deterministic_controller", event_type="run_start", current_task=request,
                     observations={"input_artifacts": [{"path": p, "sha256": sha256_file(run_dir / p)} for p in inputs.values()],
                                   "provided_scores": provided_scores, "planner_prompt_version": planner.PROMPT_VERSION,
                                   "planner_instructions_sha256": planner.instructions_sha256()},
                     validation_status="n/a")
        return c

    def save(self) -> None:
        self.st["evidence"], self.st["assessments"] = self.ctx.evidence, self.ctx.assessments
        (self.run_dir / "state.json").write_text(json.dumps(self.st, indent=2, default=str))

    # ---------------------------------------------------------------- helpers
    def _ev(self, **kw) -> dict:
        return self.log.append(run_id=self.st["run_id"], task_id=self.st["task_id"], step_id=self.step_id, **kw)

    @property
    def step_id(self) -> str:
        return f"S{self.st['step']:03d}"

    def _transition(self, dst: str, why: str) -> None:
        src = self.st["state"]
        if src == dst:
            return
        S.check_transition(src, dst)
        self.st["state"] = dst
        self._ev(agent_id="Controller", actor_kind="deterministic_controller", event_type="state_transition",
                 observations={"from": src, "to": dst}, decision_justification=why)

    def _eligibility_complete(self) -> bool:
        a = self.ctx.assessments
        return f"phenotype:{self.st['current_score']}" in a and f"coverage:{self.st['current_genotype']}" in a

    def _precondition(self, action: str, args: dict) -> str | None:
        st = self.st
        if st["state"] in S.TERMINAL:
            return "run is terminal"
        has_evidence = bool(self.ctx.evidence)
        if action in ("search_alternative_scores", "assess_phenotype_compatibility", "inspect_variant_coverage",
                      "validate_effect_alleles", "select_alternative_eligible_score", "verify_checksum",
                      "repair_column_order", "regenerate_authorized_test_input") and not has_evidence:
            return "requires an evidence record (inspect_score_metadata) first"
        corrective = (action in self.registry and self.registry.get(action).corrective) or \
                     (action == "calculate_prs" and st["pending_problem"])
        if corrective and not st["in_recovery"] and st["recovery_cycles"] >= MAX_RECOVERY_CYCLES:
            return f"recovery limit reached ({MAX_RECOVERY_CYCLES} cycles)"
        if action == "approve_plan" and not self._eligibility_complete():
            return ("requires phenotype assessment for the current score and coverage inspection for the current "
                    f"genotype artifact ({st['current_genotype']})")
        if action == "calculate_prs":
            if not st["plan_approved"]:
                return "requires an approved plan for the current inputs"
            if not st["checksum_verified"].get(args.get("pgs_id", st["current_score"])):
                return "requires verify_checksum for this score in this run"
            if st["state"] not in (S.PLAN_APPROVED, S.EXECUTING, S.REPLAN_REQUIRED):
                return f"not permitted in state {st['state']}"
        if action == "submit_for_validation":
            if not st["last_scores"]:
                return "requires a successful calculate_prs"
            if st["state"] != S.EXECUTING:
                return "submit only after a fresh calculate_prs (state EXECUTING)"
            if st["last_scores"]["pgs_id"] in st["blocked_submissions"]:
                return "the Critic ruled that this score cannot be released for this request (retry not allowed)"
        return None

    def permitted(self) -> tuple[list[dict], list[dict]]:
        allowed, blocked = [], []
        for name in self.registry.names() + list(CONTROL_ACTIONS):
            if name in self.registry:
                spec = self.registry.get(name)
                desc, args = spec.description, spec.arguments
            else:
                desc, args = CONTROL_ACTIONS[name]
            why = self._precondition(name, {})
            (blocked if why else allowed).append({"action": name, "description": desc, "arguments": args} if not why
                                                 else {"action": name, "reason": why})
        return allowed, blocked

    # ---------------------------------------------------------------- packets
    def packet(self) -> Path:
        self.st["packet"] += 1
        allowed, blocked = self.permitted()
        last = self.st["last_result"]
        p = {
            "packet_number": self.st["packet"], "run_id": self.st["run_id"],
            "researcher_request": self.st["request"],
            "provided_inputs": {"genotype_artifact": self.st["inputs"]["genotype_artifact"], "provided_scores": self.st["provided_scores"]},
            "current_genotype_artifact": self.st["current_genotype"], "current_score": self.st["current_score"],
            "workflow_state": self.st["state"],
            "budgets": {"decisions_used": self.st["decisions"], "max_decisions": MAX_DECISIONS,
                        "recovery_cycles_used": self.st["recovery_cycles"], "max_recovery_cycles": MAX_RECOVERY_CYCLES},
            "permitted_actions": allowed, "not_permitted_now": blocked,
            "last_action_result": last, "last_decision_rejected": self.st["last_rejection"],
            "critic_feedback": self.st["critic_verdicts"][-1] if self.st["critic_verdicts"] else None,
            "history": self.st["history"],
        }
        path = self.run_dir / "packets" / f"packet_{self.st['packet']:03d}.json"
        path.write_text(json.dumps(p, indent=1, default=str))
        self.save()
        return path

    # ---------------------------------------------------------------- one Planner turn
    def apply_decision(self, reply_path: Path, relay_meta: dict) -> dict:
        st = self.st
        st["step"] += 1
        reply_text = Path(reply_path).read_text()
        packet_path = self.run_dir / "packets" / f"packet_{st['packet']:03d}.json"
        self._ev(agent_id="ClaudeCodeRelay", actor_kind="claude_code_relay", event_type="relay",
                 current_task="deliver packet to Planner subagent and return its reply verbatim",
                 observations={"packet": {"path": str(packet_path.relative_to(self.run_dir)), "sha256": sha256_file(packet_path)},
                               "reply": {"path": str(Path(reply_path).resolve().relative_to(self.run_dir.resolve())), "sha256": sha256_file(reply_path)},
                               **{k: relay_meta.get(k) for k in ("subagent_id", "model", "latency_ms", "total_tokens", "planner_tool_uses")}},
                 duration_seconds=(relay_meta.get("latency_ms") or 0) / 1000 or None)
        try:
            d = planner.parse_decision(reply_text)
        except planner.DecisionParseError as e:
            d, parse_err = None, str(e)
        else:
            parse_err = None
        self._ev(agent_id=PLANNER_ID, actor_kind="model_driven_agent", event_type="llm_decision",
                 current_task=(d or {}).get("observation"), observations={"reply_sha256": sha256_file(reply_path),
                 "task_definition": (d or {}).get("task_definition"), "expected_result": (d or {}).get("expected_result"),
                 "parse_error": parse_err},
                 proposed_actions=(d or {}).get("options_considered"), selected_action=(d or {}).get("selected_action"),
                 tool_arguments_ref=(d or {}).get("action_arguments"), decision_justification=(d or {}).get("decision_justification"),
                 available_actions=[a["action"] for a in self.permitted()[0]])
        st["decisions"] += 1
        if d and d.get("task_definition") and not st["task_definition"]:
            st["task_definition"] = d["task_definition"]
        action = (d or {}).get("selected_action")
        args = (d or {}).get("action_arguments") or {}
        reason = parse_err
        if reason is None:
            if action not in self.registry and action not in CONTROL_ACTIONS:
                reason = f"unknown action {action!r}"
            else:
                expected = self.registry.get(action).arguments if action in self.registry else CONTROL_ACTIONS[action][1]
                if set(args) != set(expected):
                    reason = f"arguments {sorted(args)} != required {sorted(expected)}"
                elif action == "submit_for_validation" and not isinstance(args.get("fulfils_request"), bool):
                    # Amendment 2 (DR-0004): type check at authorization so the Planner can correct it.
                    reason = "fulfils_request must be a JSON boolean (true or false), not a string"
                else:
                    reason = self._precondition(action, args)
        self._ev(agent_id="Controller", actor_kind="deterministic_controller", event_type="deterministic_rule",
                 selected_action=action, validation_status="rejected" if reason else "authorized",
                 decision_justification=reason or "action permitted in current state with valid arguments")
        if reason:
            st["invalid_streak"] += 1
            st["last_rejection"] = {"action": action, "reason": reason}
            st["history"].append({"step": self.step_id, "action": action, "status": "rejected_by_controller", "reason": reason})
            if st["invalid_streak"] >= MAX_INVALID_STREAK:
                return self._terminal(S.FAILED, f"{MAX_INVALID_STREAK} consecutive invalid decisions")
            return self._after_turn()
        st["invalid_streak"], st["last_rejection"] = 0, None
        if action in self.registry:
            self._run_tool(action, args)
        else:
            r = self._control(action, args, d)
            if r is not None:
                return r
        return self._after_turn()

    def _after_turn(self) -> dict:
        if self.st["state"] in S.TERMINAL:
            return {"terminal": self.st["state"]}
        if self.st["decisions"] >= MAX_DECISIONS:
            return self._terminal(S.FAILED, f"decision budget of {MAX_DECISIONS} exhausted")
        return {"next_packet": str(self.packet())}

    def _start_recovery_if_corrective(self, action: str) -> None:
        st = self.st
        corrective = (action in self.registry and self.registry.get(action).corrective) or \
                     (action == "calculate_prs" and st["pending_problem"])
        if corrective and not st["in_recovery"]:
            st["recovery_cycles"] += 1
            st["in_recovery"] = True
            st["pending_problem"] = False
            self._ev(agent_id="Controller", actor_kind="deterministic_controller", event_type="deterministic_rule",
                     selected_action=action, retry_count=st["recovery_cycles"],
                     decision_justification=f"recovery cycle {st['recovery_cycles']} of {MAX_RECOVERY_CYCLES} started")

    def _run_tool(self, action: str, args: dict) -> None:
        st = self.st
        self._start_recovery_if_corrective(action)
        if action == "calculate_prs":
            self._transition(S.EXECUTING, "calculate_prs authorized")
        res = self.registry.execute(action, args, ctx=self.ctx, log=self.log, run_id=st["run_id"], task_id=st["task_id"],
                                    step_id=self.step_id, artifacts_dir=self.run_dir / "artifacts",
                                    retry_count=st["recovery_cycles"], invoked_by=PLANNER_ID)
        if res.status == "ok" and action in self.hooks:     # harness fault injection (logged only in the hidden harness log)
            self.hooks[action](self.run_dir, res)
        if action == "inspect_score_metadata" and res.status == "ok" and st["state"] in (S.INITIALIZED, S.REPLAN_REQUIRED):
            self._transition(S.EVIDENCE_RETRIEVED, "score evidence retrieved")
        if action == "verify_checksum" and res.status == "ok":
            st["checksum_verified"][args["pgs_id"]] = True
        if action in ("repair_column_order", "regenerate_authorized_test_input") and res.status == "ok":
            new = res.data.get("repaired_artifact") or res.data.get("regenerated_artifact")
            st["current_genotype"], st["plan_approved"] = new, False
            if st["state"] in (S.ELIGIBILITY_CHECKED, S.PLAN_APPROVED):
                self._transition(S.EVIDENCE_RETRIEVED, "genotype artifact replaced; eligibility must be re-checked")
        if action in ("assess_phenotype_compatibility", "inspect_variant_coverage") and res.status == "ok" \
                and self._eligibility_complete() and st["state"] in (S.EVIDENCE_RETRIEVED, S.REPLAN_REQUIRED):
            self._transition(S.ELIGIBILITY_CHECKED, "phenotype and coverage assessments complete for current inputs")
        if action == "inspect_variant_coverage" and res.status == "ok" and res.data.get("issues"):
            st["pending_problem"] = True
        if action == "calculate_prs":
            if res.status == "ok":
                st["last_scores"] = {"scores_artifact": res.data["scores_artifact"], "pgs_id": args["pgs_id"]}
            else:
                st["pending_problem"] = True
                self._transition(S.REPLAN_REQUIRED, f"calculate_prs failed: {res.error_code}")
        st["last_result"] = {"step": self.step_id, "action": action, "arguments": args, "status": res.status,
                             "error_code": res.error_code, "data": res.data}
        st["history"].append({"step": self.step_id, "action": action, "arguments": args, "status": res.status,
                              "error_code": res.error_code})

    def _control(self, action: str, args: dict, d: dict) -> dict | None:
        st = self.st
        if action == "approve_plan":
            st["plan_approved"] = True
            self._transition(S.PLAN_APPROVED, "Planner committed to plan; eligibility checks complete")
            st["last_result"] = {"step": self.step_id, "action": action, "status": "ok", "data": {"plan": args["plan"]}}
            st["history"].append({"step": self.step_id, "action": action, "status": "ok"})
            (self.run_dir / "artifacts" / f"{self.step_id}_plan.json").write_text(json.dumps(args, indent=2))
            return None
        if action == "submit_for_validation":
            self._transition(S.VALIDATING, "submitted to Validation Critic")
            sub = dict(args)
            sub_path = self.run_dir / "critic" / f"{self.step_id}_submission.json"
            sub_path.write_text(json.dumps(sub, indent=2))
            t0 = time.perf_counter()
            verdict = validation_critic.review(self.run_dir, {"requested_phenotype": st["requested_phenotype"], "request": st["request"]},
                                               sub, read_events(self.run_dir / "events.jsonl"),
                                               self.run_dir / "critic" / f"{self.step_id}_verdict.json")
            vpath = self.run_dir / "critic" / f"{self.step_id}_verdict.json"
            self._ev(agent_id=validation_critic.AGENT_ID, actor_kind="deterministic_specialist", event_type="verification_judgment",
                     tool_name="independently_verify_prs",
                     tool_arguments_ref={"path": str(sub_path.relative_to(self.run_dir)), "sha256": sha256_file(sub_path)},
                     tool_result_ref={"path": str(vpath.relative_to(self.run_dir)), "sha256": sha256_file(vpath)},
                     validation_status=verdict["judgment"],
                     observations={"failed_criteria": verdict.get("failed_criteria"), "retry_allowed": verdict.get("retry_allowed"),
                                   "missing_evidence": verdict.get("missing_evidence")},
                     duration_seconds=round(time.perf_counter() - t0, 6), retry_count=st["recovery_cycles"])
            st["in_recovery"] = False
            brief = {"step": self.step_id, "judgment": verdict["judgment"], "failed_criteria": verdict.get("failed_criteria"),
                     "retry_allowed": verdict.get("retry_allowed"), "remediation": verdict.get("remediation"),
                     "missing_evidence": verdict.get("missing_evidence"),
                     "failed_evidence": [c["evidence"] for c in verdict.get("checks", []) if c["status"] != "PASS"]}
            st["critic_verdicts"].append(brief)
            st["history"].append({"step": self.step_id, "action": action, "status": verdict["judgment"]})
            st["last_result"] = {"step": self.step_id, "action": action, "status": verdict["judgment"], "data": brief}
            if verdict["judgment"] == "PASS":
                self._transition(S.COMPLETED, "Critic PASS")
                rel = self.run_dir / "released"
                rel.mkdir(exist_ok=True)
                shutil.copy2(self.run_dir / sub["scores_artifact"], rel / "prs_scores.csv")
                (rel / "summary.json").write_text(json.dumps(sub, indent=2))
                return self._terminal(S.COMPLETED, "validated", already=True)
            st["pending_problem"] = True
            if verdict.get("retry_allowed") is False:
                st["blocked_submissions"].append(sub.get("pgs_id"))
            st["last_scores"] = None
            self._transition(S.REPLAN_REQUIRED, f"Critic {verdict['judgment']}: {verdict.get('failed_criteria') or verdict.get('missing_evidence')}")
            return None
        if action == "request_human_review":
            st["history"].append({"step": self.step_id, "action": action, "status": "ok"})
            (self.run_dir / "human_review_request.json").write_text(json.dumps({"question": args["question"],
                "justification": d.get("decision_justification"), "requested_at": utcnow()}, indent=2))
            return self._terminal(S.REQUIRES_HUMAN_REVIEW, args["question"])
        if action == "abstain":
            st["history"].append({"step": self.step_id, "action": action, "status": "ok"})
            return self._terminal(S.ABSTAINED, args["reason"])
        raise AssertionError(action)

    # ---------------------------------------------------------------- end of run
    def _terminal(self, final: str, reason: str, already: bool = False) -> dict:
        if not already:
            self._transition(final, reason)
        st = self.st
        events = read_events(self.run_dir / "events.jsonl")
        tools = [e for e in events if e["event_type"] == "tool_execution"]
        relays = [e for e in events if e["event_type"] == "relay"]
        outcome = {
            "run_id": st["run_id"], "final_state": final, "reason": reason, "released": final == S.COMPLETED,
            "n_planner_decisions": st["decisions"], "n_tool_executions": len(tools),
            "n_critic_reviews": len(st["critic_verdicts"]), "critic_judgments": [v["judgment"] for v in st["critic_verdicts"]],
            "recovery_cycles": st["recovery_cycles"], "action_sequence": [h["action"] for h in st["history"]],
            "tool_time_s": round(sum(e["duration_seconds"] or 0 for e in tools), 4),
            "relay_latency_s": round(sum((e["observations"].get("latency_ms") or 0) for e in relays) / 1000, 2),
            "planner_total_tokens": sum((e["observations"].get("total_tokens") or 0) for e in relays) or None,
            "planner_tool_uses": sum((e["observations"].get("planner_tool_uses") or 0) for e in relays),
            "started_at": st["started_at"], "finished_at": utcnow(),
            "task_definition": st["task_definition"],
        }
        self._ev(agent_id="Controller", actor_kind="deterministic_controller", event_type="run_end", observations=outcome,
                 validation_status=final)
        st["terminal"] = outcome
        (self.run_dir / "outcome.json").write_text(json.dumps(outcome, indent=2))
        self._write_report(outcome)
        self.save()
        return {"terminal": final, "outcome": outcome}

    def _write_report(self, o: dict) -> None:
        st = self.st
        lines = [f"# PRSWeave run {st['run_id']}", "", f"**Request:** {st['request']}", "",
                 f"**Final state:** {o['final_state']}. {o['reason']}", "",
                 f"Planner decisions: {o['n_planner_decisions']}; tool executions: {o['n_tool_executions']}; "
                 f"Critic reviews: {o['n_critic_reviews']} {o['critic_judgments']}; recovery cycles: {o['recovery_cycles']}.", "",
                 "## Decision sequence", "", "| Step | Action | Status |", "|---|---|---|"]
        lines += [f"| {h['step']} | {h['action']} | {h['status']}{' (' + h['error_code'] + ')' if h.get('error_code') else ''} |"
                  for h in st["history"]]
        if o["released"]:
            sub = json.loads((self.run_dir / "released/summary.json").read_text())
            lines += ["", "## Planner summary (verified by the Critic)", "", sub["summary"], "", "## Released scores", "",
                      "| IID | Score | Variants used | QC |", "|---|---|---|---|"]
            with open(self.run_dir / "released/prs_scores.csv") as fh:
                lines += [f"| {r['IID']} | {r['score']} | {r['n_variants_used']}/{r['n_variants_total']} | {r['qc_status']} |"
                          for r in csv.DictReader(fh)]
        lines += ["", "## Fixed limitations", "",
                  "- Genotypes are synthetic effect-allele dosages; no ancestry, phenotype or real allele harmonization.",
                  "- PGS005206 is a total-body BMD score; nothing here is a hip-BMD result.",
                  "- Derivation of the published weights is partly unverified (DR-0002).",
                  "- Raw weighted sums only; no percentiles, risk categories or clinical meaning."]
        (self.run_dir / "final_report.md").write_text("\n".join(lines) + "\n")
