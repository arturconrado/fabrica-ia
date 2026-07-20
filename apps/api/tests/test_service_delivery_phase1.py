import os
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ASF_DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import ProductionRuntimeConfigError, Settings, get_settings, validate_production_runtime
from app.auth.dependencies import ensure_tenant, ensure_user_membership
from app.models import AIActivity, AgentRunState, Approval, ApprovalRequest, Artifact, AuditProjection, Base, CommercialProposal, ComponentInstance, Contract, Entitlement, HomologationPackage, HomologationReport, LedgerRecord, MvpRun, Opportunity, Program, Project, PromptEvaluation, PromptVersion, QualityGate, Tenant, WorkflowRun, WorkflowSlot, utcnow
from app.agents.production_pipeline_provider import ProductionPipelineProvider
from app.service_delivery.ai_prompts import ACTIVE_PROMPT_VERSION, PROMPT_DEFINITIONS, PROMPT_FIXTURES
from app.service_delivery.demo_seed import ATLAS_TENANT_ID, NIMBUS_TENANT_ID, seed_demo_data
from app.service_delivery.commands import begin_command, complete_command
from app.service_delivery.capacity import acquire_workflow_slot, release_workflow_slot
from app.service_delivery.ledger import rebuild_projections, verify_hash_chain
from app.service_delivery.mvp_factory import MvpFactoryService
from app.service_delivery.service import DomainError, ServiceDeliveryService, require_entitlement


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_demo_seed_is_idempotent_and_builds_two_tenants(db):
    first = seed_demo_data(db)
    db.commit()
    counts = {
        "programs": db.query(Program).count(),
        "components": db.query(ComponentInstance).count(),
        "ledger": db.query(LedgerRecord).count(),
    }
    second = seed_demo_data(db)
    db.commit()
    assert first["atlas_program_id"] == second["atlas_program_id"]
    assert db.query(Program).count() == counts["programs"]
    assert db.query(ComponentInstance).count() == counts["components"]
    assert db.query(LedgerRecord).count() == counts["ledger"]


def test_same_email_never_reassigns_an_oidc_subject(db):
    ensure_tenant(db, "identity-tenant", "Identity Tenant")
    first, _ = ensure_user_membership(
        db,
        "identity-tenant",
        "oidc-subject-1",
        email="owner@example.com",
        role="owner",
    )
    second, _ = ensure_user_membership(
        db,
        "identity-tenant",
        "oidc-subject-2",
        email="owner@example.com",
        role="viewer",
    )
    assert first.id != second.id
    assert first.subject == "oidc-subject-1"
    assert second.subject == "oidc-subject-2"


def test_ledger_hash_chain_detects_tampering(db):
    seed_demo_data(db)
    db.commit()
    assert verify_hash_chain(db, ATLAS_TENANT_ID)
    record = db.query(LedgerRecord).filter_by(tenant_id=ATLAS_TENANT_ID).first()
    record.payload_json = {"summary": "tampered"}
    db.commit()
    assert not verify_hash_chain(db, ATLAS_TENANT_ID)


def test_entitlement_blocks_uncontracted_component_start(db):
    data = seed_demo_data(db)
    db.commit()
    service = ServiceDeliveryService()
    blocked = db.query(ComponentInstance).filter_by(tenant_id=ATLAS_TENANT_ID, component_code="ai_office").first()
    with pytest.raises(DomainError) as exc:
        service.transition_component(
            db,
            ATLAS_TENANT_ID,
            "actor",
            "test",
            blocked.id,
            "active",
            "idem-ai-office",
            "Attempt expansion",
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ENTITLEMENT_REQUIRED"
    assert data["atlas_project_id"]


def test_tenant_isolation_hides_known_ids(db):
    data = seed_demo_data(db)
    db.commit()
    service = ServiceDeliveryService()
    with pytest.raises(DomainError) as exc:
        service.get_program(db, NIMBUS_TENANT_ID, data["atlas_program_id"])
    assert exc.value.status_code == 404


def test_approval_decision_is_idempotent(db):
    seed_demo_data(db)
    db.commit()
    service = ServiceDeliveryService()
    approval = db.query(Approval).filter_by(tenant_id=ATLAS_TENANT_ID, status="pending").first()
    service.decide_approval(db, ATLAS_TENANT_ID, "actor", "corr", approval.id, "approve", "ok", "approval-idem")
    db.commit()
    ledger_count = db.query(LedgerRecord).filter_by(tenant_id=ATLAS_TENANT_ID).count()
    service.decide_approval(db, ATLAS_TENANT_ID, "actor", "corr", approval.id, "approve", "ok", "approval-idem")
    db.commit()
    assert db.query(Approval).filter_by(id=approval.id).first().status == "approved"
    assert db.query(LedgerRecord).filter_by(tenant_id=ATLAS_TENANT_ID).count() == ledger_count


def test_runtime_matrix_allows_test_mock_and_blocks_operational_mock():
    validate_production_runtime(
        Settings(
            runtime_profile="test",
            agent_provider="mock",
            workflow_backend="homologation",
            database_url="postgresql+psycopg://factory:factory@localhost:5432/factory",
        )
    )
    with pytest.raises(ProductionRuntimeConfigError):
        validate_production_runtime(
            Settings(
                runtime_profile="homologation",
                agent_provider="mock",
                workflow_backend="homologation",
                database_url="postgresql+psycopg://factory:factory@localhost:5432/factory",
            )
        )
    with pytest.raises(ProductionRuntimeConfigError):
        validate_production_runtime(
            Settings(
                runtime_profile="production",
                agent_provider="mock",
                workflow_backend="temporal",
                database_url="postgresql+psycopg://factory:factory@localhost:5432/factory",
            )
        )


def test_production_runtime_requires_an_otlp_trace_exporter():
    with pytest.raises(ProductionRuntimeConfigError, match="ASF_OTEL_EXPORTER_OTLP_ENDPOINT"):
        validate_production_runtime(
            Settings(
                environment="production",
                runtime_profile="production",
                database_url="postgresql+psycopg://factory_app:secret@postgres:5432/factory",
                auth_disabled=False,
                oidc_issuer_url="https://auth.example.test/realms/asf",
                oidc_jwks_url="http://keycloak:8080/realms/asf/protocol/openid-connect/certs",
                agent_provider="litellm",
                workflow_backend="temporal",
                openrouter_api_key="provider-secret-placeholder",
                litellm_api_key="proxy-secret-placeholder",
                mcp_enabled=True,
                sandbox_backend="kubernetes",
                sandbox_workspace_pvc="asf-sandbox-workspaces",
                generative_build_enabled=True,
                s3_endpoint_url="http://minio:9000",
                s3_bucket="software-factory-artifacts",
                s3_access_key_id="non-default-user",
                s3_secret_access_key="non-default-secret",
                encryption_key="encryption-secret-placeholder",
                observability_enabled=True,
                otel_exporter_otlp_endpoint="",
            )
        )


def test_ai_native_prompt_registry_is_versioned_and_evaluated(db):
    seed_demo_data(db)
    db.commit()
    prompts = db.query(PromptVersion).filter_by(
        tenant_id="global",
        version=ACTIVE_PROMPT_VERSION,
        status="active",
    ).all()
    prompt_codes = {prompt.code for prompt in prompts}
    assert {definition["code"] for definition in PROMPT_DEFINITIONS}.issubset(prompt_codes)
    scoper = next(prompt for prompt in prompts if prompt.code == "mvp_scoper")
    result_schema = scoper.output_schema_json["properties"]["result"]
    assert {"mvp", "p1", "p2", "screens", "apis", "acceptance_criteria"}.issubset(result_schema["required"])
    assert result_schema["properties"]["mvp"]["type"] == "array"
    assert db.query(PromptEvaluation).count() >= len(PROMPT_DEFINITIONS) + len(PROMPT_FIXTURES)


def test_briefing_parser_preserves_structured_users_and_workflow():
    output = {
        "facts": ["A real business workflow was provided."],
        "assumptions": [],
        "unknowns": ["Which approver owns exceptions?"],
        "risks": [],
        "recommendations": [],
        "confidence": 0.92,
        "result": {
            "summary": "Contract operations workflow.",
            "target_user": {"primary": "Operations", "secondary": "Approver"},
            "workflow": ["Create contract", "Issue invoice", "Approve exception"],
            "mvp_features": ["Contracts", "Invoices"],
            "integrations": [],
            "constraints": ["Tenant scoped"],
            "success_metrics": ["No cross-tenant access"],
            "artifact_markdown": "# Briefing\n\nContract operations workflow.",
        },
    }

    structured = MvpFactoryService()._briefing_from_ai("Build contract approvals.", output)

    assert structured["target_user"] == {"primary": "Operations", "secondary": "Approver"}
    assert structured["workflow"] == ["Create contract", "Issue invoice", "Approve exception"]
    assert structured["unknowns"] == ["Which approver owns exceptions?"]


def test_scope_parser_normalizes_structured_phases_screens_and_apis():
    output = {
        "result": {
            "mvp": {"objective": "Core flow", "in_scope": ["Clients", "Contracts"]},
            "p1": {"objective": "Reliability", "scope": ["Audit export"]},
            "p2": {"objective": "Automation", "in_scope": ["ERP integration"]},
            "screens": {"mvp": [{"name": "Contracts", "purpose": "Manage contract lifecycle"}]},
            "apis": {"mvp": [{"method": "GET/POST", "path": "/api/contracts", "purpose": "Contract CRUD"}]},
            "acceptance_criteria": ["Tenant data remains isolated"],
            "deliverables": ["Backend", "Frontend"],
            "scope_markdown": "# Scope\n\nCore flow.",
            "acceptance_markdown": "# Acceptance\n\nTenant isolation.",
        }
    }

    scope = MvpFactoryService()._scope_from_ai(output)

    assert scope["mvp"] == ["Clients", "Contracts"]
    assert scope["p1"] == ["Audit export"]
    assert scope["screens"] == ["Contracts — Manage contract lifecycle"]
    assert scope["apis"] == ["GET/POST /api/contracts — Contract CRUD"]


class InvalidThenValidCommercialGateway:
    def __init__(self):
        self.calls = 0

    def call(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            parsed = {"text": '{"facts": ["truncated"]'}
        else:
            parsed = {
                "facts": ["A contracted workflow was supplied."],
                "assumptions": [],
                "unknowns": [],
                "risks": [],
                "recommendations": ["Proceed with bounded discovery."],
                "evidence_refs": ["opportunity-retry"],
                "confidence": 0.91,
                "requires_human_review": True,
                "result": {
                    "score_commentary": "The deterministic score remains authoritative.",
                    "fit_summary": "The workflow is bounded and suitable for an MVP.",
                    "validation_questions": [],
                },
            }
        return {"id": f"commercial-call-{self.calls}", "content": {"parsed": parsed}}


def test_commercial_activity_retries_an_invalid_structured_response(db, monkeypatch):
    seed_demo_data(db)
    db.commit()
    monkeypatch.setenv("ASF_RUNTIME_PROFILE", "homologation")
    get_settings.cache_clear()
    try:
        service = MvpFactoryService()
        gateway = InvalidThenValidCommercialGateway()
        service.model_gateway = gateway

        activity = service._record_ai_activity(
            db,
            tenant_id=ATLAS_TENANT_ID,
            actor_user_id="actor",
            correlation_id="commercial-retry",
            resource_type="opportunity",
            resource_id="opportunity-retry",
            agent_name="Idea Validator Agent",
            activity_type="idea.validated",
            prompt_code="idea_validator",
            input_json={"summary": "Bounded workflow"},
            output_json={},
        )

        assert gateway.calls == 2
        assert activity.status == "completed"
        assert activity.output_json["result"]["fit_summary"].startswith("The workflow")
    finally:
        get_settings.cache_clear()


def test_mvp_factory_journey_records_ai_activity_and_ledger(db):
    seed_demo_data(db)
    db.commit()
    service = MvpFactoryService()
    prospect = service.create_prospect(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "mvp-test",
        {"name": "Delta Health", "company": "Delta Health", "sector": "healthcare", "source": "unit-test"},
    )
    opportunity = service.create_opportunity(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "mvp-test",
        {"prospect_id": prospect.id, "title": "Clinical approval MVP", "summary": "Approval workflow with SLA"},
    )
    service.add_briefing(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "mvp-test",
        opportunity.id,
        "Hospital group needs an approval workflow with SLA, evidence upload, audit trail and executive dashboard.",
    )
    validated = service.validate_idea(db, ATLAS_TENANT_ID, "actor", "mvp-test", opportunity.id)
    spec = service.scope_mvp(db, ATLAS_TENANT_ID, "actor", "mvp-test", opportunity.id)
    run = service.generate_mvp(db, ATLAS_TENANT_ID, "actor", "mvp-test", opportunity.id)
    service.decide_mvp_run(db, ATLAS_TENANT_ID, "actor", "mvp-test", run.id, "approve", "ok")
    db.commit()

    assert validated.validation_score >= 55
    assert spec.blueprint_ref.endswith("@1.0")
    assert db.query(MvpRun).filter_by(id=run.id, tenant_id=ATLAS_TENANT_ID).first().status == "approved"
    assert db.query(CommercialProposal).filter_by(tenant_id=ATLAS_TENANT_ID, opportunity_id=opportunity.id).count() == 1
    artifacts = db.query(Artifact).filter_by(tenant_id=ATLAS_TENANT_ID, mvp_run_id=run.id).all()
    assert len(artifacts) >= 14
    assert {artifact.evidence_classification for artifact in artifacts}.issubset(
        {"real", "declared", "calculated", "estimated", "simulated", "recommendation"}
    )
    assert run.test_summary_json["status"] == "not_run"
    assert run.test_summary_json["passed"] == 0
    ai_events = db.query(AIActivity).filter_by(tenant_id=ATLAS_TENANT_ID).filter(AIActivity.resource_id.in_([prospect.id, opportunity.id, run.id])).all()
    assert len(ai_events) >= 6
    assert all(event.ledger_record_id for event in ai_events)
    assert db.query(LedgerRecord).filter(LedgerRecord.tenant_id == ATLAS_TENANT_ID, LedgerRecord.event_type.like("ai.%")).count() >= len(ai_events)
    assert verify_hash_chain(db, ATLAS_TENANT_ID)


def test_replaying_discovery_never_regresses_an_approved_converted_mission(db):
    seed_demo_data(db)
    db.commit()
    service = MvpFactoryService()
    prospect = service.create_prospect(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "monotonic-state",
        {"name": "Monotonic Client", "company": "Monotonic Client", "sector": "services"},
    )
    opportunity = service.create_opportunity(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "monotonic-state",
        {"prospect_id": prospect.id, "title": "Monotonic Mission", "summary": "Approval workflow"},
    )
    briefing_text = "Operations needs an approval workflow with audit trail, SLA, dashboard and tenant isolation."
    service.add_briefing(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id, briefing_text)
    service.validate_idea(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id)
    service.scope_mvp(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id)
    mvp_run = service.generate_mvp(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id)
    proposal = db.query(CommercialProposal).filter_by(opportunity_id=opportunity.id).one()
    mvp_run.status = "approved"
    proposal.status = "approved"
    opportunity.status = "converted"
    opportunity.stage = "delivery"
    db.flush()

    service.add_briefing(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id, briefing_text)
    service.validate_idea(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id)
    service.scope_mvp(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id)
    replayed = service.generate_mvp(db, ATLAS_TENANT_ID, "actor", "monotonic-state", opportunity.id)

    assert replayed.id == mvp_run.id
    assert replayed.status == "approved"
    assert proposal.status == "approved"
    assert opportunity.status == "converted"
    assert opportunity.stage == "delivery"


def test_mvp_factory_blocks_tenant_without_entitlement(db):
    seed_demo_data(db)
    db.commit()
    service = MvpFactoryService()
    before = db.query(AIActivity).filter_by(tenant_id=NIMBUS_TENANT_ID).count()
    with pytest.raises(DomainError) as exc:
        service.create_prospect(
            db,
            NIMBUS_TENANT_ID,
            "actor",
            "blocked-mvp",
            {"name": "Nimbus Prospect", "company": "Nimbus Prospect"},
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ENTITLEMENT_REQUIRED"
    assert db.query(AIActivity).filter_by(tenant_id=NIMBUS_TENANT_ID).count() == before


def test_entitlement_resolution_uses_an_active_grant_with_available_capacity(db):
    seed_demo_data(db)
    existing = db.query(Entitlement).filter_by(tenant_id=ATLAS_TENANT_ID, component_code="rapid_mvp_factory").first()
    contract = Contract(
        id="validation-capacity-contract",
        tenant_id=ATLAS_TENANT_ID,
        contract_number="VALIDATION-CAPACITY",
        status="active",
    )
    available = Entitlement(
        id="validation-capacity-entitlement",
        tenant_id=ATLAS_TENANT_ID,
        contract_id=contract.id,
        component_definition_id=existing.component_definition_id,
        component_code=existing.component_code,
        status="granted",
        capabilities_json=list(existing.capabilities_json),
        limits_json={"mvp_runs": 100},
    )
    db.add_all([contract, available])
    db.flush()

    selected = require_entitlement(
        db,
        tenant_id=ATLAS_TENANT_ID,
        component_code="rapid_mvp_factory",
        capability="mvp.generate",
        limit_name="mvp_runs",
        current_value=4,
    )

    assert selected.id == available.id


def test_prospect_batch_validates_ten_and_generates_one_mvp(db):
    seed_demo_data(db)
    db.commit()
    service = MvpFactoryService()
    payload = {
        "prospects": [
            {
                "name": f"Batch Prospect {index}",
                "company": f"Batch Prospect {index}",
                "sector": "enterprise",
                "opportunity_title": f"Batch approval MVP {index}",
                "briefing": "Client needs an approval workflow with SLA, responsible users, evidence, dashboard and audit trail.",
            }
            for index in range(10)
        ]
    }
    result = service.create_prospect_batch(db, ATLAS_TENANT_ID, "actor", "batch-test", payload)
    db.commit()

    assert result["total"] == 10
    assert len(result["generated_mvp_runs"]) == 1
    assert db.query(Opportunity).filter(Opportunity.tenant_id == ATLAS_TENANT_ID, Opportunity.title.like("Batch approval MVP%")).count() == 10
    assert db.query(MvpRun).filter(MvpRun.tenant_id == ATLAS_TENANT_ID, MvpRun.id.in_(result["generated_mvp_runs"])).count() == 1


def test_command_receipt_replays_same_result_and_rejects_payload_change(db):
    seed_demo_data(db)
    db.commit()
    receipt, cached = begin_command(
        db,
        tenant_id=ATLAS_TENANT_ID,
        command_name="test.command",
        idempotency_key="stable-key",
        request_payload={"value": 1},
    )
    assert cached is None
    complete_command(db, receipt, response={"ok": True}, resource_type="test", resource_id="one")
    db.commit()

    _, cached = begin_command(
        db,
        tenant_id=ATLAS_TENANT_ID,
        command_name="test.command",
        idempotency_key="stable-key",
        request_payload={"value": 1},
    )
    assert cached == {"ok": True}
    with pytest.raises(DomainError) as exc:
        begin_command(
            db,
            tenant_id=ATLAS_TENANT_ID,
            command_name="test.command",
            idempotency_key="stable-key",
            request_payload={"value": 2},
        )
    assert exc.value.detail["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"


def test_expired_command_receipt_lease_can_be_recovered(db):
    seed_demo_data(db)
    receipt, cached = begin_command(
        db,
        tenant_id=ATLAS_TENANT_ID,
        command_name="test.recoverable",
        idempotency_key="recoverable-key",
        request_payload={"value": 1},
    )
    assert cached is None
    receipt.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    recovered, cached = begin_command(
        db,
        tenant_id=ATLAS_TENANT_ID,
        command_name="test.recoverable",
        idempotency_key="recoverable-key",
        request_payload={"value": 1},
    )
    assert cached is None
    assert recovered.id == receipt.id
    assert recovered.attempt_count == 2


def test_ledger_projections_are_rebuildable(db):
    seed_demo_data(db)
    db.commit()
    ledger_count = db.query(LedgerRecord).filter_by(tenant_id=ATLAS_TENANT_ID).count()
    db.query(AuditProjection).filter_by(tenant_id=ATLAS_TENANT_ID).delete(synchronize_session=False)
    rebuilt = rebuild_projections(db, ATLAS_TENANT_ID)
    db.commit()
    assert rebuilt["audit_projections"] == ledger_count
    assert db.query(AuditProjection).filter_by(tenant_id=ATLAS_TENANT_ID).count() == ledger_count
    assert verify_hash_chain(db, ATLAS_TENANT_ID)


def test_approved_opportunity_converts_to_contracted_delivery(db):
    seed_demo_data(db)
    db.commit()
    factory = MvpFactoryService()
    prospect = factory.create_prospect(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "delivery-test",
        {"name": "Delivery Co", "company": "Delivery Co"},
    )
    opportunity = factory.create_opportunity(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "delivery-test",
        {"prospect_id": prospect.id, "title": "Controlled Delivery"},
    )
    factory.add_briefing(
        db,
        ATLAS_TENANT_ID,
        "actor",
        "delivery-test",
        opportunity.id,
        "Client needs an approval workflow with evidence, dashboard, responsible users and audit trail.",
    )
    factory.validate_idea(db, ATLAS_TENANT_ID, "actor", "delivery-test", opportunity.id)
    factory.scope_mvp(db, ATLAS_TENANT_ID, "actor", "delivery-test", opportunity.id)
    run = factory.generate_mvp(db, ATLAS_TENANT_ID, "actor", "delivery-test", opportunity.id)
    factory.approve_opportunity(
        db,
        ATLAS_TENANT_ID,
        "sponsor",
        "delivery-test",
        opportunity.id,
        "Approved for the assisted deterministic pilot.",
        "opportunity-approval-test",
    )
    result = factory.convert_to_delivery(
        db,
        ATLAS_TENANT_ID,
        "manager",
        "delivery-test",
        opportunity.id,
        "activate approved proposal",
        "opportunity-conversion-test",
    )
    db.commit()

    assert result["opportunity"]["status"] == "converted"
    assert db.query(Contract).filter_by(id=result["contract"]["id"], tenant_id=ATLAS_TENANT_ID, status="active").count() == 1
    entitlement = db.query(Entitlement).filter_by(id=result["entitlement"]["id"], tenant_id=ATLAS_TENANT_ID).one()
    assert entitlement.status == "granted"
    assert entitlement.terms_json["build_mode"] == "deterministic_package"
    assert entitlement.terms_json["generative_build"] is False
    assert db.query(Project).filter_by(id=result["project"]["id"], tenant_id=ATLAS_TENANT_ID).count() == 1
    component = db.query(ComponentInstance).filter_by(id=result["component_instance"]["id"], tenant_id=ATLAS_TENANT_ID).one()
    assert component.entitlement_id == entitlement.id
    assert db.query(MvpRun).filter_by(id=run.id, component_instance_id=result["component_instance"]["id"]).count() == 1


def test_global_workflow_capacity_is_capped_and_reusable(db):
    runs = []
    projects = []
    for tenant_index in range(6):
        tenant_id = f"capacity-tenant-{tenant_index}"
        db.add(Tenant(id=tenant_id, name=f"Capacity Tenant {tenant_index}", slug=tenant_id))
        project = Project(id=f"capacity-project-{tenant_index}", tenant_id=tenant_id, name="Capacity")
        db.add(project)
        projects.append(project)
    db.flush()
    for tenant_index in range(5):
        for tenant_run_index in range(2):
            index = tenant_index * 2 + tenant_run_index
            run = WorkflowRun(
                id=f"capacity-{index}",
                tenant_id=projects[tenant_index].tenant_id,
                project_id=projects[tenant_index].id,
                workflow_id="software_factory_homologation_v1",
                demand="capacity test",
                status="scheduled",
            )
            db.add(run)
            db.flush()
            acquire_workflow_slot(db, run.id)
            runs.append(run)
    overflow = WorkflowRun(
        id="capacity-overflow",
        tenant_id=projects[5].tenant_id,
        project_id=projects[5].id,
        workflow_id="software_factory_homologation_v1",
        demand="capacity overflow",
        status="scheduled",
    )
    db.add(overflow)
    db.flush()
    with pytest.raises(DomainError) as exc:
        acquire_workflow_slot(db, overflow.id)
    assert exc.value.detail["code"] == "PILOT_WORKFLOW_LIMIT"
    release_workflow_slot(db, runs[0].id)
    acquire_workflow_slot(db, overflow.id)
    assert db.query(WorkflowSlot).count() == 10


def test_per_tenant_workflow_capacity_is_capped_at_two(db):
    tenant = Tenant(id="tenant-cap", name="Tenant Cap", slug="tenant-cap")
    project = Project(id="tenant-cap-project", tenant_id=tenant.id, name="Tenant Cap")
    db.add_all([tenant, project])
    db.flush()
    for index in range(3):
        run = WorkflowRun(
            id=f"tenant-cap-{index}",
            tenant_id=tenant.id,
            project_id=project.id,
            workflow_id="software_factory_homologation_v1",
            demand="tenant capacity test",
            status="scheduled",
        )
        db.add(run)
        db.flush()
        if index < 2:
            acquire_workflow_slot(db, run.id)
        else:
            overflow = run
    with pytest.raises(DomainError) as exc:
        acquire_workflow_slot(db, overflow.id)
    assert exc.value.detail["code"] == "TENANT_WORKFLOW_LIMIT"


def test_contracted_workflow_limit_is_enforced_inside_capacity_lock(db):
    tenant = Tenant(id="contract-cap", name="Contract Cap", slug="contract-cap")
    project = Project(id="contract-cap-project", tenant_id=tenant.id, name="Contract Cap")
    first = WorkflowRun(
        id="contract-cap-1",
        tenant_id=tenant.id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand="first",
        status="scheduled",
    )
    second = WorkflowRun(
        id="contract-cap-2",
        tenant_id=tenant.id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand="second",
        status="scheduled",
    )
    db.add_all([tenant, project, first, second])
    db.flush()
    acquire_workflow_slot(db, first.id, tenant_limit=1)
    with pytest.raises(DomainError) as exc:
        acquire_workflow_slot(db, second.id, tenant_limit=1)
    assert exc.value.detail["code"] == "TENANT_WORKFLOW_LIMIT"
    assert exc.value.detail["details"]["limit"] == 1


def test_cancellation_releases_capacity_only_when_runner_acknowledges(db):
    tenant = Tenant(id="cancel-tenant", name="Cancel Tenant", slug="cancel-tenant")
    project = Project(id="cancel-project", tenant_id=tenant.id, name="Cancel Project")
    run = WorkflowRun(
        id="cancel-run",
        tenant_id=tenant.id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand="cancel",
        status="cancel_requested",
    )
    db.add_all([tenant, project, run])
    db.flush()
    acquire_workflow_slot(db, run.id)
    assert db.get(WorkflowSlot, run.id) is not None
    ProductionPipelineProvider()._finalize_cancellation(db, run)
    assert run.status == "cancelled"
    assert db.get(WorkflowSlot, run.id) is None
    assert db.query(LedgerRecord).filter_by(tenant_id=tenant.id, event_type="run.cancellation_acknowledged").count() == 1


def test_final_decisions_cannot_revert_a_terminal_run(db):
    tenant = Tenant(id="decision-tenant", name="Decision Tenant", slug="decision-tenant")
    project = Project(id="decision-project", tenant_id=tenant.id, name="Decision Project")
    run = WorkflowRun(
        id="decision-run",
        tenant_id=tenant.id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand="decision",
        status="approved_for_homologation",
    )
    db.add_all([tenant, project, run])
    db.flush()
    provider = ProductionPipelineProvider()
    with pytest.raises(DomainError) as reject_error:
        provider.reject_run(db, run.id, "late rejection", commit=False)
    assert reject_error.value.detail["code"] == "RUN_NOT_AWAITING_APPROVAL"
    with pytest.raises(DomainError) as rework_error:
        provider.request_changes(db, run.id, "late rework", commit=False)
    assert rework_error.value.detail["code"] == "REWORK_EXECUTOR_UNAVAILABLE"
    assert run.status == "approved_for_homologation"


def test_temporal_agent_state_seed_is_retry_safe(db):
    tenant = Tenant(id="temporal-seed", name="Temporal Seed", slug="temporal-seed")
    project = Project(id="temporal-seed-project", tenant_id=tenant.id, name="Temporal Seed")
    run = WorkflowRun(
        id="temporal-seed-run",
        tenant_id=tenant.id,
        project_id=project.id,
        workflow_id="software_factory_homologation_v1",
        demand="seed retry",
        status="scheduled",
    )
    db.add_all([tenant, project, run])
    db.flush()
    provider = ProductionPipelineProvider()
    provider._seed_agent_operations(db, run)
    db.flush()
    first_count = db.query(AgentRunState).filter_by(run_id=run.id, tenant_id=tenant.id).count()
    provider._seed_agent_operations(db, run)
    db.flush()
    rows = db.query(AgentRunState).filter_by(run_id=run.id, tenant_id=tenant.id).all()
    assert len(rows) == first_count
    assert len({row.agent_name for row in rows}) == first_count


def test_human_approval_cannot_override_technical_blocker(db):
    data = seed_demo_data(db)
    run = WorkflowRun(
        id="blocked-approval-run",
        tenant_id=ATLAS_TENANT_ID,
        project_id=data["atlas_project_id"],
        workflow_id="software_factory_homologation_v1",
        demand="blocked approval test",
        status="waiting_for_human",
    )
    db.add(run)
    db.add(
        ApprovalRequest(
            id="blocked-approval-request",
            tenant_id=ATLAS_TENANT_ID,
            run_id=run.id,
            title="Final approval",
            description="Must remain blocked",
            status="pending",
            requested_action="approve_for_homologation",
        )
    )
    db.add(
        QualityGate(
            id="blocked-test-gate",
            tenant_id=ATLAS_TENANT_ID,
            run_id=run.id,
            gate_id="tests",
            name="Tests",
            category="technical",
            status="blocked",
            blockers_json=["No passing tests"],
        )
    )
    db.add(
        HomologationReport(
            id="blocked-report",
            tenant_id=ATLAS_TENANT_ID,
            run_id=run.id,
            status="blocked",
            score=0,
            blockers_json=["No passing tests"],
            summary="Blocked",
        )
    )
    db.add(HomologationPackage(id="blocked-package", tenant_id=ATLAS_TENANT_ID, run_id=run.id, path="/tmp/blocked", status="created"))
    db.flush()

    with pytest.raises(DomainError) as exc:
        ProductionPipelineProvider().approve_run(db, run.id, "I approve anyway")
    assert exc.value.detail["code"] == "TECHNICAL_BLOCKERS_PRESENT"
    assert run.status == "waiting_for_human"
    assert db.get(QualityGate, "blocked-test-gate").status == "blocked"
