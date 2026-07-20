import asyncio
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from temporalio.client import Client

from app.agents.ai_native_contracts import (
    ArtifactSectionResult,
    FileBatchResult,
    FileOperation,
    NodePlanResult,
    OutputUnitDescriptor,
)
from app.agents.segmented_execution import SegmentedExecutionError, SegmentedExecutionService
from app.auth.dependencies import ensure_tenant
from app.domain.workflow_transition import TransitionState, WorkflowTransitionEngine, WorkflowTransitionError
from app.learning.global_registry import GlobalLearningRegistryService
from app.models import (
    AgentStepExecution,
    Artifact,
    ArtifactFragment,
    Base,
    ExecutionUnit,
    GlobalLearningDeployment,
    LearningCandidate,
    LearningEvaluation,
    LedgerRecord,
    ModelCall,
    Project,
    WorkflowNodeState,
    WorkflowDefinition,
    WorkflowRun,
    utcnow,
)
from app.observability.slo import SLOCalculator
from app.api.routes_health import _aggregate_technical_metrics
from app.providers.model_gateway import ModelGateway
from app.providers.temporal_runner import TemporalWorkflowRunner
from app.agents.ai_native_executor import AINativeWorkflowExecutor


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
        executor_protocol_version="segmented-output-v1",
        trace_id=f"trace-{run_id}",
        demand=f"Private demand for {tenant_id}",
        status="running",
        current_node="Architect",
        current_phase="architecture",
        ai_budget_usd=15,
        ai_cost_usd=0,
    )
    db.add_all([project, run])
    db.commit()
    return run


def _descriptor(key: str, unit_type: str, order: int, *, target: str = "", dependencies=None):
    return OutputUnitDescriptor(
        key=key,
        unit_type=unit_type,
        order=order,
        targets=[target] if target else [],
        dependencies=list(dependencies or []),
        output_budget_tokens=1000,
    )


def test_segmented_contracts_bound_order_dependencies_and_file_batch_size():
    with pytest.raises(ValidationError, match="contiguous"):
        NodePlanResult(
            summary="Invalid gap",
            confidence=0.9,
            units=[
                _descriptor("section", "artifact_section", 1, target="ARCHITECTURE.md"),
                _descriptor("final", "finalize", 2, dependencies=["section"]),
            ],
        )
    with pytest.raises(ValidationError, match="precede"):
        NodePlanResult(
            summary="Forward dependency",
            confidence=0.9,
            units=[
                _descriptor("section", "artifact_section", 0, target="ARCHITECTURE.md", dependencies=["final"]),
                _descriptor("final", "finalize", 1),
            ],
        )
    operations = [
        FileOperation(operation="create", path=f"generated_app/backend/file_{index}.py", content="VALUE = 1\n")
        for index in range(5)
    ]
    with pytest.raises(ValidationError):
        FileBatchResult(batch_key="oversized", operations=operations)


def test_transition_engine_is_deterministic_and_enforces_persisted_loop_limit():
    graph = {
        "execution": {"max_total_steps": 12},
        "nodes": [
            {"id": "USER"},
            {"id": "Engineer"},
            {"id": "Reviewer"},
            {"id": "FINAL"},
        ],
        "edges": [
            {"from": "USER", "to": "Engineer", "condition": "success"},
            {"from": "Engineer", "to": "Reviewer", "condition": "success"},
            {"from": "Reviewer", "to": "Engineer", "condition": "needs_changes", "max_iterations": 2},
            {"from": "Reviewer", "to": "FINAL", "condition": "approved"},
        ],
    }
    engine = WorkflowTransitionEngine(graph)
    state = TransitionState(current_node="USER")
    state = engine.transition(state, "success").state
    assert state.current_node == "Engineer"
    for _ in range(2):
        state = engine.transition(state, "success").state
        state = engine.transition(state, "needs_changes").state
    state = engine.transition(state, "success").state
    with pytest.raises(WorkflowTransitionError, match="loop limit"):
        engine.transition(state, "needs_changes")


def test_segmented_units_and_artifact_assembly_are_exactly_once(db):
    run = _run(db, "client-a", "run-segmented")
    state = WorkflowNodeState(
        id="state-segmented",
        tenant_id=run.tenant_id,
        run_id=run.id,
        node_id="Architect",
        phase="architecture",
        agent_name="Architect",
        status="running",
        iteration=1,
        max_iterations=1,
    )
    call = ModelCall(
        id="call-segmented",
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_name="Architect",
        provider="test",
        model_name="asf-reasoning",
        model_role="reasoning",
        status="success",
    )
    db.add_all([state, call])
    db.flush()
    step = AgentStepExecution(
        id="step-segmented",
        tenant_id=run.tenant_id,
        run_id=run.id,
        workflow_node_state_id=state.id,
        node_id="Architect",
        phase="architecture",
        iteration=1,
        attempt=1,
        status="running",
        input_hash="input",
        input_manifest_json={},
        output_manifest_json={},
        output_refs_json=[],
    )
    db.add(step)
    db.flush()
    plan = NodePlanResult(
        summary="Two deterministic architecture sections",
        confidence=0.95,
        units=[
            _descriptor("architecture-context", "artifact_section", 0, target="ARCHITECTURE.md"),
            _descriptor("architecture-decisions", "artifact_section", 1, target="ARCHITECTURE.md", dependencies=["architecture-context"]),
            _descriptor("final", "finalize", 2, dependencies=["architecture-decisions"]),
        ],
    )
    service = SegmentedExecutionService()
    first = service.persist_plan(
        db,
        run=run,
        node_state=state,
        step=step,
        node_id="Architect",
        phase="architecture",
        iteration=1,
        plan=plan,
        strategy="segmented_artifact",
        trace_id=run.trace_id,
    )
    replay = service.persist_plan(
        db,
        run=run,
        node_state=state,
        step=step,
        node_id="Architect",
        phase="architecture",
        iteration=1,
        plan=plan,
        strategy="segmented_artifact",
        trace_id=run.trace_id,
    )
    assert [unit.id for unit in first] == [unit.id for unit in replay]

    for index, unit in enumerate(first[:2]):
        service.start_unit(db, run=run, unit=unit)
        section = ArtifactSectionResult(
            artifact_name="ARCHITECTURE.md",
            section_key=unit.unit_key,
            section_title=f"Section {index + 1}",
            order=index,
            markdown=f"## Section {index + 1}\n\nVerified content {index + 1}.",
            citations=[run.id],
            final=index == 1,
        )
        fragment = service.persist_artifact_fragment(
            db, run=run, unit=unit, result=section, model_call_id=call.id
        )
        assert service.persist_artifact_fragment(
            db, run=run, unit=unit, result=section, model_call_id=call.id
        ).id == fragment.id
        service.complete_unit(
            db,
            run=run,
            unit=unit,
            output=section.model_dump(mode="json"),
            model_call_id=call.id,
        )
    service.start_unit(db, run=run, unit=first[2])
    service.complete_unit(
        db,
        run=run,
        unit=first[2],
        output={"decision": "success", "summary": "Architecture complete", "confidence": 0.95},
        model_call_id=call.id,
    )
    artifact = service.assemble_artifact(
        db,
        run=run,
        node_id="Architect",
        iteration=1,
        artifact_name="ARCHITECTURE.md",
        step_execution_id=step.id,
    )
    replayed_artifact = service.assemble_artifact(
        db,
        run=run,
        node_id="Architect",
        iteration=1,
        artifact_name="ARCHITECTURE.md",
        step_execution_id=step.id,
    )
    db.commit()

    assert artifact.id == replayed_artifact.id
    assert db.query(Artifact).filter_by(run_id=run.id, name="ARCHITECTURE.md").count() == 1
    assert db.query(ArtifactFragment).filter_by(run_id=run.id).count() == 2
    assert db.query(LedgerRecord).filter_by(tenant_id=run.tenant_id, event_type="output.unit_planned").count() == 3
    with pytest.raises(SegmentedExecutionError, match="cannot be replaced"):
        service.complete_unit(db, run=run, unit=first[0], output={"changed": True}, model_call_id=call.id)


class ProviderAwareCacheGateway(ModelGateway):
    def __init__(self):
        self.options = []

    def _call_litellm(self, model_name, messages, response_schema, max_output_tokens=None, provider_options=None):
        self.options.append(provider_options or {})
        return {
            "parsed": {"ok": True},
            "raw": '{"ok": true}',
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 25,
                "prompt_tokens_details": {"cached_tokens": 900},
                "cache_creation_input_tokens": 1100,
                "cache_savings_usd": 0.012,
            },
            "cache_savings_usd": 0.012,
            "provider_route": "openrouter/test-route",
            "provider_request_id": f"request-{len(self.options)}",
            "finish_reason": "stop",
            "estimated_cost_usd": 0.02,
        }


class GranularSegmentedGateway:
    def call(self, **kwargs):
        schema = kwargs.get("response_schema") or {}
        properties = schema.get("properties") or {}
        if "units" in properties:
            parsed = {
                "decision": "success",
                "summary": "Plan one bounded architecture section and finalize it.",
                "units": [
                    {
                        "key": "architecture-core",
                        "unit_type": "artifact_section",
                        "targets": ["ARCHITECTURE.md"],
                        "order": 0,
                        "dependencies": [],
                        "input_budget_tokens": 1000,
                        "output_budget_tokens": 1000,
                    },
                    {
                        "key": "final",
                        "unit_type": "finalize",
                        "targets": [],
                        "order": 1,
                        "dependencies": ["architecture-core"],
                        "input_budget_tokens": 1000,
                        "output_budget_tokens": 1000,
                    },
                ],
                "citations": [kwargs["run_id"]],
                "confidence": 0.95,
            }
        elif "artifact_name" in properties:
            parsed = {
                "artifact_name": "ARCHITECTURE.md",
                "artifact_type": "markdown",
                "audience": "internal",
                "section_key": "architecture-core",
                "section_title": "Architecture core",
                "order": 0,
                "markdown": "# Architecture\n\nTenant-scoped modular service.",
                "citations": [kwargs["run_id"]],
                "final": True,
            }
        else:
            parsed = {
                "decision": "success",
                "summary": "Architecture artifact completed from the persisted section.",
                "risks": [],
                "handoff": None,
                "produced_refs": ["ARCHITECTURE.md"],
                "confidence": 0.95,
            }
        call_id = str(uuid.uuid4())
        kwargs["db"].add(
            ModelCall(
                id=call_id,
                tenant_id=kwargs["tenant_id"],
                run_id=kwargs["run_id"],
                execution_unit_id=kwargs.get("execution_unit_id") or None,
                agent_name=kwargs["agent_name"],
                workflow_node_state_id=kwargs.get("workflow_node_state_id") or None,
                prompt_version_id=kwargs.get("prompt_version_id") or None,
                provider="granular-test",
                model_name=f"asf-{kwargs.get('model_role') or 'default'}",
                model_role=kwargs.get("model_role") or "default",
                input_hash=kwargs.get("input_hash") or "",
                response_json={"parsed": parsed},
                status="success",
                finish_reason="stop",
            )
        )
        kwargs["db"].flush()
        return {"id": call_id, "invocation_id": "", "model": "test", "content": {"parsed": parsed}}


def test_temporal_granular_executor_plans_and_executes_one_model_call_per_unit(db):
    ensure_tenant(db, "global", "Global prompt registry")
    run = _run(db, "client-granular", "run-granular")
    definition = WorkflowDefinition(
        id="definition-granular",
        tenant_id=run.tenant_id,
        workflow_id=run.workflow_id,
        version="2.13.test",
        name="Granular test workflow",
        yaml_path="test",
        yaml_content="""
graph:
  execution: {max_total_steps: 4}
  nodes:
    - {id: USER, type: input}
    - id: Architect
      type: agent
      phase: architecture
      skill: architect
      model_role: reasoning
      outputs: [ARCHITECTURE.md]
      max_output_tokens: 4000
      context_policy:
        version: 2.13.test
        allowed_reference_types: [demand]
        input_budget_tokens: 4000
        file_mode: none
    - {id: Human Approval, type: human, phase: approval}
    - {id: FINAL, type: terminal}
  edges:
    - {from: USER, to: Architect, condition: success}
    - {from: Architect, to: Human Approval, condition: success}
    - {from: Human Approval, to: FINAL, condition: approved}
""",
    )
    run.context_manifest_json = {"workflow_version": definition.version}
    db.add(definition)
    db.commit()
    executor = AINativeWorkflowExecutor(gateway=GranularSegmentedGateway())

    planned = executor.plan_temporal_segmented_node(db, run=run)
    assert planned["status"] == "planned"
    assert len(planned["execution_unit_ids"]) == 2
    assert db.query(ModelCall).filter_by(run_id=run.id).count() == 1

    first = executor.execute_temporal_output_unit(
        db, run=run, execution_unit_id=planned["execution_unit_ids"][0]
    )
    assert first["status"] == "completed"
    assert db.query(ModelCall).filter_by(run_id=run.id).count() == 2
    final = executor.execute_temporal_output_unit(
        db, run=run, execution_unit_id=planned["execution_unit_ids"][1]
    )
    assert final["status"] == "completed"
    assert db.query(ModelCall).filter_by(run_id=run.id).count() == 3

    definition_row, node = executor._segmented_definition_and_node(db, run)
    result = executor._execute_segmented_node(
        db,
        run=run,
        node=node,
        workflow_version=definition_row.version,
        iteration=1,
        attempt=1,
        mode="finalize",
    )
    db.commit()
    assert result.decision == "success"
    assert db.query(ModelCall).filter_by(run_id=run.id).count() == 3
    assert db.query(Artifact).filter_by(run_id=run.id, name="ARCHITECTURE.md").count() == 1
    assert all(
        unit.model_call_id
        for unit in db.query(ExecutionUnit).filter_by(run_id=run.id, action="execute").all()
    )
    replayed_plan = executor.plan_temporal_segmented_node(db, run=run)
    for unit_id in replayed_plan["execution_unit_ids"]:
        assert executor.execute_temporal_output_unit(
            db, run=run, execution_unit_id=unit_id
        )["status"] == "completed"
    assert db.query(ModelCall).filter_by(run_id=run.id).count() == 3


def test_prompt_cache_key_is_global_stable_and_provider_usage_is_persisted(db, monkeypatch):
    monkeypatch.setenv("ASF_FAST_UPSTREAM_MODEL", "openai/gpt-5.4-mini")
    gateway = ProviderAwareCacheGateway()
    keys = []
    for tenant_id in ("client-a", "client-b"):
        run = _run(db, tenant_id, f"run-cache-{tenant_id}")
        result = gateway.call(
            db=db,
            tenant_id=tenant_id,
            run_id=run.id,
            agent_name="Demand Classifier",
            model_role="fast",
            cache_scope="global_static",
            routing_policy_version="2.13.0",
            messages=[
                {"role": "system", "content": "Stable global operating policy. " * 240},
                {"role": "user", "content": f"Confidential request for {tenant_id}"},
            ],
        )
        call = db.get(ModelCall, result["id"])
        keys.append(call.prompt_cache_key)
        assert call.cache_eligible_tokens > 0
        assert call.cache_read_tokens == 900
        assert call.cache_write_tokens == 1100
        assert call.cache_savings_usd == pytest.approx(0.012)
        assert call.provider_route == "openrouter/test-route"
        assert tenant_id not in call.prompt_cache_key
        db.commit()
    assert keys[0] == keys[1]
    assert all(option["cache_mode"] == "openai_key" for option in gateway.options)
    assert all(option["prompt_cache_key"] == keys[0] for option in gateway.options)


def test_global_learning_requires_human_evidence_and_rolls_back_only_the_tenant_pointer(db):
    ensure_tenant(db, "client-a", "Client A")
    candidate = LearningCandidate(
        id="candidate-global",
        tenant_id="client-a",
        candidate_type="context_strategy",
        scope="global",
        title="Acceptance criteria discipline",
        abstract_pattern="Require explicit acceptance criteria before approving a change.",
        target_agents_json=["Code Reviewer"],
        evidence_json={},
        anonymization_json={
            "contains_raw_source": False,
            "contains_client_facts": False,
            "redaction_counts": {},
        },
        evidence_run_count=3,
        evidence_tenant_count=2,
        status="approved",
    )
    evaluation = LearningEvaluation(
        id="evaluation-global",
        tenant_id="client-a",
        candidate_id=candidate.id,
        status="passed",
        repetitions=3,
        gate_results_json={"schemas": True, "isolation": True, "quality": True},
        finished_at=utcnow(),
    )
    db.add_all([candidate, evaluation])
    db.commit()
    service = GlobalLearningRegistryService()
    policy = service.promote(
        db,
        candidate=candidate,
        actor_user_id="owner",
        comment="Reviewed anonymization and blind benchmark evidence.",
        idempotency_key="promote-global",
    )
    db.commit()
    previous = None
    for index, stage in enumerate(("shadow", "internal", "canary", "active")):
        deployment = service.deploy(
            db,
            tenant_id="client-a",
            policy=policy,
            rollout_stage=stage,
            actor_user_id="owner",
            comment=f"Human rollout decision for {stage}.",
            idempotency_key=f"deploy-global-{stage}",
            expected_version=index,
        )
        db.commit()
        if previous:
            assert previous.status == "superseded"
        previous = deployment
    effective = service.effective_policy(db, tenant_id="client-a")
    assert effective["global"][0]["policy_id"] == policy.id
    assert "tenant_id" not in policy.__table__.columns

    restored = service.rollback(
        db,
        tenant_id="client-a",
        deployment=deployment,
        actor_user_id="owner",
        comment="Canary comparison requires rollback.",
        idempotency_key="rollback-global-active",
        expected_version=deployment.record_version,
    )
    db.commit()
    assert restored.rollout_stage == "canary"
    assert service.effective_policy(db, tenant_id="client-a")["global"] == []
    assert db.query(GlobalLearningDeployment).filter_by(tenant_id="client-a").count() == 4


def test_slo_does_not_turn_missing_evidence_green_and_counts_only_eligible_cache_calls(db):
    ensure_tenant(db, "client-empty", "Client Empty")
    empty = SLOCalculator().calculate(db, tenant_id="client-empty")
    assert empty["status"] == "insufficient_evidence"
    assert not any(empty["criteria"].values())

    gateway = ProviderAwareCacheGateway()
    run = _run(db, "client-cache", "run-cache-slo")
    gateway.call(
        db=db,
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_name="Demand Classifier",
        model_role="fast",
        cache_scope="global_static",
        messages=[
            {"role": "system", "content": "Stable global operating policy. " * 240},
            {"role": "user", "content": "Tenant-private request"},
        ],
    )
    db.commit()
    calculated = SLOCalculator().calculate(db, tenant_id=run.tenant_id)
    assert calculated["metrics"]["cache_eligible_calls"] == 1
    assert calculated["criteria"]["cache_telemetry_coverage_100_percent"] is True
    assert calculated["criteria"]["warmed_cache_read_positive"] is True
    assert calculated["status"] == "insufficient_evidence"


def test_aggregate_technical_metrics_exposes_only_numeric_operational_evidence(db):
    run = _run(db, "client-metrics", "run-metrics")
    db.add(
        ModelCall(
            id="call-metrics",
            tenant_id=run.tenant_id,
            run_id=run.id,
            agent_name="Architect",
            provider="test",
            model_name="asf-reasoning",
            model_role="reasoning",
            status="success",
            prompt_tokens=101,
            completion_tokens=23,
            cache_eligible_tokens=80,
            cache_read_tokens=40,
            cache_savings_usd=0.01,
            estimated_cost_usd=0.02,
            duration_seconds=1.5,
        )
    )
    db.commit()

    aggregate = _aggregate_technical_metrics(db)

    assert aggregate["workflow_runs_by_status"]["running"] == 1
    assert aggregate["prompt_tokens"] == 101
    assert aggregate["completion_tokens"] == 23
    assert aggregate["cache_read_tokens"] == 40
    serialized = str(aggregate)
    assert run.tenant_id not in serialized
    assert run.id not in serialized
    assert run.demand not in serialized


def test_segmented_protocol_selects_the_new_temporal_workflow(monkeypatch):
    calls = []

    class Handle:
        result_run_id = "temporal-segmented"

    class FakeClient:
        async def start_workflow(self, workflow, payload, **kwargs):
            calls.append((workflow, payload, kwargs))
            return Handle()

    async def connect(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(Client, "connect", connect)
    result = asyncio.run(
        TemporalWorkflowRunner().start_enterprise_run(
            tenant_id="client-a",
            demand="Segmented mission",
            run_id="run-a",
            executor_protocol_version="segmented-output-v1",
        )
    )
    assert calls[0][0] == "SoftwareFactoryAINativeWorkflowV2"
    assert calls[0][1]["executor_protocol_version"] == "segmented-output-v1"
    assert result.run_id == "temporal-segmented"
