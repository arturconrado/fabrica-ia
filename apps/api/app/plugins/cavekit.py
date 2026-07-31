"""Cavekit v4.1 prompt protocol mapped onto the durable factory workflow."""

from __future__ import annotations

from typing import Any

from app.agents.ai_native_contracts import stable_hash


CAVEKIT_VERSION = "4.1.0"
CAVEKIT_SOURCE_REVISION = "c322f0bb6db82163041930467f3ce32754d42827"
CAVEKIT_SOURCE_URL = "https://github.com/JuliusBrussee/cavekit"

_STAGES: dict[str, str] = {
    "grill": "Clarify only blocking ambiguity. Never guess a goal, constraint, interface or edge case.",
    "spec": "Use compact §G goal, §C constraints, §I interfaces, §R cited research, §V testable invariants, §T tasks and §B bugs.",
    "research": "Scope at most three unknowns. Every external fact needs an authorized source; otherwise mark it `?`.",
    "review": "Try to refute the spec with evidence. Classify findings BLOCK, HARDEN or NOTE and end GO or NO-GO.",
    "build": "Implement one bounded task at a time. Cite every touched §I and §V and name the exact verification oracle.",
    "check": "Compare §I, §V and §T with code and evidence. Report MATCH/HOLD or DRIFT/VIOLATE/MISSING/STALE.",
    "backprop": "On a real failure, record root cause in §B, add a testable §V when useful, add its failing test, then fix.",
    "deepen": "Only after green checks, propose at most one behaviour-preserving interface simplification; never churn.",
    "caveman": "Compress internal spec prose without changing identifiers, paths, numbers, code, JSON, YAML or facts.",
}


class CavekitPolicy:
    @staticmethod
    def manifest() -> dict[str, Any]:
        payload = {
            "name": "cavekit",
            "version": CAVEKIT_VERSION,
            "source_revision": CAVEKIT_SOURCE_REVISION,
            "source_url": CAVEKIT_SOURCE_URL,
            "license": "MIT",
            "capabilities": list(_STAGES),
            "access_mode": "structured_prompt_protocol",
            "automatic_updates": False,
        }
        return {**payload, "manifest_sha256": stable_hash(payload)}

    @staticmethod
    def prompt(stages: list[str]) -> str:
        selected = [f"CAVEKIT {stage.upper()}: {_STAGES[stage]}" for stage in stages if stage in _STAGES]
        return "\n".join(selected)

    @staticmethod
    def stages_for_node(node: dict[str, Any]) -> list[str]:
        configured = [str(stage).strip().lower() for stage in (node.get("cavekit_stages") or [])]
        return list(dict.fromkeys(stage for stage in configured if stage in _STAGES))

    @staticmethod
    def stages_for_action(node: dict[str, Any], action: str) -> list[str]:
        stages = CavekitPolicy.stages_for_node(node)
        action_type = action.split(":", 1)[0]
        if action_type != "observe":
            stages = [stage for stage in stages if stage != "backprop"]
        if action_type != "deepen":
            stages = [stage for stage in stages if stage != "deepen"]
        return stages
