#!/usr/bin/env python3
"""Stage 3 experiment harness.

The harness alone reads the hidden scenario configs. It builds each run's inputs
(faults are applied to copies), gives the run an opaque ID, and records
everything it does in that run's harness_log.jsonl, which the Planner and
Critic never see.

Relay protocol (Claude Code = relay):
    prepare  --scenario a --rep 1          -> prints the first Planner message file
    step     --run-dir D --reply F [meta]  -> records the reply, executes, prints the next message file or the terminal state

Usage:
    python3 experiments/stage3/run_experiments.py prepare --scenario a --rep 1
    python3 experiments/stage3/run_experiments.py step --run-dir results/stage3/scenario_a/run_1 \
        --reply results/stage3/scenario_a/run_1/decisions/reply_001.txt --subagent-id X --latency-ms 1234 \
        --total-tokens 5678 --tool-uses 0 --model sonnet
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from prsweave.agents import planner  # noqa: E402
from prsweave.orchestration.controller import Controller  # noqa: E402
from prsweave.orchestration.event_log import sha256_file, utcnow  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/stage3"
REQUEST = ("Using the published polygenic score provided ({scores}) and the genotype dosage file provided for 20 "
           "individuals, compute a validated polygenic score for {phenotype} for each individual and report the "
           "results with their limitations.")


def load_scenario(sid: str) -> dict:
    return json.loads((HERE / f"scenario_{sid.lower()}.json").read_text())


def harness_log(run_dir: Path, **rec) -> None:
    with open(run_dir / "harness_log.jsonl", "a") as fh:
        fh.write(json.dumps({"timestamp": utcnow(), **rec}) + "\n")


def build_inputs(sc: dict, run_dir: Path) -> dict:
    """Copy the source genotype file into the run and apply any before-run faults to the copy."""
    src = ROOT / sc["genotype_source"]
    dst = run_dir / "inputs" / "dosages.tsv"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    harness_log(run_dir, action="copy_input", source=sc["genotype_source"], source_sha256=sha256_file(src),
                dest="inputs/dosages.tsv")
    for f in sc["faults"]:
        if f["type"] == "permute_columns":
            lines = dst.read_text().splitlines(keepends=True)
            comments = [l for l in lines if l.startswith("#")]
            body = [l.rstrip("\n").split("\t") for l in lines if not l.startswith("#")]
            head = body[0]
            order = [head.index(c) for c in f["column_order"]]
            if sorted(f["column_order"]) != sorted(head):
                raise SystemExit("fault column_order must be a permutation of the header")
            with open(dst, "w") as fh:
                fh.writelines(comments)
                for row in body:
                    fh.write("\t".join(row[i] for i in order) + "\n")
            harness_log(run_dir, action="fault_applied", fault=f, result_sha256=sha256_file(dst))
    return {"genotype_artifact": "inputs/dosages.tsv"}


def hooks_for(sc: dict, run_dir: Path) -> dict:
    hooks = {}
    for f in sc["faults"]:
        if f["type"] == "corrupt_scores_after_write":
            tool = f["stage"].split(":", 1)[1]
            state_p = run_dir / "harness_state.json"

            def corrupt(run_dir_, res, f=f, state_p=state_p):
                hs = json.loads(state_p.read_text()) if state_p.exists() else {"count": 0}
                hs["count"] += 1
                state_p.write_text(json.dumps(hs))
                if hs["count"] != f["occurrence"]:
                    return
                p = run_dir_ / res.data["scores_artifact"]
                with open(p) as fh:
                    rows = list(csv.reader(fh))
                before = sha256_file(p)
                for r in rows[1:]:
                    if r[0] == f["iid"]:
                        old, r[2] = r[2], f["replace_with"]
                with open(p, "w", newline="") as fh:
                    csv.writer(fh).writerows(rows)
                harness_log(run_dir_, action="fault_applied", fault=f, artifact=res.data["scores_artifact"],
                            original_value=old, sha256_before=before, sha256_after=sha256_file(p))
            hooks[tool] = corrupt
    return hooks


def message_for(ctrl: Controller, packet_path: Path, first: bool) -> Path:
    packet = json.loads(packet_path.read_text())
    text = planner.render_first_message(packet) if first else planner.render_followup(packet)
    out = ctrl.run_dir / "packets" / (packet_path.stem.replace("packet", "message") + ".txt")
    out.write_text(text)
    return out


def cmd_prepare(a) -> None:
    sc = load_scenario(a.scenario)
    run_dir = RESULTS / f"scenario_{sc['scenario_id'].lower()}" / f"run_{a.rep}"
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; runs are never overwritten")
    run_dir.mkdir(parents=True)
    run_id = "R" + hashlib.sha256(f"{sc['scenario_id']}-{a.rep}-{secrets.token_hex(8)}".encode()).hexdigest()[:8]
    harness_log(run_dir, action="prepare", scenario_id=sc["scenario_id"], rep=a.rep, run_id=run_id,
                scenario_sha256=sha256_file(HERE / f"scenario_{sc['scenario_id'].lower()}.json"))
    inputs = build_inputs(sc, run_dir)
    request = REQUEST.format(scores=", ".join(sc["provided_scores"]), phenotype=sc["requested_phenotype"])
    ctrl = Controller.create(run_dir, run_id, request, sc["requested_phenotype"], sc["provided_scores"], inputs)
    idx_p = RESULTS / "run_index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {}
    idx[run_id] = {"scenario_id": sc["scenario_id"], "rep": a.rep, "run_dir": str(run_dir.relative_to(ROOT))}
    idx_p.write_text(json.dumps(idx, indent=2))
    msg = message_for(ctrl, ctrl.packet(), first=True)
    print(json.dumps({"run_id": run_id, "run_dir": str(run_dir.relative_to(ROOT)), "message": str(msg.relative_to(ROOT))}))


def cmd_step(a) -> None:
    run_dir = ROOT / a.run_dir
    with open(run_dir / "harness_log.jsonl") as fh:
        sid = next(json.loads(l)["scenario_id"] for l in fh if '"prepare"' in l)
    ctrl = Controller(run_dir, post_tool_hooks=hooks_for(load_scenario(sid), run_dir))
    meta = {"subagent_id": a.subagent_id, "model": a.model, "latency_ms": a.latency_ms, "total_tokens": a.total_tokens,
            "planner_tool_uses": a.tool_uses}
    r = ctrl.apply_decision(ROOT / a.reply, meta)
    if "next_packet" in r:
        msg = message_for(ctrl, Path(r["next_packet"]), first=False)
        print(json.dumps({"next_message": str(msg.relative_to(ROOT)), "state": ctrl.st["state"],
                          "last": {k: (ctrl.st["last_result"] or {}).get(k) for k in ("action", "status", "error_code")},
                          "rejected": ctrl.st["last_rejection"]}))
    else:
        print(json.dumps({"terminal": r["terminal"], "outcome": r.get("outcome")}, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--scenario", required=True)
    p.add_argument("--rep", type=int, default=1)
    s = sub.add_parser("step")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--reply", required=True)
    s.add_argument("--subagent-id")
    s.add_argument("--model")
    s.add_argument("--latency-ms", type=int)
    s.add_argument("--total-tokens", type=int)
    s.add_argument("--tool-uses", type=int)
    a = ap.parse_args()
    {"prepare": cmd_prepare, "step": cmd_step}[a.cmd](a)


if __name__ == "__main__":
    main()
