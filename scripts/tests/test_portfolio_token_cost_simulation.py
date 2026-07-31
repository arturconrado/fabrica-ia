from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "simulate_portfolio_token_costs.py"
SPEC = importlib.util.spec_from_file_location("portfolio_token_cost_simulation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def pricing() -> dict:
    return json.loads(
        (ROOT / "homologation" / "cost-model" / "openrouter-pricing-2026-07-31.json").read_text()
    )


def test_simulation_covers_all_offerings_and_deliverables() -> None:
    result = MODULE.simulate(pricing())
    expected = result["topologies"]["current_runtime"]["expected"]

    assert len(expected["offerings"]) == 8
    assert sum(len(item["deliverables"]) for item in expected["offerings"]) == 104
    assert result["portfolio_version"] == "2.1"
    assert result["policy_version"] == "2.14.0"
    assert result["preflight_budget"]["passed"] is True
    assert result["preflight_budget"]["expected_cost_usd"] <= 15
    assert result["preflight_budget"]["conservative_cost_usd"] <= 30


def test_non_ai_delivery_modes_have_zero_tokens_and_cost() -> None:
    result = MODULE.simulate(pricing())
    deliverables = [
        deliverable
        for offering in result["topologies"]["current_runtime"]["expected"]["offerings"]
        for deliverable in offering["deliverables"]
    ]

    external = [item for item in deliverables if item["execution_mode"] in {"human", "integration"}]
    assert external
    assert all(item["usage"]["input_tokens"] == 0 for item in external)
    assert all(item["usage"]["output_tokens"] == 0 for item in external)
    assert all(item["usage"]["cost_usd"] == 0 for item in external)


def test_current_pilot_costs_six_full_runs_and_recommendation_shares_one() -> None:
    result = MODULE.simulate(pricing())
    current = next(
        item
        for item in result["topologies"]["current_runtime"]["expected"]["offerings"]
        if item["code"] == "ai_use_case_pilot_sprint"
    )
    recommended = next(
        item
        for item in result["topologies"]["recommended_shared"]["expected"]["offerings"]
        if item["code"] == "ai_use_case_pilot_sprint"
    )
    current_technical = [item for item in current["deliverables"] if item["execution_mode"] == "technical_run"]
    recommended_technical = [
        item for item in recommended["deliverables"] if item["execution_mode"] == "technical_run"
    ]

    assert len(current_technical) == 6
    unit_cost = current["technical_run_unit_cost"]["cost_usd"]
    assert all(item["usage"]["cost_usd"] == unit_cost for item in current_technical)
    assert round(sum(item["usage"]["cost_usd"] for item in recommended_technical), 5) == round(unit_cost, 5)


def test_v21_engineering_shares_one_materialized_technical_run() -> None:
    result = MODULE.simulate(pricing())
    current = next(
        item
        for item in result["topologies"]["current_runtime"]["expected"]["offerings"]
        if item["code"] == "ai_engineering_productivity_accelerator"
    )
    recommended = next(
        item
        for item in result["topologies"]["recommended_shared"]["expected"]["offerings"]
        if item["code"] == "ai_engineering_productivity_accelerator"
    )

    current_technical = [
        item for item in current["deliverables"] if item["execution_mode"] == "technical_run"
    ]
    recommended_technical = [
        item for item in recommended["deliverables"] if item["execution_mode"] == "technical_run"
    ]
    assert len(current_technical) == len(recommended_technical) == 2
    unit_cost = current["technical_run_unit_cost"]["cost_usd"]
    assert round(sum(item["usage"]["cost_usd"] for item in current_technical), 5) == round(unit_cost * 2, 5)
    assert round(sum(item["usage"]["cost_usd"] for item in recommended_technical), 5) == round(unit_cost, 5)
    assert recommended["total"]["cost_usd"] < current["total"]["cost_usd"]


def test_scenarios_are_monotonic_and_shared_topology_is_cheaper_for_portfolio() -> None:
    result = MODULE.simulate(pricing())
    current = result["topologies"]["current_runtime"]
    costs = [
        current[name]["portfolio_with_two_office_cycles"]["cost_usd"]
        for name in ("lean", "expected", "conservative")
    ]

    assert costs[0] < costs[1] < costs[2]
    assert (
        result["topologies"]["recommended_shared"]["expected"]["portfolio_with_two_office_cycles"]["cost_usd"]
        < current["expected"]["portfolio_with_two_office_cycles"]["cost_usd"]
    )


def test_rendered_report_mentions_zero_paid_calls_and_budgets_are_caps() -> None:
    rendered = MODULE.render_markdown(MODULE.simulate(pricing()))

    assert "nenhuma chamada de IA" in rendered
    assert "proteções de gasto" in rendered
    assert "AI Use Case Pilot" in rendered
