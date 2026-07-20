from typing import Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.auth.dependencies import ensure_tenant, ensure_user_membership
from app.db.session import set_tenant_context
from app.domain.ids import new_id
from app.models import (
    Approval,
    AuditLog,
    AuditProjection,
    ComponentDefinition,
    ComponentInstance,
    Contract,
    Entitlement,
    GamificationEvent,
    LedgerRecord,
    Membership,
    Program,
    Project,
    Role,
    Score,
    Tenant,
    UserAccount,
)
from app.service_delivery.ai_prompts import ensure_prompt_versions
from app.service_delivery.calculations import DeterministicCalculationEngine
from app.service_delivery.ledger import append_ledger_event
from app.service_delivery.mvp_factory import MvpFactoryService
from app.service_delivery.service import ensure_component_definitions


ATLAS_TENANT_ID = "atlas-industrial"
NIMBUS_TENANT_ID = "nimbus-financeira"


DEMO_USERS = [
    ("admin@demo.local", "Atlas Admin", "super_admin"),
    ("consultant@demo.local", "Atlas Consultant", "consultant"),
    ("sponsor@demo.local", "Atlas Sponsor", "client_sponsor"),
    ("reviewer@demo.local", "Atlas Reviewer", "reviewer"),
    ("auditor@demo.local", "Atlas Auditor", "auditor"),
]


CAPABILITIES = [
    "component.view",
    "component.start",
    "intake.upload",
    "approval.submit",
    "deliverable.generate",
]

MVP_CAPABILITIES = [
    "briefing.intake",
    "idea.validate",
    "mvp.scope",
    "mvp.generate",
    "mvp.review",
    "proposal.generate",
    "package.export",
    "component.start",
    "component.view",
    "asf.run.create",
    "homologation.package",
    "delivery.approve",
]


def seed_demo_data(db: Session, actor_user_id: str = "system") -> Dict[str, str]:
    ensure_component_definitions(db)
    ensure_prompt_versions(db)
    local = ensure_tenant(db, "local-dev", "Local Development")
    local.runtime_configuration_json = {"runtime_profile": "homologation", "llm_provider": "mock", "onboarding_status": "accepted", "build_mode": "deterministic_package", "generative_build": False}
    ensure_user_membership(
        db,
        "local-dev",
        "operator@local.dev",
        email="operator@local.dev",
        name="Local Operator",
        role="owner",
    )
    atlas = ensure_tenant(db, ATLAS_TENANT_ID, "Atlas Industrial S.A.")
    atlas.runtime_configuration_json = {"runtime_profile": "homologation", "llm_provider": "mock", "onboarding_status": "accepted", "build_mode": "deterministic_package", "generative_build": False}
    atlas.retention_policy_json = {"documents_days": 365, "audit_years": 7}
    nimbus = ensure_tenant(db, NIMBUS_TENANT_ID, "Nimbus Financeira S.A.")
    nimbus.runtime_configuration_json = {"runtime_profile": "homologation", "llm_provider": "mock", "onboarding_status": "accepted", "build_mode": "deterministic_package", "generative_build": False}
    nimbus.retention_policy_json = {"documents_days": 180, "audit_years": 7}
    for email, name, role in DEMO_USERS:
        user, membership = ensure_user_membership(db, ATLAS_TENANT_ID, email, email=email, name=name, role=role)
        membership.role = role
        user.name = name
    ensure_user_membership(db, NIMBUS_TENANT_ID, "nimbus.auditor@demo.local", email="nimbus.auditor@demo.local", name="Nimbus Auditor", role="auditor")

    set_tenant_context(db, ATLAS_TENANT_ID, actor_user_id)
    atlas_program = _get_or_create_program(
        db,
        tenant_id=ATLAS_TENANT_ID,
        name="Programa Corporativo de IA Atlas",
        description="Programa de descoberta de valor, governança e preparação de adoção de IA.",
        sponsor="Marina Rocha",
        start_date="2026-07-01",
        target_end_date="2026-12-31",
    )
    atlas_project = _get_or_create_project(
        db,
        tenant_id=ATLAS_TENANT_ID,
        program_id=atlas_program.id,
        name="Assessment Corporativo 2026",
        scope="Compras, operações, TI, jurídico e engenharia.",
        owner_user_id=_user_id(db, "consultant@demo.local"),
    )
    atlas_contract = _get_or_create_contract(
        db,
        tenant_id=ATLAS_TENANT_ID,
        contract_number="ATLAS-AI-2026-001",
        status="active",
        valid_from="2026-07-01",
        valid_until="2026-12-31",
        scope_summary="Discovery e Responsible AI & Governance para cinco áreas corporativas.",
    )
    discovery_entitlement = _get_or_create_entitlement(
        db,
        tenant_id=ATLAS_TENANT_ID,
        contract=atlas_contract,
        component_code="ai_value_discovery",
        limits={"areas": 5, "interviews": 20, "users": 50, "connectors": 3, "deliverable_revisions": 2},
    )
    governance_entitlement = _get_or_create_entitlement(
        db,
        tenant_id=ATLAS_TENANT_ID,
        contract=atlas_contract,
        component_code="responsible_ai_governance",
        limits={"areas": 5, "interviews": 12, "users": 30, "connectors": 2, "deliverable_revisions": 2},
    )
    mvp_entitlement = _get_or_create_entitlement(
        db,
        tenant_id=ATLAS_TENANT_ID,
        contract=atlas_contract,
        component_code="rapid_mvp_factory",
        limits={"prospects": 20, "mvp_runs": 3, "users": 20, "deliverable_revisions": 2, "concurrent_workflows": 2},
        capabilities=MVP_CAPABILITIES,
    )
    discovery = _get_or_create_component(
        db,
        tenant_id=ATLAS_TENANT_ID,
        project_id=atlas_project.id,
        entitlement=discovery_entitlement,
        component_code="ai_value_discovery",
        status="active",
        progress=70.0,
        health=78.0,
        current_phase="Priorização e ROI",
        milestones=[
            {"name": "Onboarding", "status": "completed", "points": 50},
            {"name": "Entrevistas", "status": "completed", "points": 80},
            {"name": "Priorização", "status": "active", "points": 20},
            {"name": "Deck executivo", "status": "pending", "points": 0},
        ],
        tasks=[
            {"name": "15 documentos simulados validados", "status": "completed"},
            {"name": "8 entrevistas concluídas", "status": "completed"},
            {"name": "5 lacunas em análise", "status": "active"},
            {"name": "Aprovação de premissas de ROI", "status": "pending"},
        ],
        limits_consumed={"areas": 5, "interviews": 8, "users": 18, "connectors": 2, "deliverable_revisions": 1},
    )
    _get_or_create_component(
        db,
        tenant_id=ATLAS_TENANT_ID,
        project_id=atlas_project.id,
        entitlement=governance_entitlement,
        component_code="responsible_ai_governance",
        status="awaiting_prerequisites",
        progress=30.0,
        health=68.0,
        current_phase="Inventário inicial",
        milestones=[
            {"name": "Inventário", "status": "active", "points": 20},
            {"name": "Classificação de risco", "status": "pending", "points": 0},
        ],
        tasks=[
            {"name": "Sponsor de governança pendente", "status": "blocked"},
            {"name": "Dependência parcial do Discovery", "status": "active"},
        ],
        limits_consumed={"areas": 2, "interviews": 2, "users": 8, "connectors": 1},
    )
    for code in ["ai_enterprise_launchpad", "engineering_productivity_accelerator", "ai_office"]:
        _get_or_create_blocked_component(db, tenant_id=ATLAS_TENANT_ID, project_id=atlas_project.id, component_code=code)
    _get_or_create_component(
        db,
        tenant_id=ATLAS_TENANT_ID,
        project_id=atlas_project.id,
        entitlement=mvp_entitlement,
        component_code="rapid_mvp_factory",
        status="active",
        progress=45.0,
        health=84.0,
        current_phase="Prospect validation",
        milestones=[
            {"name": "Briefing intake", "status": "completed", "points": 25},
            {"name": "Idea validation", "status": "active", "points": 15},
            {"name": "MVP package", "status": "pending", "points": 0},
        ],
        tasks=[
            {"name": "10 prospects capacity enabled", "status": "completed"},
            {"name": "1 demo opportunity generated", "status": "active"},
        ],
        limits_consumed={"prospects": 1, "mvp_runs": 1, "users": 6, "deliverable_revisions": 0},
    )

    approval = _get_or_create_approval(
        db,
        tenant_id=ATLAS_TENANT_ID,
        resource_id=discovery.id,
        approver_user_id=_user_id(db, "sponsor@demo.local"),
    )
    _upsert_project_health(db, tenant_id=ATLAS_TENANT_ID, program_id=atlas_program.id, project_id=atlas_project.id, approvals_sla=80.0)
    _seed_gamification(db, tenant_id=ATLAS_TENANT_ID, program_id=atlas_program.id, component_id=discovery.id)
    _seed_ledger_events(db, tenant_id=ATLAS_TENANT_ID, actor_user_id=actor_user_id, program_id=atlas_program.id, project_id=atlas_project.id, component_id=discovery.id, approval_id=approval.id)
    _seed_mvp_factory_data(db, actor_user_id=actor_user_id, project_id=atlas_project.id, program_id=atlas_program.id)

    set_tenant_context(db, NIMBUS_TENANT_ID, actor_user_id)
    nimbus_program = _get_or_create_program(
        db,
        tenant_id=NIMBUS_TENANT_ID,
        name="Programa de IA Nimbus",
        description="Tenant isolado para validação de segregação.",
        sponsor="Rafael Lima",
        start_date="2026-08-01",
        target_end_date="2026-10-31",
    )
    _get_or_create_project(
        db,
        tenant_id=NIMBUS_TENANT_ID,
        program_id=nimbus_program.id,
        name="Assessment Financeiro 2026",
        scope="Dados mínimos de demonstração isolada.",
        owner_user_id="",
    )
    _seed_ledger_events(db, tenant_id=NIMBUS_TENANT_ID, actor_user_id=actor_user_id, program_id=nimbus_program.id, project_id="", component_id="", approval_id="")
    db.flush()
    set_tenant_context(db, ATLAS_TENANT_ID, actor_user_id)
    return {"atlas_tenant_id": ATLAS_TENANT_ID, "nimbus_tenant_id": NIMBUS_TENANT_ID, "atlas_program_id": atlas_program.id, "atlas_project_id": atlas_project.id}


def reset_demo_data(db: Session, tenant_id: str = ATLAS_TENANT_ID) -> None:
    from app.models import AIActivity, AgentRecommendation, Artifact, Briefing, CommercialProposal, MvpRun, MvpSpec, Opportunity, Prospect

    if tenant_id not in {ATLAS_TENANT_ID, NIMBUS_TENANT_ID}:
        raise ValueError("Only demo tenants can be reset")
    set_tenant_context(db, tenant_id)
    tenant_ids = [tenant_id]
    # The event ledger is append-only in every profile. Reset only disposable
    # demo business data and preserve tenant identities, memberships and ledger.
    db.query(Artifact).filter(Artifact.tenant_id.in_(tenant_ids), Artifact.mvp_run_id.is_not(None)).delete(synchronize_session=False)
    for model in [AgentRecommendation, AIActivity, CommercialProposal, MvpRun, MvpSpec, Briefing, Opportunity, Prospect]:
        db.query(model).filter(model.tenant_id.in_(tenant_ids)).delete(synchronize_session=False)
    append_ledger_event(
        db,
        tenant_id=tenant_id,
        aggregate_type="demo",
        aggregate_id=tenant_id,
        event_type="demo.reset",
        idempotency_key=f"demo-reset:{new_id()}",
        payload={"summary": "Disposable MVP intake data reset; operational base and ledger retained."},
    )
    db.flush()


def _user_id(db: Session, email: str) -> str:
    user = db.query(UserAccount).filter_by(email=email).first()
    return user.id if user else ""


def _component_definition(db: Session, code: str) -> ComponentDefinition:
    definition = db.query(ComponentDefinition).filter_by(code=code, version="1.0").first()
    if not definition:
        raise RuntimeError(f"Missing component definition: {code}")
    return definition


def _get_or_create_program(db: Session, *, tenant_id: str, name: str, description: str, sponsor: str, start_date: str, target_end_date: str) -> Program:
    program = db.query(Program).filter_by(tenant_id=tenant_id, name=name).first()
    if program:
        return program
    program = Program(id=new_id(), tenant_id=tenant_id, name=name, description=description, sponsor=sponsor, status="active", start_date=start_date, target_end_date=target_end_date)
    db.add(program)
    db.flush()
    return program


def _get_or_create_project(db: Session, *, tenant_id: str, program_id: str, name: str, scope: str, owner_user_id: str) -> Project:
    project = db.query(Project).filter_by(tenant_id=tenant_id, program_id=program_id, name=name).first()
    if project:
        return project
    project = Project(id=new_id(), tenant_id=tenant_id, program_id=program_id, name=name, description=scope, scope=scope, owner_user_id=owner_user_id, status="active")
    db.add(project)
    db.flush()
    return project


def _get_or_create_contract(db: Session, *, tenant_id: str, contract_number: str, status: str, valid_from: str, valid_until: str, scope_summary: str) -> Contract:
    contract = db.query(Contract).filter_by(tenant_id=tenant_id, contract_number=contract_number).first()
    if contract:
        return contract
    contract = Contract(id=new_id(), tenant_id=tenant_id, contract_number=contract_number, status=status, valid_from=valid_from, valid_until=valid_until, scope_summary=scope_summary, commercial_metadata_json={"sector": "manufacturing", "employees": 2500})
    db.add(contract)
    db.flush()
    return contract


def _get_or_create_entitlement(db: Session, *, tenant_id: str, contract: Contract, component_code: str, limits: Dict[str, int], capabilities: Optional[list] = None) -> Entitlement:
    entitlement = db.query(Entitlement).filter_by(tenant_id=tenant_id, contract_id=contract.id, component_code=component_code).first()
    if entitlement:
        entitlement.limits_json = limits
        if capabilities:
            entitlement.capabilities_json = sorted(set(entitlement.capabilities_json or []).union(capabilities))
        return entitlement
    definition = _component_definition(db, component_code)
    entitlement = Entitlement(
        id=new_id(),
        tenant_id=tenant_id,
        contract_id=contract.id,
        component_definition_id=definition.id,
        component_code=component_code,
        status="granted",
        valid_from=contract.valid_from,
        valid_until=contract.valid_until,
        limits_json=limits,
        capabilities_json=capabilities or CAPABILITIES,
        terms_json={"commercial_scope": "demo"},
    )
    db.add(entitlement)
    db.flush()
    return entitlement


def _get_or_create_component(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    entitlement: Entitlement,
    component_code: str,
    status: str,
    progress: float,
    health: float,
    current_phase: str,
    milestones: Iterable[Dict[str, object]],
    tasks: Iterable[Dict[str, object]],
    limits_consumed: Dict[str, int],
) -> ComponentInstance:
    component = db.query(ComponentInstance).filter_by(tenant_id=tenant_id, project_id=project_id, component_code=component_code).first()
    if component:
        return component
    definition = _component_definition(db, component_code)
    component = ComponentInstance(
        id=new_id(),
        tenant_id=tenant_id,
        project_id=project_id,
        component_definition_id=definition.id,
        entitlement_id=entitlement.id,
        component_code=component_code,
        component_version=definition.version,
        blueprint_ref=definition.default_blueprint_ref,
        status=status,
        progress=progress,
        health=health,
        current_phase=current_phase,
        limits_consumed_json=limits_consumed,
        milestones_json=list(milestones),
        tasks_json=list(tasks),
    )
    db.add(component)
    db.flush()
    return component


def _get_or_create_blocked_component(db: Session, *, tenant_id: str, project_id: str, component_code: str) -> ComponentInstance:
    component = db.query(ComponentInstance).filter_by(tenant_id=tenant_id, project_id=project_id, component_code=component_code).first()
    if component:
        return component
    definition = _component_definition(db, component_code)
    component = ComponentInstance(
        id=new_id(),
        tenant_id=tenant_id,
        project_id=project_id,
        component_definition_id=definition.id,
        component_code=component_code,
        component_version=definition.version,
        blueprint_ref=definition.default_blueprint_ref,
        status="blocked",
        progress=0,
        health=0,
        current_phase="Not contracted",
        blocked_reason="Component is available for expansion but has no granted entitlement.",
    )
    db.add(component)
    db.flush()
    return component


def _get_or_create_approval(db: Session, *, tenant_id: str, resource_id: str, approver_user_id: str) -> Approval:
    approval = db.query(Approval).filter_by(tenant_id=tenant_id, resource_type="component_instance", resource_id=resource_id, title="Aprovação de premissas de ROI").first()
    if approval:
        return approval
    approval = Approval(
        id=new_id(),
        tenant_id=tenant_id,
        resource_type="component_instance",
        resource_id=resource_id,
        approver_user_id=approver_user_id,
        title="Aprovação de premissas de ROI",
        description="Validar premissas usadas no cálculo determinístico de ROI e priorização.",
        status="pending",
        due_date="2026-07-31",
        impact_json={"stage_gate": "Discovery ROI", "risk": "medium"},
    )
    db.add(approval)
    db.flush()
    return approval


def _upsert_project_health(db: Session, *, tenant_id: str, program_id: str, project_id: str, approvals_sla: float) -> None:
    inputs = {
        "data_completeness": 72.0,
        "operational_progress": 70.0,
        "quality": 82.0,
        "participation": 75.0,
        "risks_resolved": 60.0,
        "approvals_sla": approvals_sla,
    }
    result = DeterministicCalculationEngine().calculate("project_health", "project_health@1.0", inputs)
    for scope_type, scope_id in [("project", project_id), ("program", program_id)]:
        score = db.query(Score).filter_by(tenant_id=tenant_id, scope_type=scope_type, scope_id=scope_id, metric="project_health").first()
        if not score:
            score = Score(id=new_id(), tenant_id=tenant_id, scope_type=scope_type, scope_id=scope_id, metric="project_health")
            db.add(score)
        score.value = result.value
        score.formula_version = result.formula_version
        score.inputs_json = inputs
        score.explanation_json = result.explanation
    db.flush()


def _seed_gamification(db: Session, *, tenant_id: str, program_id: str, component_id: str) -> None:
    for event_type, points, reason in [
        ("document.validated", 75, "15 documentos validados"),
        ("interview.completed", 80, "8 entrevistas concluidas"),
        ("stage_gate.pending", 20, "Priorizacao em andamento"),
    ]:
        existing = db.query(GamificationEvent).filter_by(tenant_id=tenant_id, component_instance_id=component_id, event_type=event_type).first()
        if existing:
            continue
        db.add(GamificationEvent(id=new_id(), tenant_id=tenant_id, program_id=program_id, component_instance_id=component_id, user_or_team="Atlas Delivery Team", event_type=event_type, points=points, reason=reason))
    db.flush()


def _seed_ledger_events(db: Session, *, tenant_id: str, actor_user_id: str, program_id: str, project_id: str, component_id: str, approval_id: str) -> None:
    events = [
        ("program", program_id, "program.demo_seeded", "Demo program seeded"),
        ("project", project_id, "project.demo_seeded", "Demo project seeded"),
        ("component_instance", component_id, "component.progress_seeded", "Component progress seeded"),
        ("approval", approval_id, "approval.pending_seeded", "Pending approval seeded"),
    ]
    for aggregate_type, aggregate_id, event_type, summary in events:
        if not aggregate_id:
            continue
        append_ledger_event(
            db,
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            correlation_id="demo-seed",
            idempotency_key=f"{tenant_id}:{event_type}:{aggregate_id}",
            payload={"summary": summary},
        )


def _seed_mvp_factory_data(db: Session, *, actor_user_id: str, project_id: str, program_id: str) -> None:
    from app.models import MvpRun, Opportunity, Prospect

    existing = db.query(Prospect).filter_by(tenant_id=ATLAS_TENANT_ID, company="Vega Retail").first()
    if existing:
        return
    mvp_service = MvpFactoryService()
    prospect = mvp_service.create_prospect(
        db,
        ATLAS_TENANT_ID,
        actor_user_id,
        "demo-seed:mvp",
        {
            "name": "Vega Retail",
            "company": "Vega Retail",
            "sector": "retail",
            "contact_email": "sponsor@vega.example",
            "source": "prospection",
        },
    )
    opportunity = mvp_service.create_opportunity(
        db,
        ATLAS_TENANT_ID,
        actor_user_id,
        "demo-seed:mvp",
        {
            "prospect_id": prospect.id,
            "program_id": program_id,
            "project_id": project_id,
            "title": "Portal de aprovação de campanhas e verba trade",
            "summary": "MVP para aprovar campanhas com SLA, orçamento e dashboard executivo.",
        },
    )
    mvp_service.add_briefing(
        db,
        ATLAS_TENANT_ID,
        actor_user_id,
        "demo-seed:mvp",
        opportunity.id,
        "Varejista precisa de portal para aprovar campanhas de trade marketing com SLA, orçamento, anexos, responsáveis e dashboard para diretoria.",
    )
    mvp_service.validate_idea(db, ATLAS_TENANT_ID, actor_user_id, "demo-seed:mvp", opportunity.id)
    mvp_service.scope_mvp(db, ATLAS_TENANT_ID, actor_user_id, "demo-seed:mvp", opportunity.id)
    mvp_service.generate_mvp(db, ATLAS_TENANT_ID, actor_user_id, "demo-seed:mvp", opportunity.id)
