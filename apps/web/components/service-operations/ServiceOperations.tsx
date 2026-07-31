"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bot,
  Boxes,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  ClipboardCheck,
  Download,
  FileCheck2,
  FileStack,
  Gauge,
  Handshake,
  Layers3,
  ListChecks,
  LockKeyhole,
  Play,
  RefreshCw,
  RotateCcw,
  Send,
  Sparkles,
  Timer,
  UserCheck,
  Users,
} from "lucide-react";

import { MarkdownViewer } from "@/components/common/MarkdownViewer";
import { OperationalGuidance } from "@/components/common/OperationalGuidance";
import { DeliverablesCenter } from "@/components/operations/OperationsViews";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Provenance, Surface } from "@/components/common/OperationalUI";
import { API_BASE, apiGet, apiPost, commandKey } from "@/lib/api";
import type {
  AgentCatalog,
  Capacity,
  Engagement,
  EngagementPlan,
  OutcomeMetric,
  ServiceDeliverable,
  ServiceAcceptanceCheck,
  ServiceCycle,
  ServiceExecution,
  EngagementDependency,
  ServiceOffering,
  ServicePortfolio,
  WorkItem,
} from "@/lib/contracts";
import { fmtDate } from "@/lib/format";
import { getBrowserSession, type BrowserSession } from "@/lib/session-client";
import { StatusBadge } from "@/lib/status";
import { useResource } from "@/hooks/useResource";


type Contract = { id: string; contract_number: string; status: string; scope_summary: string };
type Program = { id: string; name: string; status: string };
const CURRENT_PORTFOLIO_VERSION = "2.1";
type ClientOverview = {
  tenant_id: string;
  summary: { engagements: number; active_engagements: number; deliverables: number; deliverables_in_review: number; deliverables_completed: number; active_work_items: number };
  engagements: Engagement[];
  deliverables: ServiceDeliverable[];
  work_items: WorkItem[];
  contracts: Contract[];
  programs: Program[];
  outcomes: OutcomeMetric[];
};

type EngagementWorkspaceData = Engagement & {
  plans: EngagementPlan[];
  workstreams: Array<{ id: string; name: string; objective: string; status: string }>;
  deliverables: ServiceDeliverable[];
  work_items: WorkItem[];
  cycles: ServiceCycle[];
  service_executions: ServiceExecution[];
  acceptance_checks: ServiceAcceptanceCheck[];
  dependencies: EngagementDependency[];
  outcomes: ClientOverview["outcomes"];
  agent_assignments: AgentCatalog["assignments"];
  events: Array<{ id: string; event_type: string; tenant_sequence: number; created_at: string; payload_json: { summary?: string } }>;
};

function RefreshButton({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 text-sm text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))]"><RefreshCw className="h-4 w-4" /> Atualizar</button>;
}

const PORTFOLIO_JOURNEY = [
  "Identificar oportunidades",
  "Priorizar investimentos",
  "Estabelecer governança",
  "Implantar capacidades",
  "Validar casos de uso",
  "Acelerar adoção",
  "Operar continuamente",
];

const PORTFOLIO_LANES = [
  {
    label: "Descobrir e priorizar",
    description: "Entender onde investir e em qual sequência.",
    codes: ["ai_value_discovery"],
  },
  {
    label: "Governar",
    description: "Criar guardrails, políticas e um cockpit de gestão.",
    codes: ["ai_governance_risk_framework", "ai_adoption_kit_governance_cockpit"],
  },
  {
    label: "Implantar e validar",
    description: "Ativar capacidades e provar casos de uso reais.",
    codes: ["ai_enterprise_launchpad", "ai_use_case_pilot_sprint"],
  },
  {
    label: "Acelerar",
    description: "Escalar produtividade para negócio e engenharia.",
    codes: ["ai_workforce_productivity_accelerator", "ai_engineering_productivity_accelerator"],
  },
  {
    label: "Operar continuamente",
    description: "Gerir portfólio, riscos, adoção e valor em ciclos.",
    codes: ["ai_office_as_a_service"],
  },
];

type ReadinessSummary = {
  ready: boolean;
  internal_assisted_pilot_ready: boolean;
  market_ready: boolean;
  homologation_tenant_count: number;
  offerings: Array<{ offering_code: string; passed: boolean }>;
  validation_reports: Array<{ report_kind: string; passed: boolean; artifact_id: string | null }>;
  release_blockers: string[];
  market_blockers: string[];
};

const EXECUTION_MODE: Record<string, { label: string; detail: string; className: string }> = {
  agent: {
    label: "IA assistida",
    detail: "A fábrica produz a análise ou o artifact com rastreabilidade.",
    className: "border-violet-500/30 bg-violet-500/10 text-violet-200",
  },
  technical_run: {
    label: "Fábrica técnica",
    detail: "A execução usa o workflow AI-native, quality gates e evidências técnicas.",
    className: "border-blue-500/30 bg-blue-500/10 text-blue-200",
  },
  human: {
    label: "Interação humana",
    detail: "Entrevista, treinamento, demonstração, comitê ou aceite registrado.",
    className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  },
  integration: {
    label: "Integração",
    detail: "Ação externa controlada por conector autorizado ou evidência humana.",
    className: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  },
};

function executionMode(mode: string) {
  return EXECUTION_MODE[mode] || {
    label: mode.replaceAll("_", " "),
    detail: "Etapa definida no catálogo contratado.",
    className: "border-line bg-[rgb(var(--panel-soft))] text-[rgb(var(--muted))]",
  };
}

function roleLabel(role: string) {
  const labels: Record<string, string> = {
    engagement_planner: "Planejador do engajamento",
    process_value_analyst: "Analista de processos e valor",
    solution_platform_architect: "Arquiteto de solução e plataforma",
    deliverable_quality_curator: "Curador de qualidade",
    governance_risk_specialist: "Especialista de governança e risco",
    enablement_handover_specialist: "Especialista de habilitação e handover",
    productivity_specialist: "Especialista de produtividade",
    ai_office_manager: "Gestor do AI Office",
    cockpit_configurator: "Configurador do Governance Cockpit",
    engagement_manager: "VP / gestor do engajamento",
  };
  return labels[role] || role.replaceAll("_", " ");
}

function OfferingProcessFlow({ offering, compact = false }: { offering: ServiceOffering; compact?: boolean }) {
  const process = offering.definition.process || [];
  if (!process.length) {
    return <EmptyState title="Processo não detalhado nesta versão" description={`Consulte a versão operacional ${CURRENT_PORTFOLIO_VERSION} para atividades e modos de execução.`} />;
  }
  return (
    <ol className="relative space-y-4">
      {process.map((step, index) => {
        const mode = executionMode(step.mode);
        return (
          <li key={`${index}-${step.name}`} className="relative grid gap-3 pl-12 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
            {index < process.length - 1 ? <span className="absolute bottom-[-1rem] left-[1.15rem] top-10 w-px bg-[rgb(var(--line))]" aria-hidden="true" /> : null}
            <span className="absolute left-0 top-0 flex h-9 w-9 items-center justify-center rounded-xl border border-blue-500/35 bg-blue-500/10 text-sm font-semibold text-blue-200">{index + 1}</span>
            <div className="min-w-0 rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4">
              <h3 className="text-sm font-semibold text-ink">{step.name}</h3>
              {!compact ? (
                <ul className="mt-3 grid gap-2 text-sm leading-6 text-[rgb(var(--muted))] md:grid-cols-2">
                  {step.activities.map((activity) => <li key={activity} className="flex gap-2"><CircleDot className="mt-2 h-2.5 w-2.5 shrink-0 text-blue-400" /> <span>{activity}</span></li>)}
                </ul>
              ) : <p className="mt-2 text-sm text-[rgb(var(--muted))]">{step.activities.length} atividades previstas</p>}
            </div>
            <span className={`inline-flex min-h-8 items-center self-start rounded-full border px-3 text-xs font-semibold ${mode.className}`} title={mode.detail}>{mode.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function OfferingCard({ offering }: { offering: ServiceOffering }) {
  const process = offering.definition.process || [];
  const deliverables = offering.definition.deliverable_templates || [];
  return (
    <article className="panel interactive-card flex min-h-[330px] flex-col overflow-hidden">
      <div className="h-1 bg-gradient-to-r from-blue-500 via-cyan-400 to-transparent" aria-hidden="true" />
      <div className="flex flex-1 flex-col p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-300">{offering.definition.journey_stage || offering.category.replaceAll("_", " ")}</p>
            <h2 className="mt-2 text-xl font-semibold leading-7 text-ink">{offering.name}</h2>
          </div>
          <span className="shrink-0 rounded-full border border-line bg-[rgb(var(--panel-soft))] px-2.5 py-1 text-xs text-[rgb(var(--muted))]">v{offering.version}</span>
        </div>
        <p className="mt-3 readable-copy text-sm text-[rgb(var(--muted))]">{offering.description}</p>
        <dl className="mt-5 grid grid-cols-3 gap-2">
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-3"><dt className="text-xs text-[rgb(var(--muted))]">Prazo</dt><dd className="mt-1 text-sm font-semibold text-ink">{offering.duration_label}</dd></div>
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-3"><dt className="text-xs text-[rgb(var(--muted))]">Etapas</dt><dd className="mt-1 text-sm font-semibold text-ink">{process.length || offering.definition.stages?.length || 0}</dd></div>
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-3"><dt className="text-xs text-[rgb(var(--muted))]">Entregáveis</dt><dd className="mt-1 text-sm font-semibold text-ink">{deliverables.length || offering.definition.deliverables?.length || 0}</dd></div>
        </dl>
        <div className="mt-auto pt-5">
          <Link href={`/service-catalog/${offering.version_id}`} className="inline-flex min-h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition-colors duration-200 hover:bg-blue-500">
            Ver fluxo completo <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </article>
  );
}

function PortfolioOperatingModel({ offerings }: { offerings: ServiceOffering[] }) {
  const byCode = new Map(offerings.map((offering) => [offering.code, offering]));
  return (
    <Surface className="overflow-hidden">
      <div className="border-b border-line px-5 py-5 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-300">Jornada modular</p>
        <h2 className="mt-2 text-xl font-semibold">Opere uma oferta, várias em paralelo ou uma sequência completa</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-[rgb(var(--muted))]">Cada engajamento preserva a autonomia dos agentes e o isolamento do cliente. Uma oferta só espera outra quando o contrato ou o owner registra uma dependência.</p>
      </div>
      <div className="grid gap-px bg-[rgb(var(--line))] lg:grid-cols-5">
        {PORTFOLIO_LANES.map((lane, index) => (
          <section key={lane.label} className="relative bg-[rgb(var(--panel))] p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-500/10 text-xs font-semibold text-blue-200">{index + 1}</span>
              {index < PORTFOLIO_LANES.length - 1 ? <ArrowRight className="h-4 w-4 text-blue-400/70" aria-hidden="true" /> : <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />}
            </div>
            <h3 className="mt-3 text-sm font-semibold text-ink">{lane.label}</h3>
            <p className="mt-1 min-h-12 text-xs leading-5 text-[rgb(var(--muted))]">{lane.description}</p>
            <div className="mt-4 space-y-2">
              {lane.codes.map((code) => {
                const offering = byCode.get(code);
                return offering ? <Link key={code} href={`/service-catalog/${offering.version_id}`} className="flex min-h-12 items-center justify-between gap-2 rounded-xl border border-line bg-[rgb(var(--panel-soft))] px-3 text-xs font-semibold transition-colors hover:border-blue-500/50"><span>{offering.name}</span><ArrowRight className="h-3.5 w-3.5 shrink-0 text-blue-400" /></Link> : null;
              })}
            </div>
          </section>
        ))}
      </div>
      <div className="grid gap-3 border-t border-line p-5 sm:grid-cols-3 sm:p-6">
        <div className="rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="flex items-center gap-2 text-sm font-semibold"><Bot className="h-4 w-4 text-violet-400" /> Autonomia por serviço</div><p className="mt-2 text-xs leading-5 text-[rgb(var(--muted))]">Equipe curada, budget, artifacts e estado próprios.</p></div>
        <div className="rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="flex items-center gap-2 text-sm font-semibold"><Layers3 className="h-4 w-4 text-blue-400" /> Paralelismo controlado</div><p className="mt-2 text-xs leading-5 text-[rgb(var(--muted))]">WIP e fairness evitam que um cliente monopolize a fábrica.</p></div>
        <div className="rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="flex items-center gap-2 text-sm font-semibold"><LockKeyhole className="h-4 w-4 text-emerald-400" /> Dependência explícita</div><p className="mt-2 text-xs leading-5 text-[rgb(var(--muted))]">Outputs são compartilhados apenas no mesmo tenant e quando autorizados.</p></div>
      </div>
    </Surface>
  );
}

export function ServiceCatalogView() {
  const { data, error, refresh } = useResource(async () => {
    const offerings = await apiGet<ServiceOffering[]>("/api/v1/service-catalog/offerings");
    let readiness: ReadinessSummary | null = null;
    try {
      readiness = await apiGet<ReadinessSummary>(`/api/v1/service-catalog/versions/${CURRENT_PORTFOLIO_VERSION}/readiness`);
    } catch {
      // Readiness is supporting operational information. Its failure must not
      // hide the contracted service definitions.
    }
    return { offerings, readiness };
  });
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Carregando catálogo operacional…" />;
  const currentOfferings = data.offerings.filter((offering) => offering.version === CURRENT_PORTFOLIO_VERSION);
  const historicalOfferings = data.offerings.filter((offering) => offering.version !== CURRENT_PORTFOLIO_VERSION);
  return <div className="space-y-6">
    <PageHeader eyebrow="Portfólio de IA" title="Produtos e serviços" description="Escolha uma oferta para entender, em linguagem clara, o que acontece em cada etapa, quem participa, o que será entregue e como o VP valida a conclusão." actions={<RefreshButton onClick={refresh} />} />
    <Surface className="overflow-hidden">
      <div className="border-b border-line px-5 py-4 sm:px-6"><h2 className="section-heading">Da oportunidade à operação contínua</h2><p className="mt-1 text-sm text-[rgb(var(--muted))]">As oito ofertas cobrem a jornada corporativa completa e podem operar em paralelo por cliente.</p></div>
      <div className="grid gap-px bg-[rgb(var(--line))] sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">{PORTFOLIO_JOURNEY.map((stage, index) => <div key={stage} className="relative min-h-28 bg-[rgb(var(--panel))] p-4"><div className="text-xs font-semibold text-blue-400">ETAPA {String(index + 1).padStart(2, "0")}</div><div className="mt-2 text-sm font-semibold leading-6">{stage}</div>{index < PORTFOLIO_JOURNEY.length - 1 ? <ArrowRight className="absolute bottom-3 right-3 h-4 w-4 text-blue-400/70" /> : <CheckCircle2 className="absolute bottom-3 right-3 h-4 w-4 text-emerald-400" />}</div>)}</div>
    </Surface>
    <PortfolioOperatingModel offerings={currentOfferings} />
    {data.readiness ? <Surface className="p-5 sm:p-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="section-heading">Situação da versão {CURRENT_PORTFOLIO_VERSION}</h2><p className="mt-1 max-w-3xl text-sm text-[rgb(var(--muted))]">Este indicador é operacional e não altera o conteúdo das ofertas. A promoção exige evidências reais e decisão humana.</p></div><div className="flex gap-2"><StatusBadge status={data.readiness.internal_assisted_pilot_ready ? "ready" : "candidate"} /><StatusBadge status={data.readiness.market_ready ? "market_ready" : "market_blocked"} /></div></div><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Ofertas homologadas" value={`${data.readiness.offerings.filter((item) => item.passed).length}/8`} /><MetricCard label="Relatórios aprovados" value={`${data.readiness.validation_reports.filter((item) => item.passed).length}/${data.readiness.validation_reports.length}`} /><MetricCard label="Tenants validados" value={data.readiness.homologation_tenant_count} /><MetricCard label="Bloqueios de mercado" value={data.readiness.market_blockers.length} /></div></Surface> : <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-100">O catálogo está disponível, mas o resumo de homologação não respondeu. Atualize para consultar os gates sem perder o conteúdo abaixo.</div>}
    <section aria-labelledby="current-offerings-heading">
      <div className="mb-4"><h2 id="current-offerings-heading" className="text-xl font-semibold text-ink">Escolha uma oferta</h2><p className="mt-1 text-sm text-[rgb(var(--muted))]">Versão {CURRENT_PORTFOLIO_VERSION} candidata à operação assistida.</p></div>
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {currentOfferings.map((offering) => <OfferingCard key={offering.version_id} offering={offering} />)}
      </div>
    </section>
    {historicalOfferings.length ? <details className="panel overflow-hidden"><summary className="flex min-h-16 cursor-pointer items-center justify-between gap-3 px-5 py-4 text-sm font-semibold"><span>Versões históricas preservadas</span><span className="flex items-center gap-2 text-xs font-normal text-[rgb(var(--muted))]">{historicalOfferings.length} registros <ChevronDown className="h-4 w-4" /></span></summary><div className="border-t border-line p-5"><p className="mb-4 text-sm text-[rgb(var(--muted))]">Disponíveis para contratos históricos; novos engajamentos devem usar a versão contratada.</p><div className="grid gap-2 md:grid-cols-2">{historicalOfferings.map((offering) => <Link key={offering.version_id} href={`/service-catalog/${offering.version_id}`} className="flex min-h-14 items-center justify-between rounded-xl border border-line bg-[rgb(var(--panel-soft))] px-4 text-sm transition-colors hover:border-blue-500/40"><span>{offering.name}</span><span className="text-xs text-[rgb(var(--muted))]">v{offering.version}</span></Link>)}</div></div></details> : null}
  </div>;
}

export function ServiceOfferingWorkspace({ offeringId }: { offeringId: string }) {
  const { data, error, refresh } = useResource(() => apiGet<ServiceOffering[]>("/api/v1/service-catalog/offerings"), [offeringId]);
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Abrindo o fluxo completo da oferta…" />;
  const offering = data.find((item) => item.version_id === offeringId) || data.find((item) => item.code === offeringId && item.version === CURRENT_PORTFOLIO_VERSION);
  if (!offering) return <ErrorState message="A oferta solicitada não existe ou não está disponível para este usuário." onRetry={refresh} />;
  const deliverables = offering.definition.deliverable_templates || [];
  const specificDod = offering.definition.definition_of_done || [];
  const corporateDod = offering.definition.corporate_definition_of_done || [];
  const team = offering.definition.team || [];
  const canStart = ["active", "candidate"].includes(offering.version_status);
  return <div className="space-y-6">
    <Link href="/service-catalog" className="inline-flex min-h-11 items-center gap-2 rounded-lg text-sm font-semibold text-blue-300 hover:text-blue-200"><ArrowLeft className="h-4 w-4" /> Voltar ao portfólio</Link>
    <Surface className="overflow-hidden">
      <div className="h-1.5 bg-gradient-to-r from-blue-500 via-cyan-400 to-transparent" />
      <div className="p-5 sm:p-7 lg:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-4xl">
            <div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-200">{offering.definition.journey_stage}</span><StatusBadge status={offering.version_status} /></div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">{offering.name}</h1>
            <p className="mt-4 readable-copy text-base text-[rgb(var(--muted))]">{offering.description}</p>
          </div>
          {canStart ? <Link href={`/engagements?offering=${offering.version_id}`} className="inline-flex min-h-12 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-xl bg-orange-500 px-5 text-sm font-semibold text-[#170A02] transition-colors hover:bg-orange-400">Iniciar este serviço <ArrowRight className="h-4 w-4" /></Link> : <span className="inline-flex min-h-12 shrink-0 items-center rounded-xl border border-line px-4 text-sm text-[rgb(var(--muted))]">Versão histórica para consulta e replay</span>}
        </div>
        <dl className="mt-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-4"><dt className="flex items-center gap-2 text-xs text-[rgb(var(--muted))]"><Timer className="h-4 w-4" /> Duração</dt><dd className="mt-2 text-base font-semibold">{offering.duration_label}</dd></div>
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-4"><dt className="flex items-center gap-2 text-xs text-[rgb(var(--muted))]"><Layers3 className="h-4 w-4" /> Etapas</dt><dd className="mt-2 text-base font-semibold">{offering.definition.process?.length || 0}</dd></div>
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-4"><dt className="flex items-center gap-2 text-xs text-[rgb(var(--muted))]"><FileStack className="h-4 w-4" /> Entregáveis</dt><dd className="mt-2 text-base font-semibold">{deliverables.length}</dd></div>
          <div className="rounded-xl bg-[rgb(var(--panel-soft))] p-4"><dt className="flex items-center gap-2 text-xs text-[rgb(var(--muted))]"><UserCheck className="h-4 w-4" /> Aprovação</dt><dd className="mt-2 text-base font-semibold">Owner + VP</dd></div>
        </dl>
      </div>
    </Surface>

    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,.55fr)]">
      <Surface className="p-5 sm:p-6"><div className="mb-6"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-300">Processo de execução</p><h2 className="mt-2 text-xl font-semibold">O que acontece, passo a passo</h2><p className="mt-2 text-sm text-[rgb(var(--muted))]">Cada atividade gera evidência; ações humanas e integrações nunca são declaradas concluídas apenas pela IA.</p></div><OfferingProcessFlow offering={offering} /></Surface>
      <div className="space-y-5">
        <Surface className="p-5"><h2 className="section-heading">Equipe responsável</h2><div className="mt-4 space-y-2">{team.map((role) => <div key={role} className="flex min-h-11 items-center gap-3 rounded-xl bg-[rgb(var(--panel-soft))] px-3 text-sm"><Users className="h-4 w-4 shrink-0 text-blue-400" /><span>{roleLabel(role)}</span></div>)}</div><div className="mt-3 flex min-h-11 items-center gap-3 rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-3 text-sm"><Handshake className="h-4 w-4 text-emerald-400" /><span>VP aprova os gates e a entrega</span></div></Surface>
        <Surface className="p-5"><h2 className="section-heading">Como a execução é controlada</h2><div className="mt-4 space-y-3">{Object.values(EXECUTION_MODE).map((mode) => <div key={mode.label}><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${mode.className}`}>{mode.label}</span><p className="mt-1 text-sm leading-6 text-[rgb(var(--muted))]">{mode.detail}</p></div>)}</div></Surface>
      </div>
    </div>

    <Surface className="overflow-hidden">
      <div className="border-b border-line px-5 py-5 sm:px-6"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-300">Saídas concretas</p><h2 className="mt-2 text-xl font-semibold">Entregáveis incluídos</h2><p className="mt-1 text-sm text-[rgb(var(--muted))]">Abra cada item para conferir formato, responsável, evidências e critérios de aceite.</p></div>
      <div className="divide-y divide-line">{deliverables.map((item, index) => <details key={item.key} className="group"><summary className="grid min-h-20 cursor-pointer list-none gap-3 px-5 py-4 sm:grid-cols-[42px_minmax(0,1fr)_auto] sm:items-center sm:px-6"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500/10 text-sm font-semibold text-blue-200">{index + 1}</span><span><span className="block text-sm font-semibold text-ink">{item.title}</span><span className="mt-1 block text-xs text-[rgb(var(--muted))]">{roleLabel(item.responsible)} · aprovação por {roleLabel(item.approver_role)}</span></span><span className="flex items-center gap-2"><span className="hidden flex-wrap justify-end gap-1 sm:flex">{item.formats.map((format) => <span key={format} className="rounded-full border border-line px-2 py-1 text-[10px] uppercase text-[rgb(var(--muted))]">{format}</span>)}</span><ChevronDown className="h-4 w-4 text-blue-400 transition-transform group-open:rotate-180" /></span></summary><div className="grid gap-5 bg-[rgb(var(--panel-soft))] px-5 py-5 sm:px-6 lg:grid-cols-3"><div><h3 className="text-xs font-semibold">Seções obrigatórias</h3><ul className="mt-2 space-y-2 text-sm text-[rgb(var(--muted))]">{item.required_sections?.map((value) => <li key={value}>• {value}</li>)}</ul></div><div><h3 className="text-xs font-semibold">Evidências exigidas</h3><ul className="mt-2 space-y-2 text-sm text-[rgb(var(--muted))]">{item.required_evidence?.map((value) => <li key={value}>• {value.replaceAll("_", " ")}</li>)}</ul></div><div><h3 className="text-xs font-semibold">Critérios de aceite</h3><ul className="mt-2 space-y-2 text-sm text-[rgb(var(--muted))]">{item.acceptance_criteria.map((value) => <li key={value}>• {value}</li>)}</ul></div></div></details>)}</div>
    </Surface>

    <div className="grid gap-6 xl:grid-cols-2">
      <Surface className="p-5 sm:p-6"><div className="flex items-center gap-3"><ListChecks className="h-5 w-5 text-emerald-400" /><h2 className="section-heading">Definition of Done da oferta</h2></div><ol className="mt-5 space-y-3">{specificDod.map((item, index) => <li key={item} className="flex gap-3 text-sm leading-6"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/10 text-xs font-semibold text-emerald-300">{index + 1}</span><span>{item}</span></li>)}</ol></Surface>
      <Surface className="p-5 sm:p-6"><div className="flex items-center gap-3"><ClipboardCheck className="h-5 w-5 text-blue-400" /><h2 className="section-heading">Definition of Done corporativo</h2></div><ol className="mt-5 space-y-3">{corporateDod.map((item, index) => <li key={item} className="flex gap-3 text-sm leading-6"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/10 text-xs font-semibold text-blue-200">{index + 1}</span><span>{item}</span></li>)}</ol></Surface>
    </div>

    {offering.definition.portfolio_commitment ? <Surface className="border-blue-500/30 p-5 sm:p-6"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-300">Compromisso da oferta</p><blockquote className="mt-3 max-w-5xl text-lg font-medium leading-8 text-ink">“{offering.definition.portfolio_commitment}”</blockquote>{offering.definition.external_constraints?.length ? <details className="mt-4 border-t border-line pt-3"><summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold text-[rgb(var(--muted))]">Ver fatores externos que exigem registro e mitigação</summary><ul className="grid gap-2 text-sm text-[rgb(var(--muted))] sm:grid-cols-2">{offering.definition.external_constraints.map((item) => <li key={item}>• {item}</li>)}</ul></details> : null}</Surface> : null}
    <div className="flex justify-end">{canStart ? <Link href={`/engagements?offering=${offering.version_id}`} className="inline-flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-xl bg-orange-500 px-5 text-sm font-semibold text-[#170A02] transition-colors hover:bg-orange-400">Iniciar este serviço <ArrowRight className="h-4 w-4" /></Link> : null}</div>
  </div>;
}

export function ClientsView() {
  const { data, error, refresh } = useResource(() => apiGet<ServicePortfolio>("/api/v1/operator/service-portfolio"));
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Carregando carteira autorizada…" />;
  const totalRisk = data.clients.reduce((sum, item) => sum + item.deliverables_at_risk, 0);
  const totalReview = data.clients.reduce((sum, item) => sum + item.deliverables_in_review, 0);
  return <div className="space-y-6"><PageHeader eyebrow="Carteira autorizada" title="Clientes" description="Resumo operacional por membership; nenhum conteúdo de negócio ou conhecimento é agregado entre tenants." actions={<RefreshButton onClick={refresh} />} />
    <div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Clientes acessíveis" value={data.clients.length} icon={<Users className="h-5 w-5" />} /><MetricCard label="Entregáveis em risco" value={totalRisk} icon={<AlertTriangle className="h-5 w-5" />} /><MetricCard label="Aguardando revisão" value={totalReview} icon={<ClipboardCheck className="h-5 w-5" />} /></div>
    {data.clients.length ? <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">{data.clients.map((client) => <Surface key={client.tenant_id} className="p-5"><div className="flex items-start justify-between gap-3"><div><h2 className="text-base font-semibold">{client.tenant_name}</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">{client.contracted_offerings} ofertas · {client.active_engagements} engajamentos ativos</p></div>{client.deliverables_at_risk ? <span className="rounded-full bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-300">{client.deliverables_at_risk} EM RISCO</span> : <span className="rounded-full bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-300">SEM ATRASO</span>}</div><div className="mt-5 grid grid-cols-3 gap-2"><div className="rounded-lg bg-[rgb(var(--panel-soft))] p-3"><div className="text-lg font-semibold">{client.active_work_items}</div><div className="text-[10px] text-[rgb(var(--muted))]">WIP</div></div><div className="rounded-lg bg-[rgb(var(--panel-soft))] p-3"><div className="text-lg font-semibold">{client.deliverables_in_review}</div><div className="text-[10px] text-[rgb(var(--muted))]">revisões</div></div><div className="rounded-lg bg-[rgb(var(--panel-soft))] p-3"><div className="text-lg font-semibold">{client.latest_hrs == null ? "—" : Math.round(client.latest_hrs)}</div><div className="text-[10px] text-[rgb(var(--muted))]">HRS</div></div></div><div className="mt-4 min-h-14 rounded-lg border border-line p-3"><div className="text-[10px] uppercase tracking-wide text-[rgb(var(--muted))]">Próximo compromisso</div><div className="mt-1 text-xs font-semibold">{client.next_commitment?.title || "Sem compromisso pendente"}</div></div><Link href={`/clients/${client.tenant_id}`} className="mt-4 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white">Abrir Cliente 360 <ArrowRight className="h-4 w-4" /></Link></Surface>)}</div> : <EmptyState title="Nenhum cliente acessível" description="Conclua o onboarding e atribua membership operacional ao usuário." />}
  </div>;
}

const ENGAGEMENT_PHASES = [
  { key: "plan", label: "1. Plano", description: "Escopo e contexto" },
  { key: "approval", label: "2. Aprovação", description: "Decisão do VP" },
  { key: "execution", label: "3. Execução", description: "Agentes e atividades" },
  { key: "deliverables", label: "4. Entregáveis", description: "Revisão e evidências" },
  { key: "acceptance", label: "5. Aceite e entrega", description: "Decisão final e pacote" },
] as const;

function engagementPhase(engagement: Engagement): (typeof ENGAGEMENT_PHASES)[number]["key"] {
  if (["completed", "delivered", "closed"].includes(engagement.status)) return "acceptance";
  if (
    engagement.counts?.deliverables
    && engagement.counts.deliverables_completed >= engagement.counts.deliverables
    && engagement.counts.acceptance_checks_total
    && engagement.counts.acceptance_checks_pending === 0
  ) return "acceptance";
  if (
    engagement.counts?.deliverables_in_review
    || engagement.counts?.deliverables_completed
  ) return "deliverables";
  if (engagement.status === "active") return "execution";
  if (engagement.status === "awaiting_approval" || engagement.latest_plan?.status === "draft") return "approval";
  return "plan";
}

export function EngagementsView({ initialOfferingId = "" }: { initialOfferingId?: string }) {
  const { data, error, refresh, setError } = useResource(async () => {
    const [engagements, offerings, contracts, programs] = await Promise.all([
      apiGet<Engagement[]>("/api/v1/engagements"),
      apiGet<ServiceOffering[]>("/api/v1/service-catalog/offerings"),
      apiGet<Contract[]>("/api/v1/contracts"),
      apiGet<Program[]>("/api/v1/programs"),
    ]);
    return { engagements, offerings, contracts, programs };
  });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [contractId, setContractId] = useState("");
  const [offeringId, setOfferingId] = useState(initialOfferingId);
  const [programId, setProgramId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [creating, setCreating] = useState(Boolean(initialOfferingId));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await apiPost("/api/v1/engagements", {
        contract_id: contractId,
        offering_version_id: offeringId,
        program_id: programId || null,
        name,
        description,
        success_criteria: [],
        service_levels: {},
      }, { idempotencyKey: commandKey("engagement-create") });
      setName(""); setDescription("");
      setCreating(false);
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao criar engajamento");
    } finally { setSubmitting(false); }
  }

  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Carregando engajamentos…" />;
  return <div className="space-y-6">
    <PageHeader eyebrow="Serviços em operação" title="Engajamentos" description="Acompanhe cada serviço contratado do plano à entrega. Abra um engajamento para ver a etapa atual e a próxima ação segura." actions={<><RefreshButton onClick={refresh} /><button type="button" onClick={() => setCreating((value) => !value)} className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#170A02] transition-colors hover:bg-orange-400"><BriefcaseBusiness className="h-4 w-4" />{creating ? "Fechar formulário" : "Novo engajamento"}</button></>} />
    {error ? <ErrorState message={error} /> : null}
    <div className={`grid gap-5 ${creating ? "2xl:grid-cols-[420px_minmax(0,1fr)]" : ""}`}>
      {creating ? <Surface className="p-5"><h2 className="text-base font-semibold text-ink">Configurar novo engajamento</h2><p className="mt-1 text-sm leading-6 text-[rgb(var(--muted))]">Primeiro criamos o rascunho. O plano, a aprovação do VP e a ativação acontecem depois, sem pular etapas.</p>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="grid gap-2 text-sm"><span className="font-medium">Nome</span><input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Ex.: Discovery — Operações 2026" /></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Oferta</span><select required value={offeringId} onChange={(event) => setOfferingId(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="">Selecione</option>{data.offerings.filter((item) => ["active", "candidate"].includes(item.version_status)).map((item) => <option key={item.version_id} value={item.version_id}>{item.name} · v{item.version} · {item.version_status}</option>)}</select></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Contrato</span><select required value={contractId} onChange={(event) => setContractId(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="">Selecione</option>{data.contracts.map((item) => <option key={item.id} value={item.id}>{item.contract_number} · {item.status}</option>)}</select></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Programa</span><select value={programId} onChange={(event) => setProgramId(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="">Sem programa</option>{data.programs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Contexto</span><textarea rows={5} maxLength={10_000} value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-lg border px-3 py-3" placeholder="Objetivo, áreas, restrições e resultado esperado" /></label>
          <button disabled={submitting} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-60"><BriefcaseBusiness className="h-4 w-4" />{submitting ? "Registrando…" : "Criar rascunho"}</button>
        </form>
      </Surface> : null}
      <Surface className="overflow-hidden">
        <div className="border-b border-line px-5 py-4 sm:px-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="section-heading">Portfólio em operação</h2><p className="mt-1 text-sm text-[rgb(var(--muted))]">Cada cartão é uma trilha autônoma. Serviços diferentes avançam em paralelo sem misturar agentes, artifacts ou aprovações.</p></div><span className="rounded-full border border-line bg-[rgb(var(--panel-soft))] px-3 py-1.5 text-xs text-[rgb(var(--muted))]">{data.engagements.length} serviços</span></div></div>
        {data.engagements.length ? <div className="grid gap-px bg-[rgb(var(--line))] md:grid-cols-2 xl:grid-cols-5">{ENGAGEMENT_PHASES.map((phase) => {
          const items = data.engagements.filter((item) => engagementPhase(item) === phase.key);
          return <section key={phase.key} className="min-h-52 bg-[rgb(var(--panel))] p-4"><div className="flex items-center justify-between gap-2"><div><h3 className="text-sm font-semibold">{phase.label}</h3><p className="mt-1 text-xs text-[rgb(var(--muted))]">{phase.description}</p></div><span className="flex h-7 min-w-7 items-center justify-center rounded-full bg-[rgb(var(--panel-soft))] px-2 text-xs font-semibold">{items.length}</span></div><div className="mt-4 space-y-3">{items.map((item) => <Link key={item.id} href={`/engagements/${item.id}`} className="interactive-card block rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="flex items-start justify-between gap-2"><h4 className="text-sm font-semibold leading-5">{item.name}</h4><ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-blue-400" /></div><p className="mt-2 text-xs leading-5 text-[rgb(var(--muted))]">{item.offering?.name || "Oferta contratada"}</p><div className="mt-3 flex flex-wrap items-center gap-2"><StatusBadge status={item.status} /><span className="text-[10px] text-[rgb(var(--muted))]">{item.counts?.deliverables || 0} entregáveis</span><span className="text-[10px] text-[rgb(var(--muted))]">{item.counts?.agent_assignments || 0} agentes</span></div></Link>)}{!items.length ? <div className="rounded-xl border border-dashed border-line p-4 text-center text-xs leading-5 text-[rgb(var(--muted))]">Nenhum serviço nesta fase.</div> : null}</div></section>;
        })}</div> : <div className="p-5"><EmptyState title="Nenhum engajamento" description="Selecione uma oferta e um contrato para estruturar a primeira operação deste cliente." action={<button type="button" onClick={() => setCreating(true)} className="min-h-11 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white">Criar primeiro engajamento</button>} /></div>}
      </Surface>
    </div>
  </div>;
}

export function ClientWorkspace({ tenantId }: { tenantId: string }) {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [data, setData] = useState<ClientOverview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getBrowserSession().then(async (value) => {
      setSession(value);
      if (!value.tenants.some((tenant) => tenant.id === tenantId)) throw new Error("Você não possui membership neste cliente.");
      if (value.active_tenant_id !== tenantId) {
        const response = await fetch("/auth/tenant", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tenant_id: tenantId }) });
        if (!response.ok) throw new Error("Não foi possível selecionar o cliente.");
        window.location.reload();
        return;
      }
      setData(await apiGet<ClientOverview>("/api/v1/client-operations/overview"));
    }).catch((reason: Error) => setError(reason.message));
  }, [tenantId]);
  if (error) return <ErrorState message={error} />;
  if (!session || !data) return <LoadingState label="Validando membership e selecionando o tenant…" />;
  const tenant = session.tenants.find((item) => item.id === tenantId);
  return <div className="space-y-6">
    <PageHeader eyebrow="Cliente 360" title={tenant?.name || tenantId} description="Contratos, serviços, entregáveis, conhecimento e ações consultados somente após ativação segura deste tenant." actions={<Link href="/engagements" className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14]"><Sparkles className="h-4 w-4" /> Novo engajamento</Link>} />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Engajamentos ativos" value={data.summary.active_engagements} icon={<BriefcaseBusiness className="h-5 w-5" />} /><MetricCard label="Entregáveis" value={data.summary.deliverables} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard label="Em revisão" value={data.summary.deliverables_in_review} icon={<ClipboardCheck className="h-5 w-5" />} /><MetricCard label="WIP ativo" value={data.summary.active_work_items} icon={<Gauge className="h-5 w-5" />} /></div>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(330px,.6fr)]"><Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Jornada de serviços</h2></div>{data.engagements.length ? <div className="divide-y divide-line">{data.engagements.map((item) => <Link key={item.id} href={`/engagements/${item.id}`} className="flex min-h-20 items-center justify-between gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))]"><div><div className="text-sm font-semibold">{item.name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{item.offering?.name} · {item.counts?.deliverables_completed || 0}/{item.counts?.deliverables || 0} entregáveis concluídos</div></div><div className="flex items-center gap-3"><StatusBadge status={item.status} /><ArrowRight className="h-4 w-4 text-blue-400" /></div></Link>)}</div> : <div className="p-5"><EmptyState title="Sem serviços ativos" description="Crie um engajamento a partir do catálogo contratado." /></div>}</Surface><div className="space-y-5"><Surface className="p-5"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Governança</h2><LockKeyhole className="h-4 w-4 text-emerald-400" /></div><dl className="mt-4 space-y-3 text-xs"><div className="flex justify-between"><dt className="text-[rgb(var(--muted))]">Contratos</dt><dd className="font-semibold">{data.contracts.length}</dd></div><div className="flex justify-between"><dt className="text-[rgb(var(--muted))]">Programas</dt><dd className="font-semibold">{data.programs.length}</dd></div><div className="flex justify-between"><dt className="text-[rgb(var(--muted))]">Métricas de resultado</dt><dd className="font-semibold">{data.outcomes.length}</dd></div></dl></Surface><Surface className="p-5"><h2 className="text-sm font-semibold">Próximas entregas</h2><div className="mt-3 space-y-2">{data.deliverables.filter((item) => !["approved", "delivered"].includes(item.status)).slice(0, 5).map((item) => <Link key={item.id} href={`/deliverables/${item.id}`} className="block rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="text-xs font-semibold">{item.title}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{item.due_at ? fmtDate(item.due_at) : "Sem prazo"}</div></Link>)}{!data.deliverables.length ? <p className="text-xs text-[rgb(var(--muted))]">Nenhum entregável materializado.</p> : null}</div></Surface></div></div>
  </div>;
}

function EngagementTeamAndOutcomes({ data, refresh, reportError, canManage }: { data: EngagementWorkspaceData; refresh: () => void; reportError: (message: string) => void; canManage: boolean }) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const [baseline, setBaseline] = useState("");
  const [target, setTarget] = useState("");
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);

  async function createOutcome(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    reportError("");
    try {
      await apiPost(`/api/v1/engagements/${data.id}/outcomes`, {
        name,
        unit,
        baseline_value: baseline === "" ? null : Number(baseline),
        target_value: target === "" ? null : Number(target),
        current_value: null,
        provenance: "real",
        source_refs: [source],
        observed_at: null,
      }, { idempotencyKey: commandKey("outcome-create") });
      setName(""); setUnit(""); setBaseline(""); setTarget(""); setSource("");
      refresh();
    } catch (reason) {
      reportError(reason instanceof Error ? reason.message : "Falha ao registrar a métrica");
    } finally {
      setBusy(false);
    }
  }

  return <div className={`grid gap-5 ${canManage ? "xl:grid-cols-[minmax(0,1.25fr)_minmax(330px,.75fr)]" : ""}`}>
    <div className="space-y-5">
      <Surface className="p-5"><div className="flex items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">Resultados e valor realizado</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Baseline, meta, observação e proveniência permanecem auditáveis.</p></div><Provenance value="real" /></div>{data.outcomes.length ? <div className="mt-4 grid gap-3 md:grid-cols-2">{data.outcomes.map((metric) => <div key={metric.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="text-xs font-semibold">{metric.name}</div><div className="mt-2 text-xl font-semibold">{metric.current_value ?? "—"} <span className="text-xs font-normal text-[rgb(var(--muted))]">{metric.unit}</span></div><div className="mt-2 text-[10px] text-[rgb(var(--muted))]">baseline {metric.baseline_value ?? "—"} · meta {metric.target_value ?? "—"} · {metric.provenance}</div></div>)}</div> : <EmptyState title="Nenhum resultado registrado" description="Cadastre a baseline e a meta antes de declarar valor realizado." />}</Surface>
      <Surface className="p-5"><h2 className="text-sm font-semibold">Equipe AI aprovada</h2><div className="mt-4 grid gap-3 md:grid-cols-2">{data.agent_assignments.length ? data.agent_assignments.map((assignment) => <div key={assignment.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="text-xs font-semibold">{assignment.agent?.name || "Versão aprovada"}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{assignment.agent?.code} · v{assignment.agent?.version} · US$ {assignment.ai_budget_usd.toFixed(2)}</div></div>) : <p className="text-xs text-[rgb(var(--muted))]">Nenhum agente alocado.</p>}</div></Surface>
    </div>
    {canManage ? <Surface className="p-5"><h2 className="text-sm font-semibold">Nova métrica</h2><form onSubmit={createOutcome} className="mt-4 space-y-3"><input required value={name} onChange={(event) => setName(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Nome da métrica" /><div className="grid grid-cols-2 gap-3"><input value={baseline} onChange={(event) => setBaseline(event.target.value)} type="number" step="any" className="min-h-11 rounded-lg border px-3 text-sm" placeholder="Baseline" /><input value={target} onChange={(event) => setTarget(event.target.value)} type="number" step="any" className="min-h-11 rounded-lg border px-3 text-sm" placeholder="Meta" /></div><input required value={unit} onChange={(event) => setUnit(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Unidade" /><input required value={source} onChange={(event) => setSource(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Referência da fonte" /><button disabled={busy} className="min-h-11 w-full rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Registrando…" : "Registrar baseline"}</button></form></Surface> : null}
  </div>;
}

function AcceptanceCheckActions({
  check,
  canOperate,
  canDecide,
  disabled,
  onEvidence,
  onDecision,
}: {
  check: ServiceAcceptanceCheck;
  canOperate: boolean;
  canDecide: boolean;
  disabled: boolean;
  onEvidence: (check: ServiceAcceptanceCheck, refs: string[], external: boolean, impact: string, mitigation: string) => void;
  onDecision: (check: ServiceAcceptanceCheck, decision: "approve" | "reject" | "external_constraint", comment: string) => void;
}) {
  const [refs, setRefs] = useState("");
  const [external, setExternal] = useState(false);
  const [impact, setImpact] = useState("");
  const [mitigation, setMitigation] = useState("");
  const [comment, setComment] = useState("");
  const evidenceRefs = refs.split(",").map((item) => item.trim()).filter(Boolean);
  const evidenceReady = evidenceRefs.length > 0 && (!external || (impact.trim().length >= 5 && mitigation.trim().length >= 5));
  const decisionReady = comment.trim().length >= 10;

  if (canOperate && ["pending", "failed"].includes(check.status)) {
    return <div className="mt-4 rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="text-xs font-semibold">Evidência do owner</div><p className="mt-1 text-[11px] text-[rgb(var(--muted))]">Registre IDs ou referências verificáveis; o VP decidirá em seguida.</p><input value={refs} onChange={(event) => setRefs(event.target.value)} className="mt-3 min-h-11 w-full rounded-lg border px-3 text-xs" placeholder="artifact:…, relatório:…, ata:…" /><label className="mt-3 flex min-h-11 items-center gap-2 text-xs"><input type="checkbox" checked={external} onChange={(event) => setExternal(event.target.checked)} /> Existe restrição externa</label>{external ? <div className="grid gap-2 sm:grid-cols-2"><textarea rows={3} value={impact} onChange={(event) => setImpact(event.target.value)} className="rounded-lg border px-3 py-2 text-xs" placeholder="Impacto comprovado" /><textarea rows={3} value={mitigation} onChange={(event) => setMitigation(event.target.value)} className="rounded-lg border px-3 py-2 text-xs" placeholder="Mitigação ou plano substituto" /></div> : null}<button disabled={disabled || !evidenceReady} onClick={() => onEvidence(check, evidenceRefs, external, impact.trim(), mitigation.trim())} className="mt-3 min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white disabled:opacity-40">Registrar evidência para o VP</button></div>;
  }
  if (canDecide && ["evidence_recorded", "external_constraint_pending"].includes(check.status)) {
    const externalDecision = check.status === "external_constraint_pending";
    return <div className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3"><div className="text-xs font-semibold">Decisão do VP</div><div className="mt-2 flex flex-wrap gap-2 text-[10px] text-[rgb(var(--muted))]">{check.evidence_refs_json.map((item) => <span key={item} className="rounded-full border border-line px-2 py-1">{item}</span>)}</div>{externalDecision ? <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs"><div><span className="font-semibold">Impacto:</span> {check.impact}</div><div className="mt-1"><span className="font-semibold">Mitigação:</span> {check.mitigation}</div></div> : null}<textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} minLength={10} className="mt-3 w-full rounded-lg border px-3 py-2 text-xs" placeholder="Explique a decisão e as condições do aceite…" /><div className="mt-3 flex flex-wrap gap-2"><button disabled={disabled || !decisionReady} onClick={() => onDecision(check, externalDecision ? "external_constraint" : "approve", comment.trim())} className="min-h-11 rounded-lg bg-emerald-500 px-3 text-xs font-semibold text-[#07110A] disabled:opacity-40">{externalDecision ? "Aceitar restrição" : "Aprovar check"}</button><button disabled={disabled || !decisionReady} onClick={() => onDecision(check, "reject", comment.trim())} className="min-h-11 rounded-lg border border-red-500/40 px-3 text-xs text-red-200 disabled:opacity-40">Rejeitar check</button></div></div>;
  }
  return null;
}

function EngagementCockpit({ data, refresh, reportError, role }: { data: EngagementWorkspaceData; refresh: () => void; reportError: (message: string) => void; role: string }) {
  const [busy, setBusy] = useState("");
  const canOperate = ["owner", "super_admin"].includes(role);
  const canDecide = role === "engagement_manager";
  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key); reportError("");
    try { await action(); refresh(); }
    catch (reason) { reportError(reason instanceof Error ? reason.message : "Falha na operação do cockpit"); }
    finally { setBusy(""); }
  };
  const execute = (item: WorkItem) => run(item.id, () => apiPost(`/api/v1/service-work-items/${item.id}/execute`, {
    expected_version: item.record_version, instructions: "Executar conforme plano aprovado e evidências tenant-scoped.", knowledge_base_ids: [],
  }, { idempotencyKey: commandKey("service-execution") }));
  const retry = (execution: ServiceExecution) => run(execution.id, () => apiPost(`/api/v1/service-executions/${execution.id}/retry`, {
    expected_version: execution.record_version, reason: "Retry manual após revisão da evidência de falha.",
  }, { idempotencyKey: commandKey("service-execution-retry") }));
  const cancel = (execution: ServiceExecution) => run(execution.id, () => apiPost(`/api/v1/service-executions/${execution.id}/cancel`, {
    expected_version: execution.record_version, reason: "Cancelamento humano registrado no cockpit.",
  }, { idempotencyKey: commandKey("service-execution-cancel") }));
  const completeExternal = (item: WorkItem, evidenceReference: string) => run(item.id, () => apiPost(`/api/v1/service-work-items/${item.id}/transitions`, {
    status: "completed",
    expected_version: item.record_version,
    reason: evidenceReference.trim(),
    override_reason: "",
  }, { idempotencyKey: commandKey("external-evidence") }));
  const evidence = (check: ServiceAcceptanceCheck, refs: string[], externalConstraint: boolean, impact: string, mitigation: string) => {
    void run(check.id, () => apiPost(`/api/v1/engagements/${data.id}/acceptance-checks/${check.id}/evidence`, {
      expected_version: check.record_version,
      evidence_refs: refs,
      external_constraint: externalConstraint, impact, mitigation,
    }, { idempotencyKey: commandKey("acceptance-evidence") }));
  };
  const decide = (check: ServiceAcceptanceCheck, decision: "approve" | "reject" | "external_constraint", comment: string) => {
    void run(check.id, () => apiPost(`/api/v1/engagements/${data.id}/acceptance-checks/${check.id}/decision`, {
      expected_version: check.record_version, decision, comment,
    }, { idempotencyKey: commandKey("acceptance-decision") }));
  };
  const createCycle = () => {
    const start = new Date();
    const end = new Date(start); end.setMonth(end.getMonth() + 1);
    void run("cycle", () => apiPost(`/api/v1/engagements/${data.id}/cycles`, {
      expected_version: data.record_version, period_start: start.toISOString(), period_end: end.toISOString(),
      comment: "Novo ciclo recorrente autorizado pelo operador.",
    }, { idempotencyKey: commandKey("service-cycle") }));
  };
  const lastCycle = data.cycles.at(-1);
  const canCreateCycle = canOperate && data.offering?.cadence !== "one_off" && Boolean(lastCycle && lastCycle.status === "completed");
  return <div className="space-y-5">
    <Surface className="p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">Fila multi-serviço</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Execução durável por prioridade, prazo e round-robin; os limites globais e por tenant são aplicados no dispatcher.</p></div><div className="flex gap-2"><StatusBadge status={data.dependencies.some((item) => item.status === "pending") ? "blocked" : "ready"} />{canCreateCycle ? <button disabled={busy !== ""} onClick={createCycle} className="min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white">Abrir próximo ciclo</button> : null}</div></div>
      {data.dependencies.length ? <div className="mt-4 grid gap-2 md:grid-cols-2">{data.dependencies.map((dependency) => <div key={dependency.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3 text-xs"><div className="flex justify-between gap-3"><span>Depende de {dependency.depends_on_engagement_id}</span><StatusBadge status={dependency.status} /></div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{dependency.dependency_type}</div></div>)}</div> : null}
      <div className="mt-4 divide-y divide-line overflow-hidden rounded-lg border border-line">{data.work_items.map((item) => { const execution = data.service_executions.find((candidate) => candidate.work_item_id === item.id); return <div key={item.id} className="grid gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_110px_140px_minmax(190px,320px)] lg:items-center"><div><div className="text-xs font-semibold">{item.title}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{item.execution_mode} · {item.priority}{item.blocked_reason ? ` · ${item.blocked_reason}` : ""}</div></div><StatusBadge status={item.status} /><div className="text-[10px] text-[rgb(var(--muted))]">{execution?.status === "waiting_for_evidence" ? "aguardando evidência real" : execution ? `${execution.attempt_count}/${execution.max_attempts} tentativas` : "não executado"}</div><div className="flex justify-end gap-2">{canOperate && item.status === "queued" && !execution ? <button disabled={busy !== ""} onClick={() => void execute(item)} className="min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white">Executar</button> : null}{canOperate && execution?.status === "waiting_for_evidence" && ["human", "integration"].includes(item.execution_mode) ? <ManualEvidenceAction item={item} disabled={busy !== ""} onComplete={(evidenceReference) => completeExternal(item, evidenceReference)} /> : null}{canOperate && execution && ["failed", "cancelled"].includes(execution.status) && execution.attempt_count < execution.max_attempts ? <button disabled={busy !== ""} onClick={() => void retry(execution)} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-3 text-xs"><RotateCcw className="h-3.5 w-3.5" /> Retry</button> : null}{canOperate && execution && ["queued", "dispatch_pending", "running", "delegated"].includes(execution.status) ? <button disabled={busy !== ""} onClick={() => void cancel(execution)} className="min-h-11 rounded-lg border border-red-500/40 px-3 text-xs text-red-200">Cancelar</button> : null}</div></div>; })}{!data.work_items.length ? <div className="p-4"><EmptyState title="Nenhum item materializado" /></div> : null}</div>
    </Surface>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(330px,.8fr)]"><Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Checks persistidos do Definition of Done</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">O owner registra evidência; o VP valida em seguida. As identidades permanecem separadas.</p></div><div className="divide-y divide-line">{data.acceptance_checks.map((check) => <article key={check.id} className="p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="text-[10px] font-semibold uppercase text-blue-400">{check.scope} · {check.cycle_key}</div><p className="mt-1 text-xs leading-5">{check.description}</p></div><StatusBadge status={check.status} /></div><AcceptanceCheckActions check={check} canOperate={canOperate} canDecide={canDecide} disabled={busy !== ""} onEvidence={evidence} onDecision={decide} /></article>)}{!data.acceptance_checks.length ? <div className="p-4"><EmptyState title="Checks serão materializados na ativação" /></div> : null}</div></Surface>
      <div className="space-y-5"><Surface className="p-5"><h2 className="text-sm font-semibold">Ciclos recorrentes</h2><div className="mt-3 space-y-2">{data.cycles.map((cycle) => <div key={cycle.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="flex justify-between gap-3"><span className="text-xs font-semibold">Ciclo {cycle.sequence}</span><StatusBadge status={cycle.status} /></div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{cycle.period_start ? fmtDate(cycle.period_start) : "início aberto"} → {cycle.period_end ? fmtDate(cycle.period_end) : "fim aberto"}</div></div>)}{!data.cycles.length ? <p className="text-xs text-[rgb(var(--muted))]">Oferta de ciclo único.</p> : null}</div></Surface>
      <Surface className="p-5"><h2 className="text-sm font-semibold">Central de artifacts e downloads</h2><div className="mt-3 space-y-2">{data.deliverables.map((deliverable) => <div key={deliverable.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold">{deliverable.title}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{deliverable.latest_revision?.artifact_refs_json.length || 0} artifacts · revisão {deliverable.current_revision}</div></div>{["approved", "delivered"].includes(deliverable.status) ? <a href={`${API_BASE}/api/v1/service-deliverables/${deliverable.id}/package/download`} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-3 text-xs"><Download className="h-3.5 w-3.5" /> ZIP</a> : <StatusBadge status={deliverable.status} />}</div></div>)}</div></Surface></div>
    </div>
  </div>;
}

export function EngagementWorkspace({ engagementId }: { engagementId: string }) {
  const { data, error, refresh, setError } = useResource(() => apiGet<EngagementWorkspaceData>(`/api/v1/engagements/${engagementId}`), [engagementId]);
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [brief, setBrief] = useState("");
  const [knowledgeIds, setKnowledgeIds] = useState("");
  const [approvalComment, setApprovalComment] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => {
    getBrowserSession().then(setSession).catch((reason: Error) => setError(reason.message));
  }, [setError]);
  useEffect(() => {
    if (!data?.id) return;
    const stream = new EventSource(`${API_BASE}/api/v1/client-operations/events`);
    stream.onmessage = () => refresh();
    return () => stream.close();
    // refresh is intentionally bound to this workspace instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagementId, data?.id]);
  const call = async (kind: string, action: () => Promise<unknown>) => { setBusy(kind); setError(""); try { await action(); refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na operação"); } finally { setBusy(""); } };
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data || !session) return <LoadingState label="Montando a esteira do engajamento…" />;
  const plan = data.latest_plan;
  const canOperate = ["owner", "super_admin"].includes(session.me.role);
  const canApprove = session.me.role === "engagement_manager";
  const activated = data.status === "active";
  const planApproved = plan ? ["approved", "synthetic_approved"].includes(plan.status) : false;
  const executionStarted = data.service_executions.length > 0;
  const executionComplete = executionStarted && data.service_executions.every((item) => ["completed", "succeeded", "awaiting_review"].includes(item.status));
  const deliveryComplete = data.deliverables.length > 0 && data.deliverables.every((item) => ["delivered", "synthetic_delivered"].includes(item.status));
  const pipeline = [
    { label: "Plano", detail: "Escopo adaptado", status: plan ? "completed" : "in_progress" },
    { label: "Aprovação VP", detail: "Four-eyes", status: planApproved ? "completed" : plan ? "in_progress" : "pending" },
    { label: "Ativação", detail: "Owner materializa", status: activated ? "completed" : planApproved ? "in_progress" : "pending" },
    { label: "Execução", detail: "Agentes e gates", status: executionComplete ? "completed" : executionStarted ? "in_progress" : "pending" },
    { label: "Entrega", detail: "Aceite e pacote", status: deliveryComplete ? "completed" : activated ? "pending" : "pending" },
  ];
  return <div className="space-y-6">
    <PageHeader eyebrow={data.offering?.name || "Engajamento"} title={data.name} description={data.description || "Operação adaptada ao contrato e ao contexto deste cliente."} actions={<><span className="rounded-full border border-line px-3 py-2 text-xs text-[rgb(var(--muted))]">{canApprove ? "Visão do VP" : "Visão do owner"}</span><StatusBadge status={data.status} /><RefreshButton onClick={refresh} /></>} />
    {data.guidance ? <OperationalGuidance guidance={data.guidance} onUseDraft={canApprove ? setApprovalComment : undefined} /> : null}
    {error ? <ErrorState message={error} /> : null}
    <Surface className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-[.16em] text-blue-400">Esteira guiada</p><h2 className="mt-2 text-lg font-semibold">Um próximo passo por vez</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">A fábrica libera cada etapa somente para o papel responsável.</p></div>
        <Link href={canApprove ? "/approvals" : "/work-queue"} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-3 text-xs font-semibold">{canApprove ? "Minha fila" : "Fila operacional"}<ArrowRight className="h-3.5 w-3.5" /></Link>
      </div>
      <ol className="mt-5 grid gap-3 md:grid-cols-5">
        {pipeline.map((step, index) => <li key={step.label} className={`rounded-xl border p-3 ${step.status === "in_progress" ? "border-blue-500/40 bg-blue-500/10" : "border-line bg-[rgb(var(--panel-soft))]"}`}><div className="flex items-center justify-between gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-[rgb(var(--panel))] text-xs font-semibold">{step.status === "completed" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : index + 1}</span><StatusBadge status={step.status} /></div><div className="mt-3 text-xs font-semibold">{step.label}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{step.detail}</div></li>)}
      </ol>
      {data.offering ? <details className="group mt-5 border-t border-line pt-3"><summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-3 text-sm font-semibold"><span>Ver roteiro completo deste serviço</span><span className="flex items-center gap-2 text-xs font-normal text-[rgb(var(--muted))]">{data.offering.definition.process?.length || 0} etapas · {data.offering.definition.deliverable_templates?.length || 0} entregáveis <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" /></span></summary><div className="mt-3 rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4 sm:p-5"><OfferingProcessFlow offering={data.offering} compact /><Link href={`/service-catalog/${data.offering.version_id}`} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg border border-blue-500/30 px-4 text-sm font-semibold text-blue-200">Abrir escopo, entregáveis e critérios <ArrowRight className="h-4 w-4" /></Link></div></details> : null}
    </Surface>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Entregáveis" value={data.counts?.deliverables || 0} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard label="Concluídos" value={data.counts?.deliverables_completed || 0} icon={<CheckCircle2 className="h-5 w-5" />} /><MetricCard label="Workstreams" value={data.counts?.workstreams || 0} icon={<Layers3 className="h-5 w-5" />} /><MetricCard label="Equipe AI" value={data.counts?.agent_assignments || 0} icon={<Bot className="h-5 w-5" />} /></div>
    {!plan && canOperate ? <Surface className="p-5"><h2 className="text-base font-semibold">1. Gerar o plano</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Descreva o contexto; o catálogo contratado continuará sendo a fonte da verdade.</p><div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]"><textarea value={brief} onChange={(event) => setBrief(event.target.value)} minLength={20} rows={6} className="rounded-lg border px-3 py-3" placeholder="Objetivo, áreas, restrições, stakeholders e critérios específicos…" /><div className="space-y-3"><input value={knowledgeIds} onChange={(event) => setKnowledgeIds(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Bases de conhecimento autorizadas" /><button disabled={busy !== "" || brief.trim().length < 20} onClick={() => void call("plan", () => apiPost(`/api/v1/engagements/${data.id}/plans/generate`, { expected_version: data.record_version, adaptation_brief: brief, knowledge_base_ids: knowledgeIds.split(",").map((item) => item.trim()).filter(Boolean) }, { idempotencyKey: commandKey("engagement-plan") }))} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-50"><Sparkles className="h-4 w-4" />{busy === "plan" ? "Gerando…" : "Gerar plano"}</button></div></div></Surface> : null}
    {!plan && !canOperate ? <Surface className="border-blue-500/30 bg-blue-500/5 p-5"><h2 className="text-sm font-semibold">Aguardando o owner gerar o plano</h2><p className="mt-2 text-xs text-[rgb(var(--muted))]">Você será avisado nesta fila quando houver uma decisão disponível.</p></Surface> : null}
    {plan ? <Surface className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[.16em] text-blue-400">Plano v{plan.version}</p><h2 className="mt-2 text-lg font-semibold">{plan.plan_json.summary || "Plano do engajamento"}</h2><p className="mt-2 text-xs text-[rgb(var(--muted))]">{plan.plan_json.workstreams?.length || 0} workstreams · {plan.plan_json.deliverables?.length || 0} entregáveis · {plan.plan_json.risks?.length || 0} riscos</p>{plan.model_call_id ? <p className="mt-2 text-[10px] text-[rgb(var(--muted))]">Model call {plan.model_call_id}</p> : null}</div><StatusBadge status={plan.status} /></div><div className="mt-5 grid gap-5 lg:grid-cols-3"><div><h3 className="text-xs font-semibold">Etapas</h3><ol className="mt-2 space-y-2 text-xs text-[rgb(var(--muted))]">{plan.plan_json.stages?.map((item, index) => <li key={item}>{index + 1}. {item}</li>)}</ol></div><div><h3 className="text-xs font-semibold">Workstreams</h3><div className="mt-2 space-y-2">{plan.plan_json.workstreams?.map((item) => <div key={item.key} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="text-xs font-semibold">{item.name}</div><p className="mt-1 text-[11px] text-[rgb(var(--muted))]">{item.objective}</p></div>)}</div></div><div><h3 className="text-xs font-semibold">Riscos</h3><ul className="mt-2 space-y-2 text-xs text-[rgb(var(--muted))]">{plan.plan_json.risks?.map((item) => <li key={item} className="flex gap-2"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />{item}</li>)}</ul></div></div>
      {plan.status === "draft" && canApprove ? <div className="mt-5 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4"><label className="grid gap-2 text-sm"><span className="font-semibold">Comentário obrigatório do VP</span><textarea value={approvalComment} onChange={(event) => setApprovalComment(event.target.value)} minLength={10} rows={3} className="rounded-lg border px-3 py-3" placeholder="Confirme escopo, riscos e condições para iniciar…" /></label><button disabled={busy !== "" || approvalComment.trim().length < 10} onClick={() => void call("approve", () => apiPost(`/api/v1/engagements/${data.id}/plans/${plan.version}/approve`, { expected_version: data.record_version, comment: approvalComment.trim() }, { idempotencyKey: commandKey("engagement-plan-approve") }))} className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-[#07110A] disabled:opacity-50"><CheckCircle2 className="h-4 w-4" /> Aprovar e liberar para o owner</button></div> : null}
      {plan.status === "draft" && !canApprove ? <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm"><div className="font-semibold text-amber-200">Aguardando a decisão do VP</div><p className="mt-1 text-xs text-[rgb(var(--muted))]">A fábrica não permite que o autor do plano aprove a própria versão.</p></div> : null}
      {planApproved && !activated && canOperate ? <button disabled={busy !== ""} onClick={() => void call("activate", () => apiPost(`/api/v1/engagements/${data.id}/activate`, { expected_version: data.record_version, comment: "Plano aprovado pelo VP; materialização da operação autorizada pelo owner." }, { idempotencyKey: commandKey("engagement-activate") }))} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white"><Play className="h-4 w-4" /> Ativar e materializar a operação</button> : null}
      {planApproved && !activated && !canOperate ? <div className="mt-5 rounded-xl border border-blue-500/30 bg-blue-500/5 p-4 text-sm"><div className="font-semibold text-blue-200">Plano {plan.status === "synthetic_approved" ? "validado em modo sintético" : "aprovado"}</div><p className="mt-1 text-xs text-[rgb(var(--muted))]">O owner recebeu o próximo passo: ativar e materializar a operação.</p></div> : null}
    </Surface> : null}
    {data.status === "active" ? <EngagementTeamAndOutcomes data={data} refresh={refresh} reportError={setError} canManage={canOperate} /> : null}
    {data.status === "active" ? <EngagementCockpit data={data} refresh={refresh} reportError={setError} role={session.me.role} /> : null}
    {data.status === "active" ? <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(330px,.75fr)]"><Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Entregáveis específicos</h2></div>{data.deliverables.length ? <div className="divide-y divide-line">{data.deliverables.map((item) => <Link key={item.id} href={`/deliverables/${item.id}`} className="flex min-h-20 items-center justify-between gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))]"><div><div className="text-sm font-semibold">{item.title}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{item.due_at ? fmtDate(item.due_at) : "Sem prazo"} · revisão {item.current_revision}</div></div><div className="flex items-center gap-3"><StatusBadge status={item.status} /><ArrowRight className="h-4 w-4 text-blue-400" /></div></Link>)}</div> : <div className="p-5"><EmptyState title="Plano sem entregáveis" description="Revise a materialização do plano aprovado." /></div>}</Surface><Surface className="p-5"><h2 className="text-sm font-semibold">Linha do tempo</h2><div className="mt-4 space-y-4">{data.events.slice(0, 10).map((event) => <div key={event.id} className="border-l border-blue-500/30 pl-3"><div className="text-xs font-semibold">{event.event_type}</div><div className="mt-1 text-[11px] text-[rgb(var(--muted))]">{event.payload_json.summary || `Evento #${event.tenant_sequence}`}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{fmtDate(event.created_at)}</div></div>)}</div></Surface></div> : null}
  </div>;
}

export function WorkQueueView() {
  const { data, error, refresh, setError } = useResource(async () => {
    const [queue, capacity, session] = await Promise.all([
      apiGet<{ generated_at: string; items: WorkItem[] }>("/api/v1/operator/work-queue"),
      apiGet<Capacity>("/api/v1/operator/capacity"),
      getBrowserSession(),
    ]);
    return { queue, capacity, session };
  });
  const [busy, setBusy] = useState("");
  async function execute(item: WorkItem) {
    if (!data || item.tenant_id !== data.session.active_tenant_id) return;
    setBusy(item.id); setError("");
    try {
      await apiPost(`/api/v1/service-work-items/${item.id}/execute`, {
        expected_version: item.record_version,
        instructions: "Executar conforme plano aprovado e evidências tenant-scoped.",
        knowledge_base_ids: [],
      }, { idempotencyKey: commandKey("service-execution") });
      refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao enfileirar execução"); }
    finally { setBusy(""); }
  }
  async function transition(item: WorkItem, status: string, evidenceReference = "") {
    if (!data || item.tenant_id !== data.session.active_tenant_id) return;
    setBusy(item.id); setError("");
    try {
      await apiPost(`/api/v1/service-work-items/${item.id}/transitions`, {
        status, expected_version: item.record_version,
        reason: status === "completed" ? evidenceReference.trim() : "",
        override_reason: "",
      }, { idempotencyKey: commandKey("work-item-transition") });
      refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na transição"); }
    finally { setBusy(""); }
  }
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Priorizando fila dos clientes…" />;
  const { capacity, queue, session } = data;
  const profileContext: Record<string, string> = {
    generalist: "Visão geral da operação",
    business_analyst: "Contexto, valor e entregáveis em primeiro plano",
    software_engineer: "Runs compartilhados, código e bloqueios técnicos em primeiro plano",
    qa_quality: "Testes, gates e evidências em primeiro plano",
    governance_risk: "Riscos, políticas e decisões em primeiro plano",
  };
  return <div className="space-y-6">
    <PageHeader eyebrow="WIP governado" title="Fila e capacidade" description={`Prioridade, SLA e bloqueios continuam determinísticos. ${profileContext[session.me.operator_profile] || profileContext.generalist}.`} actions={<RefreshButton onClick={refresh} />} />
    {error ? <ErrorState message={error} /> : null}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="WIP global" value={`${capacity.active_total}/${capacity.global_limit}`} detail="Limite determinístico" icon={<Gauge className="h-5 w-5" />} /><MetricCard label="Slots disponíveis" value={capacity.available_slots} icon={<Boxes className="h-5 w-5" />} /><MetricCard label="Em fila" value={queue.items.filter((item) => item.status === "queued").length} icon={<CalendarClock className="h-5 w-5" />} /><MetricCard label="Bloqueados" value={queue.items.filter((item) => item.status === "blocked").length} icon={<AlertTriangle className="h-5 w-5" />} /></div>
    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,.65fr)]"><Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Próximas ações</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Bloqueios, prioridade e prazo ordenados no servidor</p></div>{queue.items.length ? <div className="divide-y divide-line">{queue.items.map((item) => {
      const activeTenant = item.tenant_id === session.active_tenant_id;
      return <article key={item.id} className={`grid gap-3 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_110px_120px_300px] lg:items-center ${activeTenant ? "bg-blue-500/[0.04]" : ""}`}><div className="min-w-0"><div className="flex items-center gap-2"><h3 className="truncate text-sm font-semibold">{item.title}</h3>{activeTenant ? <span className="rounded-full bg-blue-500/15 px-2 py-1 text-[9px] font-semibold text-blue-300">TENANT ATIVO</span> : null}</div><p className="mt-1 truncate text-xs text-[rgb(var(--muted))]">{item.tenant_name} · {item.engagement_name} · {item.execution_mode}</p>{item.operation_key ? <p className="mt-1 text-[10px] text-violet-300">Grupo técnico {item.operation_key} · {item.related_deliverables?.length || 0} entregáveis · um único slot</p> : null}{item.run_id ? <p className="mt-1 break-all text-[10px] text-blue-300">Run compartilhado: {item.run_id}</p> : item.execution_status ? <p className="mt-1 text-[10px] text-blue-300">Execução durável: {item.execution_status}</p> : null}{item.blocked_reason ? <p className="mt-2 text-xs text-red-300">{item.blocked_reason}</p> : null}</div><StatusBadge status={item.status} /><div className="text-xs text-[rgb(var(--muted))]">{item.due_at ? fmtDate(item.due_at) : "Sem prazo"}</div><div className="flex justify-end gap-2">{activeTenant && item.status === "queued" && !item.execution_id ? <button disabled={busy === item.id} onClick={() => void execute(item)} className="min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white">Enfileirar</button> : null}{activeTenant && item.status === "in_progress" && ["human", "integration"].includes(item.execution_mode) ? <ManualEvidenceAction item={item} disabled={busy === item.id} onComplete={(evidence) => transition(item, "completed", evidence)} /> : null}{!activeTenant && item.tenant_id ? <Link href={`/clients/${item.tenant_id}`} className="inline-flex min-h-11 items-center rounded-lg border border-line px-3 text-xs">Selecionar cliente</Link> : null}</div></article>;
    })}</div> : <div className="p-5"><EmptyState title="Fila vazia" description="Work items serão materializados após ativação de um plano aprovado." /></div>}</Surface><Surface className="p-5"><h2 className="text-sm font-semibold">Capacidade por cliente</h2><div className="mt-4 space-y-3">{capacity.tenants.map((tenant) => <div key={tenant.tenant_id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="flex items-center justify-between"><div className="text-xs font-semibold">{tenant.tenant_name}</div><span className="text-[10px] text-[rgb(var(--muted))]">{tenant.active}/{tenant.limit}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[rgb(var(--panel))]"><div className={`h-full rounded-full ${tenant.over_capacity ? "bg-red-500" : "bg-blue-500"}`} style={{ width: `${Math.min(100, tenant.limit ? tenant.active / tenant.limit * 100 : 0)}%` }} /></div><div className="mt-2 text-[10px] text-[rgb(var(--muted))]">{tenant.queued} em fila · {tenant.blocked} bloqueados</div></div>)}</div></Surface></div>
  </div>;
}

function ManualEvidenceAction({ item, disabled, onComplete }: { item: WorkItem; disabled: boolean; onComplete: (evidence: string) => Promise<void> }) {
  const [evidence, setEvidence] = useState("");
  const ready = evidence.trim().length >= 10;
  return <div className="grid w-full gap-2"><input value={evidence} onChange={(event) => setEvidence(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-xs" placeholder={`Evidência da atividade ${item.execution_mode}`} aria-label={`Evidência para ${item.title}`} /><button disabled={disabled || !ready} onClick={() => void onComplete(evidence)} className="min-h-11 rounded-lg bg-emerald-500 px-3 text-xs font-semibold text-[#07110A] disabled:opacity-40">Registrar conclusão</button></div>;
}

export function ServiceDeliverablesView({ role = "" }: { role?: string }) {
  const { data, error, refresh } = useResource(() => apiGet<ServiceDeliverable[]>("/api/v1/service-deliverables"));
  const isVp = role === "engagement_manager";
  const [filter, setFilter] = useState(isVp ? "review_ready" : "all");
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Carregando portfólio de entregáveis…" />;
  const visible = filter === "all" ? data : data.filter((item) => item.status === filter);
  return <div className="space-y-6"><PageHeader eyebrow="Entregas de negócio" title={isVp ? "Entregáveis para decisão" : "Entregáveis"} description={isVp ? "Valide conteúdo, evidências, riscos e critérios; depois confirme a entrega final no mesmo workspace." : "Cada item pertence a um cliente, oferta e engajamento; revisions, artifacts, evidências e model calls permanecem rastreáveis."} actions={<RefreshButton onClick={refresh} />} />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Total" value={data.length} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard label="Em produção" value={data.filter((item) => item.status === "in_progress").length} /><MetricCard label="Para validar" value={data.filter((item) => item.status === "review_ready").length} /><MetricCard label="Confirmar entrega" value={data.filter((item) => item.status === "approved").length} /></div>
    <Surface><div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Portfólio isolado do tenant ativo</h2><label className="flex items-center gap-2 text-xs text-[rgb(var(--muted))]">Status<select value={filter} onChange={(event) => setFilter(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="all">Todos</option><option value="planned">Planejado</option><option value="in_progress">Em produção</option><option value="review_ready">Para validar</option><option value="approved">Confirmar entrega</option><option value="delivered">Entregue</option></select></label></div>{visible.length ? <div className="divide-y divide-line">{visible.map((item) => <Link key={item.id} href={`/deliverables/${item.id}`} className="grid min-h-24 gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] lg:grid-cols-[minmax(0,1fr)_180px_120px_100px_160px] lg:items-center"><div className="min-w-0"><h2 className="truncate text-sm font-semibold">{item.title}</h2><p className="mt-1 truncate text-xs text-[rgb(var(--muted))]">{item.engagement?.name} · {item.offering?.name}</p></div><div className="text-xs text-[rgb(var(--muted))]">{item.due_at ? fmtDate(item.due_at) : "Sem prazo"}</div><StatusBadge status={item.status} /><div><div className="text-sm font-semibold">v{item.current_revision}</div><div className="text-[10px] text-[rgb(var(--muted))]">revisão</div></div><span className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-line px-3 text-xs font-semibold">{isVp && item.status === "review_ready" ? "Validar agora" : isVp && item.status === "approved" ? "Confirmar entrega" : "Abrir"}<ArrowRight className="h-4 w-4 text-blue-400" /></span></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum entregável neste estado" description={isVp ? "Quando o owner submeter um entregável, ele aparecerá aqui automaticamente." : "Entregáveis aparecem após a ativação do plano do engajamento."} /></div>}</Surface>
  </div>;
}

export function DeliverablesExperience() {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getBrowserSession().then(setSession).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <ErrorState message={error} />;
  if (!session) return <LoadingState label="Carregando experiência de entrega…" />;
  if (["client_sponsor", "process_owner", "reviewer", "auditor"].includes(session.me.role)) return <DeliverablesCenter />;
  return <ServiceDeliverablesView role={session.me.role} />;
}

export function ServiceDeliverableWorkspace({ deliverableId }: { deliverableId: string }) {
  const { data, error, refresh, setError } = useResource(() => apiGet<ServiceDeliverable>(`/api/v1/service-deliverables/${deliverableId}`), [deliverableId]);
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [instructions, setInstructions] = useState("");
  const [knowledgeIds, setKnowledgeIds] = useState("");
  const [busy, setBusy] = useState("");
  const [comment, setComment] = useState("");
  useEffect(() => { getBrowserSession().then(setSession).catch((reason: Error) => setError(reason.message)); }, [setError]);
  const act = async (kind: string, fn: () => Promise<unknown>) => { setBusy(kind); setError(""); try { await fn(); setComment(""); refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na operação"); } finally { setBusy(""); } };
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data || !session) return <LoadingState label="Carregando entregável e evidências…" />;
  const latest = data.latest_revision;
  const canOperate = ["owner", "super_admin"].includes(session.me.role);
  const isVp = session.me.role === "engagement_manager";
  const isApproved = ["approved", "synthetic_approved"].includes(data.status);
  const isDelivered = ["delivered", "synthetic_delivered"].includes(data.status);
  const decisionCommentReady = comment.trim().length >= 10;
  const risks = latest?.content_json.risks || [];
  const nextActions = latest?.content_json.next_actions || [];
  const evidenceRefs = latest?.evidence_refs_json || [];
  const artifactRefs = latest?.artifact_refs_json || [];
  const decisionTitle = isVp
    ? data.status === "review_ready" ? "Sua decisão: validar o entregável" : isApproved ? "Sua decisão: confirmar a entrega" : isDelivered ? "Entrega concluída" : "Aguardando produção do owner"
    : data.status === "review_ready" ? "Aguardando validação do VP" : isApproved ? "Validado pelo VP; aguardando entrega final" : "Próxima ação do owner";
  const decisionDetail = isVp
    ? data.status === "review_ready" ? "Leia o conteúdo, confira critérios, evidências e riscos e registre uma decisão comentada." : isApproved ? data.status === "synthetic_approved" ? "Confirme a passagem sintética pela entrega. Ela permanece inelegível para liberação real." : "Baixe o pacote editável, confirme destinatário/canal e registre a entrega." : isDelivered ? "A decisão final e a entrega já estão registradas no ledger." : "O item aparecerá para decisão depois que o owner produzir e submeter uma revisão."
    : data.status === "review_ready" ? "O conteúdo está imutável enquanto o VP revisa esta versão." : "Produza, verifique e submeta a revisão quando estiver pronta.";
  return <div className="space-y-6"><PageHeader eyebrow={data.offering?.name || "Entregável"} title={data.title} description={data.description} actions={<>{["approved", "delivered"].includes(data.status) ? <a href={`${API_BASE}/api/v1/service-deliverables/${data.id}/package/download`} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 text-sm"><Download className="h-4 w-4" /> Pacote editável</a> : null}<StatusBadge status={data.status} /><RefreshButton onClick={refresh} /></>} />{data.guidance ? <OperationalGuidance guidance={data.guidance} onUseDraft={setComment} /> : null}{error ? <ErrorState message={error} /> : null}
    <Surface className={`border p-5 ${isVp && ["review_ready", "approved"].includes(data.status) ? "border-emerald-500/40 bg-emerald-500/5" : "border-blue-500/30 bg-blue-500/5"}`}><div className="flex items-start gap-3"><ClipboardCheck className={`mt-0.5 h-5 w-5 shrink-0 ${isVp && ["review_ready", "approved"].includes(data.status) ? "text-emerald-300" : "text-blue-300"}`} /><div><div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[rgb(var(--muted))]">{isVp ? "Visão do VP" : "Visão do owner"}</div><h2 className="mt-1 text-base font-semibold text-ink">{decisionTitle}</h2><p className="mt-2 text-sm leading-6 text-[rgb(var(--muted))]">{decisionDetail}</p></div></div></Surface>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Revisão" value={data.current_revision || "—"} /><MetricCard label="Audiência" value={data.audience} icon={<Users className="h-5 w-5" />} /><MetricCard label="Prazo" value={data.due_at ? fmtDate(data.due_at) : "—"} icon={<CalendarClock className="h-5 w-5" />} /><MetricCard label="Proveniência" value={latest?.model_call_id ? "IA rastreada" : latest ? "Operador" : "—"} icon={<LockKeyhole className="h-5 w-5" />} /></div>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(350px,.65fr)]"><Surface className="p-5">{latest?.content_json.content_markdown ? <><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">{latest.content_json.title || data.title}</h2><p className="mt-1 text-[10px] text-[rgb(var(--muted))]">Revision {latest.revision} · {latest.model_call_id ? `model call ${latest.model_call_id}` : "entrada humana"}</p></div><Provenance value={latest.model_call_id ? "real" : "declared"} /></div><MarkdownViewer content={latest.content_json.content_markdown} /></> : <EmptyState title="Conteúdo ainda não produzido" description="Gere uma revisão com IA usando apenas contexto autorizado ou registre uma revisão manual pela API." />}</Surface>
      <div className="space-y-5"><Surface className="p-5"><h2 className="text-sm font-semibold">Guia de validação</h2><div className="mt-4 space-y-3">{[["1", "Conteúdo", latest?.content_json.executive_summary || "Leia a revisão integral exibida ao lado."], ["2", "Critérios", `${data.acceptance_criteria_json.length} critérios de aceite e ${data.definition_of_done_json.length} itens de DoD.`], ["3", "Evidências", `${evidenceRefs.length} referências e ${artifactRefs.length} artifacts persistidos.`], ["4", "Riscos", risks.length ? `${risks.length} riscos ou limitações registrados.` : "Nenhum risco registrado nesta revisão; confirme se isso é adequado."]].map(([number, title, detail]) => <div key={number} className="flex gap-3 rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-[10px] font-semibold text-blue-300">{number}</span><div><div className="text-xs font-semibold">{title}</div><p className="mt-1 text-[11px] leading-5 text-[rgb(var(--muted))]">{detail}</p></div></div>)}</div></Surface>
        <Surface className="p-5"><h2 className="text-sm font-semibold">Critérios e Definition of Done</h2><div className="mt-4"><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-blue-400">Critérios de aceite</div><ul className="mt-2 space-y-2">{data.acceptance_criteria_json.map((item) => <li key={item} className="flex gap-2 text-xs text-[rgb(var(--muted))]"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-400" />{item}</li>)}</ul></div><div className="mt-5"><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-400">Definition of Done</div><ul className="mt-2 space-y-2">{data.definition_of_done_json.map((item) => <li key={item} className="flex gap-2 text-xs text-[rgb(var(--muted))]"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />{item}</li>)}</ul></div></Surface>
        <Surface className="p-5"><h2 className="text-sm font-semibold">Evidências, riscos e próximos passos</h2><div className="mt-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-blue-400">Evidências</div>{evidenceRefs.length ? <ul className="mt-2 space-y-2">{evidenceRefs.map((item) => <li key={item} className="break-all text-xs text-[rgb(var(--muted))]">{item}</li>)}</ul> : <p className="mt-2 text-xs text-amber-200">Nenhuma referência externa; a aprovação não substitui os checks persistidos do DoD.</p>}<div className="mt-5 text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-400">Riscos e limitações</div>{risks.length ? <ul className="mt-2 space-y-2">{risks.map((item) => <li key={item} className="flex gap-2 text-xs text-[rgb(var(--muted))]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />{item}</li>)}</ul> : <p className="mt-2 text-xs text-[rgb(var(--muted))]">Nenhum risco registrado.</p>}<div className="mt-5 text-[10px] font-semibold uppercase tracking-[0.14em] text-blue-400">Próximos passos</div>{nextActions.length ? <ul className="mt-2 space-y-2">{nextActions.map((item) => <li key={item} className="text-xs text-[rgb(var(--muted))]">{item}</li>)}</ul> : <p className="mt-2 text-xs text-[rgb(var(--muted))]">Nenhum próximo passo registrado.</p>}</Surface>
        {canOperate && !["approved", "delivered", "review_ready"].includes(data.status) ? <Surface className="p-5"><h2 className="text-sm font-semibold">Produção assistida</h2><p className="mt-1 text-xs leading-5 text-[rgb(var(--muted))]">A saída será persistida como nova revisão; ausência de evidência será explicitada pelo modelo.</p><textarea rows={4} value={instructions} onChange={(event) => setInstructions(event.target.value)} className="mt-4 w-full rounded-lg border px-3 py-3 text-sm" placeholder="Orientações específicas para esta revisão" /><input value={knowledgeIds} onChange={(event) => setKnowledgeIds(event.target.value)} className="mt-3 min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Knowledge base IDs, separados por vírgula" /><button disabled={busy !== ""} onClick={() => void act("generate", () => apiPost(`/api/v1/service-deliverables/${data.id}/revisions/generate`, { instructions, knowledge_base_ids: knowledgeIds.split(",").map((item) => item.trim()).filter(Boolean) }, { idempotencyKey: commandKey("deliverable-generate") }))} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-50"><Sparkles className="h-4 w-4" />{busy === "generate" ? "Gerando…" : "Gerar nova revisão"}</button></Surface> : null}
        {canOperate && data.status === "in_progress" && latest ? <Surface className="p-5"><h2 className="text-sm font-semibold">Submeter ao VP</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Resuma o que foi produzido e quais evidências sustentam a revisão.</p><textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} className="mt-3 w-full rounded-lg border px-3 py-3 text-sm" placeholder="Resumo para decisão do VP" /><button disabled={busy !== "" || comment.trim().length < 10} onClick={() => void act("submit", () => apiPost(`/api/v1/service-deliverables/${data.id}/submit`, { expected_version: data.record_version, comment: comment.trim() }, { idempotencyKey: commandKey("deliverable-submit") }))} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white disabled:opacity-50"><Send className="h-4 w-4" /> Submeter ao VP</button></Surface> : null}
        {isVp && data.status === "review_ready" ? <Surface className="border border-emerald-500/40 bg-emerald-500/5 p-5"><h2 className="text-sm font-semibold">Registrar decisão do entregável</h2><p className="mt-1 text-xs leading-5 text-[rgb(var(--muted))]">Seu comentário é obrigatório e ficará vinculado a esta revisão no ledger.</p><textarea rows={4} value={comment} onChange={(event) => setComment(event.target.value)} minLength={10} className="mt-3 w-full rounded-lg border px-3 py-3 text-sm" placeholder="Explique o aceite, os ajustes necessários ou o motivo da rejeição…" /><div className="mt-3 grid gap-2 sm:grid-cols-3"><button disabled={busy !== "" || !decisionCommentReady} onClick={() => void act("approve", () => apiPost(`/api/v1/service-deliverables/${data.id}/decisions`, { decision: "approve", comment: comment.trim(), expected_version: data.record_version }, { idempotencyKey: commandKey("deliverable-approve") }))} className="min-h-11 rounded-lg bg-emerald-500 text-xs font-semibold text-[#07110A] disabled:opacity-40">Aprovar entregável</button><button disabled={busy !== "" || !decisionCommentReady} onClick={() => void act("changes", () => apiPost(`/api/v1/service-deliverables/${data.id}/decisions`, { decision: "changes_requested", comment: comment.trim(), expected_version: data.record_version }, { idempotencyKey: commandKey("deliverable-changes") }))} className="min-h-11 rounded-lg border border-amber-500/40 text-xs text-amber-200 disabled:opacity-40">Solicitar ajustes</button><button disabled={busy !== "" || !decisionCommentReady} onClick={() => void act("reject", () => apiPost(`/api/v1/service-deliverables/${data.id}/decisions`, { decision: "reject", comment: comment.trim(), expected_version: data.record_version }, { idempotencyKey: commandKey("deliverable-reject") }))} className="min-h-11 rounded-lg border border-red-500/40 text-xs text-red-200 disabled:opacity-40">Rejeitar</button></div></Surface> : null}
      </div></div>
    {isVp && isApproved ? <Surface className="border border-orange-500/40 bg-orange-500/5 p-5"><div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-end"><div><h2 className="text-sm font-semibold">Confirmar entrega final</h2><p className="mt-1 text-xs leading-5 text-[rgb(var(--muted))]">{data.status === "synthetic_approved" ? "Validação sintética: registre a passagem pela etapa; ela não conclui o engajamento nem libera produção." : "Baixe o pacote editável, confirme o destinatário e registre canal, data ou referência do aceite. Essa ação encerra o entregável."}</p></div><div><textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} minLength={10} className="w-full rounded-lg border px-3 py-3 text-sm" placeholder="Ex.: pacote apresentado ao comitê e aceite registrado na ata…" /><button disabled={busy !== "" || !decisionCommentReady} onClick={() => void act("deliver", () => apiPost(`/api/v1/service-deliverables/${data.id}/deliver`, { expected_version: data.record_version, comment: comment.trim() }, { idempotencyKey: commandKey("deliverable-deliver") }))} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-50"><Send className="h-4 w-4" /> Confirmar entrega final</button></div></div></Surface> : null}
    {data.approval && data.approval.comments ? <Surface className="p-5"><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-400">Última decisão registrada</div><p className="mt-2 text-sm leading-6 text-[rgb(var(--muted))]">{data.approval.comments}</p></Surface> : null}
  </div>;
}

export function AgentStudioView() {
  const { data, error, refresh, setError } = useResource(() => apiGet<AgentCatalog>("/api/v1/agent-catalog"));
  const [title, setTitle] = useState("");
  const [capability, setCapability] = useState("");
  const [description, setDescription] = useState("");
  const [gapType, setGapType] = useState("agent");
  const [busy, setBusy] = useState("");
  const versionsByAgent = useMemo(() => new Map(data?.versions.map((item) => [item.agent_definition_id, item]) || []), [data]);
  async function createGap(event: FormEvent) {
    event.preventDefault(); setBusy("create-gap"); setError("");
    try { await apiPost("/api/v1/agent-gaps", { title, capability, description, gap_type: gapType, source_type: "operator", source_id: "" }, { idempotencyKey: commandKey("agent-gap") }); setTitle(""); setCapability(""); setDescription(""); refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao registrar lacuna"); }
    finally { setBusy(""); }
  }
  const action = async (id: string, fn: () => Promise<unknown>) => { setBusy(id); setError(""); try { await fn(); refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na operação"); } finally { setBusy(""); } };
  if (error && !data) return <ErrorState message={error} onRetry={refresh} />;
  if (!data) return <LoadingState label="Carregando catálogo e avaliações de agentes…" />;
  const activeAssignments = data.assignments.filter((item) => item.status === "active").length;
  return <div className="space-y-6"><PageHeader eyebrow="Autonomia governada" title="Agent Studio" description="Agentes tenant-private são propostos pela IA, avaliados três vezes e só recebem versão imutável após decisão humana." actions={<RefreshButton onClick={refresh} />} />{error ? <ErrorState message={error} /> : null}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Agentes aprovados" value={data.definitions.filter((item) => item.status === "approved").length} icon={<Bot className="h-5 w-5" />} /><MetricCard label="Alocações ativas" value={activeAssignments} /><MetricCard label="Lacunas abertas" value={data.gaps.filter((item) => !["resolved", "rejected"].includes(item.status)).length} /><MetricCard label="Aguardando decisão" value={data.candidates.filter((item) => item.status === "ready_for_approval").length} /></div>
    <div className="grid gap-5 2xl:grid-cols-[390px_minmax(0,1fr)]"><Surface className="p-5"><h2 className="text-base font-semibold">Registrar lacuna</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Lacunas de ferramenta ficam bloqueadas para engenharia; nenhum agente pode criar executáveis.</p><form onSubmit={createGap} className="mt-5 space-y-4"><label className="grid gap-2 text-sm"><span>Nome</span><input required value={title} onChange={(event) => setTitle(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Ex.: Analista regulatório" /></label><label className="grid gap-2 text-sm"><span>Capacidade</span><input required value={capability} onChange={(event) => setCapability(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="regulatory_assessment" /></label><label className="grid gap-2 text-sm"><span>Tipo</span><select value={gapType} onChange={(event) => setGapType(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="agent">Agente</option><option value="tool">Ferramenta</option></select></label><label className="grid gap-2 text-sm"><span>Contexto</span><textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-lg border px-3 py-3" /></label><button disabled={busy !== ""} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14]"><AlertTriangle className="h-4 w-4" /> Registrar lacuna</button></form></Surface>
      <div className="space-y-5"><Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Lacunas e candidatos</h2></div>{data.gaps.length ? <div className="divide-y divide-line">{data.gaps.map((gap) => {
        const candidate = data.candidates.find((item) => item.capability_gap_id === gap.id);
        const evaluation = candidate ? data.evaluations.find((item) => item.candidate_id === candidate.id) : undefined;
        return <article key={gap.id} className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><h3 className="text-sm font-semibold">{gap.title}</h3><StatusBadge status={gap.status} /></div><p className="mt-1 text-xs text-[rgb(var(--muted))]">{gap.capability} · {gap.gap_type}</p></div><div className="flex flex-wrap gap-2">{gap.gap_type === "agent" && !candidate ? <button disabled={busy !== ""} onClick={() => void action(gap.id, () => apiPost(`/api/v1/agent-gaps/${gap.id}/generate-candidate`, { constraints: "Use apenas tools allowlisted e mantenha contexto tenant-private." }, { idempotencyKey: commandKey("agent-candidate") }))} className="min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white">Gerar candidato</button> : null}{candidate?.status === "draft" ? <button disabled={busy !== ""} onClick={() => void action(candidate.id, () => apiPost(`/api/v1/agent-candidates/${candidate.id}/evaluate`, undefined, { idempotencyKey: commandKey("agent-evaluate") }))} className="min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white">Avaliar 3×</button> : null}{candidate?.status === "ready_for_approval" ? <><button disabled={busy !== ""} onClick={() => void action(candidate.id, () => apiPost(`/api/v1/agent-candidates/${candidate.id}/decisions`, { decision: "approve", comment: "Avaliação revisada e agente homologado pelo operador." }, { idempotencyKey: commandKey("agent-approve") }))} className="min-h-11 rounded-lg bg-emerald-500 px-3 text-xs font-semibold text-[#07110A]">Homologar</button><button disabled={busy !== ""} onClick={() => void action(candidate.id, () => apiPost(`/api/v1/agent-candidates/${candidate.id}/decisions`, { decision: "reject", comment: "Candidato não atende à necessidade operacional." }, { idempotencyKey: commandKey("agent-reject") }))} className="min-h-11 rounded-lg border border-red-500/40 px-3 text-xs text-red-200">Rejeitar</button></> : null}</div></div>{candidate ? <div className="mt-4 rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="flex items-center justify-between gap-3"><div><div className="text-xs font-semibold">{candidate.proposed_definition_json.name || "Candidato"}</div><p className="mt-1 text-[11px] text-[rgb(var(--muted))]">{candidate.proposed_definition_json.purpose}</p></div><StatusBadge status={candidate.status} /></div>{evaluation ? <div className="mt-3 flex items-center gap-3 text-[10px] text-[rgb(var(--muted))]"><StatusBadge status={evaluation.status} /><span>{evaluation.repetitions} repetições</span><span>{Math.round(Number(evaluation.metrics_json.schema_valid_rate || 0) * 100)}% schemas válidos</span></div> : null}</div> : null}</article>;
      })}</div> : <div className="p-5"><EmptyState title="Nenhuma lacuna registrada" description="Os agentes base já estão disponíveis; registre apenas capacidades realmente ausentes." /></div>}</Surface>
      <Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Catálogo aprovado do tenant</h2></div><div className="grid gap-3 p-4 md:grid-cols-2">{data.definitions.map((agent) => { const version = versionsByAgent.get(agent.id); return <article key={agent.id} className="rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold">{agent.name}</h3><p className="mt-1 text-xs text-[rgb(var(--muted))]">{agent.purpose}</p></div><StatusBadge status={agent.status} /></div><div className="mt-4 flex flex-wrap gap-2 text-[10px] text-[rgb(var(--muted))]"><span className="rounded-full border border-line px-2 py-1">{agent.scope}</span>{version ? <><span className="rounded-full border border-line px-2 py-1">v{version.version}</span><span className="rounded-full border border-line px-2 py-1">{version.model_role}</span></> : null}</div></article>; })}</div></Surface></div>
    </div>
  </div>;
}
