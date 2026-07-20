import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.agents.ai_native_context import TenantContextBuilder
from app.agents.ai_native_contracts import AgentStepResult, ArtifactOutput, FileOperation
from app.agents.ai_native_executor import AINativeExecutionError, AINativeWorkflowExecutor
from app.auth.dependencies import ensure_tenant
from app.core.config import get_settings
from app.db.session import set_tenant_context
from app.models import (
    AIInvocation,
    AgentStepExecution,
    Artifact,
    Base,
    FileChange,
    ModelCall,
    Project,
    WorkflowDefinition,
    WorkflowRun,
)
from app.providers.model_gateway import (
    ModelGateway,
    ModelGatewayError,
    portable_response_schema,
    request_max_output_tokens,
    request_timeout_seconds,
)
from app.providers.cost_governor import AIInvocationScope, CostEnvelope


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


def _run(db, tenant_id: str, run_id: str = "run-ai-native") -> WorkflowRun:
    ensure_tenant(db, "global", "Global prompt registry")
    ensure_tenant(db, tenant_id, tenant_id)
    project = Project(id=f"project-{tenant_id}", tenant_id=tenant_id, name=f"Project {tenant_id}")
    run = WorkflowRun(
        id=run_id,
        tenant_id=tenant_id,
        project_id=project.id,
        workflow_id="software_factory_ai_native_v2",
        generation_mode="ai_native_v2",
        demand=f"Private demand for {tenant_id}",
        status="running",
        current_node="Engineer",
        current_phase="implementation",
        ai_budget_usd=15,
        ai_cost_usd=0,
    )
    db.add_all([project, run])
    db.commit()
    return run


def test_agent_step_contract_rejects_paths_outside_generated_workspace():
    with pytest.raises(ValidationError):
        FileOperation(operation="create", path="../secrets.env", content="forbidden")
    with pytest.raises(ValidationError):
        FileOperation(operation="create", path="README.md", content="outside generated_app")


def test_artifact_contract_allows_real_specs_but_keeps_a_bounded_limit():
    artifact = ArtifactOutput(name="UX_SPEC.md", content="x" * 30_000)
    assert len(artifact.content) == 30_000
    with pytest.raises(ValidationError):
        ArtifactOutput(name="PRD.md", content="x" * 40_001)


def test_agent_step_contract_allows_a_bounded_fullstack_file_set():
    operations = [
        FileOperation(
            operation="create",
            path=f"generated_app/backend/app/module_{index}.py",
            content=f"VALUE = {index}\n",
        )
        for index in range(32)
    ]
    result = AgentStepResult(
        status="success",
        decision="success",
        summary="Bounded vertical slice",
        file_operations=operations,
        confidence=0.9,
    )
    assert len(result.file_operations) == 32
    with pytest.raises(ValidationError):
        AgentStepResult(
            status="success",
            decision="success",
            summary="Too many files",
            confidence=0.9,
            file_operations=operations
            + [
                FileOperation(
                    operation="create",
                    path="generated_app/backend/app/overflow.py",
                    content="VALUE = 33\n",
                )
            ],
        )


def test_provider_schema_is_portable_while_local_contract_keeps_constraints():
    source = AgentStepResult.response_schema()
    portable = portable_response_schema(source)

    assert "maxItems" in source["properties"]["artifacts"]
    assert "maxItems" not in portable["properties"]["artifacts"]
    artifact_schema = portable["$defs"]["ArtifactOutput"]
    assert "maxLength" not in artifact_schema["properties"]["content"]
    assert "pattern" not in portable["$defs"]["RequirementOutput"]["properties"]["requirement_id"]
    assert "title" in portable["$defs"]["RequirementOutput"]["properties"]
    assert portable["properties"]["artifacts"]["items"]["$ref"] == "#/$defs/ArtifactOutput"
    assert portable["properties"]["decision"]["enum"] == source["properties"]["decision"]["enum"]
    assert set(portable["required"]) == set(portable["properties"])
    assert set(portable["$defs"]["RequirementOutput"]["required"]) == set(
        portable["$defs"]["RequirementOutput"]["properties"]
    )
    assert portable["$defs"]["RequirementOutput"]["additionalProperties"] is False


def test_model_timeouts_are_bounded_by_role(monkeypatch):
    monkeypatch.setenv("ASF_FAST_MODEL", "fast-test")
    monkeypatch.setenv("ASF_REASONING_MODEL", "reasoning-test")
    monkeypatch.setenv("ASF_CODE_MODEL", "code-test")
    monkeypatch.setenv("ASF_MODEL_REQUEST_TIMEOUT_SECONDS", "44")
    monkeypatch.setenv("ASF_FAST_MODEL_REQUEST_TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("ASF_REASONING_MODEL_REQUEST_TIMEOUT_SECONDS", "22")
    monkeypatch.setenv("ASF_CODE_MODEL_REQUEST_TIMEOUT_SECONDS", "33")
    get_settings.cache_clear()
    assert request_timeout_seconds("fast-test") == 11
    assert request_timeout_seconds("reasoning-test") == 22
    assert request_timeout_seconds("code-test") == 33
    assert request_timeout_seconds("custom-model") == 44
    get_settings.cache_clear()


def test_model_output_limits_are_bounded_by_role(monkeypatch):
    monkeypatch.setenv("ASF_FAST_MODEL", "fast-test")
    monkeypatch.setenv("ASF_REASONING_MODEL", "reasoning-test")
    monkeypatch.setenv("ASF_CODE_MODEL", "code-test")
    monkeypatch.setenv("ASF_MODEL_MAX_OUTPUT_TOKENS", "444")
    monkeypatch.setenv("ASF_FAST_MODEL_MAX_OUTPUT_TOKENS", "111")
    monkeypatch.setenv("ASF_REASONING_MODEL_MAX_OUTPUT_TOKENS", "222")
    monkeypatch.setenv("ASF_CODE_MODEL_MAX_OUTPUT_TOKENS", "333")
    get_settings.cache_clear()
    assert request_max_output_tokens("fast-test") == 111
    assert request_max_output_tokens("reasoning-test") == 222
    assert request_max_output_tokens("code-test") == 333
    assert request_max_output_tokens("custom-model") == 444
    get_settings.cache_clear()


def test_node_schema_exposes_mutation_and_test_requests_only_to_authorized_roles():
    executor = AINativeWorkflowExecutor()
    classifier = executor._response_schema_for_node(
        {"id": "Demand Classifier", "allowed_tools": []},
        observation_only=False,
    )
    engineer = executor._response_schema_for_node(
        {"id": "Engineer", "allowed_tools": ["write_workspace"]},
        observation_only=False,
    )
    qa = executor._response_schema_for_node(
        {"id": "QA Engineer", "allowed_tools": ["read_workspace", "backend_tests"]},
        observation_only=False,
    )

    assert "file_operations" not in classifier["properties"]
    assert "test_requests" not in classifier["properties"]
    assert "file_operations" in engineer["properties"]
    assert "test_requests" not in engineer["properties"]
    assert "file_operations" not in qa["properties"]
    assert "test_requests" in qa["properties"]


def test_retry_routing_repairs_schema_and_repeats_transient_on_same_model():
    node = {"model_role": "fast"}
    assert AINativeWorkflowExecutor._model_role_for_attempt(node, 2, "schema_repair") == "fast"
    assert AINativeWorkflowExecutor._model_role_for_attempt(node, 2, "transient") == "fast"
    assert AINativeWorkflowExecutor._model_role_for_attempt(node, 2, "semantic_escalation") == "reasoning"
    assert AINativeWorkflowExecutor._model_role_for_attempt({"model_role": "code"}, 2, "semantic_escalation") == "code"


def test_context_bundle_never_contains_other_tenant_material(db):
    run_a = _run(db, "client-a", "run-a")
    run_b = _run(db, "client-b", "run-b")
    db.add_all(
        [
            Artifact(
                id="artifact-a",
                tenant_id="client-a",
                run_id=run_a.id,
                node_id="Product Manager",
                artifact_type="markdown",
                name="PRD.md",
                path="docs/PRD.md",
                content="CANARY-CLIENT-A",
            ),
            Artifact(
                id="artifact-b",
                tenant_id="client-b",
                run_id=run_b.id,
                node_id="Product Manager",
                artifact_type="markdown",
                name="PRD.md",
                path="docs/PRD.md",
                content="CANARY-CLIENT-B",
            ),
        ]
    )
    db.commit()

    set_tenant_context(db, "client-a", "operator")
    bundle = TenantContextBuilder().build(db, run=run_a, node_id="Architect")
    serialized = bundle.model_dump_json()
    assert bundle.tenant_id == "client-a"
    assert "CANARY-CLIENT-A" in serialized
    assert "CANARY-CLIENT-B" not in serialized
    assert all(reference.metadata.get("tenant_id") in {None, "client-a"} for reference in bundle.references)


class PersistingGateway:
    def call(self, **kwargs):
        db = kwargs["db"]
        call_id = str(uuid.uuid4())
        parsed = {
            "status": "success",
            "decision": "success",
            "summary": "Implemented a tenant-scoped service from the supplied demand.",
            "artifacts": [
                {
                    "name": "IMPLEMENTATION_SUMMARY.md",
                    "artifact_type": "markdown",
                    "content": "# Implementation\n\nGenerated from the approved context.",
                    "audience": "internal",
                    "evidence_classification": "real",
                    "source_refs": [kwargs["run_id"]],
                }
            ],
            "file_operations": [
                {
                    "operation": "create",
                    "path": "generated_app/backend/app/main.py",
                    "content": "from fastapi import FastAPI\napp = FastAPI()\n",
                    "rationale": "Create the generated API entrypoint.",
                },
                {"operation": "create", "path": "generated_app/backend/tests/test_api.py", "content": "def test_boot():\n    assert True\n"},
                {"operation": "create", "path": "generated_app/frontend/package.json", "content": "{\"scripts\":{\"test\":\"node --test\",\"build\":\"next build\",\"test:visual\":\"node --test\",\"test:a11y\":\"node --test\"}}"},
                {"operation": "create", "path": "generated_app/frontend/app/page.tsx", "content": "export default function Page(){return <main>Client workspace</main>}"},
                {"operation": "create", "path": "generated_app/README.md", "content": "# Generated application\n"},
            ],
            "requirements": [],
            "test_requests": [],
            "risks": [],
            "citations": [kwargs["run_id"]],
            "handoff": {"to": "Code Reviewer", "summary": "Review persisted diff", "output_refs": []},
            "confidence": 0.9,
        }
        db.add(
            ModelCall(
                id=call_id,
                tenant_id=kwargs["tenant_id"],
                run_id=kwargs["run_id"],
                agent_name=kwargs["agent_name"],
                workflow_node_state_id=kwargs["workflow_node_state_id"],
                prompt_version_id=kwargs["prompt_version_id"],
                provider="test-contract-gateway",
                model_name="asf-code",
                model_role=kwargs["model_role"],
                input_hash=kwargs["input_hash"],
                output_hash="output-hash",
                context_refs_json=kwargs["context_refs"],
                response_json={"parsed": parsed},
                status="success",
            )
        )
        db.flush()
        return {"id": call_id, "model": "asf-code", "content": {"parsed": parsed}}


class PersistingInvalidGateway:
    def call(self, **kwargs):
        db = kwargs["db"]
        call_id = str(uuid.uuid4())
        parsed = {"status": "success", "summary": "Missing required decision and confidence."}
        db.add(
            ModelCall(
                id=call_id,
                tenant_id=kwargs["tenant_id"],
                run_id=kwargs["run_id"],
                agent_name=kwargs["agent_name"],
                workflow_node_state_id=kwargs["workflow_node_state_id"],
                prompt_version_id=kwargs["prompt_version_id"],
                provider="test-invalid-gateway",
                model_name="asf-code",
                model_role=kwargs["model_role"],
                input_hash=kwargs["input_hash"],
                response_json={"parsed": parsed},
                status="success",
            )
        )
        db.flush()
        return {"id": call_id, "model": "asf-code", "content": {"parsed": parsed}}


class PersistingProviderErrorGateway:
    def call(self, **kwargs):
        db = kwargs["db"]
        call_id = str(uuid.uuid4())
        db.add(
            ModelCall(
                id=call_id,
                tenant_id=kwargs["tenant_id"],
                run_id=kwargs["run_id"],
                agent_name=kwargs["agent_name"],
                provider="test-error-gateway",
                model_name="asf-fast",
                model_role=kwargs["model_role"],
                response_json={"parse_error": "truncated"},
                status="invalid_response",
                error="Provider response was not valid JSON: truncated",
            )
        )
        db.flush()
        raise ModelGatewayError("Provider response was not valid JSON: truncated", call_id=call_id)


class BudgetBlockedGateway:
    def __init__(self):
        self.calls = 0

    def call(self, **kwargs):
        self.calls += 1
        raise ModelGatewayError("AI operation budget exhausted before provider call")


def test_model_output_directly_creates_linked_artifact_file_and_step(db, tmp_path, monkeypatch):
    monkeypatch.setenv("ASF_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        run = _run(db, "client-linked", "run-linked")
        executor = AINativeWorkflowExecutor(gateway=PersistingGateway())
        result = executor._execute_agent_node(
            db,
            run=run,
            node={
                "id": "Engineer",
                "phase": "implementation",
                "skill": "engineer",
                "model_role": "code",
                "outputs": ["IMPLEMENTATION_SUMMARY.md"],
                "allowed_tools": ["write_workspace"],
                "allowed_decisions": ["success"],
            },
            workflow_version="2.0.0",
            iteration=1,
        )
        step = db.query(AgentStepExecution).filter_by(run_id=run.id).one()
        artifact = db.query(Artifact).filter_by(run_id=run.id).one()
        changes = db.query(FileChange).filter_by(run_id=run.id).all()
        assert result.decision == "success"
        assert step.model_call_id
        assert artifact.model_call_id == step.model_call_id
        assert artifact.step_execution_id == step.id
        assert len(changes) == 5
        assert all(change.model_call_id == step.model_call_id for change in changes)
        assert all(change.step_execution_id == step.id for change in changes)
        assert all(change.diff for change in changes)
        assert (tmp_path / "workspaces" / "tenants" / "client-linked" / run.id / "generated_app/backend/app/main.py").is_file()
    finally:
        get_settings.cache_clear()


def test_invalid_model_output_remains_linked_to_failed_step(db):
    run = _run(db, "client-invalid", "run-invalid")
    executor = AINativeWorkflowExecutor(gateway=PersistingInvalidGateway())

    with pytest.raises(ValidationError):
        executor._execute_agent_node(
            db,
            run=run,
            node={
                "id": "Engineer",
                "phase": "implementation",
                "skill": "engineer",
                "model_role": "code",
                "outputs": ["IMPLEMENTATION_SUMMARY.md"],
                "allowed_tools": ["write_workspace"],
                "allowed_decisions": ["success"],
            },
            workflow_version="2.2.0",
            iteration=1,
        )

    step = db.query(AgentStepExecution).filter_by(run_id=run.id).one()
    assert step.status == "failed"
    assert step.model_call_id
    assert db.get(ModelCall, step.model_call_id) is not None


def test_provider_error_remains_linked_to_failed_step(db):
    run = _run(db, "client-provider-error", "run-provider-error")
    executor = AINativeWorkflowExecutor(gateway=PersistingProviderErrorGateway())

    with pytest.raises(ModelGatewayError, match="not valid JSON"):
        executor._execute_agent_node(
            db,
            run=run,
            node={
                "id": "Demand Classifier",
                "phase": "demand_classification",
                "skill": "demand_classifier",
                "model_role": "fast",
                "outputs": ["DOMAIN_CLASSIFICATION.md"],
                "allowed_decisions": ["success"],
            },
            workflow_version="2.9.0",
            iteration=1,
        )

    step = db.query(AgentStepExecution).filter_by(run_id=run.id).one()
    assert step.status == "failed"
    assert step.model_call_id
    assert db.get(ModelCall, step.model_call_id).status == "invalid_response"


def test_budget_block_pauses_run_without_retry(db):
    run = _run(db, "client-budget-pause", "run-budget-pause")
    db.add(
        WorkflowDefinition(
            id=str(uuid.uuid4()),
            tenant_id=run.tenant_id,
            workflow_id="software_factory_ai_native_v2",
            version="2.13.0",
            name="Budget pause test",
            yaml_path="test",
            yaml_content="""
graph:
  execution:
    max_total_steps: 2
  nodes:
    - id: Demand Classifier
      type: agent
      phase: demand_classification
      skill: demand_classifier
      model_role: fast
      outputs: [DOMAIN_CLASSIFICATION.md]
      allowed_tools: []
    - id: Human Approval
      type: human
      phase: approval
  edges:
    - from: Demand Classifier
      to: Human Approval
      condition: success
""",
        )
    )
    run.context_manifest_json = {"workflow_version": "2.13.0"}
    db.commit()
    gateway = BudgetBlockedGateway()

    result = AINativeWorkflowExecutor(gateway=gateway).execute(db, run=run, provider=object())

    assert result.status == "pending"
    assert result.current_phase == "budget_paused"
    assert gateway.calls == 1


class FixedCostGateway(ModelGateway):
    def _call_litellm(self, model_name, messages, response_schema):
        return {
            "parsed": {"ok": True},
            "raw": "{\"ok\": true}",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "estimated_cost_usd": 2.0,
        }


class InvalidJSONGateway(ModelGateway):
    def _call_litellm(self, model_name, messages, response_schema):
        return {
            "parsed": {"text": '{"incomplete":'},
            "raw": '{"incomplete":',
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "estimated_cost_usd": 0.01,
            "parse_error": "Expecting value",
        }


def test_gateway_marks_malformed_json_as_an_invalid_response(db):
    run = _run(db, "client-invalid-json", "run-invalid-json")
    with pytest.raises(ModelGatewayError, match="not valid JSON") as exc_info:
        InvalidJSONGateway().call(
            db=db,
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name="Demand Classifier",
            model_role="fast",
            messages=[{"role": "user", "content": "Return structured JSON"}],
        )

    call = db.query(ModelCall).filter_by(run_id=run.id).one()
    assert exc_info.value.call_id == call.id
    assert call.status == "invalid_response"
    assert "not valid JSON" in call.error


def test_gateway_records_actual_cost_and_blocks_a_call_that_exceeds_run_budget(db):
    run = _run(db, "client-budget", "run-budget")
    run.ai_budget_usd = 1.0
    db.commit()
    with pytest.raises(ModelGatewayError, match="would exceed"):
        FixedCostGateway().call(
            db=db,
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name="Engineer",
            model_role="code",
            messages=[{"role": "user", "content": "bounded request"}],
        )
    db.refresh(run)
    call = db.query(ModelCall).filter_by(run_id=run.id).one()
    assert call.status == "budget_exceeded"
    assert call.estimated_cost_usd == 2.0
    assert run.ai_cost_usd == 2.0


def test_gateway_groups_attempts_in_one_scoped_invocation(db):
    run = _run(db, "client-invocation", "run-invocation")
    scope = AIInvocationScope(
        scope_type="factory_run",
        scope_id=run.id,
        correlation_id=run.id,
        policy_version="2.13.0",
        invocation_id="logical-invocation",
        routing_reason="protected_quality_role",
        envelope=CostEnvelope(soft_budget_usd=40, hard_budget_usd=50),
    )
    gateway = FixedCostGateway()
    first = gateway.call(
        db=db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_name="Engineer",
        model_role="code",
        max_output_tokens=10,
        messages=[{"role": "user", "content": "first attempt"}],
        invocation_scope=scope,
    )
    scope.attempt_number = 2
    scope.retry_classification = "schema_repair"
    second = gateway.call(
        db=db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_name="Engineer",
        model_role="code",
        max_output_tokens=10,
        messages=[{"role": "user", "content": "repair"}],
        invocation_scope=scope,
    )
    invocation = db.get(AIInvocation, "logical-invocation")
    assert first["invocation_id"] == second["invocation_id"] == invocation.id
    assert invocation.attempt_count == 2
    assert invocation.retry_classification == "schema_repair"
    assert invocation.actual_cost_usd == 4.0
    assert invocation.prompt_tokens == 20
    assert db.query(ModelCall).filter_by(ai_invocation_id=invocation.id).count() == 2


def test_patch_file_operation_requires_base_hash_and_does_not_duplicate_content():
    with pytest.raises(ValidationError):
        FileOperation(operation="patch", path="generated_app/app.py", patch="@@ -1 +1 @@\n-old\n+new\n")
    operation = FileOperation(
        operation="patch",
        path="generated_app/app.py",
        patch="@@ -1 +1 @@\n-old\n+new\n",
        base_sha256="a" * 64,
    )
    assert operation.content == ""


def test_executor_rejects_decisions_not_present_in_persisted_graph(db):
    run = _run(db, "client-decision", "run-decision")
    context = TenantContextBuilder().build(db, run=run, node_id="Code Reviewer")
    result = AgentStepResult(
        status="success",
        decision="success",
        summary="Invalid reviewer transition",
        confidence=0.8,
    )
    with pytest.raises(AINativeExecutionError, match="not allowed"):
        AINativeWorkflowExecutor()._validate_result(
            db,
            run=run,
            node={"id": "Code Reviewer", "allowed_decisions": ["approved", "needs_changes"]},
            result=result,
            context=context,
        )
