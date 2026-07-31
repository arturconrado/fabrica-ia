from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "evaluate-agentic-journeys.py"
SPEC = importlib.util.spec_from_file_location("evaluate_agentic_journeys", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_realistic_scenarios_cover_catalog_teams_process_modes_and_adversarial_sources():
    payload = MODULE.load_json(MODULE.DEFAULT_SCENARIOS)

    result = MODULE.validate_scenarios(payload)

    assert result["status"] == "valid"
    assert result["scenarios"] == 8
    assert result["minimum_repeated_runs"] == 3
    assert len(result["offering_codes"]) == 8
    assert all(
        scenario["adversarial_source"]
        and scenario["forbidden_claims"]
        and scenario["specificity_terms"]
        and set(scenario["ai_system"]["evaluation_dimensions"])
        == MODULE.AI_NATIVE_QUALITY_DIMENSIONS
        for scenario in payload["scenarios"]
    )


def test_no_single_synthetic_run_can_claim_agentic_journey_homologation():
    scenarios = MODULE.load_json(MODULE.DEFAULT_SCENARIOS)
    first = scenarios["scenarios"][0]
    evidence = {
        "schema_version": "agentic-journey-evidence/1.0",
        "portfolio_version": "2.1",
        "runs": [
            {
                "scenario_id": first["id"],
                "run_id": "synthetic-one",
                "validation_mode": "synthetic",
                "provider_call_ids": [],
                "producer_user_id": "owner",
                "approver_user_id": "owner",
                "ledger_event_types": [],
                "execution_modes": ["agent"],
                "deliverables": [],
            }
        ],
    }

    report = MODULE.evaluate_evidence(
        scenarios_payload=scenarios,
        evidence_payload=evidence,
    )

    run = report["runs"][0]
    assert report["passed"] is False
    assert report["release_decision"] == "blocked"
    assert {
        "contracted_deliverable_coverage_incomplete",
        "validation_mode_not_real",
        "provider_calls_missing",
        "four_eyes_identity_not_distinct",
        "required_ledger_events_missing",
        "contracted_process_modes_not_executed",
    }.issubset(run["blockers"])
    assert all(
        "insufficient_repeated_runs" in item["blockers"]
        for item in report["repeated_evaluations"]
    )


def test_one_full_journey_plus_two_real_probes_satisfies_repetition_for_one_scenario():
    scenarios = MODULE.load_json(MODULE.DEFAULT_SCENARIOS)
    scenario = scenarios["scenarios"][0]
    offering = next(
        item
        for item in MODULE._portfolio_v2()["offerings"]
        if item["code"] == scenario["offering_code"]
    )

    def deliverable(template, index: int):
        unique_terms = " ".join(f"dimensao{index}{letter}" for letter in "abcdefghij")
        content = {
            "title": f"{template['title']} — AtlasLog",
            "content_markdown": (
                f"# {template['title']} — AtlasLog\n\n"
                "## Objetivo\n\nAvaliar a decisão da AtlasLog com dados rastreáveis e revisão humana do VP.\n\n"
                "## Conteúdo\n\nA operação possui 14 centros e avalia roteirização, atendimento e manutenção. "
                f"Este entregável cobre especificamente {template['title']} e {unique_terms}. A análise separa "
                "fatos fornecidos, hipóteses, dependências e limites sem declarar benefício futuro.\n\n"
                "## Evidências\n\nO contexto vem do artifact tenant-scoped verificado para esta rodada.\n\n"
                "## Riscos e limitações\n\nBaseline financeiro, entrevistas e integrações ainda dependem de "
                "evidência real e não podem ser tratados como conclusão.\n\n"
                "## Próximos passos\n\nO owner confere a proveniência e o VP decide com comentário explícito.\n"
            ),
            "evidence_claims": ["A AtlasLog informou 14 centros e roteirização no escopo."],
            "risks": ["O baseline financeiro ainda não foi validado."],
            "next_actions": ["Revisão independente do VP."],
        }
        return {
            "template_key": template["key"],
            "producer_agent_code": template["responsible"],
            "content": content,
            "evidence_refs": ["artifact:atlaslog-source"],
            "verified_evidence_refs": ["artifact:atlaslog-source"],
        }

    common = {
        "scenario_id": scenario["id"],
        "validation_mode": "real",
        "producer_user_id": "owner",
        "approver_user_id": "vp",
        "provider_call_ids": ["model-call-one"],
    }
    full = {
        **common,
        "run_id": "atlaslog-full",
        "run_kind": "full_journey",
        "ledger_event_types": sorted(MODULE.REQUIRED_LEDGER_EVENTS),
        "execution_modes": scenario["expected_modes"],
        "deliverables": [
            deliverable(template, index)
            for index, template in enumerate(offering["deliverable_templates"], start=1)
        ],
        "agent_trace": [
            {
                "agent_code": role,
                "task_id": f"atlaslog-task-{index}",
                "input_refs": ["artifact:atlaslog-source"],
                "model_call_ids": ["model-call-one"] if index == 1 else [],
                "output_artifact_ids": [f"artifact:atlaslog-output-{index}"],
                "review_artifact_id": f"artifact:atlaslog-review-{index}",
                "status": "terminal",
            }
            for index, role in enumerate(scenario["expected_roles"], start=1)
        ],
        "ai_system_evaluation": {
            "evaluation_id": "atlaslog-ai-eval-1",
            "dataset_id": "atlaslog-opportunity-ranking-v1",
            "dataset_sha256": "a" * 64,
            "sample_count": 12,
            "metrics": {
                "task_quality": {"value": 0.92, "threshold": 0.9, "direction": "gte"},
                "groundedness": {"value": 0.96, "threshold": 0.9, "direction": "gte"},
                "safety": {"value": 1.0, "threshold": 1.0, "direction": "gte"},
                "human_control": {"value": 1.0, "threshold": 1.0, "direction": "gte"},
                "latency": {"value": 2200, "threshold": 5000, "direction": "lte"},
                "cost": {"value": 0.41, "threshold": 2.0, "direction": "lte"},
            },
            "tested_failure_modes": scenario["ai_system"]["failure_modes"],
            "human_controls_tested": scenario["ai_system"]["human_controls"],
            "prohibited_autonomy_violations": 0,
            "artifacts": [
                {"ref": "artifact:atlaslog-evaluation", "sha256": "b" * 64}
            ],
        },
    }
    probe_template = next(
        item
        for item in offering["deliverable_templates"]
        if item["key"] == scenario["probe_template_key"]
    )
    probes = [
        {
            **common,
            "run_id": f"atlaslog-probe-{index}",
            "run_kind": "repeat_probe",
            "provider_call_ids": [f"model-call-probe-{index}"],
            "ledger_event_types": sorted(MODULE.REQUIRED_PROBE_LEDGER_EVENTS),
            "execution_modes": ["agent"],
            "deliverables": [deliverable(probe_template, 20 + index)],
        }
        for index in (1, 2)
    ]

    report = MODULE.evaluate_evidence(
        scenarios_payload=scenarios,
        evidence_payload={
            "schema_version": "agentic-journey-evidence/1.0",
            "portfolio_version": "2.1",
            "runs": [full, *probes],
        },
    )

    atlaslog = next(
        item
        for item in report["repeated_evaluations"]
        if item["scenario_id"] == scenario["id"]
    )
    assert all(item["passed"] for item in report["runs"])
    assert atlaslog["passed"] is True
    assert atlaslog["runs"] == 3
    assert atlaslog["pass_rate"] == 1.0
    assert report["passed"] is False  # the other seven real journeys remain absent


def test_full_journey_without_ai_system_evaluation_or_agent_trace_is_blocked():
    scenarios = MODULE.load_json(MODULE.DEFAULT_SCENARIOS)
    scenario = scenarios["scenarios"][0]

    report = MODULE.evaluate_evidence(
        scenarios_payload=scenarios,
        evidence_payload={
            "schema_version": "agentic-journey-evidence/1.0",
            "portfolio_version": "2.1",
            "runs": [
                {
                    "scenario_id": scenario["id"],
                    "run_id": "structure-only",
                    "run_kind": "full_journey",
                    "validation_mode": "real",
                    "provider_call_ids": ["untraced-call"],
                    "producer_user_id": "owner",
                    "approver_user_id": "vp",
                    "ledger_event_types": sorted(MODULE.REQUIRED_LEDGER_EVENTS),
                    "execution_modes": scenario["expected_modes"],
                    "deliverables": [],
                }
            ],
        },
    )

    blockers = report["runs"][0]["blockers"]
    assert "agent_trace_missing" in blockers
    assert "ai_evaluation_dataset_missing" in blockers
    assert "ai_evaluation_artifacts_missing" in blockers
    assert any(item.startswith("ai_metric_missing:") for item in blockers)


def test_technical_journey_requires_code_diffs_tests_and_hashed_delivery_package():
    valid = {
        "technical_evidence": {
            "quality_gates_passed": 17,
            "hrs": 93,
            "ponytail_status": "terminal",
            "cavekit_status": "terminal",
            "homologation_package_id": "package-mvp",
            "file_changes": 24,
            "diffs_with_content": 24,
            "code_artifact_refs": ["artifact:source", "artifact:tests"],
            "test_report_ids": ["report:unit", "report:e2e"],
            "delivery_package_sha256": "d" * 64,
            "workflow_version": "2.14.0",
            "workflow_run_count": 1,
            "service_execution_count": 1,
            "workflow_slot_count": 1,
            "operation_key": "software_product",
            "authored_roles": ["Engineer", "QA Engineer", "DevOps Engineer"],
            "qa_test_files": ["generated_app/backend/tests/test_api.py"],
            "devops_files": ["generated_app/docker-compose.yml"],
            "terminal_agent_roles": sorted(MODULE.AI_NATIVE_TECHNICAL_ROLES),
            "terminal_ponytail_roles": sorted(MODULE.AI_NATIVE_TECHNICAL_ROLES),
            "terminal_cavekit_roles": sorted(MODULE.AI_NATIVE_TECHNICAL_ROLES),
        }
    }

    assert MODULE._technical_checks(
        valid,
        {"technical_run"},
        technical_group={"key": "software_product"},
    ) == []

    invalid = {
        "technical_evidence": {
            "quality_gates_passed": 17,
            "hrs": 93,
            "ponytail_status": "terminal",
            "cavekit_status": "terminal",
            "homologation_package_id": "package-mvp",
            "file_changes": 3,
            "diffs_with_content": 2,
        }
    }
    blockers = MODULE._technical_checks(
        invalid,
        {"technical_run"},
        technical_group={"key": "software_product"},
    )
    assert "technical_file_change_diffs_incomplete" in blockers
    assert "technical_code_artifacts_missing" in blockers
    assert "technical_test_reports_missing" in blockers
    assert "technical_delivery_package_hash_invalid" in blockers
