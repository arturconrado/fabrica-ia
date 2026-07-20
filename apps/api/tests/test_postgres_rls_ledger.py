import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import (
    AIInvocation,
    AgentDefinition,
    ArtifactFragment,
    ExecutionUnit,
    GlobalLearningDeployment,
    GlobalLearningPolicy,
    KnowledgeBase,
    ModelCall,
    Program,
    Project,
    Tenant,
    WorkflowRun,
)
from app.service_delivery.ledger import append_ledger_event, verify_hash_chain


pytestmark = pytest.mark.postgres_hardening


def set_tenant_context(db, tenant_id: str) -> None:
    db.info["tenant_id"] = tenant_id
    db.info["user_id"] = "postgres-test"
    db.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant_id, true), "
            "set_config('app.user_id', 'postgres-test', true)"
        ),
        {"tenant_id": tenant_id},
    )


@pytest.fixture()
def postgres_sessions():
    url = os.getenv("ASF_TEST_POSTGRES_URL", "")
    admin_url = os.getenv("ASF_TEST_POSTGRES_ADMIN_URL", "")
    if not url or not admin_url:
        pytest.skip("ASF_TEST_POSTGRES_URL and ASF_TEST_POSTGRES_ADMIN_URL are required for RLS and concurrent-ledger tests")
    engine = create_engine(url, pool_pre_ping=True)
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    AdminSession = sessionmaker(bind=admin_engine, expire_on_commit=False)
    return engine, Session, AdminSession


def test_runtime_database_role_cannot_bypass_rls(postgres_sessions):
    engine, _, _ = postgres_sessions
    with engine.connect() as connection:
        role = connection.execute(
            text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).mappings().one()
    assert role["rolname"] == "factory_app"
    assert role["rolsuper"] is False
    assert role["rolbypassrls"] is False


def test_runtime_role_can_read_only_rls_safe_aggregate_technical_metrics(postgres_sessions):
    engine, _, AdminSession = postgres_sessions
    suffix = uuid.uuid4().hex
    tenant_id = f"metrics-{suffix}"
    run_id = str(uuid.uuid4())
    setup = AdminSession()
    try:
        tenant = Tenant(id=tenant_id, name="Metrics tenant", slug=tenant_id)
        setup.add(tenant)
        setup.flush()
        project = Project(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Metrics project")
        setup.add(project)
        setup.flush()
        run = WorkflowRun(
            id=run_id,
            tenant_id=tenant_id,
            project_id=project.id,
            workflow_id="software_factory_ai_native_v2",
            generation_mode="ai_native_v2",
            executor_protocol_version="segmented-output-v1",
            demand="Private metrics demand",
            status="running",
        )
        setup.add(run)
        setup.flush()
        call = ModelCall(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            run_id=run_id,
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
        )
        setup.add(call)
        setup.commit()
    finally:
        setup.close()

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM workflow_runs")).scalar_one() == 0
        function_security = connection.execute(
            text(
                "SELECT p.prosecdef, p.proconfig, COALESCE(p.proacl::text, '') "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname = 'asf_aggregate_technical_metrics'"
            )
        ).one()
        payload = connection.execute(text("SELECT public.asf_aggregate_technical_metrics()")).scalar_one()

    assert function_security[0] is True
    assert "search_path=pg_catalog, public" in (function_security[1] or [])
    assert "factory_app=X/" in function_security[2]
    assert not any(entry.startswith("=X/") for entry in function_security[2].strip("{}").split(","))
    assert payload["prompt_tokens"] >= 101
    assert payload["completion_tokens"] >= 23
    assert payload["cache_read_tokens"] >= 40
    serialized = str(payload)
    assert tenant_id not in serialized
    assert run_id not in serialized
    assert "Private metrics demand" not in serialized


def test_postgres_rls_hides_direct_cross_tenant_id(postgres_sessions):
    _, Session, AdminSession = postgres_sessions
    suffix = uuid.uuid4().hex
    tenant_a = f"rls-a-{suffix}"
    tenant_b = f"rls-b-{suffix}"
    program_a = str(uuid.uuid4())
    program_b = str(uuid.uuid4())
    admin = AdminSession()
    admin.add_all(
        [
            Tenant(id=tenant_a, name="RLS A", slug=tenant_a),
            Tenant(id=tenant_b, name="RLS B", slug=tenant_b),
        ]
    )
    admin.commit()
    admin.close()
    db = Session()
    try:
        set_tenant_context(db, tenant_a)
        db.add(Program(id=program_a, tenant_id=tenant_a, name="Visible A"))
        db.commit()
        set_tenant_context(db, tenant_b)
        db.add(Program(id=program_b, tenant_id=tenant_b, name="Visible B"))
        db.commit()

        set_tenant_context(db, tenant_a)
        hidden_tenant = db.execute(text("SELECT id FROM tenants WHERE id = :id"), {"id": tenant_b}).first()
        leaked = db.execute(text("SELECT id FROM programs WHERE id = :id"), {"id": program_b}).first()
        visible = db.execute(text("SELECT id FROM programs WHERE id = :id"), {"id": program_a}).first()
        assert hidden_tenant is None
        assert leaked is None
        assert visible is not None
    finally:
        db.close()


def test_postgres_rls_hides_cross_tenant_knowledge_base(postgres_sessions):
    _, Session, AdminSession = postgres_sessions
    suffix = uuid.uuid4().hex
    tenant_a = f"knowledge-a-{suffix}"
    tenant_b = f"knowledge-b-{suffix}"
    admin = AdminSession()
    admin.add_all(
        [
            Tenant(id=tenant_a, name="Knowledge A", slug=tenant_a),
            Tenant(id=tenant_b, name="Knowledge B", slug=tenant_b),
        ]
    )
    admin.commit()
    admin.close()

    db = Session()
    try:
        set_tenant_context(db, tenant_a)
        base_a = KnowledgeBase(id=str(uuid.uuid4()), tenant_id=tenant_a, name="Private A")
        db.add(base_a)
        db.commit()
        set_tenant_context(db, tenant_b)
        assert db.execute(text("SELECT id FROM knowledge_bases WHERE id = :id"), {"id": base_a.id}).first() is None
        assert db.query(KnowledgeBase).filter_by(id=base_a.id).first() is None
    finally:
        db.close()


def test_postgres_rls_hides_cross_tenant_agent_definition(postgres_sessions):
    _, Session, AdminSession = postgres_sessions
    suffix = uuid.uuid4().hex
    tenant_a = f"agent-a-{suffix}"
    tenant_b = f"agent-b-{suffix}"
    admin = AdminSession()
    admin.add_all(
        [Tenant(id=tenant_a, name="Agent A", slug=tenant_a), Tenant(id=tenant_b, name="Agent B", slug=tenant_b)]
    )
    admin.commit()
    admin.close()

    db = Session()
    try:
        set_tenant_context(db, tenant_a)
        definition = AgentDefinition(
            id=str(uuid.uuid4()), tenant_id=tenant_a, code="private_specialist",
            name="Private Specialist", purpose="Tenant-private capability", scope="tenant", status="approved",
        )
        db.add(definition)
        db.commit()
        set_tenant_context(db, tenant_b)
        assert db.execute(text("SELECT id FROM agent_definitions WHERE id = :id"), {"id": definition.id}).first() is None
        assert db.query(AgentDefinition).filter_by(id=definition.id).first() is None
    finally:
        db.close()


def test_postgres_rls_hides_cross_tenant_ai_invocation(postgres_sessions):
    _, Session, AdminSession = postgres_sessions
    suffix = uuid.uuid4().hex
    tenant_a = f"invocation-a-{suffix}"
    tenant_b = f"invocation-b-{suffix}"
    admin = AdminSession()
    admin.add_all(
        [Tenant(id=tenant_a, name="Invocation A", slug=tenant_a), Tenant(id=tenant_b, name="Invocation B", slug=tenant_b)]
    )
    admin.commit()
    admin.close()

    db = Session()
    try:
        set_tenant_context(db, tenant_a)
        invocation = AIInvocation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            idempotency_key=str(uuid.uuid4()),
            scope_type="rag_query",
            scope_id=str(uuid.uuid4()),
            policy_version="2.13.0",
            routing_policy_version="2.13.0",
        )
        db.add(invocation)
        db.commit()
        set_tenant_context(db, tenant_b)
        assert db.execute(text("SELECT id FROM ai_invocations WHERE id = :id"), {"id": invocation.id}).first() is None
        assert db.query(AIInvocation).filter_by(id=invocation.id).first() is None
    finally:
        db.close()


def test_postgres_rls_isolates_segmented_units_fragments_and_global_deployments(postgres_sessions):
    _, Session, AdminSession = postgres_sessions
    suffix = uuid.uuid4().hex
    tenant_a = f"segmented-a-{suffix}"
    tenant_b = f"segmented-b-{suffix}"
    admin = AdminSession()
    try:
        admin.add_all(
            [Tenant(id=tenant_a, name="Segmented A", slug=tenant_a), Tenant(id=tenant_b, name="Segmented B", slug=tenant_b)]
        )
        admin.flush()
        project = Project(id=str(uuid.uuid4()), tenant_id=tenant_a, name="Private segmented project")
        admin.add(project)
        admin.flush()
        run = WorkflowRun(
            id=str(uuid.uuid4()), tenant_id=tenant_a, project_id=project.id,
            workflow_id="software_factory_ai_native_v2", generation_mode="ai_native_v2",
            executor_protocol_version="segmented-output-v1", demand="Private A", status="running",
        )
        admin.add(run)
        admin.flush()
        call = ModelCall(
            id=str(uuid.uuid4()), tenant_id=tenant_a, run_id=run.id, agent_name="Architect",
            provider="test", model_name="asf-reasoning", model_role="reasoning", status="success",
        )
        admin.add(call)
        admin.flush()
        unit = ExecutionUnit(
            id=str(uuid.uuid4()), tenant_id=tenant_a, run_id=run.id, model_call_id=call.id,
            node_id="Architect", phase="architecture", iteration=1, unit_key="private-section",
            unit_type="artifact_section", strategy="segmented_artifact", action="execute", status="completed",
            output_hash="a" * 64,
        )
        admin.add(unit)
        admin.flush()
        fragment = ArtifactFragment(
            id=str(uuid.uuid4()), tenant_id=tenant_a, run_id=run.id, execution_unit_id=unit.id,
            model_call_id=call.id, node_id="Architect", iteration=1, artifact_name="ARCHITECTURE.md",
            section_key="private-section", order_index=0, content="private tenant A architecture",
            checksum="b" * 64,
        )
        policy = GlobalLearningPolicy(
            id=str(uuid.uuid4()), policy_type="context_strategy", version=f"global-{suffix}",
            title="Abstract global rule", abstract_pattern="Require explicit acceptance criteria.",
            pattern_fingerprint=uuid.uuid4().hex, status="approved",
        )
        admin.add(policy)
        admin.flush()
        deployment = GlobalLearningDeployment(
            id=str(uuid.uuid4()), tenant_id=tenant_a, policy_id=policy.id,
            policy_type=policy.policy_type, rollout_stage="active", status="active",
        )
        admin.add_all([fragment, deployment])
        admin.commit()
    finally:
        admin.close()

    db = Session()
    try:
        set_tenant_context(db, tenant_b)
        assert db.query(ExecutionUnit).filter_by(id=unit.id).first() is None
        assert db.query(ArtifactFragment).filter_by(id=fragment.id).first() is None
        assert db.query(GlobalLearningDeployment).filter_by(id=deployment.id).first() is None
        visible_global = db.query(GlobalLearningPolicy).filter_by(id=policy.id).first()
        assert visible_global is not None
        assert "tenant_id" not in visible_global.__table__.columns
    finally:
        db.close()


def test_postgres_concurrent_ledger_is_ordered_and_retry_idempotent(postgres_sessions):
    _, Session, AdminSession = postgres_sessions
    tenant_id = f"ledger-{uuid.uuid4().hex}"
    setup = AdminSession()
    setup.add(Tenant(id=tenant_id, name="Ledger concurrency", slug=tenant_id))
    setup.commit()
    setup.close()

    def append(index: int, key: str) -> str:
        db = Session()
        try:
            set_tenant_context(db, tenant_id)
            record = append_ledger_event(
                db,
                tenant_id=tenant_id,
                aggregate_type="concurrency_test",
                aggregate_id=str(index),
                event_type="approval.concurrent",
                idempotency_key=key,
                payload={"summary": f"Concurrent approval {index}"},
            )
            db.commit()
            return record.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        distinct_ids = list(pool.map(lambda index: append(index, f"distinct-{index}"), range(20)))
    assert len(set(distinct_ids)) == 20

    with ThreadPoolExecutor(max_workers=5) as pool:
        retried_ids = list(pool.map(lambda _index: append(999, "same-retry-key"), range(5)))
    assert len(set(retried_ids)) == 1

    check = Session()
    try:
        set_tenant_context(check, tenant_id)
        assert verify_hash_chain(check, tenant_id)
        count = check.execute(text("SELECT count(*) FROM ledger_records WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id}).scalar_one()
        assert count == 21
    finally:
        check.close()
