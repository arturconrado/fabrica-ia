import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_auth, routes_operator
from app.api.routes_operator import portfolio
from app.api.routes_review import _run_bundle, decide_review_item, review_inbox
from app.api.routes_workflows import serialize_workflow_topology
from app.cli.bootstrap_tenant import seed_release_assets
from app.auth import dependencies as auth_dependencies
from app.auth.dependencies import Principal, ensure_tenant, ensure_user_membership, require_roles, tenant_runtime_configuration
from app.core.config import Settings
from app.models import (
    Artifact,
    Approval,
    Base,
    Contract,
    Engagement,
    GamificationEvent,
    HomologationPackage,
    LedgerRecord,
    Membership,
    MvpRun,
    Opportunity,
    OfferingVersion,
    Program,
    Project,
    ServiceExecution,
    ServiceWorkItem,
    Tenant,
    WorkflowDefinition,
    WorkflowRun,
    Entitlement,
    ComponentInstance,
)
from app.schemas.operational import WorkflowTopologyResponse
from app.schemas.operational import ReviewDecision
from app.schemas import OperatorProfileUpdate
from app.service_delivery.ledger import GAMIFICATION_POINTS, append_ledger_event, rebuild_projections
from app.service_delivery.catalog import ensure_service_catalog


@pytest.fixture()
def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db, Session
    finally:
        db.close()
        engine.dispose()


def _principal(tenant_id: str, user_id: str = "operator-user", role: str = "operator") -> Principal:
    return Principal(
        tenant_id=tenant_id,
        user_id=user_id,
        subject="oidc-subject",
        email="operator@example.test",
        name="Assisted Operator",
        role=role,
        claims={},
        auth_mode="oidc",
    )


def test_tenant_runtime_configuration_keeps_limits_and_rag_opt_in_explicit():
    settings = Settings(
        _env_file=None,
        generative_build_enabled=True,
        pilot_max_users_per_tenant=7,
        pilot_max_concurrent_workflows_per_tenant=2,
        knowledge_max_bases_per_tenant=3,
        knowledge_max_documents_per_tenant=4,
        knowledge_max_total_chars_per_tenant=5,
    )
    pending = tenant_runtime_configuration(settings, "tenant-a", onboarding_status="pending")
    enabled = tenant_runtime_configuration(
        settings,
        "tenant-a",
        onboarding_status="accepted",
        rag_generation_enabled=True,
    )
    assert pending["rag_generation"] == "extractive_only"
    assert enabled["rag_generation"] == "enabled"
    assert enabled["llm_real"] == "enabled"
    assert enabled["storage_prefix"] == "tenants/tenant-a/"
    assert enabled["limits"] == {
        "users": 7,
        "concurrent_workflows": 2,
        "knowledge_bases": 3,
        "knowledge_documents": 4,
        "knowledge_total_chars": 5,
    }


def test_release_seed_is_idempotent_and_contracts_only_the_validation_component(database):
    db, _ = database
    tenant = ensure_tenant(db, "release-contracts", "Release Contracts")
    user, _ = ensure_user_membership(
        db, tenant_id=tenant.id, subject="service-account-release",
        name="Release Validation Service Account", role="release_validator",
    )
    first = seed_release_assets(db, tenant_id=tenant.id, actor_user_id=user.id)
    db.commit()
    second = seed_release_assets(db, tenant_id=tenant.id, actor_user_id=user.id)
    db.commit()
    assert first == second
    entitlements = db.query(Entitlement).filter_by(tenant_id=tenant.id).all()
    assert [(item.component_code, item.status) for item in entitlements] == [
        ("rapid_mvp_factory", "granted")
    ]
    components = db.query(ComponentInstance).filter_by(tenant_id=tenant.id).all()
    assert [item.component_code for item in components] == ["rapid_mvp_factory"]


def test_oidc_authorization_cache_collapses_a_same_identity_burst(monkeypatch):
    tenant_id = f"authz-{uuid.uuid4()}"
    subject = f"subject-{uuid.uuid4()}"
    counter_lock = Lock()
    calls = 0

    def resolve(_db, *, tenant_id: str, subject: str, user_id: str = ""):
        del tenant_id, subject, user_id
        nonlocal calls
        with counter_lock:
            calls += 1
        sleep(0.03)
        return (
            SimpleNamespace(id="user-1"),
            SimpleNamespace(status="active"),
            SimpleNamespace(status="active", role="engagement_manager"),
        )

    monkeypatch.setattr(auth_dependencies, "find_onboarded_principal", resolve)
    monkeypatch.setattr(auth_dependencies, "set_tenant_context", lambda *_args, **_kwargs: None)
    auth_dependencies.invalidate_authorization_cache(tenant_id=tenant_id, subject=subject)
    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(
            lambda _index: auth_dependencies.authorize_oidc_principal(
                object(),
                tenant_id=tenant_id,
                subject=subject,
            ),
            range(24),
        ))

    assert calls == 1
    assert results == [("user-1", "engagement_manager")] * 24
    auth_dependencies.invalidate_authorization_cache(tenant_id=tenant_id, subject=subject)
    assert auth_dependencies.authorize_oidc_principal(
        object(),
        tenant_id=tenant_id,
        subject=subject,
    ) == ("user-1", "engagement_manager")
    assert calls == 2


def test_fresh_database_contains_no_runtime_demo_records(database):
    db, _Session = database
    assert db.query(Tenant).count() == 0
    assert db.query(Program).count() == 0
    assert db.query(Project).count() == 0
    assert db.query(Opportunity).count() == 0
    assert db.query(MvpRun).count() == 0
    assert db.query(WorkflowRun).count() == 0


def test_service_deliverables_use_only_the_specialized_vp_decision_flow(database):
    db, _Session = database
    ensure_tenant(db, "client-vp", "Client VP")
    db.add_all([
        Approval(
            id="deliverable-approval",
            tenant_id="client-vp",
            resource_type="service_deliverable",
            resource_id="deliverable-one",
            title="Review deliverable",
            description="Must use the service-deliverable state machine",
            status="pending",
        ),
        Approval(
            id="regular-approval",
            tenant_id="client-vp",
            resource_type="commercial_proposal",
            resource_id="proposal-one",
            title="Review proposal",
            description="Generic review flow",
            status="pending",
        ),
    ])
    db.commit()
    principal = _principal("client-vp", user_id="vp-user", role="engagement_manager")

    inbox = review_inbox(principal, db)
    assert [item["id"] for item in inbox["items"]] == ["regular-approval"]

    with pytest.raises(HTTPException) as exc:
        decide_review_item(
            "deliverable-approval",
            ReviewDecision(decision="approve", comment="Reviewed in the wrong endpoint"),
            "generic-deliverable-decision",
            principal,
            db,
        )
    assert exc.value.status_code == 409


def test_topology_contract_preserves_conditions_and_review_loops():
    yaml_content = """
graph:
  ui:
    direction: LR
  phases:
    - id: build
      label: Build
    - id: review
      label: Review
  nodes:
    - id: engineer
      type: agent
      phase: build
      skill: implementation
    - id: reviewer
      type: agent
      phase: review
  edges:
    - from: engineer
      to: reviewer
      condition: tests_passed
    - from: reviewer
      to: engineer
      condition: changes_requested
      max_iterations: 3
"""
    workflow = WorkflowDefinition(
        id=str(uuid.uuid4()),
        tenant_id="client-topology",
        workflow_id="review-loop",
        version="1.0",
        name="Review loop",
        description="Persisted topology",
        yaml_content=yaml_content,
    )
    serialized = serialize_workflow_topology(workflow)
    response = WorkflowTopologyResponse.model_validate(serialized).model_dump(by_alias=True)
    assert response["ui"] == {"direction": "LR"}
    assert response["nodes"][0]["skill"] == "implementation"
    assert response["edges"] == [
        {"from": "engineer", "to": "reviewer", "condition": "tests_passed", "max_iterations": None},
        {"from": "reviewer", "to": "engineer", "condition": "changes_requested", "max_iterations": 3},
    ]


def test_xp_is_ledger_linked_idempotent_and_ignores_failures_and_queries(database):
    db, _Session = database
    ensure_tenant(db, "client-xp", "Client XP")
    for event_type, points in GAMIFICATION_POINTS.items():
        record = append_ledger_event(
            db,
            tenant_id="client-xp",
            aggregate_type="test",
            aggregate_id=event_type,
            event_type=event_type,
            actor_user_id="operator-user",
            idempotency_key=f"xp:{event_type}",
            payload={"summary": event_type},
        )
        duplicate = append_ledger_event(
            db,
            tenant_id="client-xp",
            aggregate_type="test",
            aggregate_id=event_type,
            event_type=event_type,
            actor_user_id="operator-user",
            idempotency_key=f"xp:{event_type}",
            payload={"summary": event_type},
        )
        assert duplicate.id == record.id
        projected = db.query(GamificationEvent).filter_by(ledger_record_id=record.id).one()
        assert projected.points == points

    for event_type in ("quality.gate_failed", "approval.rejected", "knowledge.retrieval_completed"):
        append_ledger_event(
            db,
            tenant_id="client-xp",
            aggregate_type="test",
            aggregate_id=event_type,
            event_type=event_type,
            actor_user_id="operator-user",
            idempotency_key=f"no-xp:{event_type}",
        )
    db.commit()
    assert db.query(GamificationEvent).count() == len(GAMIFICATION_POINTS)
    assert sum(row.points for row in db.query(GamificationEvent).all()) == 230
    assert all(row.ledger_record_id for row in db.query(GamificationEvent).all())

    counts = rebuild_projections(db, "client-xp")
    assert counts["gamification_events"] == len(GAMIFICATION_POINTS)
    assert db.query(GamificationEvent).count() == len(GAMIFICATION_POINTS)


def test_portfolio_enumerates_exactly_five_operator_memberships_with_tenant_scoped_summaries(database):
    db, _Session = database
    operator_id = ""
    expected_hrs = {}
    for index in range(1, 6):
        tenant_id = f"client-{index}"
        ensure_tenant(db, tenant_id, f"Client {index}")
        user, membership = ensure_user_membership(
            db,
            tenant_id,
            "shared-operator-subject",
            email="operator@example.test",
            role="operator",
        )
        operator_id = user.id
        membership.role = "operator"
        project = Project(
            id=f"project-{index}",
            tenant_id=tenant_id,
            name=f"Private project {index}",
            description="tenant scoped",
        )
        run = WorkflowRun(
            id=f"run-{index}",
            tenant_id=tenant_id,
            project_id=project.id,
            workflow_id="factory",
            demand=f"Private demand {index}",
            status="running",
            homologation_readiness_score=float(index * 10),
        )
        db.add_all([project, run])
        expected_hrs[tenant_id] = float(index * 10)
    db.commit()
    result = portfolio(_principal("client-1", operator_id), db)
    assert len(result.clients) == 5
    assert {item.tenant_id for item in result.clients} == set(expected_hrs)
    for item in result.clients:
        assert item.active_runs == 1
        assert item.hrs.value == expected_hrs[item.tenant_id]
        assert item.hrs.source_refs == [f"run-{item.tenant_id.split('-')[-1]}"]


def test_operator_work_queue_projects_execution_identity_and_mode(database):
    db, _Session = database
    ensure_tenant(db, "client-queue", "Client Queue")
    user, membership = ensure_user_membership(
        db,
        "client-queue",
        "queue-operator-subject",
        email="operator@example.test",
        role="operator",
    )
    membership.role = "operator"
    membership.operator_profile = "software_engineer"
    ensure_service_catalog(db)
    offering_version = db.query(OfferingVersion).filter_by(version="2.0").first()
    contract = Contract(
        id="contract-queue",
        tenant_id="client-queue",
        contract_number="QUEUE-001",
        status="active",
    )
    engagement = Engagement(
        id="engagement-queue",
        tenant_id="client-queue",
        contract_id=contract.id,
        offering_version_id=offering_version.id,
        name="Queue projection",
        status="active",
    )
    queued_agent = ServiceWorkItem(
        id="work-item-agent",
        tenant_id="client-queue",
        engagement_id=engagement.id,
        title="Already enqueued",
        execution_mode="technical_run",
        status="queued",
    )
    queued_human = ServiceWorkItem(
        id="work-item-human",
        tenant_id="client-queue",
        engagement_id=engagement.id,
        title="Still actionable",
        execution_mode="human",
        status="queued",
    )
    blocked_business = ServiceWorkItem(
        id="work-item-blocked",
        tenant_id="client-queue",
        engagement_id=engagement.id,
        title="Critical business exception",
        execution_mode="human",
        status="blocked",
        priority="normal",
    )
    execution = ServiceExecution(
        id="execution-agent",
        tenant_id="client-queue",
        engagement_id=engagement.id,
        work_item_id=queued_agent.id,
        execution_mode="technical_run",
        status="queued",
    )
    db.add(contract)
    db.flush()
    db.add(engagement)
    db.flush()
    db.add_all([queued_agent, queued_human, blocked_business])
    db.flush()
    db.add(execution)
    db.commit()
    result = routes_operator.operator_work_queue(_principal("client-queue", user.id), db)
    rows = {row["id"]: row for row in result["items"]}

    assert rows[queued_agent.id]["execution_mode"] == "technical_run"
    assert rows[queued_agent.id]["execution_id"] == execution.id
    assert rows[queued_agent.id]["execution_status"] == "queued"
    assert rows[queued_human.id]["execution_mode"] == "human"
    assert rows[queued_human.id]["execution_id"] is None
    assert rows[queued_human.id]["execution_status"] is None
    ordered_ids = [row["id"] for row in result["items"]]
    assert ordered_ids[0] == blocked_business.id
    assert ordered_ids.index(queued_agent.id) < ordered_ids.index(queued_human.id)


def test_operator_profile_changes_copy_only_and_preserves_rbac(database):
    db, _Session = database
    ensure_tenant(db, "client-profile", "Client Profile")
    user, membership = ensure_user_membership(
        db,
        tenant_id="client-profile",
        subject="profile-subject",
        email="profile@example.test",
        role="operator",
    )
    db.commit()
    result = routes_auth.update_operator_profile(
        OperatorProfileUpdate(operator_profile="qa_quality"),
        _principal("client-profile", user.id),
        db,
    )
    db.refresh(membership)
    assert result == {"operator_profile": "qa_quality"}
    assert membership.operator_profile == "qa_quality"
    assert membership.role == "operator"
    assert db.query(Membership).filter_by(
        tenant_id="client-profile",
        user_id=user.id,
    ).count() == 1
    event = db.query(LedgerRecord).filter_by(
        tenant_id="client-profile",
        event_type="membership.operator_profile_changed",
    ).one()
    assert event.payload_json["role"] == "operator"


def test_operator_capacity_counts_machine_wip_not_external_evidence_waits(database):
    db, _Session = database
    ensure_tenant(db, "client-capacity", "Client Capacity")
    user, membership = ensure_user_membership(
        db,
        tenant_id="client-capacity",
        subject="capacity-owner",
        email="capacity@example.test",
        role="operator",
    )
    membership.role = "operator"
    ensure_service_catalog(db)
    offering_version = db.query(OfferingVersion).filter_by(version="2.0").first()
    contract = Contract(
        id="contract-capacity", tenant_id="client-capacity",
        contract_number="CAP-001", status="active",
    )
    engagement = Engagement(
        id="engagement-capacity", tenant_id="client-capacity",
        contract_id=contract.id, offering_version_id=offering_version.id,
        name="Capacity projection", status="active",
    )
    machine_item = ServiceWorkItem(
        id="work-capacity-machine", tenant_id="client-capacity",
        engagement_id=engagement.id, title="Machine work",
        execution_mode="agent", status="in_progress",
    )
    external_item = ServiceWorkItem(
        id="work-capacity-external", tenant_id="client-capacity",
        engagement_id=engagement.id, title="External evidence",
        execution_mode="human", status="in_progress",
    )
    db.add(contract)
    db.flush()
    db.add(engagement)
    db.flush()
    db.add_all([machine_item, external_item])
    db.flush()
    db.add_all([
        ServiceExecution(
            id="execution-capacity-machine", tenant_id="client-capacity",
            engagement_id=engagement.id, work_item_id=machine_item.id,
            execution_mode="agent", status="running",
        ),
        ServiceExecution(
            id="execution-capacity-external", tenant_id="client-capacity",
            engagement_id=engagement.id, work_item_id=external_item.id,
            execution_mode="human", status="waiting_for_evidence",
        ),
    ])
    db.commit()

    result = routes_operator.operator_capacity(_principal("client-capacity", user.id), db)

    assert result.active_total == 1
    assert result.available_slots == result.global_limit - 1
    assert result.tenants[0]["active"] == 1


def test_reviewer_bundle_exposes_only_promoted_artifacts_and_sanitized_package(database):
    db, _Session = database
    ensure_tenant(db, "client-review", "Client Review")
    project = Project(id="project-review", tenant_id="client-review", name="Review project", description="")
    run = WorkflowRun(
        id="run-review",
        tenant_id="client-review",
        project_id=project.id,
        workflow_id="factory",
        demand="Review the authorized package",
        status="waiting_for_human",
    )
    db.add_all([project, run])
    db.flush()
    db.add_all([
        Artifact(
            id="artifact-internal",
            tenant_id="client-review",
            run_id=run.id,
            artifact_type="internal_log",
            name="Internal prompt",
            path="/private/internal.md",
            content="must remain private",
            audience="internal",
        ),
        Artifact(
            id="artifact-reviewer",
            tenant_id="client-review",
            run_id=run.id,
            artifact_type="report",
            name="Authorized report",
            path="/private/authorized.md",
            content="safe content",
            audience="reviewer",
            evidence_classification="real",
        ),
        HomologationPackage(
            id="package-review",
            tenant_id="client-review",
            run_id=run.id,
            path="s3://private/tenant/run.zip",
            status="created",
            manifest_json={
                "run_id": run.id,
                "storage_prefix": "tenants/client-review/private",
                "source_files": ["secret.py"],
                "artifacts": [{"id": "artifact-reviewer", "name": "Authorized report", "classification": "real", "path": "/private/authorized.md"}],
            },
        ),
    ])
    db.commit()

    bundle = _run_bundle(db, "client-review", run)
    assert [artifact["id"] for artifact in bundle["artifacts"]] == ["artifact-reviewer"]
    assert "path" not in bundle["artifacts"][0]
    manifest = bundle["packages"][0]["manifest_json"]
    assert "storage_prefix" not in manifest
    assert "source_files" not in manifest
    assert "path" not in manifest["artifacts"][0]


def test_role_matrix_blocks_reviewer_from_technical_routes_and_auditor_from_decisions():
    technical = require_roles("operator")
    decisions = require_roles("operator", "reviewer")
    assert decisions(_principal("client", role="reviewer")).role == "reviewer"
    with pytest.raises(HTTPException) as reviewer_denied:
        technical(_principal("client", role="reviewer"))
    assert reviewer_denied.value.status_code == 403
    with pytest.raises(HTTPException) as auditor_denied:
        decisions(_principal("client", role="auditor"))
    assert auditor_denied.value.status_code == 403


def test_release_validator_is_readiness_only_and_never_inherits_owner_or_operator_authority():
    principal = _principal("release-homologation", role="release_validator")
    assert require_roles("release_validator")(principal).role == "release_validator"
    for protected_role in ("owner", "operator", "engagement_manager"):
        with pytest.raises(HTTPException) as denied:
            require_roles(protected_role)(principal)
        assert denied.value.status_code == 403
