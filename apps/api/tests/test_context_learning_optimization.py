from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.agents.ai_native_context import TenantContextBuilder
from app.agents.ai_native_contracts import ContextPolicy
from app.agents.ai_native_executor import AINativeWorkflowExecutor
from app.agents.ai_native_executor import apply_unified_patch
from app.api.routes_runs import get_token_analysis
from app.api.routes_ai_cost import ai_cost_analysis, ai_invocation_detail
from app.auth.dependencies import Principal, ensure_tenant
from app.db.session import set_tenant_context
from app.learning.optimization_service import (
    LearningOptimizationError,
    LearningOptimizationService,
    anonymize_abstract_pattern,
)
from app.learning.reward_service import reward_from_rating
from app.models import (
    AIInvocation,
    AgentStepExecution,
    Artifact,
    Base,
    ContextBuild,
    GlobalLearningEvidence,
    LearningLesson,
    LearningPolicy,
    ModelCall,
    Project,
    WorkflowNodeState,
    WorkflowRun,
    utcnow,
)
from app.providers.model_gateway import request_max_output_tokens
from app.schemas.operational import AICostAnalysisResponse, AIInvocationDetailResponse, TokenAnalysisResponse
from app.workflow.cost_policy_compiler import compile_cost_policy_workflow, load_frozen_v211_workflow


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _run(db, tenant_id: str, run_id: str) -> WorkflowRun:
    ensure_tenant(db, tenant_id, tenant_id)
    project = Project(id=f"project-{run_id}", tenant_id=tenant_id, name=f"Project {run_id}")
    run = WorkflowRun(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project.id,
        workflow_id="software_factory_ai_native_v2",
        generation_mode="ai_native_v2",
        demand="Create a tenant-scoped operational service",
        status="running",
        current_node="Architect",
        current_phase="architecture",
    )
    db.add_all([project, run])
    db.commit()
    return run


def test_workflow_v212_has_explicit_context_and_output_budget_for_every_agent():
    document = yaml.safe_load(Path("../../workflows/software_factory_ai_native_v2.yaml").read_text())
    graph = document["graph"]
    assert graph["version"] == "2.12.0"
    agents = [node for node in graph["nodes"] if node["type"] == "agent"]
    assert agents
    for node in agents:
        assert node["max_output_tokens"] > 0
        policy = ContextPolicy.model_validate(node["context_policy"])
        assert policy.version == "2.12.0"
        assert policy.input_budget_tokens >= 1000
    engineer = next(node for node in agents if node["id"] == "Engineer")
    assert engineer["max_output_tokens"] == 32_000


def test_v213_compiler_preserves_v212_and_applies_bounded_role_policies():
    base = yaml.safe_load(Path("../../workflows/software_factory_ai_native_v2.yaml").read_text())["graph"]
    candidate = yaml.safe_load(compile_cost_policy_workflow())["graph"]
    assert base["version"] == "2.12.0"
    assert candidate["version"] == "2.13.0"
    assert candidate["execution"]["cost_policy_version"] == "2.13.0"
    agents = [node for node in candidate["nodes"] if node["type"] == "agent"]
    assert agents
    for node in agents:
        policy = ContextPolicy.model_validate(node["context_policy"])
        assert policy.version == "2.13.0"
        assert policy.max_selected_references <= 24
        assert node["output_budget_policy"]["method"] == "frozen-p95-valid-plus-20-percent"
    engineer = next(node for node in agents if node["id"] == "Engineer")
    demand = next(node for node in agents if node["id"] == "Demand Classifier")
    quality = next(node for node in agents if node["id"] == "Quality Governor")
    assert engineer["max_output_tokens"] == 32_000
    assert engineer["context_policy"]["input_budget_tokens"] == 40_000
    assert demand["reserved_budget_usd"] == 6.0
    assert quality["reserved_budget_usd"] == 0.0


def test_frozen_v211_baseline_loads_without_database_history():
    baseline = yaml.safe_load(load_frozen_v211_workflow())["graph"]
    assert baseline["id"] == "software_factory_ai_native_v2"
    assert baseline["version"] == "2.11.0"
    assert any(edge["to"] == "Engineer" and edge.get("condition") == "needs_changes" for edge in baseline["edges"])


def test_unified_patch_applies_only_matching_hunks():
    original = "alpha\nbeta\ngamma\n"
    patch = "--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n alpha\n-beta\n+beta improved\n gamma\n"
    assert apply_unified_patch(original, patch) == "alpha\nbeta improved\ngamma\n"
    with pytest.raises(Exception, match="context does not match"):
        apply_unified_patch("different\nbeta\ngamma\n", patch)


def test_context_policy_selects_required_material_and_discards_noise_within_budget(db):
    run = _run(db, "client-a", "run-context")
    paragraphs = "\n\n".join(f"Requirement paragraph {index}." * 20 for index in range(30))
    artifacts = [
        Artifact(
            id="required",
            tenant_id=run.tenant_id,
            run_id=run.id,
            node_id="Product Manager",
            artifact_type="markdown",
            name="PRD.md",
            path="docs/PRD.md",
            content=paragraphs,
        )
    ]
    for index in range(8):
        artifacts.append(
            Artifact(
                id=f"noise-{index}", tenant_id=run.tenant_id, run_id=run.id, node_id="Other",
                artifact_type="markdown", name=f"NOISE-{index}.md", path=f"docs/NOISE-{index}.md",
                content=paragraphs.replace("Requirement", f"Noise {index}"),
            )
        )
    db.add_all(artifacts)
    db.commit()
    policy = ContextPolicy(
        allowed_reference_types=["demand", "artifact"],
        required_artifacts=["PRD.md"],
        optional_artifacts=[f"NOISE-{index}.md" for index in range(8)],
        input_budget_tokens=1000,
        file_mode="none",
    )
    bundle = TenantContextBuilder().build(db, run=run, node_id="Architect", policy=policy)
    assert any(reference.label == "PRD.md" for reference in bundle.references)
    assert bundle.estimated_input_tokens <= policy.input_budget_tokens
    assert bundle.discarded_tokens > 0
    assert bundle.discarded_references


def test_role_schema_removes_irrelevant_fields_and_unused_definitions():
    schema = AINativeWorkflowExecutor._response_schema_for_node(
        {"id": "Demand Classifier", "allowed_tools": []}, observation_only=False
    )
    assert "file_operations" not in schema["properties"]
    assert "requirements" not in schema["properties"]
    assert "test_requests" not in schema["properties"]
    assert "FileOperation" not in schema["$defs"]
    assert "RequirementOutput" not in schema["$defs"]


def test_node_output_limit_never_exceeds_the_role_ceiling(monkeypatch):
    monkeypatch.setenv("ASF_CODE_MODEL", "code-test")
    monkeypatch.setenv("ASF_CODE_MODEL_MAX_OUTPUT_TOKENS", "32000")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert request_max_output_tokens("code-test", 4000) == 4000
    assert request_max_output_tokens("code-test", 64000) == 32000
    get_settings.cache_clear()


def test_neutral_reward_is_zero_and_never_positive():
    assert reward_from_rating(-1) == -1.0
    assert reward_from_rating(0) == 0.0
    assert reward_from_rating(1) == 1.0


def test_anonymizer_removes_secrets_identifiers_code_and_paths():
    source = (
        "Use token sk-test-12345678901234567890 for alice@example.com in "
        "generated_app/backend/auth.py. ```python\nprint('client')\n```"
    )
    sanitized, evidence = anonymize_abstract_pattern(source)
    assert "sk-test" not in sanitized
    assert "alice@example.com" not in sanitized
    assert "print('client')" not in sanitized
    assert "generated_app/backend/auth.py" not in sanitized
    assert evidence["contains_raw_source"] is False
    assert evidence["source_sha256"] != evidence["result_sha256"]


def test_global_evidence_counts_only_pseudonyms_across_two_tenants(db):
    service = LearningOptimizationService()
    candidates = []
    for tenant, run_id in [("client-a", "run-a"), ("client-b", "run-b")]:
        run = _run(db, tenant, run_id)
        lesson = LearningLesson(
            id=f"lesson-{tenant}", tenant_id=tenant, run_id=run.id, scope="project",
            agent_name="Code Reviewer",
            lesson="Always compare the changed behavior against explicit acceptance criteria before approval.",
            evidence_json={}, status="approved", approved_at=utcnow(),
        )
        db.add(lesson)
        db.commit()
        candidate = service.propose_global_candidate(
            db, tenant_id=tenant, lesson_id=lesson.id, actor_user_id="curator",
            target_agents=["Code Reviewer"],
        )
        db.commit()
        candidates.append(candidate)
    set_tenant_context(db, "client-a", "curator")
    service.evaluate_candidate(db, candidate=candidates[0], actor_user_id="curator")
    assert candidates[0].evidence_run_count == 2
    assert candidates[0].evidence_tenant_count == 2
    rows = db.query(GlobalLearningEvidence).all()
    serialized = " ".join(f"{row.tenant_pseudonym} {row.run_fingerprint}" for row in rows)
    assert "client-a" not in serialized
    assert "client-b" not in serialized
    assert "run-a" not in serialized
    assert "run-b" not in serialized


def test_candidate_cannot_be_promoted_without_independent_evidence_and_passing_evaluation(db):
    run = _run(db, "client-a", "run-approval")
    lesson = LearningLesson(
        id="lesson-approval", tenant_id=run.tenant_id, run_id=run.id, scope="project",
        agent_name="Architect", lesson="Prefer explicit bounded context policies for each architectural task.",
        evidence_json={}, status="approved", approved_at=utcnow(),
    )
    db.add(lesson)
    db.commit()
    service = LearningOptimizationService()
    candidate = service.propose_global_candidate(
        db, tenant_id=run.tenant_id, lesson_id=lesson.id, actor_user_id="curator"
    )
    with pytest.raises(LearningOptimizationError) as captured:
        service.decide_candidate(
            db, candidate=candidate, decision="approve", comment="Reviewed", actor_user_id="owner"
        )
    assert captured.value.detail["code"] == "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    assert candidate.status == "candidate"


def test_token_analysis_reports_real_usage_cache_retries_and_reference_reasons(db):
    run = _run(db, "client-a", "run-token-analysis")
    state = WorkflowNodeState(
        id="state-analysis", tenant_id=run.tenant_id, run_id=run.id, node_id="Architect",
        phase="architecture", agent_name="Architect", status="success", iteration=1, max_iterations=1,
    )
    db.add(state)
    db.flush()
    call = ModelCall(
        id="call-analysis", tenant_id=run.tenant_id, run_id=run.id, agent_name="Architect",
        workflow_node_state_id=state.id, provider="litellm", model_name="asf-reasoning",
        model_role="reasoning", status="success", prompt_tokens=1200, completion_tokens=300,
        cache_read_tokens=200, cache_creation_tokens=50, max_output_tokens=6000,
        estimated_cost_usd=0.12, duration_seconds=3.5,
    )
    db.add(call)
    db.flush()
    step = AgentStepExecution(
        id="step-analysis", tenant_id=run.tenant_id, run_id=run.id, workflow_node_state_id=state.id,
        model_call_id=call.id, node_id="Architect", phase="architecture", iteration=1, attempt=2,
        status="completed", decision="success", input_hash="input", output_hash="output",
        input_manifest_json={}, output_manifest_json={}, output_refs_json=[],
    )
    context = ContextBuild(
        id="context-analysis", tenant_id=run.tenant_id, run_id=run.id, step_execution_id=step.id,
        node_id="Architect", policy_version="2.12.0", input_budget_tokens=28000,
        estimated_input_tokens=900, selected_tokens=900, discarded_tokens=2400,
        selected_references_json=[{"kind": "artifact", "ref_id": "prd", "label": "PRD.md", "estimated_tokens": 900, "reason": "artifact obrigatório"}],
        discarded_references_json=[{"kind": "file", "ref_id": "noise", "estimated_tokens": 2400, "reason": "fora do orçamento"}],
        selection_reasons_json={"prd": "artifact obrigatório"},
    )
    db.add(step)
    db.flush()
    db.add(context)
    db.commit()
    principal = Principal(
        tenant_id=run.tenant_id, user_id="operator", subject="operator", email="", name="Operator",
        role="operator", claims={}, auth_mode="test",
    )
    analysis = get_token_analysis(run.id, principal, db)
    TokenAnalysisResponse.model_validate(analysis)
    assert analysis["totals"] == {
        "prompt_tokens": 1200,
        "completion_tokens": 300,
        "total_tokens": 1500,
        "cache_read_tokens": 200,
        "context_selected_tokens": 900,
        "context_discarded_tokens": 2400,
        "cost_usd": 0.12,
        "latency_seconds": 3.5,
        "retries": 1,
    }
    assert analysis["nodes"][0]["context"]["references"][0]["reason"] == "artifact obrigatório"


def test_operator_cost_analysis_and_invocation_detail_do_not_return_prompts(db):
    run = _run(db, "client-a", "run-cost-api")
    invocation = AIInvocation(
        id="invocation-api", tenant_id=run.tenant_id, idempotency_key="invocation-api",
        scope_type="factory_run", scope_id=run.id, correlation_id=run.id, run_id=run.id,
        agent_name="Architect", policy_version="2.13.0", routing_policy_version="2.13.0",
        requested_model_role="reasoning", resolved_model_name="asf-reasoning",
        routing_reason="protected_quality_role", retry_classification="initial", attempt_count=1,
        status="success", soft_budget_usd=12, hard_budget_usd=15,
        projected_input_tokens=1000, projected_output_tokens=5000, projected_cost_usd=0.2,
        prompt_tokens=900, completion_tokens=400, cache_read_tokens=100, actual_cost_usd=0.18,
    )
    call = ModelCall(
        id="cost-call", tenant_id=run.tenant_id, ai_invocation_id=invocation.id, run_id=run.id,
        agent_name="Architect", provider="litellm", model_name="asf-reasoning", model_role="reasoning",
        status="success", prompt_tokens=900, completion_tokens=400, cache_read_tokens=100,
        max_output_tokens=5000, projected_cost_usd=0.2, estimated_cost_usd=0.18,
        request_json={"messages": [{"role": "user", "content": "private"}]},
        response_json={"raw": "private output"},
    )
    db.add_all([invocation, call])
    db.commit()
    principal = Principal(
        tenant_id=run.tenant_id, user_id="operator", subject="operator", email="", name="Operator",
        role="operator", claims={}, auth_mode="test",
    )
    analysis = ai_cost_analysis("journey", None, None, principal, db)
    AICostAnalysisResponse.model_validate(analysis)
    assert analysis["totals"]["actual_cost_usd"] == 0.18
    assert analysis["groups"][0]["key"] == "factory_run"
    detail = ai_invocation_detail(invocation.id, principal, db)
    AIInvocationDetailResponse.model_validate(detail)
    serialized = str(detail)
    assert "private output" not in serialized
    assert '"content": "private"' not in serialized
    assert detail["redactions"]["prompts"] == "not_returned"


def test_rollout_advances_from_shadow_but_requires_real_evidence_after_internal(db):
    run = _run(db, "client-a", "run-rollout")
    policy = LearningPolicy(
        id="policy-rollout", tenant_id=run.tenant_id, policy_type="lesson", version="2.12.test",
        status="shadow", configuration_json={"rollout_stage": "shadow"}, created_by_user_id="owner",
    )
    db.add(policy)
    db.commit()
    service = LearningOptimizationService()
    service.advance_rollout(db, policy=policy, actor_user_id="owner", comment="Benchmark passed")
    assert policy.status == "internal"
    with pytest.raises(LearningOptimizationError) as captured:
        service.advance_rollout(db, policy=policy, actor_user_id="owner", comment="Advance without a mission")
    assert captured.value.detail["code"] == "ROLLOUT_EVIDENCE_REQUIRED"
    assert policy.status == "internal"
