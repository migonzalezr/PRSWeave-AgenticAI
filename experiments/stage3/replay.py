#!/usr/bin/env python3
"""Deterministic replay of recorded Stage 3 runs (no model calls).

For each agentic run, this script rebuilds the inputs exactly as the harness did, in a temporary
directory. It then feeds the recorded Planner replies (decisions/reply_NNN.txt), in order,
through a fresh controller with the same fault hooks, and compares the result of every tool
execution and Critic verdict with the original. Fields that legitimately vary (timestamps,
cache serve times, absolute temp paths) are ignored.

A matching replay shows that the recorded decisions fully determine the tool outputs. It does
NOT show that a new model call would make the same decisions.

Usage: python3 experiments/stage3/replay.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_experiments import build_inputs, hooks_for, load_scenario  # noqa: E402
from prsweave.orchestration.controller import Controller  # noqa: E402
from prsweave.orchestration.event_log import read_events  # noqa: E402

VOLATILE = {"retrieval_time", "retrieved_at", "served_from", "latency_s", "timestamp"}


def scrub(x):
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return x


def outcomes(run_dir: Path) -> list:
    out = []
    for e in read_events(run_dir / "events.jsonl"):
        if e["event_type"] == "tool_execution":
            r = json.loads((run_dir / e["tool_result_ref"]["path"]).read_text())
            out.append(("tool", e["step_id"], e["tool_name"], r["status"], scrub(r["data"])))
        elif e["event_type"] == "verification_judgment":
            v = json.loads((run_dir / e["tool_result_ref"]["path"]).read_text())
            out.append(("verdict", e["step_id"], v["judgment"], v.get("failed_criteria")))
        elif e["event_type"] == "run_end":
            out.append(("end", e["validation_status"]))
    return out


def replay(run_rel: str, scenario_id: str) -> dict:
    src = ROOT / run_rel
    st = json.loads((src / "state.json").read_text())
    sc = load_scenario(scenario_id)
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "run"
        rd.mkdir()
        build_inputs(sc, rd)
        ctrl = Controller.create(rd, st["run_id"], st["request"], st["requested_phenotype"], st["provided_scores"], st["inputs"])
        ctrl.packet()
        hooks = hooks_for(sc, rd)
        for reply in sorted((src / "decisions").glob("reply_*.txt")):
            dst = rd / "decisions" / reply.name
            dst.parent.mkdir(exist_ok=True)
            shutil.copy2(reply, dst)
            c = Controller(rd, post_tool_hooks=hooks)
            r = c.apply_decision(dst, {})
            if "terminal" in r:
                break
        a, b = outcomes(src), outcomes(rd)
    first_diff = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if first_diff is None and len(a) != len(b):
        first_diff = min(len(a), len(b))
    return {"run": run_rel, "n_outcomes_original": len(a), "n_outcomes_replay": len(b), "identical": a == b,
            "first_difference_index": first_diff,
            "first_difference": None if first_diff is None else {"original": a[first_diff] if first_diff < len(a) else None,
                                                                   "replay": b[first_diff] if first_diff < len(b) else None}}


if __name__ == "__main__":
    idx = json.loads((ROOT / "results/stage3/run_index.json").read_text())
    res = [replay(m["run_dir"], m["scenario_id"]) for _, m in sorted(idx.items(), key=lambda kv: kv[1]["run_dir"])]
    (ROOT / "results/stage3/replay_check.json").write_text(json.dumps(res, indent=2, default=str))
    for r in res:
        print(f"{r['run']}: identical={r['identical']} ({r['n_outcomes_original']} vs {r['n_outcomes_replay']} outcomes)"
              + ("" if r["identical"] else f"; first difference at {r['first_difference_index']}: {str(r['first_difference'])[:300]}"))
