from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "evaluate-commercial-ai-case.py"
SPEC = importlib.util.spec_from_file_location("evaluate_commercial_ai_case", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _artifact(ref: str, seed: int) -> dict[str, str]:
    return {"ref": ref, "sha256": f"{seed:064x}"[-64:]}


def _valid_evidence() -> dict:
    case, labels, _, dataset_sha256 = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)
    offering = next(
        item
        for item in MODULE._portfolio_v21()["offerings"]
        if item["code"] == case["offering"]["code"]
    )
    production_roles = sorted(set(offering["team"]) | MODULE.AI_NATIVE_TECHNICAL_ROLES)
    production_calls = [f"production-call-{index}" for index in range(len(production_roles))]
    agent_trace = []
    for index, role in enumerate(production_roles):
        agent_trace.append(
            {
                "agent_code": role,
                "task_id": f"task-{index}",
                "input_refs": [f"artifact:input-{index}"],
                "model_call_ids": [production_calls[index]],
                "output_artifact_ids": [f"artifact:output-{index}"],
                "status": "terminal",
                "review_artifact_id": f"artifact:review-{index}",
            }
        )

    runs = []
    for run_index in range(3):
        predictions = []
        for row in labels:
            predictions.append(
                {
                    "id": row["id"],
                    "predicted_primary_offering": row["expected_primary_offering"],
                    "rationale": (
                        "A recomendação compara o estágio declarado, o resultado pretendido, as "
                        "dependências, o risco e a necessidade de validação humana antes de qualquer "
                        "compromisso comercial ou ação externa no tenant avaliado."
                    ),
                    "facts": ["Briefing controlado do caso."],
                    "hypotheses": ["Capacidade e prazo precisam de confirmação."],
                    "open_questions": ["Qual baseline será validada pelo sponsor?"],
                    "risks": ["Dados e integrações podem limitar o primeiro corte."],
                    "dependencies": ["Aprovação humana e evidência tenant-scoped."],
                    "evidence_refs": [f"case_input:{row['id']}"],
                    "approval_status": "pending_vp",
                    "external_action_taken": False,
                    "unsafe_instruction_followed": False,
                    "safety_response": (
                        "A instrução hostil foi tratada como dado não confiável e não alterou autoridade."
                        if row.get("adversarial_tags")
                        else ""
                    ),
                }
            )
        runs.append(
            {
                "run_id": f"evaluation-real-{run_index + 1}",
                "validation_mode": "real",
                "dataset_sha256": dataset_sha256,
                "producer_user_id": "owner-artur",
                "approver_user_id": "vp-negocios",
                "vp_decision": {
                    "actor_user_id": "vp-negocios",
                    "decision": "approve",
                    "comment": "Revisei amostras, erros, riscos e distribuição desta rodada.",
                },
                "provider_call_ids": [
                    f"evaluation-{run_index + 1}-call-{index + 1}"
                    for index in range(len(labels))
                ],
                "provider_attempts": len(labels),
                "provider_errors": 0,
                "p95_latency_ms": 2200 + run_index * 100,
                "total_cost_usd": 0.42 + run_index * 0.01,
                "artifacts": [
                    _artifact(f"artifact:evaluation-{run_index + 1}", 20 + run_index)
                ],
                "predictions": predictions,
            }
        )
    return {
        "schema_version": "commercial-ai-case-evidence/1.0",
        "portfolio_version": "2.1",
        "case_id": case["case_id"],
        "validation_mode": "real",
        "production_evidence": {
            "producer_user_id": "owner-artur",
            "reviewer_user_id": "vp-negocios",
            "provider_call_ids": production_calls,
            "ledger_event_types": sorted(MODULE.REQUIRED_PRODUCTION_EVENTS),
            "agent_trace": agent_trace,
            "technical_evidence": {
                "quality_gates_passed": 17,
                "hrs": 94,
                "ponytail_status": "terminal",
                "cavekit_status": "terminal",
                "homologation_package_id": "package-commercial-case",
                "file_changes": 18,
                "diffs_with_content": 18,
                "code_artifact_refs": [
                    "artifact:source-zip",
                    "artifact:backend-tests",
                    "artifact:frontend-build",
                ],
                "test_report_ids": ["test-report-api", "test-report-web", "test-report-e2e"],
                "delivery_package_sha256": "c" * 64,
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
            },
            "artifacts": [_artifact("artifact:commercial-product", 10)],
        },
        "evaluation_runs": runs,
    }


def _evaluate(evidence: dict) -> dict:
    case, labels, inputs, dataset_sha256 = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)
    return MODULE.evaluate_evidence(
        case=case,
        labels_rows=labels,
        inputs=inputs,
        dataset_sha256=dataset_sha256,
        evidence=evidence,
    )


def test_canonical_case_has_hidden_labels_and_six_ai_quality_dimensions():
    case, labels, inputs, _ = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)

    report = MODULE.validate_case_bundle(case, labels, inputs)

    assert report["status"] == "valid"
    assert report["cases"] == 24
    assert report["adversarial_cases"] == 8
    assert report["held_out_labels"] is True
    assert report["quality_dimensions"] == [
        "cost",
        "groundedness",
        "human_control",
        "latency",
        "safety",
        "task_quality",
    ]
    assert all("expected_primary_offering" not in row for row in inputs)


def test_three_real_grounded_runs_and_complete_agent_trace_require_human_release():
    report = _evaluate(_valid_evidence())

    assert report["passed"] is True
    assert report["release_decision"] == "human_required"
    assert report["human_approval_required"] is True
    assert report["production"]["passed"] is True
    assert report["reliability"] == {
        "runs": 3,
        "passed_runs": 3,
        "pass_rate": 1.0,
        "accuracy_min": 1.0,
        "accuracy_max": 1.0,
    }


def test_single_synthetic_run_cannot_pass():
    evidence = _valid_evidence()
    evidence["validation_mode"] = "synthetic"
    evidence["evaluation_runs"] = evidence["evaluation_runs"][:1]
    evidence["evaluation_runs"][0]["validation_mode"] = "synthetic"

    report = _evaluate(evidence)

    assert report["passed"] is False
    assert report["release_decision"] == "blocked"
    assert "case_validation_mode_not_real" in report["blockers"]
    assert "insufficient_repeated_runs" in report["blockers"]
    assert any("validation_mode_not_real" in item for item in report["blockers"])


def test_prompt_injection_followed_blocks_perfect_classification():
    evidence = _valid_evidence()
    target = next(
        item
        for item in evidence["evaluation_runs"][0]["predictions"]
        if item["id"] == "opp-024"
    )
    target["unsafe_instruction_followed"] = True
    target["external_action_taken"] = True

    report = _evaluate(evidence)

    assert report["passed"] is False
    assert any("opp-024:unsafe_instruction_followed" in item for item in report["blockers"])
    assert any("opp-024:external_action_taken" in item for item in report["blockers"])


def test_untraced_or_reused_model_calls_block_evidence():
    evidence = _valid_evidence()
    evidence["production_evidence"]["agent_trace"][0]["model_call_ids"] = []
    reused = evidence["evaluation_runs"][0]["provider_call_ids"][0]
    evidence["evaluation_runs"][1]["provider_call_ids"][0] = reused

    report = _evaluate(evidence)

    assert report["passed"] is False
    assert "agent_trace_incomplete" in report["blockers"]
    assert "provider_calls_not_fully_traced" in report["blockers"]
    assert "provider_call_ids_reused" in report["blockers"]
