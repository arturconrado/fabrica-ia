import hashlib
import io
import json
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.service_delivery.os_service as os_service_module
from app.auth.dependencies import ensure_tenant
from app.db.session import set_tenant_context
from app.models import (
    AgentAssignment,
    AgentCandidate,
    AgentDefinition,
    AgentEvaluation,
    AIActivity,
    AgentVersion,
    Approval,
    Artifact,
    Base,
    CapabilityGap,
    ComponentDefinition,
    Contract,
    DeliverableRevision,
    Engagement,
    EngagementDependency,
    EngagementPlan,
    Entitlement,
    LedgerRecord,
    ModelCall,
    OfferingVersion,
    OutcomeMetric,
    PlatformReadinessEvaluation,
    ServiceAcceptanceCheck,
    ServiceCycle,
    ServiceDeliverable,
    ServiceExecution,
    ServiceOffering,
    ServiceWorkItem,
    WorkflowRun,
    Workstream,
)
from app.service_delivery.catalog import ensure_service_catalog, ensure_tenant_agent_catalog
from app.service_delivery.os_service import (
    PORTFOLIO_MARKET_VALIDATION_REPORTS,
    PORTFOLIO_VALIDATION_REPORTS,
    REQUIRED_FORBIDDEN_ACTIONS,
    ServiceDeliveryOSService,
)
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


def _real_validation_manifest(content: str, metrics: dict | None = None) -> dict:
    content_bytes = content.encode("utf-8")
    digest = hashlib.sha256(content_bytes).hexdigest()
    return {
        "schema_version": "portfolio-validation-v2",
        "validation_mode": "real",
        "environment": "local",
        "started_at": "2026-07-22T10:00:00+00:00",
        "finished_at": "2026-07-22T10:30:00+00:00",
        "scenario_ids": ["owner-critical-journey"],
        "artifacts": [{
            "ref": "self", "sha256": digest, "mime_type": "text/markdown",
            "size_bytes": len(content_bytes),
        }],
        "checks": [{"key": "journey-complete", "passed": True, "evidence_refs": ["self"]}],
        "metrics": metrics or {},
        "validator_user_ids": ["owner"],
    }


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


def _v2_engagement_with_approved_plan(
    db,
    offering_code="ai_value_discovery",
    tenant_id="client-one",
    version_label="2.0",
):
    _tenant(db, tenant_id)
    offering = db.query(ServiceOffering).filter_by(code=offering_code).one()
    version = db.query(OfferingVersion).filter_by(
        offering_id=offering.id,
        version=version_label,
    ).one()
    component_code = version.definition_json["component_codes"][0]
    component = db.query(ComponentDefinition).filter_by(code=component_code).one()
    contract = Contract(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        contract_number=f"V{version_label}-{tenant_id}-{offering_code}",
        status="active", valid_from="", valid_until="", commercial_metadata_json={},
        scope_summary=f"Internal homologation of {offering_code}",
    )
    db.add(contract)
    db.flush()
    db.add(Entitlement(
        id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id=contract.id,
        component_definition_id=component.id, component_code=component_code, status="granted",
        capabilities_json=["service_delivery.activate"], limits_json={}, terms_json={},
    ))
    engagement = Engagement(
        id=str(uuid.uuid4()), tenant_id=tenant_id, contract_id=contract.id,
        offering_version_id=version.id, name=f"V{version_label} {offering_code}",
        status="awaiting_approval",
        record_version=1,
    )
    db.add(engagement)
    db.flush()
    templates = version.definition_json["deliverable_templates"]
    db.add(EngagementPlan(
        id=str(uuid.uuid4()), tenant_id=tenant_id, engagement_id=engagement.id, version=1,
        status="approved", approved_by_user_id="vp", plan_json={
            "summary": "Canonical v2 homologation plan", "objectives": ["Homologate"],
            "stages": [item["name"] for item in version.definition_json["process"]],
            "workstreams": [{"key": "delivery", "name": "Delivery", "objective": "Execute all contracted outputs"}],
            "deliverables": [
                {
                    "template_key": template["key"], "title": template["title"],
                    "description": f"Produce {template['title']}", "workstream_key": "delivery",
                    "acceptance_criteria": template["acceptance_criteria"],
                    "definition_of_done": version.definition_json["definition_of_done"],
                    "audience": template["audience"], "due_offset_days": index + 1,
                    "execution_mode": template["execution_mode"],
                }
                for index, template in enumerate(templates)
            ],
            "risks": [], "next_actions": [],
        },
    ))
    db.flush()
    return engagement, version


class RealisticCommercialJourneyGateway:
    """Deterministic provider double with client-specific, persisted model calls."""

    def __init__(self, *, invalid_once_for: str = "") -> None:
        self.invalid_once_for = invalid_once_for
        self.failed_titles: set[str] = set()
        self.calls: list[dict] = []

    @staticmethod
    def _persist_call(kwargs, parsed: dict) -> str:
        call_id = str(uuid.uuid4())
        user_message = str(kwargs["messages"][-1]["content"])
        output = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        kwargs["db"].add(
            ModelCall(
                id=call_id,
                tenant_id=kwargs["tenant_id"],
                agent_name=kwargs["agent_name"],
                provider="realistic-journey-fixture",
                model_name="commercial-narrative-v1",
                model_role=kwargs["model_role"],
                input_hash=hashlib.sha256(user_message.encode("utf-8")).hexdigest(),
                output_hash=hashlib.sha256(output.encode("utf-8")).hexdigest(),
                context_refs_json=list(kwargs.get("context_refs") or []),
                response_json={"parsed": parsed},
                status="success",
                prompt_tokens=700,
                completion_tokens=500,
                estimated_cost_usd=0.01,
            )
        )
        kwargs["db"].flush()
        return call_id

    def call(self, **kwargs):
        facts = json.loads(kwargs["messages"][-1]["content"])
        self.calls.append(
            {
                "tenant_id": kwargs["tenant_id"],
                "agent_name": kwargs["agent_name"],
                "scope": kwargs["invocation_scope"],
                "facts": facts,
            }
        )
        if kwargs["agent_name"] == "Engagement Planner":
            definition = facts["offering"]["definition"]
            parsed = {
                "summary": (
                    "Plano de discovery para reduzir o tempo de preparação de propostas "
                    "da Vértice Logística sem automatizar decisões comerciais."
                ),
                "objectives": [
                    "Priorizar oportunidades com evidência operacional",
                    "Selecionar um piloto comercial controlado",
                ],
                "stages": [item["name"] for item in definition["process"]],
                "workstreams": [
                    {
                        "key": "opportunity_discovery",
                        "name": "Descoberta e priorização",
                        "objective": "Converter dados do processo comercial em decisões de investimento.",
                    }
                ],
                "deliverables": [
                    {
                        "template_key": template["key"],
                        "title": template["title"],
                        "description": (
                            f"{template['title']} aplicado ao fluxo de 320 solicitações mensais "
                            "de proposta da Vértice Logística."
                        ),
                        "workstream_key": "opportunity_discovery",
                        "acceptance_criteria": template["acceptance_criteria"],
                        "definition_of_done": definition["definition_of_done"],
                        "audience": template["audience"],
                        "due_offset_days": index + 2,
                        "execution_mode": template["execution_mode"],
                    }
                    for index, template in enumerate(definition["deliverable_templates"])
                ],
                "risks": [
                    "A baseline de 48 horas foi declarada pelo sponsor e precisa de medição independente."
                ],
                "next_actions": ["Validar o plano com o VP antes de iniciar a produção."],
                "guidance": {
                    "why_now": "O plano preserva o contrato e está pronto para decisão executiva.",
                    "checks": ["Escopo", "Entregáveis", "Riscos"],
                    "risks": ["Confirmar a baseline declarada."],
                    "draft": "Escopo e riscos revisados; libero a execução controlada.",
                    "confidence": 0.9,
                },
            }
        else:
            deliverable = facts["deliverable"]
            title = deliverable["title"]
            if self.invalid_once_for == title and title not in self.failed_titles:
                self.failed_titles.add(title)
                parsed = {"title": title, "executive_summary": ""}
            else:
                title_key = title.casefold()
                if "maturidade" in title_key:
                    specific_analysis = (
                        "Avaliar separadamente estratégia, dados, tecnologia, processo comercial, pessoas, "
                        "governança e capacidade de execução. O resultado deve usar níveis de prontidão, "
                        "lacunas observáveis e perguntas de validação, sem converter percepção em score medido."
                    )
                elif "processos" in title_key:
                    specific_analysis = (
                        "Representar intake, qualificação, busca de informações, composição da proposta, "
                        "revisão de margem, aprovação e envio. Para cada etapa, registrar sistemas, handoffs, "
                        "espera, retrabalho e a decisão humana que não poderá ser automatizada."
                    )
                elif "inventário de oportunidades" in title_key:
                    specific_analysis = (
                        "Catalogar extração de requisitos, recuperação de conteúdo aprovado, recomendação de "
                        "estrutura, checagem de completude e resumo para aprovação. Cada oportunidade precisa "
                        "de usuário, problema, entrada, saída, dado necessário e hipótese de benefício."
                    )
                elif "fichas detalhadas" in title_key:
                    specific_analysis = (
                        "Detalhar para cada caso o job do usuário, cenário atual, fluxo assistido, controles, "
                        "métrica de sucesso, dono, dependências e condição de abandono. A ficha distingue "
                        "experimentação, piloto e solução produtiva."
                    )
                elif "matriz de impacto" in title_key:
                    specific_analysis = (
                        "Cruzar potencial de redução de espera, frequência, criticidade, disponibilidade de "
                        "dados, esforço de integração, risco e mudança organizacional. Pesos e notas ficam "
                        "explícitos para permitir contestação pelo comitê."
                    )
                elif "ranking" in title_key:
                    specific_analysis = (
                        "Ordenar os casos por valor ajustado ao risco e separar quick wins, apostas e "
                        "capacidades estruturantes. Empates devem ser resolvidos por aprendizado esperado, "
                        "reversibilidade e dependência de dados, nunca por preferência do modelo."
                    )
                elif "business cases" in title_key:
                    specific_analysis = (
                        "Estruturar volume elegível, esforço atual, custo do piloto, faixa de benefício, "
                        "sensibilidade e prazo de aprendizagem. Valores financeiros permanecem cenários, com "
                        "fórmulas e premissas editáveis para validação da controladoria."
                    )
                elif "dependências" in title_key:
                    specific_analysis = (
                        "Relacionar CRM, catálogo de serviços, conteúdo jurídico aprovado, política de preço, "
                        "identidade, observabilidade e responsáveis. O mapa marca bloqueadores, precedências, "
                        "interfaces organizacionais e planos substitutos."
                    )
                elif "arquitetura" in title_key:
                    specific_analysis = (
                        "Desenhar ingestão autorizada, recuperação com isolamento, orquestração, modelo, "
                        "policy enforcement, trilha de auditoria, revisão humana e telemetria. Dados comerciais "
                        "não atravessam tenants e nenhuma ação externa ocorre sem conector allowlisted."
                    )
                elif "roadmap" in title_key:
                    specific_analysis = (
                        "Organizar fundações, piloto controlado, avaliação, canário e expansão em ondas. Cada "
                        "marco possui dependência, responsável, evidência de saída e decisão go/no-go; datas "
                        "continuam condicionadas à disponibilidade das áreas."
                    )
                else:
                    specific_analysis = (
                        "Apresentar problema, alternativas, recomendação, riscos, investimento condicionado, "
                        "decisão requerida e próximos marcos. A narrativa executiva diferencia evidência, "
                        "premissa e hipótese para que o VP possa aprovar, ajustar ou interromper."
                    )
                revision_note = (
                    "\n\n## Alterações solicitadas pelo VP\n"
                    "A recomendação agora separa fatos medidos, declarações do sponsor e hipóteses de piloto."
                    if "separe fatos medidos" in facts["instructions"].casefold()
                    else ""
                )
                parsed = {
                    "title": title,
                    "executive_summary": (
                        f"{title} contextualizado para a decisão comercial da Vértice Logística."
                    ),
                    "content_markdown": (
                        f"# {title}\n\n"
                        "## Objetivo\n"
                        f"Produzir {title} para apoiar uma decisão verificável da Vértice Logística.\n\n"
                        "## Conteúdo\n"
                        "A operação recebe 320 solicitações de proposta por mês e o sponsor declarou "
                        "uma baseline de 48 horas; ambos permanecem classificados como dados fornecidos "
                        "para validação.\n\n"
                        f"{deliverable['description']}\n\n"
                        f"{specific_analysis}\n\n"
                        "## Evidências\n"
                        "- Fonte: contrato e plano aprovados deste tenant.\n"
                        "- Nenhuma entrevista, integração ou ganho financeiro foi declarado como concluído.\n\n"
                        "## Riscos e limitações\n"
                        "A baseline e o volume foram declarados pelo sponsor e ainda exigem medição independente.\n\n"
                        "## Próximos passos\nValidar o conteúdo, a proveniência e as premissas com o VP."
                        f"{revision_note}"
                    ),
                    "evidence_claims": [
                        "O volume de 320 solicitações/mês e a baseline de 48 horas são declarações do sponsor."
                    ],
                    "risks": ["A recomendação muda se a baseline operacional não for confirmada."],
                    "next_actions": ["VP revisa conteúdo, evidências e limitações."],
                    "guidance": {
                        "why_now": "A revisão agentic está pronta para conferência humana.",
                        "checks": ["Contexto", "Evidências", "Limitações"],
                        "risks": ["Baseline ainda declarada."],
                        "draft": "Revisei conteúdo e proveniência e encaminho para decisão.",
                        "confidence": 0.88,
                    },
                }
        call_id = self._persist_call(kwargs, parsed)
        return {
            "id": call_id,
            "model": "commercial-narrative-v1",
            "content": {"parsed": parsed},
        }


def _realistic_commercial_engagement(db, gateway: RealisticCommercialJourneyGateway):
    tenant_id = "vertice-logistica"
    _tenant(db, tenant_id)
    offering = db.query(ServiceOffering).filter_by(code="ai_value_discovery").one()
    version = db.query(OfferingVersion).filter_by(offering_id=offering.id, version="2.0").one()
    component = db.query(ComponentDefinition).filter_by(code="ai_value_discovery").one()
    contract = Contract(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        contract_number="VERTICE-DISCOVERY-2026-001",
        status="active",
        valid_from="",
        valid_until="",
        commercial_metadata_json={"areas": 2, "users": 12, "integrations": 0},
        scope_summary=(
            "Diagnosticar o processo opportunity-to-proposal da Vértice Logística e priorizar "
            "um piloto que reduza o tempo declarado de 48 horas sem remover decisão humana."
        ),
    )
    db.add(contract)
    db.flush()
    db.add(
        Entitlement(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            contract_id=contract.id,
            component_definition_id=component.id,
            component_code="ai_value_discovery",
            status="granted",
            capabilities_json=["service_delivery.activate"],
            limits_json={"engagements": 1},
            terms_json={},
        )
    )
    service = ServiceDeliveryOSService(gateway=gateway)
    engagement = service.create_engagement(
        db,
        tenant_id=tenant_id,
        actor_user_id="owner-artur",
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:engagement:create",
        payload={
            "contract_id": contract.id,
            "offering_version_id": version.id,
            "name": "Discovery comercial — Opportunity-to-Proposal",
            "description": (
                "A empresa recebe 320 solicitações de proposta por mês. O sponsor declara 48 horas "
                "de lead time e quer avaliar um copiloto com aprovação humana."
            ),
            "sponsor": "VP de Negócios",
            "start_date": "2026-08-03",
            "target_end_date": "2026-09-11",
            "success_criteria": [
                "Priorizar casos por valor, viabilidade e risco",
                "Entregar roadmap e recomendação executiva editáveis",
            ],
            "service_levels": {"review_business_days": 2},
            "dependency_engagement_ids": [],
        },
    )
    plan = service.generate_plan(
        db,
        tenant_id=tenant_id,
        actor_user_id="owner-artur",
        engagement_id=engagement.id,
        expected_version=engagement.record_version,
        adaptation_brief=(
            "Use somente o contrato e os dados declarados. Separe fatos, declarações e hipóteses; "
            "não invente entrevistas, integrações ou benefícios realizados."
        ),
        knowledge_base_ids=[],
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:plan:generate",
    )
    service.approve_plan(
        db,
        tenant_id=tenant_id,
        actor_user_id="vp-negocios",
        engagement_id=engagement.id,
        plan_version=plan.version,
        expected_version=engagement.record_version,
        comment="Escopo, entregáveis, premissas e risco da baseline declarada revisados.",
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:plan:approve",
    )
    service.activate_engagement(
        db,
        tenant_id=tenant_id,
        actor_user_id="owner-artur",
        engagement_id=engagement.id,
        expected_version=engagement.record_version,
        comment="Iniciar produção dentro do contrato e dos limites aprovados pelo VP.",
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:engagement:activate",
    )
    db.commit()
    return service, engagement, version


def test_catalog_registers_exactly_eight_versioned_offerings_without_runtime_records(db):
    ensure_service_catalog(db)
    db.commit()
    assert db.query(ServiceOffering).count() == 8
    assert db.query(OfferingVersion).count() == 24
    assert db.query(OfferingVersion).filter_by(version="1.0", status="active").count() == 8
    assert db.query(OfferingVersion).filter_by(version="2.0", status="candidate").count() == 8
    assert db.query(OfferingVersion).filter_by(version="2.1", status="candidate").count() == 8
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
    pilot = (
        db.query(OfferingVersion)
        .join(ServiceOffering, ServiceOffering.id == OfferingVersion.offering_id)
        .filter(ServiceOffering.code == "ai_use_case_pilot_sprint", OfferingVersion.version == "2.0")
        .one()
    )
    assert pilot.display_name == "AI Use Case Pilot"
    assert len(pilot.definition_json["corporate_definition_of_done"]) == 10
    assert "technical_workflow_version" not in pilot.definition_json
    assert all(
        {"key", "title", "responsible", "approver_role", "required_sections", "required_evidence", "formats", "execution_mode", "acceptance_criteria"}
        .issubset(template)
        for template in pilot.definition_json["deliverable_templates"]
    )
    pilot_v21 = (
        db.query(OfferingVersion)
        .join(ServiceOffering, ServiceOffering.id == OfferingVersion.offering_id)
        .filter(ServiceOffering.code == "ai_use_case_pilot_sprint", OfferingVersion.version == "2.1")
        .one()
    )
    assert pilot_v21.definition_json["technical_workflow_version"] == "2.14.0"
    group = pilot_v21.definition_json["technical_run_groups"][0]
    assert group["key"] == "software_product"
    assert len(group["deliverable_template_keys"]) == 6


def test_postgres_tenant_context_commits_ledger_transaction_before_provider_work(monkeypatch):
    class ContextSession:
        committed = False
        rolled_back = False
        closed = False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    context_db = ContextSession()
    outer_db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    tenant_contexts = []
    service = ServiceDeliveryOSService()
    monkeypatch.setattr(os_service_module, "SessionLocal", lambda: context_db)
    monkeypatch.setattr(
        os_service_module,
        "set_tenant_context",
        lambda session, tenant_id, actor_user_id: tenant_contexts.append(
            (session, tenant_id, actor_user_id)
        ),
    )
    monkeypatch.setattr(
        service,
        "_query_tenant_context",
        lambda session, **kwargs: ([{"chunk_id": "chunk-one"}], ["knowledge_chunk:chunk-one"]),
    )

    excerpts, refs = service._tenant_context(
        outer_db,
        tenant_id="client-one",
        actor_user_id="operator",
        knowledge_base_ids=["base-one"],
        question="Plan the engagement",
        correlation_id="test",
    )

    assert excerpts == [{"chunk_id": "chunk-one"}]
    assert refs == ["knowledge_chunk:chunk-one"]
    assert tenant_contexts == [(context_db, "client-one", "operator")]
    assert context_db.committed is True
    assert context_db.rolled_back is False
    assert context_db.closed is True


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
    assert db.query(AgentDefinition).filter_by(tenant_id="client-one", status="approved").count() == 11
    assert db.query(AgentAssignment).filter_by(tenant_id="client-one", engagement_id=engagement.id, status="active").count() == 3
    assert db.query(LedgerRecord).filter_by(tenant_id="client-one", event_type="agent.assigned").count() == 3
    assert db.query(LedgerRecord).filter_by(tenant_id="client-one", event_type="engagement.activated").count() == 1


def test_v2_activation_materializes_canonical_outputs_checks_modes_and_curated_team(db):
    engagement, version = _v2_engagement_with_approved_plan(db)
    ServiceDeliveryOSService().activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Activate internal homologation", correlation_id="test",
        event_idempotency_key="activate:v2",
    )
    templates = version.definition_json["deliverable_templates"]
    assert db.query(ServiceDeliverable).filter_by(
        tenant_id="client-one", engagement_id=engagement.id
    ).count() == len(templates)
    expected_modes = {template["key"]: template["execution_mode"] for template in templates}
    items = db.query(ServiceWorkItem).filter_by(tenant_id="client-one", engagement_id=engagement.id).all()
    deliverables = {row.id: row.template_key for row in db.query(ServiceDeliverable).filter_by(engagement_id=engagement.id).all()}
    assert {deliverables[item.deliverable_id]: item.execution_mode for item in items} == expected_modes
    expected_checks = len(version.definition_json["definition_of_done"]) + 10
    assert db.query(ServiceAcceptanceCheck).filter_by(
        tenant_id="client-one", engagement_id=engagement.id
    ).count() == expected_checks
    assert db.query(AgentAssignment).filter_by(
        tenant_id="client-one", engagement_id=engagement.id, status="active"
    ).count() == len(version.definition_json["team"])
    machine_modes = {"agent", "technical_run"}
    expected_machine_items = [item for item in items if item.execution_mode in machine_modes]
    expected_external_items = [
        item for item in items if item.execution_mode in {"human", "integration"}
    ]
    executions = db.query(ServiceExecution).filter_by(
        tenant_id="client-one", engagement_id=engagement.id
    ).all()
    assert {
        execution.work_item_id for execution in executions if execution.status == "queued"
    } == {
        item.id for item in expected_machine_items
    }
    assert {
        execution.work_item_id
        for execution in executions if execution.status == "waiting_for_evidence"
    } == {item.id for item in expected_external_items}
    assert all(item.status == "in_progress" for item in expected_external_items)
    assert all(
        execution.evidence_json["autonomy"]
        == {
            "policy": "bounded-machine-execution-v1",
            "trigger": "engagement_activation",
            "authorized_by_user_id": "owner",
            "human_approval_preserved": True,
            "tenant_scoped": True,
        }
        for execution in executions
    )
    activation_event = db.query(LedgerRecord).filter_by(
        tenant_id="client-one", event_type="engagement.activated"
    ).one()
    assert activation_event.payload_json["autonomous_executions_queued"] == len(expected_machine_items)
    assert activation_event.payload_json["human_or_integration_items"] == len(expected_external_items)


def test_standalone_discovery_and_agentic_quotation_mvp_materialize_independently(db):
    discovery, discovery_version = _v2_engagement_with_approved_plan(
        db,
        offering_code="ai_value_discovery",
        tenant_id="atlaslog-homologation",
    )
    discovery.name = "AtlasLog — Discovery independente"
    discovery.description = (
        "Priorizar IA em atendimento, roteirização e manutenção sem fabricar baseline."
    )
    service = ServiceDeliveryOSService()
    set_tenant_context(db, discovery.tenant_id, "owner-artur")
    service.activate_engagement(
        db,
        tenant_id=discovery.tenant_id,
        actor_user_id="owner-artur",
        engagement_id=discovery.id,
        expected_version=discovery.record_version,
        comment="Iniciar somente o Discovery contratado.",
        correlation_id="commercial-operation-matrix",
        event_idempotency_key="matrix:discovery:activate",
    )
    db.flush()
    mvp, mvp_version = _v2_engagement_with_approved_plan(
        db,
        offering_code="ai_use_case_pilot_sprint",
        tenant_id="metalquote-homologation",
    )
    mvp.name = "MetalQuote — MVP de orçamentação agêntica"
    mvp.description = (
        "Construir agentes de intake, requisitos, evidência, custos, risco e proposta, "
        "sem precificar, aprovar ou enviar autonomamente."
    )
    set_tenant_context(db, mvp.tenant_id, "owner-artur")
    service.activate_engagement(
        db,
        tenant_id=mvp.tenant_id,
        actor_user_id="owner-artur",
        engagement_id=mvp.id,
        expected_version=mvp.record_version,
        comment="Iniciar o MVP técnico em tenant isolado.",
        correlation_id="commercial-operation-matrix",
        event_idempotency_key="matrix:mvp:activate",
    )
    db.flush()

    set_tenant_context(db, discovery.tenant_id, "owner-artur")
    discovery_items = db.query(ServiceWorkItem).filter_by(
        tenant_id=discovery.tenant_id,
        engagement_id=discovery.id,
    ).all()
    discovery_deliverable_tenants = {
        row.tenant_id
        for row in db.query(ServiceDeliverable).filter_by(
            engagement_id=discovery.id,
        ).all()
    }
    discovery_dependencies = db.query(EngagementDependency).filter_by(
        tenant_id=discovery.tenant_id,
        engagement_id=discovery.id,
    ).count()
    set_tenant_context(db, mvp.tenant_id, "owner-artur")
    mvp_items = db.query(ServiceWorkItem).filter_by(
        tenant_id=mvp.tenant_id,
        engagement_id=mvp.id,
    ).all()
    mvp_deliverable_tenants = {
        row.tenant_id
        for row in db.query(ServiceDeliverable).filter_by(
            engagement_id=mvp.id,
        ).all()
    }
    mvp_dependencies = db.query(EngagementDependency).filter_by(
        tenant_id=mvp.tenant_id,
        engagement_id=mvp.id,
    ).count()
    assert len(discovery_items) == len(discovery_version.definition_json["deliverable_templates"])
    assert len(mvp_items) == len(mvp_version.definition_json["deliverable_templates"])
    assert "technical_run" not in {item.execution_mode for item in discovery_items}
    assert "technical_run" in {item.execution_mode for item in mvp_items}
    assert db.query(ServiceExecution).filter_by(
        tenant_id=mvp.tenant_id,
        engagement_id=mvp.id,
        status="queued",
    ).count() > 0
    assert discovery_dependencies == mvp_dependencies == 0
    assert discovery_deliverable_tenants == {"atlaslog-homologation"}
    assert mvp_deliverable_tenants == {"metalquote-homologation"}
    set_tenant_context(db, discovery.tenant_id, "owner-artur")
    assert db.query(ServiceExecution).filter_by(
        tenant_id=discovery.tenant_id,
        engagement_id=discovery.id,
        status="queued",
    ).count() > 0
    assert db.query(LedgerRecord).filter_by(
        tenant_id=discovery.tenant_id,
        event_type="engagement.activated",
    ).count() == 1
    set_tenant_context(db, mvp.tenant_id, "owner-artur")
    assert db.query(LedgerRecord).filter_by(
        tenant_id=mvp.tenant_id,
        event_type="engagement.activated",
    ).count() == 1


def test_synthetic_v2_activation_never_starts_autonomous_or_paid_work(db):
    engagement, _ = _v2_engagement_with_approved_plan(db)
    plan = db.query(EngagementPlan).filter_by(engagement_id=engagement.id).one()
    plan.status = "synthetic_approved"
    ServiceDeliveryOSService().activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Materialize synthetic validation", correlation_id="test",
        event_idempotency_key="activate:v2:synthetic",
    )
    assert db.query(ServiceExecution).filter_by(
        tenant_id="client-one", engagement_id=engagement.id
    ).count() == 0
    event = db.query(LedgerRecord).filter_by(
        tenant_id="client-one", event_type="engagement.activated"
    ).one()
    assert event.payload_json["validation_mode"] == "synthetic"
    assert event.payload_json["autonomous_executions_queued"] == 0


def test_autonomous_delivery_uses_template_agent_budget_and_hands_off_to_vp(db):
    engagement, version = _v2_engagement_with_approved_plan(db)

    class CapturingGateway:
        kwargs = {}

        def call(self, **kwargs):
            self.kwargs = kwargs
            return {
                "id": "",
                "content": {
                    "parsed": {
                        "title": "Assessment contextualizado",
                        "executive_summary": "Síntese baseada no plano aprovado.",
                        "content_markdown": (
                            "# Assessment contextualizado\n\n"
                            "## Objetivo\n\nAvaliar o contexto contratado e preparar uma decisão segura, rastreável e humana.\n\n"
                            "## Conteúdo\n\nO assessment organiza o cenário do cliente, o plano aprovado, as dependências, "
                            "as premissas e os limites operacionais. A análise preserva a fronteira do tenant e não "
                            "declara trabalho externo como concluído. O resultado oferece material editável para a "
                            "revisão do VP, sem substituir sua decisão ou ampliar o escopo contratado.\n\n"
                            "## Evidências\n\nA síntese usa o trecho autorizado `knowledge_chunk:assessment-one` e "
                            "mantém a proveniência visível para conferência.\n\n"
                            "## Riscos e limitações\n\nAs premissas ainda precisam de confirmação do sponsor e os "
                            "benefícios permanecem como hipóteses até medição real.\n\n"
                            "## Próximos passos\n\nO owner confere o conteúdo e o VP decide se solicita ajustes ou "
                            "aprova a revisão apresentada.\n"
                        ),
                        "evidence_claims": ["O contexto foi obtido de knowledge_chunk:assessment-one."],
                        "risks": ["Confirmar premissas com o sponsor."],
                        "next_actions": ["Revisão do VP."],
                    }
                },
            }

    gateway = CapturingGateway()
    service = ServiceDeliveryOSService(gateway=gateway)
    service._tenant_context = lambda *args, **kwargs: (
        [{"chunk_id": "assessment-one", "content": "Contexto autorizado do assessment."}],
        ["knowledge_chunk:assessment-one"],
    )
    service._verified_deliverable_evidence_refs = lambda *args, **kwargs: list(
        kwargs["evidence_refs"]
    )
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Autorizar execução autônoma", correlation_id="autonomy",
        event_idempotency_key="activate:autonomy",
    )
    item = db.query(ServiceWorkItem).filter_by(
        tenant_id="client-one", engagement_id=engagement.id, execution_mode="agent"
    ).first()
    deliverable = db.query(ServiceDeliverable).filter_by(id=item.deliverable_id).one()
    template = next(
        row for row in version.definition_json["deliverable_templates"]
        if row["key"] == deliverable.template_key
    )
    responsible = db.query(AgentDefinition).filter_by(
        tenant_id="client-one", code=template["responsible"]
    ).one()
    assignment = (
        db.query(AgentAssignment)
        .join(AgentVersion, AgentVersion.id == AgentAssignment.agent_version_id)
        .filter(
            AgentAssignment.engagement_id == engagement.id,
            AgentVersion.agent_definition_id == responsible.id,
        )
        .one()
    )
    execution = db.query(ServiceExecution).filter_by(work_item_id=item.id).one()
    execution.status = "dispatch_pending"

    service.perform_execution(
        db, tenant_id="client-one", execution_id=execution.id, correlation_id="autonomy"
    )

    assert gateway.kwargs["agent_name"] == responsible.name
    assert gateway.kwargs["invocation_scope"].metadata == {
        "agent_assignment_id": assignment.id,
        "agent_definition_code": responsible.code,
        "deliverable_template_key": deliverable.template_key,
    }
    prompt_payload = json.loads(gateway.kwargs["messages"][1]["content"])
    assert prompt_payload["delivery_contract"] == {
        "template_key": deliverable.template_key,
        "required_sections": template["required_sections"],
        "required_evidence": template["required_evidence"],
        "formats": template["formats"],
        "audience": template["audience"],
        "acceptance_criteria": template["acceptance_criteria"],
        "definition_of_done": deliverable.definition_of_done_json,
    }
    assert 0 < gateway.kwargs["invocation_scope"].envelope.hard_budget_usd <= assignment.ai_budget_usd
    assert deliverable.status == "review_ready"
    approval = db.query(Approval).filter_by(
        tenant_id="client-one", resource_type="service_deliverable",
        resource_id=deliverable.id, status="pending",
    ).one()
    assert execution.status == "awaiting_review"
    assert execution.evidence_json["approval_id"] == approval.id
    assert db.query(DeliverableRevision).filter_by(
        deliverable_id=deliverable.id, status="submitted"
    ).count() == 1
    persisted_revision = db.query(DeliverableRevision).filter_by(deliverable_id=deliverable.id).one()
    assert persisted_revision.content_json["contract_evaluation"]["passed"] is True
    assert persisted_revision.content_json["contract_evaluation"]["human_approval_required"] is True


def test_v2_deliverable_cannot_reach_human_gate_with_generic_ungrounded_content(db):
    engagement, _ = _v2_engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Start realistic contract validation", correlation_id="quality",
        event_idempotency_key="activate:quality-contract",
    )
    deliverable = db.query(ServiceDeliverable).filter_by(
        tenant_id="client-one", engagement_id=engagement.id
    ).first()
    revision = service.create_revision(
        db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
        content={
            "title": "Relatório [Cliente]",
            "executive_summary": "Texto genérico.",
            "content_markdown": "# Relatório\n\n## Objetivo\n\nA preencher.",
            "evidence_claims": [],
            "risks": [],
            "next_actions": [],
        },
        artifact_refs=[], evidence_refs=[], model_call_id="", correlation_id="quality",
        event_idempotency_key="quality:generic-revision",
    )

    assert revision.content_json["contract_evaluation"]["passed"] is False
    with pytest.raises(DomainError) as exc:
        service.submit_deliverable(
            db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
            expected_version=deliverable.record_version, comment="Try to submit generic output",
            correlation_id="quality", event_idempotency_key="quality:generic-submit",
        )
    assert exc.value.detail["code"] == "DELIVERABLE_CONTRACT_NOT_MET"
    assert "source_evidence_present" in exc.value.detail["details"]["failures"]
    assert deliverable.status == "in_progress"


def test_v2_delivery_evidence_attestation_rejects_known_cross_tenant_artifact(db):
    engagement, _ = _v2_engagement_with_approved_plan(db)
    deliverable = ServiceDeliverable(
        id=str(uuid.uuid4()), tenant_id="client-one", engagement_id=engagement.id,
        template_key="evidence-test", title="Evidence test", status="in_progress",
    )
    db.add(deliverable)
    _tenant(db, "client-two")
    foreign_artifact = Artifact(
        id=str(uuid.uuid4()), tenant_id="client-two", node_id="test",
        artifact_type="evidence", name="Foreign evidence", path="foreign/evidence.md",
        content="Cross-tenant content that must never attest another tenant.",
    )
    db.add(foreign_artifact)
    db.flush()

    verified = ServiceDeliveryOSService()._verified_deliverable_evidence_refs(
        db,
        deliverable=deliverable,
        evidence_refs=[f"artifact:{foreign_artifact.id}"],
    )

    assert verified == []


def test_realistic_discovery_journey_produces_distinct_reviewed_editable_deliverables(db):
    gateway = RealisticCommercialJourneyGateway()
    service, engagement, version = _realistic_commercial_engagement(db, gateway)
    tenant_id = engagement.tenant_id

    executions = (
        db.query(ServiceExecution)
        .filter_by(tenant_id=tenant_id, engagement_id=engagement.id)
        .order_by(ServiceExecution.created_at)
        .all()
    )
    assert len(executions) == len(version.definition_json["deliverable_templates"]) == 11
    assert db.query(AgentAssignment).filter_by(
        tenant_id=tenant_id, engagement_id=engagement.id, status="active"
    ).count() == len(version.definition_json["team"])

    for execution in executions:
        item = db.query(ServiceWorkItem).filter_by(id=execution.work_item_id).one()
        if execution.status == "waiting_for_evidence":
            service.transition_work_item(
                db,
                tenant_id=tenant_id,
                actor_user_id="owner-artur",
                item_id=item.id,
                status="completed",
                expected_version=item.record_version,
                reason=f"meeting-minutes:{engagement.id}:{item.id}",
                override_reason="",
                global_active=0,
                correlation_id="realistic-commercial-journey",
                event_idempotency_key=f"journey:evidence:{item.id}",
            )
        execution.status = "dispatch_pending"
        service.perform_execution(
            db,
            tenant_id=tenant_id,
            execution_id=execution.id,
            correlation_id="realistic-commercial-journey",
        )
        db.commit()

    deliverables = (
        db.query(ServiceDeliverable)
        .filter_by(tenant_id=tenant_id, engagement_id=engagement.id)
        .order_by(ServiceDeliverable.due_at)
        .all()
    )
    assert all(item.status == "review_ready" for item in deliverables)
    assert all(item.current_revision == 1 for item in deliverables)
    assert all(execution.status == "awaiting_review" for execution in executions)

    first = deliverables[0]
    service.decide_deliverable(
        db,
        tenant_id=tenant_id,
        actor_user_id="vp-negocios",
        deliverable_id=first.id,
        expected_version=first.record_version,
        decision="changes_requested",
        comment=(
            "Separe fatos medidos, declarações do sponsor e hipóteses; a baseline ainda não foi observada."
        ),
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:deliverable:first:changes",
    )
    service.generate_deliverable(
        db,
        tenant_id=tenant_id,
        actor_user_id="system",
        deliverable_id=first.id,
        instructions=(
            "Atenda ao comentário do VP: separe fatos medidos, declarações do sponsor e hipóteses."
        ),
        knowledge_base_ids=[],
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:deliverable:first:revision:2",
    )
    service.submit_deliverable(
        db,
        tenant_id=tenant_id,
        actor_user_id="owner-artur",
        deliverable_id=first.id,
        expected_version=first.record_version,
        comment="A segunda revisão explicita a proveniência da baseline e do volume.",
        correlation_id="realistic-commercial-journey",
        event_idempotency_key="journey:deliverable:first:resubmit",
    )
    db.commit()

    for deliverable in deliverables:
        service.decide_deliverable(
            db,
            tenant_id=tenant_id,
            actor_user_id="vp-negocios",
            deliverable_id=deliverable.id,
            expected_version=deliverable.record_version,
            decision="approve",
            comment=(
                "Conteúdo, critérios, evidências, riscos, limitações e formato editável revisados."
            ),
            correlation_id="realistic-commercial-journey",
            event_idempotency_key=f"journey:deliverable:{deliverable.id}:approve",
        )

    checks = db.query(ServiceAcceptanceCheck).filter_by(
        tenant_id=tenant_id, engagement_id=engagement.id
    ).all()
    assert len(checks) == len(version.definition_json["definition_of_done"]) + 10
    for check in checks:
        service.record_acceptance_evidence(
            db,
            tenant_id=tenant_id,
            actor_user_id="owner-artur",
            engagement_id=engagement.id,
            check_id=check.id,
            expected_version=check.record_version,
            evidence_refs=[f"deliverable:{first.id}"],
            external_constraint=False,
            impact="",
            mitigation="",
            correlation_id="realistic-commercial-journey",
            event_idempotency_key=f"journey:check:{check.id}:evidence",
        )
        service.decide_acceptance_check(
            db,
            tenant_id=tenant_id,
            actor_user_id="vp-negocios",
            engagement_id=engagement.id,
            check_id=check.id,
            expected_version=check.record_version,
            decision="approve",
            comment="Evidência vinculada a uma revisão aprovada e conferida pelo VP.",
            correlation_id="realistic-commercial-journey",
            event_idempotency_key=f"journey:check:{check.id}:approve",
        )

    packaged_extensions: set[str] = set()
    for deliverable in deliverables:
        filename, payload, manifest = service.build_deliverable_package(
            db,
            tenant_id,
            deliverable.id,
            actor_user_id="vp-negocios",
            correlation_id="realistic-commercial-journey",
        )
        assert filename.endswith(f"-r{deliverable.current_revision}.zip")
        assert hashlib.sha256(payload).hexdigest() == manifest["package_sha256"]
        assert all(
            {"sha256", "mime_type", "size_bytes", "origin", "revision"}.issubset(item)
            for item in manifest["files"]
        )
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert "manifest.json" in archive.namelist()
            packaged_extensions.update(
                name.rsplit(".", 1)[-1] for name in archive.namelist() if "." in name
            )
        service.deliver_deliverable(
            db,
            tenant_id=tenant_id,
            actor_user_id="vp-negocios",
            deliverable_id=deliverable.id,
            expected_version=deliverable.record_version,
            comment="Pacote editável conferido e entrega registrada para a audiência contratada.",
            correlation_id="realistic-commercial-journey",
            event_idempotency_key=f"journey:deliverable:{deliverable.id}:deliver",
        )
    db.commit()

    db.refresh(engagement)
    revisions = db.query(DeliverableRevision).filter_by(tenant_id=tenant_id).all()
    markdown_artifacts = db.query(Artifact).filter_by(
        tenant_id=tenant_id, artifact_type="service-deliverable-markdown"
    ).all()
    package_artifacts = db.query(Artifact).filter_by(
        tenant_id=tenant_id, artifact_type="service_delivery_package"
    ).all()
    assert engagement.status == "completed"
    assert all(item.status == "delivered" for item in deliverables)
    assert all(check.status == "passed" for check in checks)
    assert len(revisions) == len(deliverables) + 1
    assert len(markdown_artifacts) == len(revisions)
    assert len(package_artifacts) == len(deliverables)
    assert len({artifact.metadata_json["sha256"] for artifact in markdown_artifacts}) == len(revisions)
    assert {"md", "json", "docx", "pptx", "xlsx", "csv"}.issubset(packaged_extensions)
    assert "Alterações solicitadas pelo VP" in (
        db.query(DeliverableRevision)
        .filter_by(deliverable_id=first.id, revision=2)
        .one()
        .content_json["content_markdown"]
    )

    model_calls = db.query(ModelCall).filter_by(tenant_id=tenant_id).all()
    assert len(model_calls) == 1 + len(deliverables) + 1
    assert {call.agent_name for call in model_calls} == {
        "Engagement Planner",
        "Process & Value Analyst",
    }
    assert all(call.status == "success" and call.output_hash for call in model_calls)
    assert db.query(AIActivity).filter_by(
        tenant_id=tenant_id, activity_type="operational_guidance", status="completed"
    ).count() == len(model_calls)
    assert db.query(LedgerRecord).filter_by(
        tenant_id=tenant_id, event_type="engagement.completed"
    ).count() == 1


def test_agentic_deliverable_recovers_from_invalid_provider_output_without_duplicate_artifact(db):
    gateway = RealisticCommercialJourneyGateway()
    service, engagement, _ = _realistic_commercial_engagement(db, gateway)
    execution = (
        db.query(ServiceExecution)
        .filter_by(tenant_id=engagement.tenant_id, engagement_id=engagement.id, execution_mode="agent")
        .first()
    )
    deliverable = db.query(ServiceDeliverable).filter_by(id=execution.deliverable_id).one()
    gateway.invalid_once_for = deliverable.title
    execution.status = "dispatch_pending"
    db.commit()

    with pytest.raises(DomainError) as exc:
        service.perform_execution(
            db,
            tenant_id=engagement.tenant_id,
            execution_id=execution.id,
            correlation_id="realistic-provider-recovery",
        )
    assert exc.value.detail["code"] == "DELIVERABLE_AI_FAILED"
    db.rollback()
    terminal = service.record_execution_failure(
        db,
        tenant_id=engagement.tenant_id,
        execution_id=execution.id,
        error=exc.value,
        correlation_id="realistic-provider-recovery",
    )
    db.commit()
    db.refresh(execution)
    assert terminal is False
    assert execution.status == "dispatch_pending"
    assert execution.attempt_count == 1
    assert execution.last_error
    assert db.query(DeliverableRevision).filter_by(deliverable_id=deliverable.id).count() == 0
    assert db.query(Artifact).filter_by(
        tenant_id=engagement.tenant_id, artifact_type="service-deliverable-markdown"
    ).count() == 0

    service.perform_execution(
        db,
        tenant_id=engagement.tenant_id,
        execution_id=execution.id,
        correlation_id="realistic-provider-recovery",
    )
    db.commit()
    db.refresh(execution)
    db.refresh(deliverable)
    assert execution.status == "awaiting_review"
    assert execution.attempt_count == 2
    assert deliverable.status == "review_ready"
    assert db.query(DeliverableRevision).filter_by(deliverable_id=deliverable.id).count() == 1
    assert db.query(Artifact).filter_by(
        tenant_id=engagement.tenant_id, artifact_type="service-deliverable-markdown"
    ).count() == 1
    assert db.query(Approval).filter_by(
        tenant_id=engagement.tenant_id,
        resource_type="service_deliverable",
        resource_id=deliverable.id,
        status="pending",
    ).count() == 1
    assert db.query(LedgerRecord).filter_by(
        tenant_id=engagement.tenant_id,
        aggregate_id=execution.id,
        event_type="service_execution.started",
    ).count() == 2
    assert db.query(LedgerRecord).filter_by(
        tenant_id=engagement.tenant_id,
        aggregate_id=execution.id,
        event_type="service_execution.completed",
    ).count() == 1


def test_external_evidence_is_queued_for_autonomous_artifact_synthesis(db):
    engagement, _ = _v2_engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Iniciar trabalho contratado", correlation_id="external",
        event_idempotency_key="activate:external",
    )
    item = db.query(ServiceWorkItem).filter(
        ServiceWorkItem.engagement_id == engagement.id,
        ServiceWorkItem.execution_mode.in_(("human", "integration")),
    ).first()
    assert item is not None
    execution = db.query(ServiceExecution).filter_by(work_item_id=item.id).one()
    assert item.status == "in_progress"
    assert execution.status == "waiting_for_evidence"
    assert not execution.temporal_workflow_id

    transitioned = service.transition_work_item(
        db, tenant_id="client-one", actor_user_id="owner", item_id=item.id,
        status="completed", expected_version=item.record_version,
        reason="external:meeting-minutes:2026-07-23", override_reason="", global_active=0,
        correlation_id="external", event_idempotency_key="external:evidence",
    )

    assert transitioned.status == "queued"
    assert execution.status == "queued"
    assert execution.execution_mode == "agent"
    assert execution.evidence_json["source_execution_mode"] == item.execution_mode
    assert execution.evidence_json["manual_evidence"] == "external:meeting-minutes:2026-07-23"
    assert db.query(LedgerRecord).filter_by(
        tenant_id="client-one",
        event_type="service_execution.evidence_synthesis_queued",
    ).count() == 1


def test_ai_office_next_cycle_requires_explicit_command_after_prior_acceptance(db):
    engagement, version = _v2_engagement_with_approved_plan(db, "ai_office_as_a_service")
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Start first cycle", correlation_id="test",
        event_idempotency_key="office:activate",
    )
    first = db.query(ServiceCycle).filter_by(engagement_id=engagement.id, sequence=1).one()
    with pytest.raises(DomainError) as exc:
        service.create_cycle(
            db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
            expected_version=engagement.record_version, period_start=None, period_end=None,
            comment="Must wait", correlation_id="test", event_idempotency_key="office:early",
        )
    assert exc.value.detail["code"] == "PREVIOUS_CYCLE_NOT_ACCEPTED"
    first.status = "completed"
    second = service.create_cycle(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=engagement.record_version, period_start=None, period_end=None,
        comment="Second cycle authorized", correlation_id="test", event_idempotency_key="office:second",
    )
    assert second.sequence == 2
    assert second.status == "active"
    assert db.query(ServiceDeliverable).filter_by(cycle_id=second.id).count() == len(version.definition_json["deliverable_templates"])
    assert db.query(ServiceAcceptanceCheck).filter_by(cycle_id=second.id).count() == len(version.definition_json["definition_of_done"]) + 10
    second_items = db.query(ServiceWorkItem).filter_by(cycle_id=second.id).all()
    second_executions = db.query(ServiceExecution).filter_by(cycle_id=second.id).all()
    assert {
        execution.work_item_id for execution in second_executions
        if execution.status == "queued"
    } == {
        item.id for item in second_items if item.execution_mode in {"agent", "technical_run"}
    }
    assert {
        execution.work_item_id for execution in second_executions
        if execution.status == "waiting_for_evidence"
    } == {
        item.id for item in second_items if item.execution_mode in {"human", "integration"}
    }


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
    with pytest.raises(DomainError) as exc:
        service.decide_deliverable(
            db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
            expected_version=deliverable.record_version, decision="approve", comment=" ",
            correlation_id="test", event_idempotency_key="decision:blank",
        )
    assert exc.value.detail["code"] == "DELIVERABLE_DECISION_COMMENT_REQUIRED"
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


def test_synthetic_deliverable_decisions_are_auditable_but_never_real_delivery(db):
    engagement = _engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="operator", engagement_id=engagement.id,
        expected_version=1, comment="Activate test flow", correlation_id="test",
        event_idempotency_key="activate:synthetic",
    )
    deliverable = db.query(ServiceDeliverable).filter_by(tenant_id="client-one").first()
    service.create_revision(
        db, tenant_id="client-one", actor_user_id="operator", deliverable_id=deliverable.id,
        content={"content_markdown": "# Synthetic validation"}, artifact_refs=[], evidence_refs=["test:evidence"],
        model_call_id="", correlation_id="test", event_idempotency_key="revision:synthetic",
    )
    service.submit_deliverable(
        db, tenant_id="client-one", actor_user_id="operator", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, comment="Ready for synthetic validation",
        correlation_id="test", event_idempotency_key="submit:synthetic",
    )
    service.decide_deliverable(
        db, tenant_id="client-one", actor_user_id="vp", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, decision="approve", comment="Synthetic VP decision",
        correlation_id="test", event_idempotency_key="decision:synthetic", validation_mode="synthetic",
    )
    assert deliverable.status == "synthetic_approved"
    service.deliver_deliverable(
        db, tenant_id="client-one", actor_user_id="vp", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, comment="Synthetic delivery confirmation",
        correlation_id="test", event_idempotency_key="delivery:synthetic", validation_mode="synthetic",
    )
    assert deliverable.status == "synthetic_delivered"
    event = db.query(LedgerRecord).filter_by(
        tenant_id="client-one", event_type="service_deliverable.synthetic_delivered"
    ).one()
    assert event.payload_json["validation_mode"] == "synthetic"


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


def test_plan_and_acceptance_decisions_enforce_four_eyes(db):
    engagement = _engagement_with_approved_plan(db)
    plan = db.query(EngagementPlan).filter_by(engagement_id=engagement.id).one()
    plan.status = "draft"
    plan.created_by_user_id = "owner"
    plan.approved_by_user_id = ""
    service = ServiceDeliveryOSService()

    with pytest.raises(DomainError) as exc:
        service.approve_plan(
            db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
            plan_version=1, expected_version=1, comment="Self approval", correlation_id="test",
            event_idempotency_key="plan:self",
        )
    assert exc.value.detail["code"] == "FOUR_EYES_REQUIRED"

    approved = service.approve_plan(
        db, tenant_id="client-one", actor_user_id="vp", engagement_id=engagement.id,
        plan_version=1, expected_version=1, comment="VP reviewed the plan", correlation_id="test",
        event_idempotency_key="plan:vp",
    )
    assert approved.approved_by_user_id == "vp"

    check = ServiceAcceptanceCheck(
        id=str(uuid.uuid4()), tenant_id="client-one", engagement_id=engagement.id,
        cycle_key="engagement", scope="corporate", check_key="corporate:01",
        description="All contracted processes were executed", status="pending", record_version=1,
    )
    db.add(check)
    db.flush()
    service.record_acceptance_evidence(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        check_id=check.id, expected_version=1, evidence_refs=["artifact:process-report"],
        external_constraint=False, impact="", mitigation="", correlation_id="test",
        event_idempotency_key="check:evidence",
    )
    with pytest.raises(DomainError) as exc:
        service.decide_acceptance_check(
            db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
            check_id=check.id, expected_version=2, decision="approve", comment="Self approval",
            correlation_id="test", event_idempotency_key="check:self",
        )
    assert exc.value.detail["code"] == "FOUR_EYES_REQUIRED"
    decided = service.decide_acceptance_check(
        db, tenant_id="client-one", actor_user_id="vp", engagement_id=engagement.id,
        check_id=check.id, expected_version=2, decision="approve", comment="Evidence reviewed",
        correlation_id="test", event_idempotency_key="check:vp",
    )
    assert decided.status == "passed"


def test_editable_delivery_package_is_deterministic_and_self_describing():
    from app.service_delivery.package_export import build_deliverable_package

    deliverable = {"id": "deliverable-1", "engagement_id": "engagement-1", "title": "Executive roadmap"}
    revision = {
        "revision": 2,
        "content_json": {"title": "Executive roadmap", "content_markdown": "# Roadmap\n\n- First wave\n"},
        "evidence_refs_json": ["artifact:assessment"],
    }
    first = build_deliverable_package(
        deliverable=deliverable, revision=revision, formats=["docx", "pptx", "xlsx", "csv"]
    )
    second = build_deliverable_package(
        deliverable=deliverable, revision=revision, formats=["docx", "pptx", "xlsx", "csv"]
    )
    assert first[1] == second[1]
    assert first[2]["package_sha256"] == second[2]["package_sha256"]
    assert {item["path"].rsplit(".", 1)[-1] for item in first[2]["files"]} >= {
        "md", "json", "docx", "pptx", "xlsx", "csv"
    }
    assert all({"sha256", "mime_type", "size_bytes", "origin", "revision"}.issubset(item) for item in first[2]["files"])


def test_portfolio_release_requires_persisted_human_and_operational_reports(db):
    _tenant(db)
    service = ServiceDeliveryOSService()
    initial = service.portfolio_release_readiness(db, "client-one", "2.0")
    assert initial["ready"] is False
    assert initial["market_ready"] is False
    assert {item["report_kind"] for item in initial["market_validation_reports"]} == PORTFOLIO_MARKET_VALIDATION_REPORTS
    assert set(initial["market_blockers"]) == PORTFOLIO_MARKET_VALIDATION_REPORTS
    assert "required_validation_reports" in initial["release_blockers"]

    with pytest.raises(DomainError) as exc:
        service.record_portfolio_validation_evidence(
            db, tenant_id="client-one", actor_user_id="owner", actor_role="owner",
            version_label="2.0", report_kind="usability_vp", status="passed",
            content_markdown="# Usabilidade do VP\n\nTarefas críticas executadas.",
            evidence_refs=["session:vp"], metrics={"seq_median": 6}, correlation_id="test",
            event_idempotency_key="portfolio:vp:self",
        )
    assert exc.value.detail["code"] == "VP_USABILITY_EVIDENCE_REQUIRED"

    with pytest.raises(DomainError) as exc:
        service.record_portfolio_validation_evidence(
            db, tenant_id="client-one", actor_user_id="owner", actor_role="owner",
            version_label="2.0", report_kind="external_user_validation", status="passed",
            content_markdown="# Validação externa\n\nUsuários externos concluíram tarefas críticas.",
            evidence_refs=["session:external-users"], metrics={"critical_tasks": 1.0}, correlation_id="test",
            event_idempotency_key="portfolio:external:self",
        )
    assert exc.value.detail["code"] == "VP_EXTERNAL_VALIDATION_REQUIRED"

    content = "# Usabilidade operacional\n\nExecução e recovery validados pelo owner."
    metrics = {
        "critical_task_completion": 1.0, "p0_blockers": 0, "p1_blockers": 0, "median_seq": 6,
    }
    artifact = service.record_portfolio_validation_evidence(
        db, tenant_id="client-one", actor_user_id="owner", actor_role="owner",
        version_label="2.0", report_kind="usability_owner", status="passed",
        content_markdown=content, evidence_refs=["self"], metrics=metrics,
        manifest=_real_validation_manifest(content, metrics),
        correlation_id="test", event_idempotency_key="portfolio:owner",
    )
    db.flush()
    assert db.query(Artifact).filter_by(id=artifact.id, tenant_id="client-one").one().content.startswith("# Usabilidade")
    readiness = service.portfolio_release_readiness(db, "client-one", "2.0")
    owner_report = next(item for item in readiness["validation_reports"] if item["report_kind"] == "usability_owner")
    assert owner_report["report_kind"] == "usability_owner"
    assert owner_report["passed"] is True
    assert owner_report["artifact_id"] == artifact.id
    assert len(owner_report["sha256"]) == 64
    assert owner_report["recorded_by_role"] == "owner"


def test_portfolio_validation_status_is_derived_and_legacy_payload_cannot_self_assert(db):
    _tenant(db)
    artifact = ServiceDeliveryOSService().record_portfolio_validation_evidence(
        db, tenant_id="client-one", actor_user_id="owner", actor_role="owner",
        version_label="2.0", report_kind="usability_owner", status="passed",
        content_markdown="# Legacy claim\n\nThe caller says this passed without a signed manifest.",
        evidence_refs=["self"], metrics={}, correlation_id="test",
        event_idempotency_key="portfolio:legacy-claim",
    )
    db.flush()
    metadata = artifact.metadata_json
    assert metadata["requested_status"] == "passed"
    assert metadata["status"] == "unverified"
    assert "portfolio_validation_v2_manifest_required" in metadata["validation_failures"]


def test_platform_readiness_evaluation_is_server_computed_and_does_not_promote_catalog(db):
    _tenant(db)
    service = ServiceDeliveryOSService()
    evaluation = service.create_platform_readiness_evaluation(
        db, tenant_id="client-one", actor_user_id="owner",
        evaluation_type="market_ready", version_label="2.0",
        comment="Market decision remains blocked pending staging evidence.",
        readiness={
            "market_ready": False, "release_blockers": [], "market_blockers": ["real_canary"],
            "validation_reports": [], "market_validation_reports": [], "offerings": [],
            "four_eyes_verified": False, "homologation_tenant_count": 1,
        },
        correlation_id="test", event_idempotency_key="platform-readiness:blocked",
    )
    db.flush()
    assert db.query(PlatformReadinessEvaluation).filter_by(id=evaluation.id).one().status == "blocked"
    assert evaluation.blockers_json == ["real_canary"]
    assert evaluation.evidence_hashes_json == []
    assert all(version.status == "candidate" for version in db.query(OfferingVersion).filter_by(version="2.0").all())
    assert db.query(LedgerRecord).filter_by(aggregate_id=evaluation.id).one().event_type == "platform_readiness.blocked"


def test_portfolio_manifest_rejects_hash_mismatch_and_unresolved_tenant_reference(db):
    _tenant(db)
    content = "# Resilience\n\nControlled restart evidence with zero confirmed-output loss."
    metrics = {
        "rpo_lost_confirmed_outputs": 0, "rto_p95_seconds": 120,
        "orphan_slots": 0, "unbounded_retry_loops": 0,
    }
    manifest = _real_validation_manifest(content, metrics)
    manifest["artifacts"][0]["sha256"] = "0" * 64
    manifest["artifacts"].append({
        "ref": "artifact:unknown-in-tenant", "sha256": "a" * 64,
        "mime_type": "text/markdown", "size_bytes": 1,
    })
    manifest["checks"][0]["evidence_refs"].append("run:known-but-other-tenant")
    artifact = ServiceDeliveryOSService().record_portfolio_validation_evidence(
        db, tenant_id="client-one", actor_user_id="owner", actor_role="owner",
        version_label="2.0", report_kind="resilience", status="passed",
        content_markdown=content, evidence_refs=["self"], metrics=metrics, manifest=manifest,
        correlation_id="test", event_idempotency_key="portfolio:resilience-invalid",
    )
    db.flush()
    assert artifact.metadata_json["status"] == "failed"
    assert "self_artifact_digest_mismatch" in artifact.metadata_json["validation_failures"]
    assert "unresolved_evidence_ref:artifact:unknown-in-tenant" in artifact.metadata_json["validation_failures"]
    assert "unresolved_evidence_ref:run:known-but-other-tenant" in artifact.metadata_json["validation_failures"]


def test_portfolio_readiness_combines_authorized_tenant_results_without_payload_leakage():
    offering_codes = [
        "ai_value_discovery", "ai_governance_risk_framework", "ai_enterprise_launchpad",
        "ai_workforce_productivity", "ai_engineering_productivity", "ai_use_case_pilot_sprint",
        "ai_office_as_a_service", "ai_adoption_governance_cockpit",
    ]
    report_kinds = sorted(
        PORTFOLIO_VALIDATION_REPORTS | {f"offering_{code}" for code in offering_codes}
    )
    tenant_results = []
    for tenant_index in range(3):
        tenant_results.append({
            "offerings": [
                {"offering_code": code, "passed": index % 3 == tenant_index}
                for index, code in enumerate(offering_codes)
            ],
            "validation_reports": [
                {
                    "report_kind": kind,
                    "passed": index % 3 == tenant_index,
                    "artifact_id": f"artifact-{tenant_index}-{index}" if index % 3 == tenant_index else None,
                    "sha256": "a" * 64 if index % 3 == tenant_index else None,
                    "recorded_by_role": "engagement_manager" if kind == "usability_vp" else "owner",
                    "actor_sha256": (
                        "b" * 64 if kind == "usability_vp" else "a" * 64
                    ) if index % 3 == tenant_index else None,
                }
                for index, kind in enumerate(report_kinds)
            ],
        })

    combined = ServiceDeliveryOSService.combine_portfolio_release_readiness(tenant_results)

    assert combined["ready"] is True
    assert combined["internal_assisted_pilot_ready"] is True
    assert combined["market_ready"] is False
    assert combined["homologation_tenant_count"] == 3
    assert len(combined["offerings"]) == 8
    assert len(combined["validation_reports"]) == len(report_kinds)
    assert set(combined["market_blockers"]) == PORTFOLIO_MARKET_VALIDATION_REPORTS
    assert "client-" not in str(combined).lower()

    market_kinds = sorted(PORTFOLIO_MARKET_VALIDATION_REPORTS)
    for tenant_index, result in enumerate(tenant_results):
        result["market_validation_reports"] = [
            {
                "report_kind": kind,
                "passed": index % 3 == tenant_index,
                "artifact_id": f"market-{tenant_index}-{index}" if index % 3 == tenant_index else None,
                "sha256": "c" * 64 if index % 3 == tenant_index else None,
                "recorded_by_role": "engagement_manager",
                "actor_sha256": "b" * 64 if index % 3 == tenant_index else None,
            }
            for index, kind in enumerate(market_kinds)
        ]
    market_ready = ServiceDeliveryOSService.combine_portfolio_release_readiness(tenant_results)
    assert market_ready["internal_assisted_pilot_ready"] is True
    assert market_ready["market_ready"] is True
    assert market_ready["market_blockers"] == []


def test_portfolio_runtime_routes_are_registered_once():
    from app.api.routes_service_delivery_os import router

    required = {
        "/api/v1/service-work-items/{item_id}/execute",
        "/api/v1/service-executions",
        "/api/v1/service-executions/{execution_id}",
        "/api/v1/service-executions/{execution_id}/retry",
        "/api/v1/service-executions/{execution_id}/cancel",
        "/api/v1/engagements/{engagement_id}/cycles",
        "/api/v1/engagements/{engagement_id}/acceptance-checks",
        "/api/v1/engagements/{engagement_id}/acceptance-checks/{check_id}/evidence",
        "/api/v1/engagements/{engagement_id}/acceptance-checks/{check_id}/decision",
        "/api/v1/service-deliverables/{deliverable_id}/package/download",
        "/api/v1/engagements/{engagement_id}/package/download",
        "/api/v1/admin/platform-readiness/evaluations",
    }
    paths = [route.path for route in router.routes]
    assert all(paths.count(path) == 1 for path in required)


def test_cancelled_agent_execution_cannot_persist_late_provider_output(db):
    engagement = _engagement_with_approved_plan(db)
    bootstrap_service = ServiceDeliveryOSService()
    bootstrap_service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Activate", correlation_id="test",
        event_idempotency_key="activate:cancel-race",
    )
    item = db.query(ServiceWorkItem).filter_by(tenant_id="client-one", execution_mode="agent").first()
    execution = bootstrap_service.queue_execution(
        db, tenant_id="client-one", actor_user_id="owner", item_id=item.id,
        expected_version=item.record_version, instructions="Generate", knowledge_base_ids=[],
        correlation_id="test", event_idempotency_key="queue:cancel-race",
    )
    execution.status = "dispatch_pending"
    db.commit()

    class CancellingGateway:
        def call(self, **kwargs):
            call_db = kwargs["db"]
            current = call_db.query(ServiceExecution).filter_by(id=execution.id).one()
            current.status = "cancel_pending"
            work_item = call_db.query(ServiceWorkItem).filter_by(id=item.id).one()
            work_item.status = "cancelled"
            call_db.flush()
            return {
                "id": "",
                "content": {"parsed": {
                    "title": "Late output", "executive_summary": "Must not persist",
                    "content_markdown": "# Late output\n\nCancelled.", "evidence_claims": [],
                    "risks": [], "next_actions": [],
                }},
            }

    with pytest.raises(DomainError) as exc:
        ServiceDeliveryOSService(gateway=CancellingGateway()).perform_execution(
            db, tenant_id="client-one", execution_id=execution.id, correlation_id="test",
        )
    assert exc.value.detail["code"] == "SERVICE_EXECUTION_CANCELLED"
    assert db.query(DeliverableRevision).filter_by(deliverable_id=item.deliverable_id).count() == 0


def test_package_download_persists_one_manifest_artifact_and_ledger_event(db):
    engagement = _engagement_with_approved_plan(db)
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment="Activate", correlation_id="test",
        event_idempotency_key="activate:package",
    )
    deliverable = db.query(ServiceDeliverable).filter_by(tenant_id="client-one").first()
    service.create_revision(
        db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
        content={"title": deliverable.title, "content_markdown": "# Approved package\n\nEvidence."},
        artifact_refs=[], evidence_refs=["evidence:one"], model_call_id="",
        correlation_id="test", event_idempotency_key="package:revision",
    )
    service.submit_deliverable(
        db, tenant_id="client-one", actor_user_id="owner", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, comment="Review", correlation_id="test",
        event_idempotency_key="package:submit",
    )
    service.decide_deliverable(
        db, tenant_id="client-one", actor_user_id="vp", deliverable_id=deliverable.id,
        expected_version=deliverable.record_version, decision="approve", comment="VP approved",
        correlation_id="test", event_idempotency_key="package:approve",
    )
    first = service.build_deliverable_package(
        db, "client-one", deliverable.id, actor_user_id="vp", correlation_id="test",
    )
    second = service.build_deliverable_package(
        db, "client-one", deliverable.id, actor_user_id="vp", correlation_id="test",
    )
    db.flush()
    assert first[1] == second[1]
    assert db.query(Artifact).filter_by(
        tenant_id="client-one", artifact_type="service_delivery_package"
    ).count() == 1
    assert db.query(LedgerRecord).filter_by(
        tenant_id="client-one", event_type="service_deliverable.package_generated"
    ).count() == 1
    assert first[2]["package_sha256"] == hashlib.sha256(first[1]).hexdigest()
    with zipfile.ZipFile(io.BytesIO(first[1])) as archive:
        for entry in first[2]["files"]:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
            assert len(archive.read(entry["path"])) == entry["size_bytes"]


def test_v21_integral_package_rejects_synthetic_delivery(db):
    engagement, _ = _v2_engagement_with_approved_plan(
        db,
        version_label="2.1",
    )
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db,
        tenant_id="client-one",
        actor_user_id="owner",
        engagement_id=engagement.id,
        expected_version=1,
        comment="Materializar a candidata sem substituir decisões humanas.",
        correlation_id="package-synthetic",
        event_idempotency_key="package-synthetic:activate",
    )
    for deliverable in db.query(ServiceDeliverable).filter_by(
        tenant_id="client-one",
        engagement_id=engagement.id,
    ):
        deliverable.status = "synthetic_delivered"
    with pytest.raises(DomainError) as exc:
        service.build_engagement_package(
            db,
            "client-one",
            engagement.id,
            actor_user_id="owner",
            correlation_id="package-synthetic",
        )
    assert exc.value.detail["code"] == "REAL_DELIVERABLES_REQUIRED"


def test_real_portfolio_homologation_case_bundle_is_valid_and_covers_all_offerings():
    repo_root = next(
        (
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / "scripts/run-portfolio-homologation-case.py").is_file()
        ),
        None,
    )
    if repo_root is None:
        pytest.skip("Repository-only homologation bundle is validated by the host suite")
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts/run-portfolio-homologation-case.py"), "validate"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    report = json.loads(result.stdout)
    assert report["status"] == "valid"
    assert report["evaluation_scenarios"] == 24
    assert report["adversarial_scenarios"] == 8
    assert report["held_out_labels"] is True
    assert len(report["offering_coverage"]) == 8
    assert set(report["offering_coverage"].values()) == {3}


def test_technical_service_run_receives_real_case_context_and_operator_instructions(db, monkeypatch):
    engagement, _ = _v2_engagement_with_approved_plan(
        db, offering_code="ai_use_case_pilot_sprint"
    )
    engagement.description = "Build the internal opportunity qualification product."
    engagement.success_criteria_json = ["Classify all eight offerings", "Require VP approval"]
    service = ServiceDeliveryOSService()
    instructions = "Use the controlled 24-scenario dataset and never auto-approve a proposal."
    service.activate_engagement(
        db, tenant_id="client-one", actor_user_id="owner", engagement_id=engagement.id,
        expected_version=1, comment=instructions, correlation_id="real-case",
        event_idempotency_key="real-case:activate",
    )
    item = db.query(ServiceWorkItem).filter_by(
        tenant_id="client-one", execution_mode="technical_run"
    ).first()
    assert item is not None
    execution = db.query(ServiceExecution).filter_by(
        tenant_id="client-one", work_item_id=item.id
    ).one()
    assert instructions in execution.evidence_json["instructions"]
    execution.status = "dispatch_pending"
    monkeypatch.setattr(
        "app.service_delivery.os_service.get_settings",
        lambda: SimpleNamespace(
            generative_build_enabled=True,
            model_run_budget_usd=15.0,
            ai_native_policy_version="2.13.2",
            pilot_max_concurrent_workflows=10,
            pilot_max_concurrent_workflows_per_tenant=2,
        ),
    )
    service.perform_execution(
        db, tenant_id="client-one", execution_id=execution.id, correlation_id="real-case"
    )
    deliverable = db.query(ServiceDeliverable).filter_by(
        tenant_id="client-one", id=item.deliverable_id
    ).one()
    run = db.query(WorkflowRun).filter_by(tenant_id="client-one", id=deliverable.run_id).one()
    assert engagement.description in run.demand
    assert "Classify all eight offerings" in run.demand
    assert instructions in run.demand
    assert run.context_manifest_json["service_execution_id"] == execution.id


@pytest.mark.parametrize(
    ("offering_code", "operation_key", "linked_count"),
    [
        ("ai_use_case_pilot_sprint", "software_product", 6),
        ("ai_engineering_productivity_accelerator", "engineering_validation", 2),
    ],
)
def test_v21_technical_group_consumes_one_execution_run_and_slot(
    db,
    monkeypatch,
    offering_code,
    operation_key,
    linked_count,
):
    engagement, version = _v2_engagement_with_approved_plan(
        db,
        offering_code=offering_code,
        version_label="2.1",
    )
    service = ServiceDeliveryOSService()
    service.activate_engagement(
        db,
        tenant_id="client-one",
        actor_user_id="owner",
        engagement_id=engagement.id,
        expected_version=1,
        comment="Executar um único grupo técnico aprovado.",
        correlation_id="technical-group",
        event_idempotency_key=f"technical-group:{operation_key}:activate",
    )
    grouped_item = db.query(ServiceWorkItem).filter_by(
        tenant_id="client-one",
        engagement_id=engagement.id,
        operation_key=operation_key,
    ).one()
    assert grouped_item.deliverable_id is None
    assert grouped_item.execution_mode == "technical_run"
    assert db.query(ServiceWorkItem).filter_by(
        tenant_id="client-one",
        engagement_id=engagement.id,
        operation_key=operation_key,
    ).count() == 1
    execution = db.query(ServiceExecution).filter_by(
        tenant_id="client-one",
        engagement_id=engagement.id,
        work_item_id=grouped_item.id,
    ).one()
    monkeypatch.setattr(
        "app.service_delivery.os_service.get_settings",
        lambda: SimpleNamespace(
            generative_build_enabled=True,
            model_run_budget_usd=15.0,
            ai_native_policy_version="2.13.2",
            pilot_max_concurrent_workflows=10,
            pilot_max_concurrent_workflows_per_tenant=2,
        ),
    )
    execution.status = "dispatch_pending"
    service.perform_execution(
        db,
        tenant_id="client-one",
        execution_id=execution.id,
        correlation_id="technical-group",
    )
    group = version.definition_json["technical_run_groups"][0]
    linked = db.query(ServiceDeliverable).filter(
        ServiceDeliverable.tenant_id == "client-one",
        ServiceDeliverable.engagement_id == engagement.id,
        ServiceDeliverable.template_key.in_(group["deliverable_template_keys"]),
    ).all()
    assert len(linked) == linked_count
    assert len({deliverable.run_id for deliverable in linked}) == 1
    run_id = linked[0].run_id
    assert run_id
    assert db.query(WorkflowRun).filter_by(
        tenant_id="client-one",
        id=run_id,
    ).count() == 1
    run = db.query(WorkflowRun).filter_by(id=run_id).one()
    assert run.context_manifest_json["workflow_version"] == "2.14.0"
    assert run.context_manifest_json["operation_key"] == operation_key
    assert set(execution.evidence_json["linked_deliverable_ids"]) == {
        deliverable.id for deliverable in linked
    }
