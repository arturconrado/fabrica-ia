#!/usr/bin/env python3
"""Deterministic token and cost simulation for candidate Portfolio 2.1.

The simulator never calls a model. It reads the same portfolio and compiled
AI-native policy used by the runtime, then applies an explicit pricing snapshot
and three utilization scenarios. Results distinguish the current execution
topology from a recommended shared technical-run topology.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.agents.ai_native_contracts import output_strategy_for_node  # noqa: E402
from app.service_delivery.catalog import AGENT_TEMPLATES, _portfolio_v21  # noqa: E402
from app.workflow.cost_policy_compiler import compile_cost_policy_workflow  # noqa: E402


DEFAULT_PRICING = REPO_ROOT / "homologation" / "cost-model" / "openrouter-pricing-2026-07-31.json"
DEFAULT_JSON_OUTPUT = REPO_ROOT / "homologation" / "cost-model" / "portfolio-token-cost-simulation.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "homologation" / "cost-model" / "portfolio-token-cost-simulation.md"
POLICY_PATH = REPO_ROOT / "workflows" / "software_factory_ai_native_v2_14_policy.yaml"


SCENARIOS: dict[str, dict[str, float | int]] = {
    "lean": {
        "plan_input_factor": 0.70,
        "plan_output_factor": 0.60,
        "deliverable_input_factor": 0.60,
        "deliverable_output_factor": 0.50,
        "technical_input_utilization": 0.45,
        "technical_output_utilization": 0.40,
        "artifact_sections": 2,
        "engineer_file_batches": 2,
        "retry_reserve_factor": 1.00,
        "cache_effectiveness": 0.80,
    },
    "expected": {
        "plan_input_factor": 1.00,
        "plan_output_factor": 1.00,
        "deliverable_input_factor": 1.00,
        "deliverable_output_factor": 1.00,
        "technical_input_utilization": 0.65,
        "technical_output_utilization": 0.55,
        "artifact_sections": 4,
        "engineer_file_batches": 4,
        "retry_reserve_factor": 1.08,
        "cache_effectiveness": 0.50,
    },
    "conservative": {
        "plan_input_factor": 1.60,
        "plan_output_factor": 1.30,
        "deliverable_input_factor": 1.65,
        "deliverable_output_factor": 1.75,
        "technical_input_utilization": 1.00,
        "technical_output_utilization": 0.85,
        "artifact_sections": 12,
        "engineer_file_batches": 8,
        "retry_reserve_factor": 1.35,
        "cache_effectiveness": 0.00,
    },
}


@dataclass
class Usage:
    calls: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: "Usage", factor: float = 1.0) -> None:
        self.calls += other.calls * factor
        self.input_tokens += round(other.input_tokens * factor)
        self.output_tokens += round(other.output_tokens * factor)
        self.cache_read_tokens += round(other.cache_read_tokens * factor)
        self.cache_write_tokens += round(other.cache_write_tokens * factor)
        self.cost_usd += other.cost_usd * factor

    def rounded(self) -> dict[str, Any]:
        return {
            "calls": round(self.calls, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def _price_usage(
    pricing: dict[str, Any],
    *,
    role: str,
    calls: float,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Usage:
    model = pricing["aliases"][role]
    rates = model["pricing"]
    cached = min(input_tokens, cache_read_tokens + cache_write_tokens)
    regular_input = input_tokens - cached
    cost = (
        regular_input * float(rates["prompt"])
        + cache_read_tokens * float(rates.get("input_cache_read", rates["prompt"]))
        + cache_write_tokens * float(rates.get("input_cache_write", rates["prompt"]))
        + output_tokens * float(rates["completion"])
    )
    return Usage(
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_usd=cost,
    )


def _scale_tokens(value: float, factor: float, ceiling: int | None = None) -> int:
    scaled = max(0, math.ceil(value * factor))
    return min(scaled, ceiling) if ceiling else scaled


def _plan_usage(pricing: dict[str, Any], offering: dict[str, Any], scenario: dict[str, Any]) -> Usage:
    deliverables = len(offering["deliverable_templates"])
    processes = len(offering.get("process") or [])
    # Calibrated against the persisted local Engagement Planner success
    # (6,079 input / 7,367 output tokens), while remaining catalog-sensitive.
    baseline_input = 2_500 + deliverables * 230 + processes * 120
    baseline_output = min(8_000, 3_400 + deliverables * 300)
    input_tokens = _scale_tokens(baseline_input, float(scenario["plan_input_factor"]))
    output_tokens = _scale_tokens(
        baseline_output,
        float(scenario["plan_output_factor"]),
        8_000,
    )
    return _price_usage(
        pricing,
        role="reasoning",
        calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _deliverable_usage(
    pricing: dict[str, Any],
    template: dict[str, Any],
    scenario: dict[str, Any],
    role: str,
) -> Usage:
    formats = set(template.get("formats") or [])
    output_by_format = 5_000
    if "xlsx" in formats:
        output_by_format = 4_200
    elif "zip" in formats:
        output_by_format = 6_500
    baseline_input = (
        7_100
        + len(template.get("required_sections") or []) * 180
        + len(template.get("required_evidence") or []) * 180
    )
    input_tokens = _scale_tokens(
        baseline_input,
        float(scenario["deliverable_input_factor"]),
    )
    output_tokens = _scale_tokens(
        output_by_format,
        float(scenario["deliverable_output_factor"]),
        12_000,
    )
    return _price_usage(
        pricing,
        role=role,
        calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _context_budgets(node: dict[str, Any]) -> tuple[int, int, int, int]:
    context = node.get("context_policy") or {}
    total = int(context.get("input_budget_tokens") or 16_000)
    plan = int(context.get("plan_input_budget_tokens") or min(total, 12_000))
    unit = int(context.get("unit_input_budget_tokens") or min(total, 16_000))
    finalize = int(context.get("finalize_input_budget_tokens") or min(total, 4_000))
    return total, plan, unit, finalize


def _technical_call(
    pricing: dict[str, Any],
    *,
    role: str,
    input_tokens: int,
    output_tokens: int,
    retry_factor: float,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Usage:
    return _price_usage(
        pricing,
        role=role,
        calls=retry_factor,
        input_tokens=round(input_tokens * retry_factor),
        output_tokens=round(output_tokens * retry_factor),
        # Retry/repair context is conservatively charged as ordinary input.
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )


def _technical_run_usage(
    pricing: dict[str, Any],
    nodes: Iterable[dict[str, Any]],
    scenario: dict[str, Any],
) -> tuple[Usage, dict[str, dict[str, Any]]]:
    total = Usage()
    by_role: dict[str, Usage] = defaultdict(Usage)
    input_util = float(scenario["technical_input_utilization"])
    output_util = float(scenario["technical_output_utilization"])
    retry_factor = float(scenario["retry_reserve_factor"])
    cache_effectiveness = float(scenario["cache_effectiveness"])

    for node in nodes:
        role = str(node.get("model_role") or "default")
        max_output = int(node.get("max_output_tokens") or 4_000)
        total_input, plan_input, unit_input, finalize_input = _context_budgets(node)
        strategy = output_strategy_for_node(str(node["id"]))
        calls: list[Usage] = []
        if strategy == "atomic":
            calls.append(
                _technical_call(
                    pricing,
                    role=role,
                    input_tokens=_scale_tokens(total_input, input_util),
                    output_tokens=_scale_tokens(max_output, output_util),
                    retry_factor=retry_factor,
                )
            )
        else:
            plan_role = str(node.get("plan_model_role") or role)
            finalize_role = str(node.get("finalize_model_role") or role)
            calls.append(
                _technical_call(
                    pricing,
                    role=plan_role,
                    input_tokens=_scale_tokens(plan_input, input_util),
                    output_tokens=_scale_tokens(min(4_000, max_output), output_util),
                    retry_factor=retry_factor,
                )
            )
            unit_count = int(
                scenario["engineer_file_batches"]
                if strategy == "segmented_workspace"
                else scenario["artifact_sections"]
            )
            desired_total_output = _scale_tokens(max_output, output_util)
            output_per_unit = max(128, math.ceil(desired_total_output / unit_count))
            stable_prefix_tokens = min(1_000, _scale_tokens(unit_input, input_util))
            for index in range(unit_count):
                input_tokens = _scale_tokens(unit_input, input_util)
                cache_write = (
                    round(stable_prefix_tokens * cache_effectiveness)
                    if index == 0 and cache_effectiveness
                    else 0
                )
                cache_read = (
                    round(stable_prefix_tokens * cache_effectiveness)
                    if index > 0 and cache_effectiveness
                    else 0
                )
                calls.append(
                    _technical_call(
                        pricing,
                        role=role,
                        input_tokens=input_tokens,
                        output_tokens=output_per_unit,
                        retry_factor=retry_factor,
                        cache_read_tokens=cache_read,
                        cache_write_tokens=cache_write,
                    )
                )
            calls.append(
                _technical_call(
                    pricing,
                    role=finalize_role,
                    input_tokens=_scale_tokens(finalize_input, input_util),
                    output_tokens=_scale_tokens(min(2_000, max_output), output_util),
                    retry_factor=retry_factor,
                )
            )
        for call in calls:
            total.add(call)
        # Attribute calls by their priced role after construction.
        if strategy == "atomic":
            by_role[role].add(calls[0])
        else:
            by_role[str(node.get("plan_model_role") or role)].add(calls[0])
            for call in calls[1:-1]:
                by_role[role].add(call)
            by_role[str(node.get("finalize_model_role") or role)].add(calls[-1])
    return total, {role: usage.rounded() for role, usage in sorted(by_role.items())}


def _compiled_nodes() -> list[dict[str, Any]]:
    compiled = yaml.safe_load(compile_cost_policy_workflow(policy_path=POLICY_PATH)) or {}
    return [
        node
        for node in ((compiled.get("graph") or {}).get("nodes") or [])
        if node.get("type") == "agent"
    ]


def _role_by_agent() -> dict[str, str]:
    return {str(agent["code"]): str(agent.get("model_role") or "reasoning") for agent in AGENT_TEMPLATES}


def _simulate_offering(
    pricing: dict[str, Any],
    offering: dict[str, Any],
    nodes: list[dict[str, Any]],
    scenario_name: str,
    topology: str,
) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_name]
    roles = _role_by_agent()
    plan = _plan_usage(pricing, offering, scenario)
    technical, technical_by_role = _technical_run_usage(pricing, nodes, scenario)
    technical_templates = [
        template
        for template in offering["deliverable_templates"]
        if template["execution_mode"] == "technical_run"
    ]
    declares_technical_process = any(
        process.get("mode") == "technical_run" for process in offering.get("process") or []
    )
    total = Usage()
    total.add(plan)
    deliverables: list[dict[str, Any]] = []
    for template in offering["deliverable_templates"]:
        mode = str(template["execution_mode"])
        role = roles.get(str(template.get("responsible") or ""), "reasoning")
        allocation = "direct"
        if mode == "agent":
            usage = _deliverable_usage(pricing, template, scenario, role)
        elif mode == "technical_run":
            role = "mixed"
            if topology == "current_runtime":
                usage = copy.deepcopy(technical)
                allocation = "one_full_factory_run"
            else:
                usage = Usage()
                usage.add(technical, factor=1 / max(1, len(technical_templates)))
                allocation = "shared_factory_run_allocation"
        else:
            usage = Usage()
            role = "none"
            allocation = "human_or_integration_no_model_call"
        total.add(usage)
        deliverables.append(
            {
                "key": template["key"],
                "title": template["title"],
                "execution_mode": mode,
                "model_role": role,
                "allocation": allocation,
                "formats": list(template.get("formats") or []),
                "usage": usage.rounded(),
            }
        )

    shared_technical = Usage()
    if topology == "recommended_shared" and declares_technical_process and not technical_templates:
        shared_technical.add(technical)
        total.add(shared_technical)

    return {
        "code": offering["code"],
        "display_name": offering["display_name"],
        "cadence": offering["cadence"],
        "scenario": scenario_name,
        "topology": topology,
        "engagement_plan": plan.rounded(),
        "shared_technical_run": shared_technical.rounded(),
        "technical_run_unit_cost": technical.rounded(),
        "technical_run_by_role": technical_by_role,
        "deliverables": deliverables,
        "total": total.rounded(),
    }


def simulate(pricing: dict[str, Any]) -> dict[str, Any]:
    portfolio = _portfolio_v21()
    nodes = _compiled_nodes()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "portfolio_version": portfolio["version"],
        "policy_version": "2.14.0",
        "pricing": pricing,
        "assumptions": {
            "scenarios": SCENARIOS,
            "historical_calibration": {
                "engagement_plan_success": {"input_tokens": 6079, "output_tokens": 7367},
                "service_deliverable_success_mean": {"input_tokens": 8576, "output_tokens": 5762},
                "note": "Local persisted samples; simulation does not query the database or call a provider.",
            },
            "budget_caps_are_not_expected_cost": {
                "engagement_plan_usd": 2.0,
                "service_deliverable_usd": 3.0,
                "technical_run_usd": 15.0,
            },
            "office_cycles_for_homologation": 2,
        },
        "topologies": {},
        "findings": [
            "Naive per-deliverable execution would start one complete 18-role factory run for each technical deliverable.",
            "Portfolio 2.1 shares exactly one software_product run across the six Pilot technical deliverables.",
            "Portfolio 2.1 materializes one engineering_validation run for the Engineering Accelerator.",
            "The candidate topology charges one execution and one slot per explicit technical group.",
        ],
    }
    for topology in ("current_runtime", "recommended_shared"):
        topology_result: dict[str, Any] = {}
        for scenario_name in SCENARIOS:
            offerings = [
                _simulate_offering(pricing, offering, nodes, scenario_name, topology)
                for offering in portfolio["offerings"]
            ]
            once = Usage()
            for offering in offerings:
                once.add(Usage(**offering["total"]))
            office = next(item for item in offerings if item["code"] == "ai_office_as_a_service")
            office_repeat = Usage()
            # A second Office cycle reuses the approved plan and regenerates only
            # the cycle deliverables; it does not create another engagement plan.
            office_repeat.add(Usage(**office["total"]))
            office_repeat.add(Usage(**office["engagement_plan"]), factor=-1)
            homologation = copy.deepcopy(once)
            homologation.add(office_repeat)
            topology_result[scenario_name] = {
                "offerings": offerings,
                "portfolio_once": once.rounded(),
                "office_additional_cycle": office_repeat.rounded(),
                "portfolio_with_two_office_cycles": homologation.rounded(),
            }
        result["topologies"][topology] = topology_result
    target = result["topologies"]["recommended_shared"]
    expected_cost = target["expected"]["portfolio_with_two_office_cycles"]["cost_usd"]
    conservative_cost = target["conservative"]["portfolio_with_two_office_cycles"]["cost_usd"]
    result["preflight_budget"] = {
        "expected_cost_usd": expected_cost,
        "expected_limit_usd": 15.0,
        "conservative_cost_usd": conservative_cost,
        "conservative_limit_usd": 30.0,
        "hard_stop_usd": 50.0,
        "passed": expected_cost <= 15.0 and conservative_cost <= 30.0,
    }
    return result


def _money(value: float) -> str:
    return f"US$ {value:,.4f}"


def render_markdown(result: dict[str, Any]) -> str:
    pricing = result["pricing"]
    lines = [
        "# Simulação de tokens e custos do portfólio 2.1",
        "",
        "> Simulação determinística; nenhuma chamada de IA é executada. Valores em USD e sem impostos, câmbio ou ferramentas cobradas à parte.",
        "",
        "## Preços utilizados",
        "",
        f"Snapshot: `{pricing['captured_at']}` · fonte: `{pricing['source']}`.",
        "",
        "| Papel | Modelo | Entrada / 1M | Saída / 1M | Cache read / 1M |",
        "|---|---|---:|---:|---:|",
    ]
    for role, model in pricing["aliases"].items():
        rates = model["pricing"]
        lines.append(
            f"| {role} | `{model['upstream_model']}` | {_money(rates['prompt'] * 1_000_000)} | "
            f"{_money(rates['completion'] * 1_000_000)} | {_money(rates['input_cache_read'] * 1_000_000)} |"
        )

    lines.extend(
        [
            "",
            "## Totais por oferta — execução ingênua de comparação",
            "",
            "Cada valor inclui um plano de engajamento. AI Office representa um ciclo; a homologação completa acrescenta o segundo ciclo sem repetir o plano.",
            "",
            "| Oferta | Enxuto | Esperado | Conservador | Tokens esperados (in/out) | Chamadas equivalentes* |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    current = result["topologies"]["current_runtime"]
    for index, offering in enumerate(current["expected"]["offerings"]):
        lean = current["lean"]["offerings"][index]["total"]
        expected = offering["total"]
        conservative = current["conservative"]["offerings"][index]["total"]
        lines.append(
            f"| {offering['display_name']} | {_money(lean['cost_usd'])} | {_money(expected['cost_usd'])} | "
            f"{_money(conservative['cost_usd'])} | {expected['input_tokens']:,} / {expected['output_tokens']:,} | {expected['calls']:.2f} |"
        )
    lines.extend(["", "| Escopo | Enxuto | Esperado | Conservador |", "|---|---:|---:|---:|"])
    for label, key in (
        ("Oito ofertas, um ciclo cada", "portfolio_once"),
        ("Homologação com dois ciclos do AI Office", "portfolio_with_two_office_cycles"),
    ):
        lines.append(
            f"| {label} | {_money(current['lean'][key]['cost_usd'])} | "
            f"{_money(current['expected'][key]['cost_usd'])} | {_money(current['conservative'][key]['cost_usd'])} |"
        )

    lines.extend(
        [
            "",
            "\\* Chamadas equivalentes incluem a reserva probabilística de retries; por isso podem ser fracionárias.",
        ]
    )

    lines.extend(
        [
            "",
            "## Efeito da topologia eficiente",
            "",
            "A topologia candidata 2.1 consolida os seis entregáveis técnicos do Pilot em uma execução e materializa uma execução compartilhada no Engineering.",
            "",
            "| Cenário | Runtime atual | Compartilhado recomendado | Economia |",
            "|---|---:|---:|---:|",
        ]
    )
    recommended = result["topologies"]["recommended_shared"]
    for scenario in SCENARIOS:
        current_cost = current[scenario]["portfolio_with_two_office_cycles"]["cost_usd"]
        recommended_cost = recommended[scenario]["portfolio_with_two_office_cycles"]["cost_usd"]
        saving = current_cost - recommended_cost
        lines.append(
            f"| {scenario} | {_money(current_cost)} | {_money(recommended_cost)} | {_money(saving)} ({saving / current_cost * 100:.1f}%) |"
        )

    lines.extend(
        [
            "",
            "## Custo esperado por entregável — comparação ingênua",
            "",
            "`human` e `integration` não chamam modelo. Em `technical_run`, o valor é o custo integral da fábrica hoje disparada por aquele entregável.",
            "",
        ]
    )
    for offering in current["expected"]["offerings"]:
        lines.extend(
            [
                f"### {offering['display_name']}",
                "",
                f"Plano compartilhado do engajamento: {_money(offering['engagement_plan']['cost_usd'])}.",
                "",
                "| Entregável | Modo | Modelo | Tokens in/out | Custo esperado | Alocação |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for deliverable in offering["deliverables"]:
            usage = deliverable["usage"]
            lines.append(
                f"| {deliverable['title']} | {deliverable['execution_mode']} | {deliverable['model_role']} | "
                f"{usage['input_tokens']:,} / {usage['output_tokens']:,} | {_money(usage['cost_usd'])} | {deliverable['allocation']} |"
            )
        if offering["shared_technical_run"]["calls"]:
            lines.append(
                f"| Execução técnica compartilhada | technical_run | mixed | "
                f"{offering['shared_technical_run']['input_tokens']:,} / {offering['shared_technical_run']['output_tokens']:,} | "
                f"{_money(offering['shared_technical_run']['cost_usd'])} | offering overhead |"
            )
        lines.append("")

    lines.extend(
        [
            "## Premissas e limites",
            "",
            "- O plano é uma chamada `reasoning` por engajamento, com teto de 8 mil tokens de saída.",
            "- Cada entregável `agent` é uma chamada própria; DOCX, XLSX e ZIP usam estimativas diferentes de conteúdo fonte.",
            "- A execução técnica usa os 18 papéis e os budgets compilados da política 2.14.0, incluindo unidades segmentadas, reserva de retry e cache somente onde reutilizável.",
            "- Os tetos de US$ 2, US$ 3 e US$ 15 são proteções de gasto, não previsões de consumo.",
            "- A simulação não inclui entrevistas humanas, armazenamento, CPU, observabilidade, web search, impostos ou câmbio.",
            "- Preços de modelos mudam. Atualize o snapshot e regenere o relatório antes de formar preço comercial.",
            "",
        ]
    )
    budget = result["preflight_budget"]
    lines.extend(
        [
            "## Gate de orçamento da homologação",
            "",
            f"- Esperado: {_money(budget['expected_cost_usd'])} / limite {_money(budget['expected_limit_usd'])}.",
            f"- Conservador: {_money(budget['conservative_cost_usd'])} / limite {_money(budget['conservative_limit_usd'])}.",
            f"- Hard stop global: {_money(budget['hard_stop_usd'])}.",
            f"- Resultado: **{'PASSOU' if budget['passed'] else 'BLOQUEADO'}**.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_pricing(pricing: dict[str, Any]) -> None:
    required_roles = {"default", "fast", "reasoning", "code"}
    aliases = pricing.get("aliases") or {}
    missing = required_roles.difference(aliases)
    if missing:
        raise ValueError(f"pricing snapshot missing roles: {sorted(missing)}")
    for role in required_roles:
        rates = aliases[role].get("pricing") or {}
        if float(rates.get("prompt", -1)) < 0 or float(rates.get("completion", -1)) < 0:
            raise ValueError(f"invalid prompt/completion pricing for {role}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pricing = json.loads(args.pricing.read_text(encoding="utf-8"))
    _validate_pricing(pricing)
    result = simulate(pricing)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    expected = result["topologies"]["current_runtime"]["expected"]["portfolio_with_two_office_cycles"]
    recommended = result["topologies"]["recommended_shared"]["expected"]["portfolio_with_two_office_cycles"]
    print(
        json.dumps(
            {
                "status": "simulated" if result["preflight_budget"]["passed"] else "blocked",
                "paid_model_calls": 0,
                "current_expected_usd": expected["cost_usd"],
                "recommended_expected_usd": recommended["cost_usd"],
                "json_output": str(args.json_output),
                "markdown_output": str(args.markdown_output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["preflight_budget"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
