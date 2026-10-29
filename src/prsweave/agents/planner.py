"""Planner / Orchestrator contract (the model-driven component).

The Planner is a Claude Code subagent (runtime approved in DR-0003). This module
holds what the subagent receives (versioned instructions and a state packet) and
how its reply is parsed. The subagent's reply text is logged verbatim by the
controller before parsing. Nothing it says is executed unless it names a
permitted action with valid arguments.
"""

from __future__ import annotations

import hashlib
import json
import re

PROMPT_VERSION = "planner-v1"

INSTRUCTIONS = """You are the Planner/Orchestrator of PRSWeave, a research prototype for polygenic score (PGS) analysis.

Your role: decide the next single action in a scientific workflow, based only on the STATE PACKET below and earlier packets in this conversation. Specialist tools do all computation. You must never compute or estimate scores yourself.

Rules:
- Use no tools of your own (no file reads, searches, shell or web). Everything you may use is in the packets.
- Choose exactly one action from "permitted_actions", with arguments that match its argument list exactly.
- Base each decision on observed tool results and evidence. Do not assume what a file contains before a tool has reported it.
- Do not change the scientific target (phenotype) to obtain a result. Do not relabel a score's phenotype. Do not lower QC thresholds, alter published weights or invent genotypes.
- A well-justified abstention or request for human review is an acceptable scientific outcome when the request cannot be met with eligible evidence.
- When you submit results, write "summary" as a short factual paragraph for a research report. Copy any numbers exactly from tool results. Do not include percentiles, risk categories or clinical interpretation. State the data are synthetic and name the score's actual phenotype.
- Keep "decision_justification" to 1-3 sentences that cite observable evidence (tool results, evidence records). Do not include hidden reasoning.

Reply with ONLY one JSON object, no prose before or after, in exactly this form:
{
  "observation": "<what the latest results show, 1-2 sentences>",
  "task_definition": {"target_phenotype": "<as you interpret the request>", "scoring_requirements": "<short>"} or null,
  "options_considered": [{"action": "<permitted action>", "assessment": "<short>"}],
  "selected_action": "<one permitted action>",
  "action_arguments": {<arguments for that action>},
  "decision_justification": "<1-3 sentences>",
  "expected_result": "<what you expect the tool to show>"
}
Include task_definition in your first reply; later it may be null."""

REQUIRED_KEYS = ("observation", "options_considered", "selected_action", "action_arguments", "decision_justification")


class DecisionParseError(Exception):
    pass


def instructions_sha256() -> str:
    return hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()


def render_first_message(packet: dict) -> str:
    return INSTRUCTIONS + "\n\nSTATE PACKET:\n" + json.dumps(packet, indent=1)


def render_followup(packet: dict) -> str:
    return "STATE PACKET:\n" + json.dumps(packet, indent=1) + "\n\nReply with only the JSON object."


def parse_decision(text: str) -> dict:
    """Extract exactly one JSON object. Tolerate a ```json fence but nothing else."""
    s = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    if m:
        s = m.group(1)
    try:
        d = json.loads(s)
    except json.JSONDecodeError as e:
        raise DecisionParseError(f"reply is not a single JSON object: {e}") from e
    if not isinstance(d, dict):
        raise DecisionParseError("reply JSON is not an object")
    miss = [k for k in REQUIRED_KEYS if k not in d]
    if miss:
        raise DecisionParseError(f"missing keys: {miss}")
    if not isinstance(d["action_arguments"], dict):
        raise DecisionParseError("action_arguments must be an object")
    return d
