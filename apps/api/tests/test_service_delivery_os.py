import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import ensure_tenant
from app.db.session import set_tenant_context
from app.models import (
    AgentAssignment,
    AgentCandidate,
    AgentDefinition,
    AgentEvaluation,
    AgentVersion,
    Base,
    CapabilityGap,
    ComponentDefinition,
    Contract,
    DeliverableRevision,
    Engagement,
    EngagementPlan,
    Entitlement,
    LedgerRecord,
    OfferingVersion,
    OutcomeMetric,
    ServiceDeliverable,
    ServiceOffering,
    ServiceWorkItem,
    Workstream,
)
from app.service_delivery.catalog import ensure_service_catalog, ensure_tenant_agent_catalog
from app.service_delivery.os_service import REQUIRED_FORBIDDEN_ACTIONS, ServiceDeliveryOSService
from app.service_delivery.service import DomainError, ensure_component_definitions


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _tenant(db, tenant_id="client-one"):
    ensure_tenant(db, tenant_id, tenant_id.replace("-", " ").title())
    ensure_component_definitions(db)
    ensure_service_catalog(db)
    db.flush()


def _engagement_with_approved_plan(db, tenant_id="client-one"):
    _tenant(db, tenant_id)
    offering = db.query(ServiceOffering).filter_by(code="ai_value_discovery").one()
    version = db.query(OfferingVersion).filter_by(offering_id=offering.id, version="1.0").one()
    component = db.query(ComponentDefinition).filter_by(code="ai_value_discovery").one()
    contract = Contract(
        id=str(uuid.uuid4()), tenant_id=tenant_id, contract_number=f"CON-{tenant_id}", status="active",
        valid_from="", valid_until="", commercial_metadata_json={}, scope_summary="Discovery for operations",
    )
    db.add(contract)
    db.flush()
    db.add(Entitlement(
        id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id=contract.id,
        component_definition_id=component.id, component_code="ai_value_discovery", status="granted",
        capabilities_json=["service_delivery.activate"], limits_json={}, terms_json={},
    ))
    engagement = Engagement(
        id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id=contract.id, offering_version_id=version.id,
        name="Discovery Operations", description="Assess priority processes", owner_user_id="operator",
        status="awaiting_approval", record_version=1,
    )
    db.add(engagement)
    db.flush()
    plan = EngagementPlan(
        id=str(uuid.uuid4()), tenant_id=tenant_id, engagement_id=engagement.id, version=1, status="approved",
        plan_json={
            "summary": "Approved plan",
            "objectives": ["Prioritize value"],
            "stages": ["Assessment", "Roadmap"],
            "workstreams": [{"key": "discovery", "name": "Discovery", "objective": "Map value"}],
            "deliverables": [
                {
                    "template_key": "maturity_assessment", "title": "Assessment de maturidade",
                    "description": "Tenant-specific assessment", "workstream_key": "discovery",
                    "acceptance_criteria": ["Evidence linked"], "definition_of_done": ["Sponsor reviewed"],
                    "audience": "reviewer", "due_offset_days": 7,
                },
                {
                    "template_key": "roadmap", "title": "Roadmap de 12 meses",
                    "description": "Prioritized roadmap", "workstream_key": "discovery",
                    "acceptance_criteria": ["Dependencies mapped"], "definition_of_done": ["Sponsor accepted"],
                    "audience": "client", "due_offset_days": 14,
                },
            ],
            "risks": [], "next_actions": ["Start interviews"],
        },
        approved_by_user_id="operator",
    )
    db.add(plan)
    db.flush()
    return engagement


def test_catalog_registers_exactly_eight_versioned_offerings_without_runtime_records(db):
    ensure_service_catalog(db)
    db.commit()
    assert db.query(ServiceOffering).count() == 8
    assert db.query(OfferingVersion).count() == 8
    assert db.query(Engagement).count() == 0
    assert db.query(ServiceDeliverable).count() == 0
    assert db.query(ServiceWorkItem).count() == 0
    assert {row.code for row in db.query(ServiceOffering).all()} == {
        "ai_value_discovery",
        "ai_governance_risk_framework",
        "ai_enterprise_launchpad",
        "ai_workforce_productivity_accelerator",
        "ai_engineering_productivity_accelerator",
        "ai_use_case_pilot_sprint",
        "ai_office_as_a_service",
        "ai_adoption_kit_governance_cockpit",
    }


def test_activation_materializes_only_the_approved_tenant_plan(db):
    engagement = _engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    activated = service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="operator", engagement_id=engagement.id,
        expected_version=1, comment="Approved for operation", correlation_id="test",
        event_idempotency_key="activate:one",
    )
    db.commit()
    assert activated.status == "active"
    assert db.query(Workstream).filter_by(tenant_id="client-one", engagement_id=engagement.id).count() == 1
    assert db.query(ServiceDeliverable).filter_by(tenant_id="client-one", engagement_id=engagement.id).count() == 2
    assert db.query(ServiceWorkItem).filter_by(tenant_id="client-one", engagement_id=engagement.id).count() == 2
    assert db.query(AgentDefinition).filter_by(tenant_id="client-one", status="approved").count() == 8
    assert db.query(AgentAssignment).filter_by(tenant_id="client-one", engagement_id=engagement.id, status="active").count() == 3
    assert db.query(LedgerRecord).filter_by(tenant_id="client-one", event_type="agent.assigned").count() == 3
    assert db.query(LedgerRecord).filter_by(tenant_id="client-one", event_type="engagement.activated").count() == 1


def test_known_cross_tenant_ids_are_not_visible(db):
    engagement = _engagement_with_approved_plan(db, "client-one")
    _tenant(db, "client-two")
    with pytest.raises(DomainError) as exc:
        ServiceDeliveryOSService().engagement_bundle(db, "client-two", engagement.id)
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "ENGAGEMENT_NOT_FOUND"


def test_five_client_service_operations_remain_tenant_scoped(db):
    service = ServiceDeliveryOSService()
    engagements = {}
    for index in range(1, 6):
        tenant_id = f"client-{index}"
        engagement = _engagement_with_approved_plan(db, tenant_id)
        engagements[tenant_id] = engagement.id
        service.activate_engagement(
            db, tenant_id=tenant_id, actor_user_id="operator", engagement_id=engagement.id,
            expected_version=1, comment=f"Activate {tenant_id}", correlation_id="five-client-test",
            event_idempotency_key=f"activate:{tenant_id}",
        )
    db.flush()

    for tenant_id, engagement_id in engagements.items():
        set_tenant_context(db, tenant_id, "operator")
        listed = service.list_engagements(db, tenant_id)
        assert [item["id"] for item in listed] == [engagement_id]
        assert db.query(ServiceDeliverable).filter_by(tenant_id=tenant_id).count() == 2
        assert db.query(AgentAssignment).filter_by(tenant_id=tenant_id, engagement_id=engagement_id).count() == 3
        for other_tenant, other_engagement_id in engagements.items():
            if other_tenant == tenant_id:
                continue
            with pytest.raises(DomainError) as exc:
                service.engagement_bundle(db, tenant_id, other_engagement_id)
            assert exc.value.status_code == 404


def test_wip_limits_block_and_audited_override_allows_start(db):
    engagement = _engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    items = []
    for index, status in enumerate(["in_progress", "in_progress", "queued"]):
        item = ServiceWorkItem(
            id=str(uuid.uuid4()), tenant_id="client-one", engagement_id=engagement.id,
            title=f"Work {index}", status=status, priority="normal", record_version=1,
        )
        db.add(item)
        items.append(item)
    db.flush()
    with pytest.raises(DomainError) as exc:
        service.transition_work_item(
            db, tenant_id="client-one", actor_user_id="operator", item_id=items[-1].id,
            status="in_progress", expected_version=1, reason="", override_reason="", global_active=5,
            correlation_id="test", event_idempotency_key="wip:block",
        )
    assert exc.value.detail["code"] == "WIP_LIMIT_REACHED"
    started = service.transition_work_item(
        db, tenant_id="client-one", actor_user_id="operator", item_id=items[-1].id,
        status="in_progress", expected_version=1, reason="", override_reason="Urgent contractual incident",
        global_active=5, correlation_id="test", event_idempotency_key="wip:override",
    )
    assert started.wip_override is True
    assert started.override_reason == "Urgent contractual incident"


def test_deliverable_revision_submission_and_human_decision_are_versioned(db):
    engagement = _engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="operator", engagement_id=engagement.id,
        expected_version=1, comment="Activate", correlation_id="test", event_idempotency_key="activate:deliverable",
    )
    deliverable = db.query(ServiceDeliverable).filter_by(tenant_id="client-one").first()
    revision = service.create_revision(
        db, tenant_id="client-one", actor_user_id="operator", deliverable_id=deliverable.id,
        content={"content_markdown": "# Real assessment"}, artifact_refs=[], evidence_refs=["document:one"],
        model_call_id="", correlation_id="test", event_idempotency_key="revision:one",
    )
    approval = service.submit_deliverable(
        db, tenant_id="client-one", actor_user_id="operator", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, comment="Ready", correlation_id="test",
        event_idempotency_key="submit:one",
    )
    decided = service.decide_deliverable(
        db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, decision="approve", comment="Evidence reviewed",
        correlation_id="test", event_idempotency_key="decision:one",
    )
    delivered = service.deliver_deliverable(
        db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, comment="Delivered to the authorized audience",
        correlation_id="test", event_idempotency_key="delivery:one",
    )
    assert revision.revision == 1
    assert approval.status == "approved"
    assert decided.status == "delivered"
    assert delivered.status == "delivered"
    assert db.query(DeliverableRevision).filter_by(id=revision.id).one().status == "approved"
    assert db.query(LedgerRecord).filter_by(tenant_id="client-one", event_type="service_deliverable.delivered").count() == 1


def test_outcome_metrics_preserve_provenance_and_optimistic_version(db):
    engagement = _engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    metric = service.create_outcome(
        db, tenant_id="client-one", actor_user_id="operator", engagement_id=engagement.id,
        payload={
            "name": "Horas mensais economizadas", "unit": "horas", "baseline_value": 0,
            "target_value": 120, "current_value": None, "provenance": "estimated",
            "source_refs": ["discovery:baseline"], "observed_at": None,
        },
        correlation_id="test", event_idempotency_key="outcome:create",
    )
    observed = service.observe_outcome(
        db, tenant_id="client-one", actor_user_id="operator", metric_id=metric.id,
        payload={
            "expected_version": 1, "current_value": 48, "provenance": "calculated",
            "source_refs": ["report:usage-july"], "observed_at": None,
            "comment": "Calculated from the authorized July usage report",
        },
        correlation_id="test", event_idempotency_key="outcome:observe",
    )
    assert observed.current_value == 48
    assert observed.provenance == "calculated"
    assert observed.record_version == 2
    assert db.query(OutcomeMetric).filter_by(tenant_id="client-one", engagement_id=engagement.id).count() == 1
    with pytest.raises(DomainError) as exc:
        service.observe_outcome(
            db, tenant_id="client-one", actor_user_id="operator", metric_id=metric.id,
            payload={"expected_version": 1, "current_value": 50, "provenance": "real", "source_refs": [], "comment": "stale"},
            correlation_id="test", event_idempotency_key="outcome:stale",
        )
    assert exc.value.detail["code"] == "STALE_RESOURCE_VERSION"


def test_agent_candidate_requires_bounded_tools_and_human_approval(db):
    _tenant(db)
    service = ServiceDeliveryOSService()
    unsafe = {
        "allowed_tools": ["arbitrary_shell"],
        "forbidden_actions": [],
        "context_policy": {"max_rag_chunks": 100, "input_budget_tokens": 500_000},
        "output_schema": {"type": "object"},
    }
    assert not all(service._candidate_checks(unsafe).values())

    gap = CapabilityGap(
        id=str(uuid.uuid4()), tenant_id="client-one", title="Specialist", capability="special_analysis",
        description="Bounded analysis", gap_type="agent", status="candidate_created",
    )
    payload = {
        "code": "special_analysis_agent", "name": "Special Analysis Agent", "purpose": "Perform bounded specialist analysis.",
        "mission": "Analyze authorized tenant evidence and return a structured assessment.",
        "responsibilities": ["analyze"], "allowed_tools": ["read_tenant_knowledge", "create_artifact"],
        "forbidden_actions": sorted(REQUIRED_FORBIDDEN_ACTIONS),
        "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
        "context_policy": {"max_rag_chunks": 4, "input_budget_tokens": 16000},
        "model_role": "reasoning", "benchmark_scenarios": ["Assess a bounded scenario"],
    }
    candidate = AgentCandidate(
        id=str(uuid.uuid4()), tenant_id="client-one", capability_gap_id=gap.id,
        proposed_definition_json=payload, status="ready_for_approval",
    )
    evaluation = AgentEvaluation(
        id=str(uuid.uuid4()), tenant_id="client-one", candidate_id=candidate.id,
        repetitions=3, status="passed", checks_json=service._candidate_checks(payload),
        metrics_json={"schema_valid_rate": 1.0}, results_json=[],
    )
    db.add_all([gap, candidate, evaluation])
    db.flush()
    approved = service.decide_candidate(
        db, tenant_id="client-one", actor_user_id="owner", candidate_id=candidate.id,
        decision="approve", comment="Three benchmark repetitions reviewed", correlation_id="test",
        event_idempotency_key="agent:approve",
    )
    assert approved.status == "approved"
    definition = db.query(AgentDefinition).filter_by(id=approved.agent_definition_id, tenant_id="client-one").one()
    version = db.query(AgentVersion).filter_by(agent_definition_id=definition.id, tenant_id="client-one").one()
    assert definition.scope == "tenant"
    assert version.status == "approved"
    assert "arbitrary_shell" not in version.allowed_tools_json


def test_builtin_agents_are_tenant_private_even_when_templates_are_shared(db):
    _tenant(db, "client-one")
    _tenant(db, "client-two")
    ensure_tenant_agent_catalog(db, "client-one")
    ensure_tenant_agent_catalog(db, "client-two")
    first = {row.code: row.id for row in db.query(AgentDefinition).filter_by(tenant_id="client-one").execution_options(include_all_tenants=True).all()}
    second = {row.code: row.id for row in db.query(AgentDefinition).filter_by(tenant_id="client-two").execution_options(include_all_tenants=True).all()}
    assert set(first) == set(second)
    assert all(first[code] != second[code] for code in first)
