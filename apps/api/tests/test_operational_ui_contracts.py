import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_operator
from app.api.routes_operator import portfolio
from app.api.routes_review import _run_bundle
from app.api.routes_workflows import serialize_workflow_topology
from app.auth.dependencies import Principal, ensure_tenant, ensure_user_membership, require_roles
from app.models import (
    Artifact,
    Base,
    GamificationEvent,
    HomologationPackage,
    LedgerRecord,
    MvpRun,
    Opportunity,
    Program,
    Project,
    Tenant,
    WorkflowDefinition,
    WorkflowRun,
)
from app.schemas.operational import WorkflowTopologyResponse
from app.service_delivery.ledger import GAMIFICATION_POINTS, append_ledger_event, rebuild_projections


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


def test_fresh_database_contains_no_runtime_demo_records(database):
    db, _Session = database
    assert db.query(Tenant).count() == 0
    assert db.query(Program).count() == 0
    assert db.query(Project).count() == 0
    assert db.query(Opportunity).count() == 0
    assert db.query(MvpRun).count() == 0
    assert db.query(WorkflowRun).count() == 0


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


def test_portfolio_enumerates_exactly_five_operator_memberships_with_tenant_scoped_summaries(database, monkeypatch):
    db, Session = database
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
    monkeypatch.setattr(routes_operator, "SessionLocal", Session)

    result = portfolio(_principal("client-1", operator_id), db)
    assert len(result.clients) == 5
    assert {item.tenant_id for item in result.clients} == set(expected_hrs)
    for item in result.clients:
        assert item.active_runs == 1
        assert item.hrs.value == expected_hrs[item.tenant_id]
        assert item.hrs.source_refs == [f"run-{item.tenant_id.split('-')[-1]}"]


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
