"""Restricted, explicit tool registry.

Only registered tools can run. Each execution writes its arguments and result
to JSON artifacts, logs a ``tool_execution`` event with SHA-256 references and
duration, and returns a ToolResult. Tools are plain Python callables with no
LLM inside, so a future planner on any model backend can call the same registry.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .event_log import EventLog, sha256_file


@dataclass
class ToolResult:
    status: str                       # "ok" | "error"
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    artifacts: list[Path] = field(default_factory=list)
    network_hosts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: str                        # agent_id of the specialist that runs it
    description: str
    arguments: dict[str, str]         # argument name -> description
    fn: Callable[..., ToolResult]
    corrective: bool = False          # counts toward a recovery cycle


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, args: dict, *, ctx: Any, log: EventLog, run_id: str, task_id: str,
                step_id: str, artifacts_dir: Path, retry_count: int, invoked_by: str) -> ToolResult:
        spec = self._tools[name]
        unknown = set(args) - set(spec.arguments)
        missing = set(spec.arguments) - set(args)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        args_path = artifacts_dir / f"{step_id}_{name}_args.json"
        args_path.write_text(json.dumps(args, indent=2, sort_keys=True))
        t0 = time.perf_counter()
        if unknown or missing:
            result = ToolResult("error", {"message": f"argument mismatch: unknown={sorted(unknown)} missing={sorted(missing)}"},
                                error_code="BAD_ARGUMENTS")
        else:
            try:
                result = spec.fn(ctx, **args)
            except Exception as e:  # a tool crash is an observable error, not a silent pass
                result = ToolResult("error", {"message": "".join(traceback.format_exception_only(type(e), e)).strip()},
                                    error_code="TOOL_EXCEPTION")
        dt = time.perf_counter() - t0
        result_path = artifacts_dir / f"{step_id}_{name}_result.json"
        result_path.write_text(json.dumps({
            "tool": name, "status": result.status, "error_code": result.error_code, "data": result.data,
            "artifacts": [{"path": str(p.relative_to(ctx.run_dir)), "sha256": sha256_file(p)} for p in result.artifacts],
            "network_hosts": result.network_hosts,
        }, indent=2, default=str))
        log.append(
            run_id=run_id, task_id=task_id, step_id=step_id, agent_id=spec.owner, actor_kind="deterministic_specialist",
            event_type="tool_execution", current_task=f"{name} (invoked by {invoked_by})", tool_name=name,
            tool_arguments_ref={"path": str(args_path.relative_to(ctx.run_dir)), "sha256": sha256_file(args_path)},
            tool_result_ref={"path": str(result_path.relative_to(ctx.run_dir)), "sha256": sha256_file(result_path)},
            observations={"status": result.status, "artifacts": [{"path": str(p.relative_to(ctx.run_dir)), "sha256": sha256_file(p)} for p in result.artifacts],
                          "network_hosts": result.network_hosts},
            error_code=result.error_code, retry_count=retry_count, duration_seconds=round(dt, 6),
        )
        return result
