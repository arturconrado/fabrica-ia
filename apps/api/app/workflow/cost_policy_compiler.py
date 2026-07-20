from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from app.agents.ai_native_contracts import ContextPolicy


def _resolve(relative: str) -> Path:
    module = Path(__file__).resolve()
    candidates = [Path.cwd() / relative]
    candidates.extend(parent / relative for parent in Path.cwd().parents)
    candidates.extend(parent / relative for parent in module.parents)
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def compile_cost_policy_workflow(
    *,
    base_path: Path | None = None,
    policy_path: Path | None = None,
) -> str:
    """Compile an immutable v2.13 candidate from the frozen v2.12 workflow and explicit overrides."""

    base_path = base_path or _resolve("workflows/software_factory_ai_native_v2.yaml")
    policy_path = policy_path or _resolve("workflows/software_factory_ai_native_v2_13_policy.yaml")
    base = yaml.safe_load(base_path.read_text()) or {}
    candidate = deepcopy(base)
    policy = yaml.safe_load(policy_path.read_text()) or {}
    graph = candidate.get("graph") or {}
    if str(graph.get("version") or "") != "2.12.0":
        raise ValueError("v2.13 policy compiler requires the frozen v2.12.0 base workflow")
    graph["version"] = "2.13.0"
    graph["description"] = "AI-native factory with cost envelopes, role schemas and section-level tenant context."
    execution = graph.setdefault("execution", {})
    execution.update(
        {
            "context_policy_version": "2.13.0",
            "routing_policy_version": "2.13.0",
            "prompt_policy_version": "2.13.0",
            "cost_policy_version": "2.13.0",
        }
    )
    overrides: dict[str, dict[str, Any]] = policy.get("nodes") or {}
    for node in graph.get("nodes") or []:
        if node.get("type") != "agent":
            continue
        override = overrides.get(str(node.get("id"))) or {}
        if "max_output_tokens" in override:
            node["max_output_tokens"] = int(override["max_output_tokens"])
        if "observation_max_output_tokens" in override:
            node["observation_max_output_tokens"] = int(override["observation_max_output_tokens"])
        if "reserved_budget_usd" in override:
            node["reserved_budget_usd"] = float(override["reserved_budget_usd"])
        context = {**(node.get("context_policy") or {}), **(override.get("context_policy") or {})}
        context["version"] = "2.13.0"
        node["context_policy"] = ContextPolicy.model_validate(context).model_dump(mode="json", exclude_defaults=True)
        node["output_budget_policy"] = {
            "method": "frozen-p95-valid-plus-20-percent",
            "floor_tokens": int((override.get("output_budget_policy") or {}).get("floor_tokens") or 0),
            "ceiling_tokens": int(node.get("max_output_tokens") or 0),
        }
    return yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True)


def load_frozen_v211_workflow(*, snapshot_path: Path | None = None) -> str:
    """Load and validate the tracked historical baseline without consulting database history."""

    path = snapshot_path or _resolve("benchmarks/workflows/software_factory_ai_native_v2_11.yaml")
    content = path.read_text()
    graph = (yaml.safe_load(content) or {}).get("graph") or {}
    if graph.get("id") != "software_factory_ai_native_v2" or str(graph.get("version")) != "2.11.0":
        raise ValueError("Frozen benchmark snapshot must be software_factory_ai_native_v2 version 2.11.0")
    return content
