#!/usr/bin/env python3
"""Build Stage 3 trace and figure artifacts from the graded results (standard library only).

Reads results/stage3/evaluation.json, which independent_evaluator.py writes, and the run logs. Writes:
  results/stage3/agent_decision_traces.jsonl   every Planner decision, with the outcome of the tool it selected
  results/stage3/decision_traces.md            one table per agentic run
  docs/figures/fig1_architecture.svg
  docs/figures/fig2_outcomes.svg
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R3 = ROOT / "results/stage3"
FIG = ROOT / "docs/figures"


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def traces(ev: dict) -> None:
    out, md = [], ["# Stage 3 decision traces", "",
                   "Generated from each run's events.jsonl. Planner text is quoted verbatim and abridged to 160 characters.", ""]
    for r in ev["runs"]:
        if r["kind"] != "agentic":
            continue
        run_dir = ROOT / r["run"]
        events = jl(run_dir / "events.jsonl")
        by_step: dict[str, dict] = {}
        for e in events:
            s = by_step.setdefault(e["step_id"], {})
            if e["event_type"] == "llm_decision":
                s["decision"] = e
            elif e["event_type"] == "deterministic_rule" and e.get("validation_status") in ("authorized", "rejected"):
                s["rule"] = e
            elif e["event_type"] == "tool_execution":
                s["tool"] = e
            elif e["event_type"] == "verification_judgment":
                s["verdict"] = e
        md += [f"## {r['run']} (scenario {r['scenario']}): {r['final_state']} [{r['outcome_class']}]", "",
               "| Step | Planner action | Controller | Result | Justification (abridged) |", "|---|---|---|---|---|"]
        for sid, s in sorted(by_step.items()):
            d = s.get("decision")
            if not d:
                continue
            res = (s.get("verdict") or {}).get("validation_status") or \
                  ((s.get("tool") or {}).get("observations") or {}).get("status") or "-"
            err = (s.get("tool") or {}).get("error_code")
            just = (d.get("decision_justification") or "").replace("|", "/")
            rec = {"run": r["run"], "scenario": r["scenario"], "step_id": sid, "selected_action": d.get("selected_action"),
                   "arguments": d.get("tool_arguments_ref"), "observation": d.get("current_task"),
                   "alternatives": [o.get("action") for o in (d.get("proposed_actions") or [])],
                   "decision_justification": d.get("decision_justification"),
                   "controller": (s.get("rule") or {}).get("validation_status"),
                   "tool_result": res, "error_code": err,
                   "critic_failed": ((s.get("verdict") or {}).get("observations") or {}).get("failed_criteria")}
            out.append(rec)
            md.append(f"| {sid} | {d.get('selected_action')} | {rec['controller']} | {res}{' ' + err if err else ''}"
                      f"{' ' + str(rec['critic_failed']) if rec['critic_failed'] else ''} | {just[:160]} |")
        md.append("")
    (R3 / "agent_decision_traces.jsonl").write_text("".join(json.dumps(x) + "\n" for x in out))
    (R3 / "decision_traces.md").write_text("\n".join(md) + "\n")


def svg(path: Path, w: int, h: int, body: list[str]) -> None:
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Helvetica,Arial,sans-serif" '
                    f'font-size="12">\n<rect width="{w}" height="{h}" fill="white"/>\n' + "\n".join(body) + "\n</svg>\n")


def box(x, y, w, h, label, sub, fill):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="#333"/>'
            f'<text x="{x + w / 2}" y="{y + h / 2 - 4}" text-anchor="middle" font-weight="bold">{label}</text>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + 12}" text-anchor="middle" font-size="10">{sub}</text>')


def arrow(x1, y1, x2, y2, dash=False):
    d = ' stroke-dasharray="5,4"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#333" stroke-width="1.5" marker-end="url(#a)"{d}/>'


def fig1() -> None:
    M, D, R = "#cfe2ff", "#e2f0d9", "#fff2cc"   # model-driven, deterministic, relay/human
    b = ['<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
         '<path d="M0,0 L8,4 L0,8 z" fill="#333"/></marker></defs>',
         '<text x="20" y="24" font-size="15" font-weight="bold">Figure 1. PRSWeave Stage 3 architecture (as implemented)</text>',
         box(20, 60, 130, 50, "Researcher", "request text only", R),
         box(200, 60, 170, 50, "Claude Code relay", "pastes packets verbatim", R),
         box(420, 50, 190, 70, "Planner", "Claude subagent (Sonnet)", M),
         box(660, 60, 180, 50, "Controller", "state machine + rules", D),
         box(560, 180, 150, 50, "Evidence Retrieval", "deterministic", D),
         box(720, 180, 150, 50, "Population Context", "deterministic", D),
         box(400, 180, 150, 50, "PRS Methods", "deterministic", D),
         box(420, 300, 330, 50, "Tool registry: 10 tools", "Stage 2 scorer, repair, regenerate, catalog cache", D),
         box(80, 300, 200, 60, "Validation Critic", "deterministic; independent scorer", D),
         box(80, 420, 200, 50, "Final report / release", "only on Critic PASS", D),
         box(420, 420, 330, 50, "Append-only hash-chained event log", "every decision, rule, tool call, verdict", D),
         arrow(150, 85, 200, 85), arrow(370, 85, 420, 85), arrow(610, 85, 660, 85),
         arrow(750, 110, 640, 180), arrow(750, 110, 795, 180), arrow(750, 110, 475, 180),
         arrow(475, 230, 520, 300), arrow(635, 230, 600, 300), arrow(795, 230, 680, 300),
         arrow(660, 100, 280, 320), arrow(180, 360, 180, 420),
         arrow(150, 300, 470, 120, dash=True),
         '<text x="250" y="230" font-size="10" fill="#a00">FAIL / INCONCLUSIVE feedback</text>',
         arrow(585, 350, 585, 420, dash=True),
         f'<rect x="20" y="500" width="14" height="14" fill="{M}" stroke="#333"/><text x="40" y="512">model-driven</text>',
         f'<rect x="150" y="500" width="14" height="14" fill="{D}" stroke="#333"/><text x="170" y="512">deterministic code</text>',
         f'<rect x="310" y="500" width="14" height="14" fill="{R}" stroke="#333"/><text x="330" y="512">human / relay</text>',
         '<text x="20" y="540" font-size="10">Not implemented: Bedrock or any cloud runtime; direct model API calls from Python; '
         'human approval inside a run (REQUIRES_HUMAN_REVIEW is terminal).</text>']
    svg(FIG / "fig1_architecture.svg", 900, 560, b)


def fig2(ev: dict) -> None:
    color = {"verified_success": "#2e7d32", "safe_non_completion": "#f9a825", "invalid_result_accepted": "#c62828",
             "unsafe_or_untraceable": "#6a1b9a", "unclassified": "#9e9e9e", "missing": "#ffffff"}
    groups = [("PRSWeave run 1 (pre-registered)", "agentic", "run_1"), ("PRSWeave run 2 (post-amendment)", "agentic", "run_2"),
              ("Baseline strict", "baseline_strict", None), ("Baseline robust", "baseline_robust", None)]
    b = ['<text x="20" y="24" font-size="15" font-weight="bold">Figure 2. Observed outcomes by scenario (independent evaluator)</text>']
    for j, s in enumerate("ABCD"):
        b.append(f'<text x="{300 + j * 120 + 50}" y="60" text-anchor="middle" font-weight="bold">Scenario {s}</text>')
    for i, (label, kind, rep) in enumerate(groups):
        y = 80 + i * 70
        b.append(f'<text x="20" y="{y + 32}">{label}</text>')
        for j, s in enumerate("ABCD"):
            r = next((x for x in ev["runs"] if x["kind"] == kind and x["scenario"] == s and (rep is None or x["run"].endswith(rep))), None)
            cls = r["outcome_class"] if r else "missing"
            txt = r["final_state"].replace("REQUIRES_HUMAN_REVIEW", "HUMAN REVIEW") if r else "not run"
            x = 300 + j * 120
            b.append(f'<rect x="{x}" y="{y}" width="100" height="50" rx="6" fill="{color[cls]}" stroke="#333"/>'
                     f'<text x="{x + 50}" y="{y + 30}" text-anchor="middle" font-size="10" '
                     f'fill="{"#000" if cls in ("safe_non_completion", "missing") else "#fff"}">{txt}</text>')
    y = 80 + len(groups) * 70 + 10
    for k, (cls, lab) in enumerate([("verified_success", "verified success"), ("safe_non_completion", "safe non-completion"),
                                    ("invalid_result_accepted", "invalid result accepted"), ("missing", "not run")]):
        b.append(f'<rect x="{20 + k * 200}" y="{y}" width="14" height="14" fill="{color[cls]}" stroke="#333"/>'
                 f'<text x="{40 + k * 200}" y="{y + 12}">{lab}</text>')
    b.append(f'<text x="20" y="{y + 40}" font-size="10">Scenario C has a single agentic run, made before the amendment; '
             'the amendment did not affect it, because C never submitted to the Critic.</text>')
    svg(FIG / "fig2_outcomes.svg", 800, y + 60, b)


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    ev = json.loads((R3 / "evaluation.json").read_text())
    traces(ev)
    fig1()
    fig2(ev)
    print("wrote agent_decision_traces.jsonl, decision_traces.md, fig1_architecture.svg, fig2_outcomes.svg")
