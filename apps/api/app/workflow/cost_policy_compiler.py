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
    """Compile an immutable cost candidate from frozen v2.12 and explicit overrides."""

    base_path = base_path or _resolve("workflows/software_factory_ai_native_v2.yaml")
    policy_path = policy_path or _resolve("workflows/software_factory_ai_native_v2_13_policy.yaml")
    base = yaml.safe_load(base_path.read_text()) or {}
    candidate = deepcopy(base)
    policy = _load_policy(policy_path)
    policy_version = str(policy.get("version") or "2.13.0")
    if not policy_version.startswith(("2.13.", "2.14.")):
        raise ValueError("policy version must stay within the supported v2.13 or v2.14 families")
    graph = candidate.get("graph") or {}
    if str(graph.get("version") or "") != "2.12.0":
        raise ValueError("v2.13 policy compiler requires the frozen v2.12.0 base workflow")
    graph["version"] = policy_version
    graph["description"] = str(
        policy.get("description")
        or "AI-native factory with cost envelopes, role schemas and section-level tenant context."
    )
    execution = graph.setdefault("execution", {})
    execution.update(
        {
            "context_policy_version": policy_version,
            "routing_policy_version": policy_version,
            "prompt_policy_version": policy_version,
            "cost_policy_version": policy_version,
        }
    )
    execution["plugins"] = deepcopy(policy.get("plugins") or {})
    if policy.get("evaluation"):
        execution["candidate_evaluation"] = deepcopy(policy["evaluation"])
    if policy.get("edge_additions"):
        graph.setdefault("edges", []).extend(deepcopy(policy["edge_additions"]))
    overrides: dict[str, dict[str, Any]] = policy.get("nodes") or {}
    node_defaults: dict[str, Any] = policy.get("node_defaults") or {}
    for node in graph.get("nodes") or []:
        if node.get("type") != "agent":
            continue
        override = _deep_merge(node_defaults, overrides.get(str(node.get("id"))) or {})
        if "max_output_tokens" in override:
            node["max_output_tokens"] = int(override["max_output_tokens"])
        if "observation_max_output_tokens" in override:
            node["observation_max_output_tokens"] = int(override["observation_max_output_tokens"])
        if "reserved_budget_usd" in override:
            node["reserved_budget_usd"] = float(override["reserved_budget_usd"])
        for key in (
            "plan_model_role",
            "finalize_model_role",
            "minimal_solution_policy",
            "ponytail_enabled",
            "ponytail_mode",
            "ponytail_commands",
            "cavekit_stages",
            "allowed_tools",
            "output_strategy",
            "workspace_ownership",
            "workspace_ownership_enforced",
            "qa_owns_tests",
        ):
            if key in override:
                node[key] = override[key]
        context = {**(node.get("context_policy") or {}), **(override.get("context_policy") or {})}
        context["version"] = policy_version
        node["context_policy"] = ContextPolicy.model_validate(context).model_dump(mode="json", exclude_defaults=True)
        node["output_budget_policy"] = {
            "method": "frozen-p95-valid-plus-20-percent",
            "floor_tokens": int((override.get("output_budget_policy") or {}).get("floor_tokens") or 0),
            "ceiling_tokens": int(node.get("max_output_tokens") or 0),
        }
    return yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_policy(path: Path) -> dict[str, Any]:
    policy = yaml.safe_load(path.read_text()) or {}
    extends = str(policy.get("extends") or "").strip()
    if not extends:
        return policy
    parent_path = Path(extends)
    if not parent_path.is_absolute():
        candidate = path.parent / parent_path
        parent_path = candidate if candidate.exists() else _resolve(extends)
    parent = _load_policy(parent_path.resolve())
    return _deep_merge(parent, {key: value for key, value in policy.items() if key != "extends"})


def load_frozen_v211_workflow(*, snapshot_path: Path | None = None) -> str:
    """Load and validate the tracked historical baseline without consulting database history."""

    path = snapshot_path or _resolve("benchmarks/workflows/software_factory_ai_native_v2_11.yaml")
    content = path.read_text()
    graph = (yaml.safe_load(content) or {}).get("graph") or {}
    if graph.get("id") != "software_factory_ai_native_v2" or str(graph.get("version")) != "2.11.0":
        raise ValueError("Frozen benchmark snapshot must be software_factory_ai_native_v2 version 2.11.0")
    return content
