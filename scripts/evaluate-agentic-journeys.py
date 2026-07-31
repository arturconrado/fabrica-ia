#!/usr/bin/env python3
"""Validate repeated, provider-real evidence for the eight portfolio journeys.

This evaluator never calls a model and never approves a deliverable. It scores
persisted run evidence against the immutable catalog, the realistic scenario
pack and deterministic delivery contracts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_SCENARIOS = (
    REPO_ROOT / "homologation" / "cases" / "portfolio-v2" / "realistic-agentic-journeys.json"
)
REQUIRED_LEDGER_EVENTS = {
    "service_deliverable.revision_created",
    "service_deliverable.submitted",
    "service_deliverable.approved",
    "service_deliverable.delivered",
}
REQUIRED_PROBE_LEDGER_EVENTS = {
    "service_deliverable.revision_created",
    "service_deliverable.submitted",
}
AI_NATIVE_QUALITY_DIMENSIONS = {
    "task_quality",
    "groundedness",
    "safety",
    "human_control",
    "latency",
    "cost",
}
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.production_pipeline_provider import AGENT_ROLES  # noqa: E402
from app.service_delivery.catalog import _portfolio_v2, _portfolio_v21  # noqa: E402
from app.service_delivery.deliverable_quality import (  # noqa: E402
    aggregate_repeated_evaluations,
    evaluate_deliverable_contract,
)
from release_evidence import enrich_release_report  # noqa: E402

AI_NATIVE_TECHNICAL_ROLES = set(AGENT_ROLES) - {"Human Approval"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "evaluate"))
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--portfolio-version",
        choices=("2.0", "2.1"),
        default="2.1",
        help="Contract catalog used to validate the evidence (default: 2.1)",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def _portfolio(version: str) -> dict[str, Any]:
    if version == "2.0":
        return _portfolio_v2()
    if version == "2.1":
        return _portfolio_v21()
    raise RuntimeError(f"Unsupported portfolio version {version!r}")


def validate_scenarios(
    payload: dict[str, Any], *, portfolio_version: str = "2.1"
) -> dict[str, Any]:
    if payload.get("schema_version") != "agentic-journey-scenarios/1.0":
        raise RuntimeError("Unsupported realistic journey scenario schema")
    scenarios = payload.get("scenarios") or []
    if len(scenarios) != 8:
        raise RuntimeError("The realistic journey pack must contain exactly eight scenarios")
    scenario_ids = [str(item.get("id") or "") for item in scenarios]
    offering_codes = [str(item.get("offering_code") or "") for item in scenarios]
    if len(set(scenario_ids)) != 8 or any(not item for item in scenario_ids):
        raise RuntimeError("Every realistic journey requires a unique non-empty id")
    if len(set(offering_codes)) != 8:
        raise RuntimeError(
            f"Every Portfolio {portfolio_version} offering must have exactly one realistic journey"
        )

    catalog = {item["code"]: item for item in _portfolio(portfolio_version)["offerings"]}
    if set(offering_codes) != set(catalog):
        raise RuntimeError(
            f"Realistic journeys do not cover the exact Portfolio {portfolio_version} offering set"
        )
    errors: list[str] = []
    for scenario in scenarios:
        code = scenario["offering_code"]
        offering = catalog[code]
        expected_roles = set(scenario.get("expected_roles") or [])
        actual_roles = set(offering.get("team") or [])
        if expected_roles != actual_roles:
            errors.append(f"{scenario['id']}: expected_roles differ from catalog team")
        expected_modes = set(scenario.get("expected_modes") or [])
        process_modes = {str(item.get("mode") or "") for item in offering.get("process") or []}
        if expected_modes != process_modes:
            errors.append(f"{scenario['id']}: expected_modes differ from contracted process modes")
        probe_template_key = str(scenario.get("probe_template_key") or "")
        probe_template = next(
            (
                item
                for item in offering.get("deliverable_templates") or []
                if item.get("key") == probe_template_key
            ),
            None,
        )
        if not probe_template or probe_template.get("execution_mode") != "agent":
            errors.append(f"{scenario['id']}: probe_template_key must select an agent deliverable")
        for field in (
            "customer",
            "brief",
            "source_facts",
            "specificity_terms",
            "forbidden_claims",
            "adversarial_source",
            "ai_system",
        ):
            if not scenario.get(field):
                errors.append(f"{scenario['id']}: missing {field}")
        ai_system = scenario.get("ai_system") or {}
        for field in (
            "use_case",
            "decision_supported",
            "grounding_sources",
            "human_controls",
            "evaluation_dimensions",
            "failure_modes",
            "prohibited_autonomy",
            "minimum_evaluation_cases",
        ):
            if not ai_system.get(field):
                errors.append(f"{scenario['id']}: ai_system missing {field}")
        if set(ai_system.get("evaluation_dimensions") or []) != AI_NATIVE_QUALITY_DIMENSIONS:
            errors.append(f"{scenario['id']}: ai_system quality dimensions are incomplete")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "status": "valid",
        "portfolio_version": portfolio_version,
        "schema_version": payload["schema_version"],
        "scenarios": len(scenarios),
        "offering_codes": sorted(offering_codes),
        "minimum_repeated_runs": int(payload.get("minimum_repeated_runs") or 3),
        "minimum_contract_pass_rate": float(payload.get("minimum_contract_pass_rate") or 0.8),
    }


def _technical_checks(
    run: dict[str, Any],
    expected_modes: set[str],
    *,
    portfolio_version: str = "2.1",
    technical_group: dict[str, Any] | None = None,
) -> list[str]:
    if "technical_run" not in expected_modes:
        evidence = run.get("technical_evidence") or {}
        if portfolio_version == "2.1" and any(
            int(evidence.get(field) or 0) > 0
            for field in ("workflow_run_count", "service_execution_count", "workflow_slot_count")
        ):
            return ["artificial_technical_run_for_non_technical_offering"]
        return []
    evidence = run.get("technical_evidence") or {}
    blockers: list[str] = []
    if int(evidence.get("quality_gates_passed") or 0) != 17:
        blockers.append("technical_quality_gates_not_17")
    if float(evidence.get("hrs") or 0.0) < 90:
        blockers.append("technical_hrs_below_90")
    if evidence.get("ponytail_status") != "terminal":
        blockers.append("ponytail_not_terminal")
    if evidence.get("cavekit_status") != "terminal":
        blockers.append("cavekit_not_terminal")
    if not evidence.get("homologation_package_id"):
        blockers.append("technical_homologation_package_missing")
    file_changes = int(evidence.get("file_changes") or 0)
    if file_changes <= 0:
        blockers.append("technical_file_changes_missing")
    if int(evidence.get("diffs_with_content") or 0) != file_changes:
        blockers.append("technical_file_change_diffs_incomplete")
    if not evidence.get("code_artifact_refs"):
        blockers.append("technical_code_artifacts_missing")
    if not evidence.get("test_report_ids"):
        blockers.append("technical_test_reports_missing")
    delivery_sha256 = str(evidence.get("delivery_package_sha256") or "")
    if not HEX_SHA256.fullmatch(delivery_sha256):
        blockers.append("technical_delivery_package_hash_invalid")
    if portfolio_version == "2.1":
        expected_operation_key = str((technical_group or {}).get("key") or "")
        if evidence.get("workflow_version") != "2.14.0":
            blockers.append("technical_workflow_version_not_2_14_0")
        if int(evidence.get("workflow_run_count") or 0) != 1:
            blockers.append("technical_workflow_run_count_not_one")
        if int(evidence.get("service_execution_count") or 0) != 1:
            blockers.append("technical_service_execution_count_not_one")
        if int(evidence.get("workflow_slot_count") or 0) != 1:
            blockers.append("technical_workflow_slot_count_not_one")
        if not expected_operation_key or evidence.get("operation_key") != expected_operation_key:
            blockers.append("technical_operation_key_mismatch")
        authored_roles = set(evidence.get("authored_roles") or [])
        if not {"Engineer", "QA Engineer", "DevOps Engineer"}.issubset(authored_roles):
            blockers.append("technical_code_authorship_incomplete")
        if not evidence.get("qa_test_files"):
            blockers.append("technical_qa_test_files_missing")
        if not evidence.get("devops_files"):
            blockers.append("technical_devops_files_missing")
        if not AI_NATIVE_TECHNICAL_ROLES.issubset(
            set(evidence.get("terminal_agent_roles") or [])
        ):
            blockers.append("technical_eighteen_roles_incomplete")
        if not AI_NATIVE_TECHNICAL_ROLES.issubset(
            set(evidence.get("terminal_ponytail_roles") or [])
        ) or not AI_NATIVE_TECHNICAL_ROLES.issubset(
            set(evidence.get("terminal_cavekit_roles") or [])
        ):
            blockers.append("technical_per_role_plugin_evidence_incomplete")
    return blockers


def _agent_trace_checks(
    run: dict[str, Any],
    *,
    expected_roles: set[str],
) -> list[str]:
    traces = run.get("agent_trace") or []
    if not isinstance(traces, list) or not traces:
        return ["agent_trace_missing"]
    blockers: list[str] = []
    traced_roles: set[str] = set()
    traced_model_calls: set[str] = set()
    for trace in traces:
        if not isinstance(trace, dict):
            blockers.append("agent_trace_invalid")
            continue
        agent_code = str(trace.get("agent_code") or "")
        traced_roles.add(agent_code)
        traced_model_calls.update(
            str(item)
            for item in (trace.get("model_call_ids") or [])
            if str(item)
        )
        if (
            not agent_code
            or not str(trace.get("task_id") or "")
            or trace.get("status") != "terminal"
            or not trace.get("input_refs")
            or not trace.get("output_artifact_ids")
            or not str(trace.get("review_artifact_id") or "")
        ):
            blockers.append("agent_trace_incomplete")
    if not expected_roles.issubset(traced_roles):
        blockers.append("contracted_agent_roles_not_traced")
    provider_call_ids = {
        str(item) for item in (run.get("provider_call_ids") or []) if str(item)
    }
    if traced_model_calls != provider_call_ids:
        blockers.append("provider_calls_not_fully_traced")
    return blockers


def _ai_system_evaluation_checks(
    run: dict[str, Any],
    *,
    profile: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    evidence = run.get("ai_system_evaluation") or {}
    blockers: list[str] = []
    if not str(evidence.get("evaluation_id") or ""):
        blockers.append("ai_evaluation_id_missing")
    if not str(evidence.get("dataset_id") or ""):
        blockers.append("ai_evaluation_dataset_missing")
    if not HEX_SHA256.fullmatch(str(evidence.get("dataset_sha256") or "")):
        blockers.append("ai_evaluation_dataset_hash_invalid")
    sample_count = int(evidence.get("sample_count") or 0)
    if sample_count < int(profile.get("minimum_evaluation_cases") or 0):
        blockers.append("ai_evaluation_sample_too_small")
    metrics = evidence.get("metrics") or {}
    metric_results: dict[str, Any] = {}
    for dimension in profile.get("evaluation_dimensions") or []:
        metric = metrics.get(dimension) if isinstance(metrics, dict) else None
        if not isinstance(metric, dict):
            blockers.append(f"ai_metric_missing:{dimension}")
            continue
        try:
            value = float(metric["value"])
            threshold = float(metric["threshold"])
        except (KeyError, TypeError, ValueError):
            blockers.append(f"ai_metric_invalid:{dimension}")
            continue
        direction = str(metric.get("direction") or "")
        if direction == "gte":
            passed = value >= threshold
        elif direction == "lte":
            passed = value <= threshold
        else:
            blockers.append(f"ai_metric_direction_invalid:{dimension}")
            continue
        metric_results[dimension] = {
            "value": value,
            "threshold": threshold,
            "direction": direction,
            "passed": passed,
        }
        if not passed:
            blockers.append(f"ai_metric_failed:{dimension}")
    if not set(profile.get("failure_modes") or []).issubset(
        set(evidence.get("tested_failure_modes") or [])
    ):
        blockers.append("ai_failure_modes_not_covered")
    if not set(profile.get("human_controls") or []).issubset(
        set(evidence.get("human_controls_tested") or [])
    ):
        blockers.append("ai_human_controls_not_tested")
    if int(evidence.get("prohibited_autonomy_violations") or 0) != 0:
        blockers.append("ai_prohibited_autonomy_violation")
    artifacts = evidence.get("artifacts") or []
    if not isinstance(artifacts, list) or not artifacts:
        blockers.append("ai_evaluation_artifacts_missing")
    elif any(
        not isinstance(item, dict)
        or not str(item.get("ref") or "")
        or not HEX_SHA256.fullmatch(str(item.get("sha256") or ""))
        for item in artifacts
    ):
        blockers.append("ai_evaluation_artifact_manifest_invalid")
    return blockers, {
        "evaluation_id": str(evidence.get("evaluation_id") or ""),
        "sample_count": sample_count,
        "metrics": metric_results,
    }


def evaluate_evidence(
    *,
    scenarios_payload: dict[str, Any],
    evidence_payload: dict[str, Any],
    portfolio_version: str = "2.1",
) -> dict[str, Any]:
    validation = validate_scenarios(
        scenarios_payload, portfolio_version=portfolio_version
    )
    if evidence_payload.get("schema_version") != "agentic-journey-evidence/1.0":
        raise RuntimeError("Unsupported agentic journey evidence schema")
    if evidence_payload.get("portfolio_version") != portfolio_version:
        raise RuntimeError(
            f"Evidence portfolio_version must be {portfolio_version}"
        )
    expected_run_id = os.getenv("ASF_PRODUCTION_E2E_RUN_ID", "").strip()
    evidence_run_id = str(evidence_payload.get("production_e2e_run_id") or "")
    scenarios = {
        item["id"]: item
        for item in scenarios_payload["scenarios"]
    }
    catalog = {
        item["code"]: item for item in _portfolio(portfolio_version)["offerings"]
    }
    runs = evidence_payload.get("runs") or []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    run_reports: list[dict[str, Any]] = []

    for run in runs:
        scenario_id = str(run.get("scenario_id") or "")
        scenario = scenarios.get(scenario_id)
        if not scenario:
            raise RuntimeError(f"Evidence references unknown scenario {scenario_id!r}")
        offering = catalog[scenario["offering_code"]]
        templates = {
            item["key"]: item
            for item in offering.get("deliverable_templates") or []
        }
        delivered = run.get("deliverables") or []
        delivered_keys = [str(item.get("template_key") or "") for item in delivered]
        blockers: list[str] = []
        run_kind = str(run.get("run_kind") or "full_journey")
        if run_kind not in {"full_journey", "repeat_probe"}:
            blockers.append("unsupported_run_kind")
        required_template_keys = (
            set(templates)
            if run_kind == "full_journey"
            else {str(scenario.get("probe_template_key") or "")}
        )
        if (
            set(delivered_keys) != required_template_keys
            or len(delivered_keys) != len(set(delivered_keys))
        ):
            blockers.append("contracted_deliverable_coverage_incomplete")
        if run.get("validation_mode") != "real":
            blockers.append("validation_mode_not_real")
        if not run.get("provider_call_ids"):
            blockers.append("provider_calls_missing")
        producer_user_id = str(run.get("producer_user_id") or "")
        approver_user_id = str(run.get("approver_user_id") or "")
        if (
            not producer_user_id
            or not approver_user_id
            or producer_user_id == approver_user_id
        ):
            blockers.append("four_eyes_identity_not_distinct")
        ledger_events = set(run.get("ledger_event_types") or [])
        required_ledger_events = (
            REQUIRED_LEDGER_EVENTS
            if run_kind == "full_journey"
            else REQUIRED_PROBE_LEDGER_EVENTS
        )
        missing_events = sorted(required_ledger_events - ledger_events)
        if missing_events:
            blockers.append("required_ledger_events_missing")
        execution_modes = set(run.get("execution_modes") or [])
        expected_modes = set(scenario.get("expected_modes") or [])
        required_execution_modes = expected_modes if run_kind == "full_journey" else {"agent"}
        if execution_modes != required_execution_modes:
            blockers.append("contracted_process_modes_not_executed")
        if run_kind == "full_journey":
            groups = offering.get("technical_run_groups") or []
            blockers.extend(
                _technical_checks(
                    run,
                    expected_modes,
                    portfolio_version=portfolio_version,
                    technical_group=groups[0] if len(groups) == 1 else None,
                )
            )
            blockers.extend(
                _agent_trace_checks(
                    run,
                    expected_roles=(
                        set(scenario.get("expected_roles") or [])
                        | (AI_NATIVE_TECHNICAL_ROLES if "technical_run" in expected_modes else set())
                    ),
                )
            )
            ai_blockers, ai_evaluation = _ai_system_evaluation_checks(
                run,
                profile=scenario.get("ai_system") or {},
            )
            blockers.extend(ai_blockers)
        else:
            ai_evaluation = {}

        evaluations: list[dict[str, Any]] = []
        peer_markdowns = [
            str((item.get("content") or {}).get("content_markdown") or "")
            for item in delivered
        ]
        for deliverable_index, deliverable in enumerate(delivered):
            template_key = str(deliverable.get("template_key") or "")
            template = templates.get(template_key)
            if not template:
                continue
            content = deliverable.get("content") or {}
            markdown = str(content.get("content_markdown") or "")
            evaluation = evaluate_deliverable_contract(
                content=content,
                template=template,
                evidence_refs=list(deliverable.get("evidence_refs") or []),
                verified_evidence_refs=list(deliverable.get("verified_evidence_refs") or []),
                peer_markdowns=[
                    item
                    for peer_index, item in enumerate(peer_markdowns)
                    if peer_index != deliverable_index
                ],
                specificity_terms=scenario.get("specificity_terms") or [],
                forbidden_claims=scenario.get("forbidden_claims") or [],
            )
            if str(deliverable.get("producer_agent_code") or "") != str(template.get("responsible") or ""):
                evaluation = {
                    **evaluation,
                    "passed": False,
                    "failures": [*evaluation["failures"], "wrong_responsible_agent"],
                }
            if not evaluation["passed"]:
                blockers.append(f"deliverable_contract_failed:{template_key}")
            evaluations.append(
                {
                    "template_key": template_key,
                    "markdown": markdown,
                    "evaluation": evaluation,
                }
            )

        report = {
            "scenario_id": scenario_id,
            "run_id": str(run.get("run_id") or ""),
            "run_kind": run_kind,
            "offering_code": scenario["offering_code"],
            "passed": not blockers,
            "blockers": sorted(set(blockers)),
            "deliverables": evaluations,
            "model_calls": len(run.get("provider_call_ids") or []),
            "ai_system_evaluation": ai_evaluation,
            "human_approval_required": True,
        }
        run_reports.append(report)
        grouped[scenario_id].append(report)

    repeated_reports: list[dict[str, Any]] = []
    minimum_runs = validation["minimum_repeated_runs"]
    minimum_pass_rate = validation["minimum_contract_pass_rate"]
    for scenario_id in scenarios:
        scenario_runs = grouped.get(scenario_id, [])
        repeated = aggregate_repeated_evaluations(
            [
                {
                    "evaluation": {
                        "passed": item["passed"],
                        "score": (
                            sum(
                                float(deliverable["evaluation"]["score"])
                                for deliverable in item["deliverables"]
                            )
                            / len(item["deliverables"])
                            if item["deliverables"]
                            else 0.0
                        ),
                    },
                    "markdown": "\n".join(
                        deliverable["markdown"]
                        for deliverable in item["deliverables"]
                    ),
                }
                for item in scenario_runs
            ],
            minimum_runs=minimum_runs,
            minimum_pass_rate=minimum_pass_rate,
        )
        full_runs = [
            item
            for item in scenario_runs
            if item["run_kind"] == "full_journey" and item["passed"]
        ]
        if not full_runs:
            repeated = {
                **repeated,
                "passed": False,
                "blockers": [*repeated["blockers"], "full_journey_missing_or_failed"],
            }
        repeated_reports.append({"scenario_id": scenario_id, **repeated})

    blockers = [
        f"{item['scenario_id']}:{blocker}"
        for item in repeated_reports
        for blocker in item["blockers"]
    ]
    blockers.extend(
        f"{item['scenario_id']}:{blocker}"
        for item in run_reports
        for blocker in item["blockers"]
    )
    if expected_run_id and evidence_run_id != expected_run_id:
        blockers.append("production_e2e_run_id_mismatch")
    return {
        "schema_version": "agentic-journey-evaluation-report/1.0",
        "portfolio_version": portfolio_version,
        "production_e2e_run_id": evidence_run_id,
        "passed": not blockers,
        "release_decision": "human_required" if not blockers else "blocked",
        "scenario_validation": validation,
        "runs": run_reports,
        "repeated_evaluations": repeated_reports,
        "blockers": sorted(set(blockers)),
        "human_approval_required": True,
    }


def main() -> int:
    started_monotonic = time.monotonic()
    args = parse_args()
    scenarios_payload = load_json(args.scenarios.resolve())
    if args.action == "validate":
        report = validate_scenarios(
            scenarios_payload, portfolio_version=args.portfolio_version
        )
    else:
        if not args.evidence:
            raise RuntimeError("--evidence is required for evaluate")
        report = evaluate_evidence(
            scenarios_payload=scenarios_payload,
            evidence_payload=load_json(args.evidence.resolve()),
            portfolio_version=args.portfolio_version,
        )
        report = enrich_release_report(
            report,
            repo_root=REPO_ROOT,
            command="evaluate-agentic-journeys.py evaluate",
            started_monotonic=started_monotonic,
            artifact_paths=(args.scenarios, args.evidence),
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("passed", report.get("status") == "valid") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"agentic journey evaluation failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
