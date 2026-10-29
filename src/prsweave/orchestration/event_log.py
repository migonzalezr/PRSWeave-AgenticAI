"""Append-only, hash-chained JSONL event log implementing the Stage 3 message contract.

Each line carries the previous line's hash (``prev_sha256``) and its own
(``event_sha256``), so any edit, deletion or reordering breaks the chain
(see ``verify_chain``).

``actor_kind`` separates who acted:
  model_driven_agent        the Planner (a Claude Code subagent)
  deterministic_specialist  Evidence, Population Context, PRS Methods, Validation Critic
  deterministic_controller  state machine and authorization rules
  claude_code_relay         the main Claude Code session passing messages
  human                     an approval by the researcher (none occur unless logged)

``event_type`` is one of EVENT_TYPES.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTOR_KINDS = ("model_driven_agent", "deterministic_specialist", "deterministic_controller", "claude_code_relay", "human")
EVENT_TYPES = ("llm_decision", "deterministic_rule", "human_approval", "relay", "tool_execution",
               "verification_judgment", "state_transition", "run_start", "run_end")

# Message-contract fields (always present, None when not applicable).
CONTRACT_FIELDS = ("run_id", "task_id", "step_id", "agent_id", "actor_kind", "event_type", "current_task",
                   "observations", "evidence_refs", "available_actions", "proposed_actions", "selected_action",
                   "decision_justification", "tool_name", "tool_arguments_ref", "tool_result_ref",
                   "validation_status", "error_code", "retry_count", "duration_seconds", "timestamp")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash(event: dict) -> str:
    return hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.seq, self.last = 0, "0" * 64
        if self.path.exists():
            with open(self.path) as fh:
                for line in fh:
                    if line.strip():
                        e = json.loads(line)
                        self.seq, self.last = e["seq"], e["event_sha256"]

    def append(self, **fields: Any) -> dict:
        if fields.get("actor_kind") not in ACTOR_KINDS:
            raise ValueError(f"actor_kind {fields.get('actor_kind')!r}")
        if fields.get("event_type") not in EVENT_TYPES:
            raise ValueError(f"event_type {fields.get('event_type')!r}")
        event = {k: None for k in CONTRACT_FIELDS}
        event.update(fields)
        event["timestamp"] = event["timestamp"] or utcnow()
        event["seq"] = self.seq + 1
        event["prev_sha256"] = self.last
        event["event_sha256"] = _hash(event)
        with open(self.path, "a") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        self.seq, self.last = event["seq"], event["event_sha256"]
        return event


def read_events(path: Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def verify_chain(path: Path) -> tuple[bool, str]:
    prev, n = "0" * 64, 0
    for e in read_events(path):
        n += 1
        if e["seq"] != n:
            return False, f"seq gap at {n}"
        if e["prev_sha256"] != prev:
            return False, f"broken chain at seq {n}"
        body = {k: v for k, v in e.items() if k != "event_sha256"}
        if _hash(body) != e["event_sha256"]:
            return False, f"hash mismatch at seq {n}"
        prev = e["event_sha256"]
    return True, f"{n} events verified"
