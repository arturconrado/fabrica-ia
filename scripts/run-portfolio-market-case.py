#!/usr/bin/env python3
"""Run a provider-real, synthetic portfolio case without persisting credentials.

The harness validates the contracted Service Delivery OS through the human
review gate. It intentionally does not impersonate the engagement manager or
claim that a technical pilot, customer interview, or external integration ran.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


CASE_NAME = "NovaMec Copiloto de Manutenção"
TENANT_ID = "market-case-novamec"
OWNER_ID = "owner-market-case"
VP_ID = "vp-review-required"
OFFERING_CODE = "ai_use_case_pilot_sprint"
TARGET_DELIVERABLE = "documento do problema"

MARKET_BRIEF = """# Brief sintético de mercado — NovaMec Serviços Industriais

Este documento descreve uma empresa e números inteiramente fictícios, criados
somente para validar a fábrica. Não contém dados pessoais ou dados de cliente.

## Contexto

A NovaMec presta manutenção de equipamentos industriais em três unidades e
coordena 180 técnicos de campo. O conhecimento operacional está distribuído
entre aproximadamente 12 mil manuais, boletins técnicos e registros de
incidentes. Técnicos relatam dificuldade para localizar instruções compatíveis
com modelo, revisão e sintoma do equipamento.

## Hipóteses a validar

- Tempo médio hipotético de busca: 30 minutos por atendimento.
- MTTR hipotético: 7,2 horas.
- Oportunidade: copiloto com recuperação de trechos, citações e confirmação
  humana antes de qualquer orientação ser usada em campo.
- Escopo do piloto: um tipo de equipamento, documentos saneados, 120 perguntas
  de avaliação e nenhuma escrita em sistemas produtivos.
- Critérios-alvo, ainda não comprovados: pelo menos 90% das respostas com fonte,
  80% de correção no dataset, zero vazamento crítico e latência p95 abaixo de
  oito segundos.
- Prazo hipotético: seis semanas, com três técnicos especialistas e um
  responsável de engenharia disponíveis para validação.

## Restrições

O assistente não toma decisão de segurança, não executa comandos em máquinas,
não substitui o procedimento oficial e não pode declarar viabilidade antes dos
testes. Métricas, entrevistas, integrações e benefícios continuam pendentes de
evidência real.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="openai/gpt-4.1-mini")
    parser.add_argument("--plan-attempts", type=int, default=2, choices=(1, 2))
    return parser.parse_args()


def configure_runtime(args: argparse.Namespace) -> Path:
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise SystemExit("OPENROUTER_API_KEY is required and must be supplied only to this process")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / "market-case.sqlite3"
    if database_path.exists():
        raise SystemExit(f"Refusing to overwrite existing case database: {database_path}")
    os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
    os.environ["ASF_DATABASE_URL"] = f"sqlite:///{database_path}"
    os.environ["ASF_RUNTIME_PROFILE"] = "development"
    os.environ["ASF_AGENT_PROVIDER"] = "litellm"
    os.environ["ASF_WORKFLOW_BACKEND"] = "homologation"
    os.environ["ASF_LITELLM_BASE_URL"] = ""
    os.environ["ASF_LITELLM_API_KEY"] = ""
    os.environ["ASF_REASONING_MODEL"] = "asf-reasoning"
    os.environ["ASF_REASONING_UPSTREAM_MODEL"] = args.model
    os.environ["ASF_SERVICE_DELIVERY_OS_ENABLED"] = "true"
    os.environ["ASF_GENERATIVE_BUILD_ENABLED"] = "false"
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "apps" / "api"))
    return database_path


def case_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def main() -> int:
    args = parse_args()
    database_path = configure_runtime(args)

    from app.auth.dependencies import ensure_tenant
    from app.db.session import SessionLocal, engine, set_tenant_context
    from app.domain.ids import new_id
    from app.models import (
        Artifact,
        Base,
        ComponentDefinition,
        Contract,
        DeliverableRevision,
        Entitlement,
        Engagement,
        LedgerRecord,
        ModelCall,
        OfferingVersion,
        ServiceDeliverable,
        ServiceExecution,
        ServiceOffering,
        ServiceWorkItem,
        utcnow,
    )
    from app.service_delivery.catalog import ensure_service_catalog
    from app.service_delivery.os_service import ServiceDeliveryOSService
    from app.service_delivery.package_export import _pptx
    from app.service_delivery.service import DomainError, actor_event, ensure_component_definitions

    run_key = case_id()
    correlation_id = f"market-case:{run_key}"
    output_dir = database_path.parent
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        ensure_tenant(db, TENANT_ID, "NovaMec Serviços Industriais — Case Sintético")
        set_tenant_context(db, TENANT_ID, OWNER_ID)
        ensure_component_definitions(db)
        ensure_service_catalog(db)
        service = ServiceDeliveryOSService()

        knowledge_base = service.knowledge.create_base(
            db,
            TENANT_ID,
            OWNER_ID,
            "Evidências sintéticas do case NovaMec",
            "Base isolada para demonstrar grounding sem dados de clientes.",
            correlation_id,
        )
        source_document = service.knowledge.add_document(
            db,
            TENANT_ID,
            OWNER_ID,
            knowledge_base.id,
            title="Brief sintético de mercado NovaMec v1",
            content=MARKET_BRIEF,
            source_type="synthetic_market_case",
            source_ref="case://novamec-maintenance-copilot/v1",
            metadata={"synthetic": True, "presentation_case": True},
            correlation_id=correlation_id,
        )

        offering = db.query(ServiceOffering).filter_by(code=OFFERING_CODE).one()
        offering_version = db.query(OfferingVersion).filter_by(
            offering_id=offering.id, version="2.1"
        ).one()
        component_code = offering_version.definition_json["component_codes"][0]
        component = db.query(ComponentDefinition).filter_by(code=component_code).one()
        contract = Contract(
            id=new_id(),
            tenant_id=TENANT_ID,
            contract_number=f"CASE-{run_key}",
            status="active",
            valid_from=date.today().isoformat(),
            valid_until="",
            commercial_metadata_json={
                "synthetic": True,
                "price_defined": False,
                "presentation_case": True,
            },
            scope_summary=(
                "Case sintético para planejar um piloto de copiloto de manutenção com grounding, "
                "citações, supervisão humana e avaliação controlada."
            ),
        )
        db.add(contract)
        db.flush()
        db.add(
            Entitlement(
                id=new_id(),
                tenant_id=TENANT_ID,
                contract_id=contract.id,
                component_definition_id=component.id,
                component_code=component_code,
                status="granted",
                capabilities_json=["service_delivery.activate", "service_delivery.execute"],
                limits_json={"presentation_case": 1},
                terms_json={"synthetic": True, "no_production_writeback": True},
            )
        )
        actor_event(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=OWNER_ID,
            aggregate_type="contract",
            aggregate_id=contract.id,
            event_type="contract.market_case_activated",
            correlation_id=correlation_id,
            idempotency_key=f"market-case:{run_key}:contract",
            payload={"summary": "Synthetic market-case contract and entitlement activated"},
        )
        engagement = service.create_engagement(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=OWNER_ID,
            correlation_id=correlation_id,
            event_idempotency_key=f"market-case:{run_key}:engagement",
            payload={
                "contract_id": contract.id,
                "offering_version_id": offering_version.id,
                "name": CASE_NAME,
                "description": "Validação de um copiloto grounded para suporte a técnicos de manutenção.",
                "sponsor": "VP de Negócios — aprovação pendente",
                "start_date": date.today().isoformat(),
                "target_end_date": "",
                "success_criteria": [
                    "Plano preserva todos os entregáveis contratados da versão 2.1",
                    "Documento do problema usa apenas evidência sintética identificada",
                    "Artifact chega ao gate de revisão humana sem autoaprovação",
                ],
                "service_levels": {"case_type": "synthetic_market_validation"},
                "dependency_engagement_ids": [],
            },
        )
        db.commit()

        adaptation_brief = (
            "Planeje o AI Use Case Pilot para o copiloto de manutenção da NovaMec. Preserve exatamente todos os "
            "template_key e entregáveis do contrato v2.1. Trate números como hipóteses sintéticas a validar, "
            "não declare entrevistas, testes, integrações, demo ou benefício como concluídos. Separe trabalho agent, "
            "technical_run, human e integration e mantenha decisão final com o VP."
        )
        plan = None
        plan_errors: list[str] = []
        for attempt in range(1, args.plan_attempts + 1):
            try:
                db.refresh(engagement)
                plan = service.generate_plan(
                    db,
                    tenant_id=TENANT_ID,
                    actor_user_id=OWNER_ID,
                    engagement_id=engagement.id,
                    expected_version=engagement.record_version,
                    adaptation_brief=adaptation_brief,
                    knowledge_base_ids=[knowledge_base.id],
                    correlation_id=f"{correlation_id}:plan:{attempt}",
                    event_idempotency_key=f"market-case:{run_key}:plan:{attempt}",
                )
                db.commit()
                break
            except DomainError as exc:
                plan_errors.append(str(exc))
                db.commit()  # retain the provider attempt and its audit trail
        if plan is None:
            raise RuntimeError(f"Provider did not produce a contract-complete plan: {plan_errors}")

        db.refresh(engagement)
        service.approve_plan(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=VP_ID,
            engagement_id=engagement.id,
            plan_version=plan.version,
            expected_version=engagement.record_version,
            comment=(
                "Synthetic harness approval of plan structure only; this identity marks the role boundary and is not "
                "a real business acceptance of deliverables."
            ),
            correlation_id=correlation_id,
            event_idempotency_key=f"market-case:{run_key}:plan-structure-approved",
        )
        db.flush()
        db.refresh(engagement)
        service.activate_engagement(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=OWNER_ID,
            engagement_id=engagement.id,
            expected_version=engagement.record_version,
            comment="Activate the synthetic case after structural plan validation.",
            correlation_id=correlation_id,
            event_idempotency_key=f"market-case:{run_key}:activate",
        )
        db.commit()

        deliverable = db.query(ServiceDeliverable).filter_by(
            tenant_id=TENANT_ID,
            engagement_id=engagement.id,
            title=TARGET_DELIVERABLE,
        ).one()
        item = db.query(ServiceWorkItem).filter_by(
            tenant_id=TENANT_ID,
            deliverable_id=deliverable.id,
        ).one()
        if item.execution_mode != "agent":
            raise RuntimeError(f"Expected an agent work item, received {item.execution_mode}")
        execution = service.queue_execution(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=OWNER_ID,
            item_id=item.id,
            expected_version=item.record_version,
            instructions=(
                "Produza somente o Documento do problema. Contextualize o setor e a jornada atual, diferencie fatos "
                "sintéticos de hipóteses, explicite usuários, entradas, saídas, restrições, riscos, métricas-alvo e "
                "perguntas em aberto. Não declare que o piloto ou seus testes já aconteceram."
            ),
            knowledge_base_ids=[knowledge_base.id],
            correlation_id=correlation_id,
            event_idempotency_key=f"market-case:{run_key}:queue",
        )
        execution.status = "dispatch_pending"
        execution.temporal_workflow_id = f"homologation-in-process:{execution.id}"
        execution.record_version += 1
        item.status = "in_progress"
        item.started_at = utcnow()
        item.record_version += 1
        actor_event(
            db,
            tenant_id=TENANT_ID,
            actor_user_id="system",
            aggregate_type="service_execution",
            aggregate_id=execution.id,
            event_type="service_execution.homologation_dispatched",
            correlation_id=correlation_id,
            idempotency_key=f"market-case:{run_key}:dispatch",
            payload={
                "summary": "Execution dispatched through the explicit in-process homologation transport",
                "production_temporal_transport": False,
            },
        )
        db.commit()

        execution = service.perform_execution(
            db,
            tenant_id=TENANT_ID,
            execution_id=execution.id,
            correlation_id=correlation_id,
        )
        db.commit()
        db.refresh(deliverable)
        if execution.status != "awaiting_review" or deliverable.status != "in_progress":
            raise RuntimeError(
                f"Unexpected execution/deliverable state: {execution.status}/{deliverable.status}"
            )
        service.submit_deliverable(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=OWNER_ID,
            deliverable_id=deliverable.id,
            expected_version=deliverable.record_version,
            comment="Documento gerado com provider real e evidência sintética; solicitar revisão humana do VP.",
            correlation_id=correlation_id,
            event_idempotency_key=f"market-case:{run_key}:submit",
        )
        db.commit()

        revision = db.query(DeliverableRevision).filter_by(
            tenant_id=TENANT_ID,
            deliverable_id=deliverable.id,
            revision=deliverable.current_revision,
        ).one()
        canonical_artifact = db.query(Artifact).filter(
            Artifact.tenant_id == TENANT_ID,
            Artifact.id.in_(revision.artifact_refs_json),
        ).one()
        calls = db.query(ModelCall).filter_by(tenant_id=TENANT_ID).order_by(ModelCall.created_at).all()
        successful_calls = [call for call in calls if call.status == "success"]
        total_cost = sum(float(call.estimated_cost_usd or 0.0) for call in calls)
        total_prompt_tokens = sum(int(call.prompt_tokens or 0) for call in calls)
        total_completion_tokens = sum(int(call.completion_tokens or 0) for call in calls)

        generated_markdown = str(revision.content_json.get("content_markdown") or "").strip() + "\n"
        deck_markdown = (
            f"# RASCUNHO — {CASE_NAME}\n\n"
            "## 1. Oportunidade de mercado\n\n"
            "Manutenção industrial concentra conhecimento em manuais, boletins e históricos difíceis de consultar no campo.\n\n"
            "## 2. Empresa e cenário\n\n"
            "NovaMec é uma empresa fictícia; os números do case são hipóteses de validação, não resultados observados.\n\n"
            "## 3. Caso de uso\n\n"
            "Copiloto grounded que recupera trechos, apresenta citações e exige confirmação humana.\n\n"
            "## 4. Escopo controlado\n\n"
            "Um equipamento, 120 perguntas, documentos saneados, sem escrita em produção e sem decisão autônoma.\n\n"
            "## 5. Critérios-alvo\n\n"
            "Fontes em 90% das respostas, 80% de correção, zero vazamento crítico e latência p95 inferior a oito segundos.\n\n"
            "## 6. Como a fábrica operou\n\n"
            f"Contrato e entitlement → plano com {len(plan.plan_json['deliverables'])} entregáveis → RAG tenant-scoped → "
            "execução agent → artifact versionado → revisão humana.\n\n"
            "## 7. Evidências desta execução\n\n"
            f"{len(successful_calls)} chamadas reais, {total_prompt_tokens} tokens de entrada, "
            f"{total_completion_tokens} tokens de saída e custo registrado de US$ {total_cost:.6f}.\n\n"
            "## 8. Gate atual\n\n"
            "Documento em review_ready. O pacote final permanece bloqueado até revisão real e decisão do VP.\n\n"
            "## 9. O que ainda não foi comprovado\n\n"
            "Construção técnica, testes do piloto, integrações, entrevistas, ganhos de negócio, Temporal em rede e aceite do cliente.\n"
        )
        pptx_payload = _pptx(f"RASCUNHO — {CASE_NAME}", deck_markdown)
        presentation_sha = hashlib.sha256(pptx_payload).hexdigest()
        presentation_artifact = Artifact(
            id=new_id(),
            tenant_id=TENANT_ID,
            node_id="service-delivery",
            artifact_type="market-case-presentation-draft",
            name=f"RASCUNHO — {CASE_NAME}",
            path=f"market-cases/{run_key}/case-presentation-draft.pptx",
            content=deck_markdown,
            audience="internal",
            evidence_classification="calculated",
            source_refs_json=[canonical_artifact.id, source_document.id, execution.id],
            metadata_json={
                "sha256": presentation_sha,
                "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "size_bytes": len(pptx_payload),
                "status": "draft_awaiting_vp_review",
            },
        )
        db.add(presentation_artifact)
        db.flush()
        actor_event(
            db,
            tenant_id=TENANT_ID,
            actor_user_id=OWNER_ID,
            aggregate_type="engagement",
            aggregate_id=engagement.id,
            event_type="engagement.market_case_presentation_drafted",
            correlation_id=correlation_id,
            idempotency_key=f"market-case:{run_key}:presentation",
            payload={
                "summary": "Editable synthetic case presentation drafted; VP review remains pending",
                "artifact_id": presentation_artifact.id,
                "sha256": presentation_sha,
            },
        )
        db.commit()

        db.refresh(deliverable)
        report = {
            "schema_version": "portfolio-market-case/1.0",
            "case_id": run_key,
            "case_name": CASE_NAME,
            "synthetic": True,
            "tenant_id": TENANT_ID,
            "offering": {"code": OFFERING_CODE, "version": "2.1", "status": offering_version.status},
            "engagement_id": engagement.id,
            "contract_id": contract.id,
            "knowledge_document_id": source_document.id,
            "plan": {
                "id": plan.id,
                "status": plan.status,
                "deliverables": len(plan.plan_json["deliverables"]),
                "required_deliverables": len(offering_version.definition_json["deliverable_templates"]),
                "provider_attempt_errors": plan_errors,
            },
            "execution": {
                "id": execution.id,
                "status": execution.status,
                "mode": execution.execution_mode,
                "transport": "in_process_homologation",
                "production_temporal_transport_validated": False,
            },
            "deliverable": {
                "id": deliverable.id,
                "title": deliverable.title,
                "status": deliverable.status,
                "revision": revision.revision,
                "artifact_id": canonical_artifact.id,
                "evidence_refs": revision.evidence_refs_json,
            },
            "provider": {
                "model_alias": "asf-reasoning",
                "upstream_model": args.model,
                "calls": len(calls),
                "successful_calls": len(successful_calls),
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "estimated_cost_usd": round(total_cost, 8),
                "routes": sorted({call.provider_route for call in calls if call.provider_route}),
            },
            "presentation": {
                "artifact_id": presentation_artifact.id,
                "status": "draft_awaiting_vp_review",
                "sha256": presentation_sha,
            },
            "governance": {
                "automatic_business_approval": False,
                "vp_review_required": True,
                "final_package_generated": False,
            },
            "validated": [
                "versioned contract and entitlement",
                "provider-real plan with every contracted template",
                "tenant-scoped grounded context",
                "agent service execution and persisted checkpoint",
                "model-call cost and token audit",
                "canonical markdown artifact",
                "four-eyes review gate",
                "editable draft presentation",
            ],
            "not_validated": [
                "networked Temporal dispatch and worker recovery",
                "technical pilot build and 17 quality gates",
                "real customer interviews, integrations or business outcomes",
                "VP decision, final delivery package and client acceptance",
            ],
            "ledger_events": db.query(LedgerRecord).filter_by(tenant_id=TENANT_ID).count(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        report_markdown = (
            f"# Case demonstrativo — {CASE_NAME}\n\n"
            "Status: **rascunho aguardando revisão real do VP**.\n\n"
            f"- Oferta: AI Use Case Pilot v2.1 (`{offering_version.status}`)\n"
            f"- Plano: {report['plan']['deliverables']}/{report['plan']['required_deliverables']} entregáveis contratados\n"
            f"- Provider: {args.model}, {len(successful_calls)}/{len(calls)} chamadas bem-sucedidas\n"
            f"- Tokens: {total_prompt_tokens} entrada / {total_completion_tokens} saída\n"
            f"- Custo registrado: US$ {total_cost:.6f}\n"
            f"- Deliverable: `{deliverable.status}`; artifact `{canonical_artifact.id}`\n"
            f"- Eventos append-only: {report['ledger_events']}\n\n"
            "## Resultado\n\n"
            "A fábrica produziu um plano contratualmente completo e um Documento do problema grounded, persistiu "
            "custos/evidências e bloqueou a entrega no gate humano. O deck editável é um rascunho interno.\n\n"
            "## Lacunas explícitas\n\n"
            + "\n".join(f"- {item}" for item in report["not_validated"])
            + "\n"
        )

        (output_dir / "source-brief.md").write_text(MARKET_BRIEF, encoding="utf-8")
        (output_dir / "generated-problem-document.md").write_text(generated_markdown, encoding="utf-8")
        (output_dir / "case-presentation-draft.md").write_text(deck_markdown, encoding="utf-8")
        (output_dir / "case-presentation-draft.pptx").write_bytes(pptx_payload)
        (output_dir / "case-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output_dir / "case-report.md").write_text(report_markdown, encoding="utf-8")
    finally:
        db.close()
        engine.dispose()

    secret = os.environ["OPENROUTER_API_KEY"].encode()
    leaked_paths = []
    for path in output_dir.rglob("*"):
        if path.is_file() and secret in path.read_bytes():
            leaked_paths.append(str(path))
    if leaked_paths:
        raise RuntimeError(f"Secret persistence check failed for: {leaked_paths}")

    print(
        json.dumps(
            {
                "status": "awaiting_vp_review",
                "output_dir": str(output_dir),
                "report": str(output_dir / "case-report.md"),
                "presentation": str(output_dir / "case-presentation-draft.pptx"),
                "secret_persisted": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
