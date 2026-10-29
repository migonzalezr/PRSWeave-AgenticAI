"""Machine-readable execution log (JSON Lines).

Every event names who acted. The three actor types are kept strictly apart:

* ``deterministic_software``: a check or computation run by PRSWeave code.
* ``claude_code_development``: a decision made by Claude Code while building
  PRSWeave (recorded in docs/decisions, referenced here by ID).
* ``prsweave_agent``: a decision made by an implemented PRSWeave agent.
  None exist before Stage 3.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ACTOR_TYPES = ("deterministic_software", "claude_code_development", "prsweave_agent")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class ExecutionLog:
    def __init__(self, path: Path, root: Path, run_id: str | None = None):
        self.path = path
        self.root = root
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.events: list[dict] = []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    def _ref(self, p: Path) -> dict:
        p = Path(p)
        rel = str(p.resolve().relative_to(self.root)) if p.resolve().is_relative_to(self.root) else str(p)
        return {"path": rel, "sha256": sha256_file(p) if p.exists() else None}

    def record(self, *, actor_type: str, actor: str, action: str, status: str = "ok",
               inputs: list[Path] = (), outputs: list[Path] = (), started_at: str | None = None,
               duration_s: float | None = None, details: dict[str, Any] | None = None,
               error: str | None = None) -> dict:
        if actor_type not in ACTOR_TYPES:
            raise ValueError(f"unknown actor_type {actor_type!r}")
        event = {
            "run_id": self.run_id,
            "seq": len(self.events) + 1,
            "started_at": started_at or utcnow(),
            "finished_at": utcnow(),
            "duration_s": None if duration_s is None else round(duration_s, 6),
            "actor_type": actor_type,
            "actor": actor,
            "action": action,
            "status": status,
            "inputs": [self._ref(p) for p in inputs],
            "outputs": [self._ref(p) for p in outputs],
            "details": details or {},
            "error": error,
        }
        self.events.append(event)
        with open(self.path, "a") as fh:
            fh.write(json.dumps(event) + "\n")
        return event

    @contextmanager
    def step(self, actor: str, action: str, inputs: list[Path] = ()) -> Iterator[dict]:
        """Time a deterministic step. Fill ctx['outputs'] and ctx['details'] inside the block.

        Errors are logged and then re-raised, so a failed check never passes silently.
        """
        ctx: dict[str, Any] = {"outputs": [], "details": {}}
        started, t0 = utcnow(), time.perf_counter()
        try:
            yield ctx
        except Exception as e:
            self.record(actor_type="deterministic_software", actor=actor, action=action, status="error",
                        inputs=inputs, outputs=ctx["outputs"], started_at=started,
                        duration_s=time.perf_counter() - t0, details=ctx["details"],
                        error="".join(traceback.format_exception_only(type(e), e)).strip())
            raise
        self.record(actor_type="deterministic_software", actor=actor, action=action,
                    status=ctx["details"].pop("_status", "ok"), inputs=inputs, outputs=ctx["outputs"],
                    started_at=started, duration_s=time.perf_counter() - t0, details=ctx["details"])


def runtime_environment() -> dict:
    return {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
            "platform": platform.platform(), "machine": platform.machine()}
