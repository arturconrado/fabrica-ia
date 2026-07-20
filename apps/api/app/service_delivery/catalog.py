import hashlib
import json
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.domain.ids import new_id
from app.models import AgentDefinition, AgentTemplate, AgentVersion, OfferingVersion, ServiceOffering


OFFERINGS: list[dict[str, Any]] = [
    {
        "code": "ai_value_discovery",
        "name": "AI Value Discovery",
        "category": "entry_service",
        "description": "Diagnóstico executivo para identificar onde a IA pode gerar maior retorno.",
        "duration_label": "4–6 semanas",
        "cadence": "one_off",
        "component_codes": ["ai_value_discovery"],
        "stages": ["Mobilização", "Assessment", "Mapeamento", "Priorização", "Roadmap", "Aceite"],
        "deliverables": [
            "Assessment de maturidade", "Mapa de processos", "Inventário de oportunidades",
            "Matriz impacto × complexidade", "Ranking de casos de uso", "Business cases preliminares",
            "Roadmap de 12 meses", "Arquitetura de referência", "Apresentação executiva",
        ],
        "definition_of_done": [
            "Stakeholders prioritários entrevistados", "Áreas previstas avaliadas", "Oportunidades registradas",
            "Top casos priorizados", "Custos, benefícios, riscos e dependências documentados",
            "Roadmap validado", "Apresentação realizada", "Aceite formal do sponsor",
        ],
    },
    {
        "code": "ai_governance_risk_framework",
        "name": "AI Governance & Risk Framework",
        "category": "productized_service",
        "description": "Estrutura mínima de governança para uso seguro e responsável de IA.",
        "duration_label": "6–8 semanas",
        "cadence": "one_off",
        "component_codes": ["responsible_ai_governance"],
        "stages": ["Inventário", "Taxonomia", "Políticas", "Controles", "Simulação", "Aceite"],
        "deliverables": [
            "Política corporativa de IA", "Inventário de soluções", "Taxonomia de riscos",
            "Matriz de classificação", "RACI", "Processo de aprovação", "Checklist de fornecedores",
            "Política de dados", "Processo de incidentes", "Modelo de documentação", "Plano de auditoria",
        ],
        "definition_of_done": [
            "Inventário inicial concluído", "Política revisada pelas áreas responsáveis", "Papéis definidos",
            "Fluxo de aprovação documentado", "Pelo menos três casos classificados",
            "Processo de incidente simulado", "Repositório de governança entregue", "Aceite do comitê responsável",
        ],
    },
    {
        "code": "ai_enterprise_launchpad",
        "name": "AI Enterprise Launchpad",
        "category": "implementation_program",
        "description": "Programa para colocar a estratégia de IA em operação nas primeiras áreas.",
        "duration_label": "8–12 semanas",
        "cadence": "one_off",
        "component_codes": ["ai_enterprise_launchpad"],
        "stages": ["Readiness", "Modelo operacional", "Configuração", "Ativação", "Adoção", "Handover"],
        "deliverables": [
            "Plano do programa", "Modelo operacional", "Configuração das plataformas", "Implantação em três áreas",
            "Biblioteca de casos de uso", "Playbooks", "Treinamentos", "Rede de champions",
            "Dashboard de adoção", "Indicadores", "Plano de expansão",
        ],
        "definition_of_done": [
            "Ferramentas configuradas conforme escopo", "Três áreas ativadas", "Casos prioritários validados",
            "Usuários treinados", "Métricas instrumentadas", "Responsáveis definidos", "Riscos críticos tratados",
            "Handover realizado", "Plano de expansão aprovado", "Aceite executivo formal",
        ],
    },
    {
        "code": "ai_workforce_productivity_accelerator",
        "name": "AI Workforce Productivity Accelerator",
        "category": "productivity_program",
        "description": "Transformação de tarefas corporativas recorrentes em fluxos assistidos por IA.",
        "duration_label": "6–10 semanas",
        "cadence": "one_off",
        "component_codes": ["ai_enterprise_launchpad"],
        "stages": ["Mapeamento", "Configuração", "Biblioteca", "Capacitação", "Telemetria", "Melhoria contínua"],
        "deliverables": [
            "Mapeamento de tarefas", "Configuração das ferramentas", "Biblioteca de prompts",
            "Assistentes por função", "Playbooks", "Workshops", "Trilhas de capacitação", "Templates",
            "Comunidade de champions", "Dashboard de uso e valor",
        ],
        "definition_of_done": [
            "Funções prioritárias mapeadas", "Workflows contratados validados", "Biblioteca publicada",
            "Usuários habilitados", "Treinamentos realizados", "Telemetria disponível", "Política de uso aplicada",
            "Responsáveis nomeados", "Plano de melhoria contínua entregue",
        ],
    },
    {
        "code": "ai_engineering_productivity_accelerator",
        "name": "AI Engineering Productivity Accelerator",
        "category": "specialized_program",
        "description": "Aumento de produtividade, qualidade e velocidade da engenharia com IA.",
        "duration_label": "6–10 semanas",
        "cadence": "one_off",
        "component_codes": ["engineering_productivity_accelerator"],
        "stages": ["Baseline", "Segurança", "Configuração", "Casos", "Gates", "Escala"],
        "deliverables": [
            "Baseline de engenharia", "Assessment de segurança", "Configuração das ferramentas",
            "Playbooks por papel", "Casos de uso", "Padrões de código", "Quality gates",
            "Treinamento de squads", "Dashboard de engenharia", "Plano de escala",
        ],
        "definition_of_done": [
            "Squads contratadas ativadas", "Ambientes configurados", "Controles de segurança validados",
            "Casos de uso testados", "Quality gates integrados", "Baseline e indicadores registrados",
            "Líderes treinados", "Documentação operacional entregue", "Piloto aprovado pelas squads e sponsor",
        ],
    },
    {
        "code": "ai_use_case_pilot_sprint",
        "name": "AI Use Case Pilot Sprint",
        "category": "validation_service",
        "description": "Sprint controlada para transformar um caso priorizado em piloto funcional e mensurável.",
        "duration_label": "4–8 semanas",
        "cadence": "one_off",
        "component_codes": ["rapid_mvp_factory"],
        "stages": ["Desenho", "Arquitetura", "Construção", "Avaliação", "Demonstração", "Decisão"],
        "deliverables": [
            "Desenho funcional", "Arquitetura", "Protótipo ou piloto", "Preparação dos dados",
            "Integração limitada", "Avaliação de respostas", "Testes de segurança", "Demonstração",
            "Relatório de resultados", "Recomendação de evolução",
        ],
        "definition_of_done": [
            "Fluxo acordado funcionando de ponta a ponta", "Dados e integrações previstas disponíveis",
            "Testes funcionais aprovados", "Avaliação mínima executada", "Riscos documentados",
            "Demonstração realizada", "Backlog produtivo criado", "Decisão formal registrada",
        ],
    },
    {
        "code": "ai_office_as_a_service",
        "name": "AI Office as a Service",
        "category": "managed_service",
        "description": "Escritório mensal para coordenar governança, adoção, portfólio e valor.",
        "duration_label": "Recorrente mensal",
        "cadence": "monthly",
        "component_codes": ["ai_office"],
        "stages": ["Intake", "Priorização", "Execução", "Comitê", "Relatório", "Próximo ciclo"],
        "deliverables": [
            "Comitê mensal", "Gestão do backlog", "Avaliação de casos de uso", "Dashboard executivo",
            "Gestão de riscos", "Capacitação contínua", "Office hours", "Revisão de fornecedores",
            "Roadmap atualizado", "Relatório de valor", "Plano mensal de ações",
        ],
        "definition_of_done": [
            "Reunião executiva realizada", "Relatório mensal entregue", "Backlog atualizado",
            "Casos previstos avaliados", "Riscos e decisões registrados", "Indicadores consolidados",
            "Ações com responsáveis e prazos definidas", "Pendências críticas escaladas", "Aceite mensal registrado",
        ],
    },
    {
        "code": "ai_adoption_kit_governance_cockpit",
        "name": "AI Adoption Kit & Governance Cockpit",
        "category": "digital_product",
        "description": "Repositório de políticas, templates, dashboards, playbooks e ativos reutilizáveis.",
        "duration_label": "2–4 semanas",
        "cadence": "one_off",
        "component_codes": ["responsible_ai_governance"],
        "stages": ["Seleção", "Configuração", "Identidade", "Integração", "Validação", "Handover"],
        "deliverables": [
            "Templates de políticas", "Questionários", "Matriz de riscos", "Catálogo de casos",
            "Calculadora de ROI", "Biblioteca de prompts", "Dashboards", "Checklists",
            "Modelos de business case", "Trilhas de treinamento", "Repositório configurado",
        ],
        "definition_of_done": [
            "Conteúdo contratado disponibilizado", "Repositório configurado", "Identidade visual aplicada",
            "Permissões validadas", "Templates testados", "Dashboard conectado às fontes previstas",
            "Administradores treinados", "Documentação de uso e atualização entregue",
        ],
    },
]


AGENT_TEMPLATES: list[dict[str, Any]] = [
    {"code": "engagement_planner", "name": "Engagement Planner", "purpose": "Adapta uma oferta contratada ao contexto e aos critérios do cliente.", "model_role": "reasoning", "tools": ["create_artifact"]},
    {"code": "process_value_analyst", "name": "Process & Value Analyst", "purpose": "Mapeia processos, oportunidades, indicadores e hipóteses de valor.", "model_role": "reasoning", "tools": ["create_artifact", "read_tenant_knowledge"]},
    {"code": "governance_risk_specialist", "name": "Governance & Risk Specialist", "purpose": "Produz inventários, políticas, controles e avaliações de risco.", "model_role": "reasoning", "tools": ["create_artifact", "read_tenant_knowledge"]},
    {"code": "adoption_enablement_lead", "name": "Adoption & Enablement Lead", "purpose": "Planeja capacitação, champions, adoção e melhoria contínua.", "model_role": "reasoning", "tools": ["create_artifact", "read_tenant_knowledge"]},
    {"code": "productivity_specialist", "name": "Productivity Specialist", "purpose": "Desenha fluxos de produtividade para workforce e engenharia.", "model_role": "reasoning", "tools": ["create_artifact", "read_tenant_knowledge"]},
    {"code": "ai_office_manager", "name": "AI Office Manager", "purpose": "Coordena backlog, comitê, riscos, ações e valor do ciclo recorrente.", "model_role": "fast", "tools": ["create_artifact", "read_tenant_knowledge"]},
    {"code": "deliverable_quality_curator", "name": "Deliverable Quality Curator", "purpose": "Verifica evidências e Definition of Done sem substituir aprovação humana.", "model_role": "reasoning", "tools": ["read_artifact", "read_evidence"]},
    {"code": "agent_architect", "name": "Agent Architect", "purpose": "Propõe agentes limitados, schemas e políticas para lacunas aprovadas.", "model_role": "reasoning", "tools": ["propose_agent_definition"]},
]


def _checksum(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def ensure_service_catalog(db: Session) -> None:
    for definition in OFFERINGS:
        offering = db.query(ServiceOffering).filter_by(code=definition["code"]).first()
        if not offering:
            offering = ServiceOffering(
                id=new_id(),
                code=definition["code"],
                name=definition["name"],
                category=definition["category"],
                description=definition["description"],
                status="active",
            )
            db.add(offering)
            db.flush()
        payload = {key: value for key, value in definition.items() if key not in {"code", "name", "category", "description"}}
        checksum = _checksum(payload)
        version = db.query(OfferingVersion).filter_by(offering_id=offering.id, version="1.0").first()
        if not version:
            db.add(
                OfferingVersion(
                    id=new_id(),
                    offering_id=offering.id,
                    version="1.0",
                    status="active",
                    duration_label=definition["duration_label"],
                    cadence=definition["cadence"],
                    definition_json=payload,
                    checksum=checksum,
                )
            )
        elif version.checksum != checksum:
            raise RuntimeError(f"Immutable offering version drift detected for {definition['code']}@1.0")

    for definition in AGENT_TEMPLATES:
        checksum = _checksum(definition)
        template = db.query(AgentTemplate).filter_by(code=definition["code"], version="1.0").first()
        if not template:
            db.add(
                AgentTemplate(
                    id=new_id(),
                    code=definition["code"],
                    version="1.0",
                    name=definition["name"],
                    purpose=definition["purpose"],
                    definition_json=definition,
                    checksum=checksum,
                    status="approved",
                )
            )
        elif template.checksum != checksum:
            raise RuntimeError(f"Immutable agent template drift detected for {definition['code']}@1.0")
    db.flush()


def ensure_tenant_agent_catalog(db: Session, tenant_id: str) -> None:
    ensure_service_catalog(db)
    templates = db.query(AgentTemplate).filter_by(status="approved").all()
    for template in templates:
        definition = db.query(AgentDefinition).filter_by(tenant_id=tenant_id, code=template.code).first()
        if not definition:
            definition = AgentDefinition(
                id=new_id(), tenant_id=tenant_id, template_id=template.id, code=template.code,
                name=template.name, purpose=template.purpose, scope="tenant", status="approved",
            )
            db.add(definition)
            db.flush()
        existing = db.query(AgentVersion).filter_by(
            tenant_id=tenant_id, agent_definition_id=definition.id, version="1.0"
        ).first()
        if existing:
            continue
        template_definition = template.definition_json or {}
        skill = {
            "id": template.code,
            "name": template.name,
            "version": "1.0",
            "mission": template.purpose,
            "allowed_tools": template_definition.get("tools", []),
            "forbidden_actions": ["cross_tenant_access", "change_quality_gates", "arbitrary_shell", "automatic_human_approval"],
        }
        version_payload = {
            "skill": skill,
            "system_prompt": f"Você é {template.name}. {template.purpose} Use somente contexto autorizado do tenant e produza JSON estruturado.",
            "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}, "artifacts": {"type": "array", "items": {"type": "object"}}}, "required": ["summary", "artifacts"]},
            "context_policy": {
                "version": "2.13.0",
                "max_rag_chunks": 4,
                "input_budget_tokens": 12000,
                "max_selected_references": 8,
                "per_kind_token_budgets": {"rag": 6000, "artifact": 4500, "lesson": 800},
                "file_mode": "none",
            },
            "allowed_tools": template_definition.get("tools", []),
            "model_role": template_definition.get("model_role", "reasoning"),
        }
        db.add(
            AgentVersion(
                id=new_id(), tenant_id=tenant_id, agent_definition_id=definition.id, version="1.0",
                status="approved", skill_yaml=yaml.safe_dump(skill, sort_keys=False, allow_unicode=True),
                system_prompt=version_payload["system_prompt"], output_schema_json=version_payload["output_schema"],
                context_policy_json=version_payload["context_policy"], allowed_tools_json=version_payload["allowed_tools"],
                model_role=version_payload["model_role"], checksum=_checksum(version_payload),
            )
        )
    db.flush()
