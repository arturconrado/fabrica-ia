"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Boxes,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  Gauge,
  Layers3,
  LockKeyhole,
  Play,
  RefreshCw,
  Send,
  Sparkles,
  Users,
} from "lucide-react";

import { MarkdownViewer } from "@/components/common/MarkdownViewer";
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
  ServiceOffering,
  ServicePortfolio,
  WorkItem,
} from "@/lib/contracts";
import { fmtDate } from "@/lib/format";
import { getBrowserSession, type BrowserSession } from "@/lib/session-client";
import { StatusBadge } from "@/lib/status";


type Contract = { id: string; contract_number: string; status: string; scope_summary: string };
type Program = { id: string; name: string; status: string };
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
  outcomes: ClientOverview["outcomes"];
  agent_assignments: AgentCatalog["assignments"];
  events: Array<{ id: string; event_type: string; tenant_sequence: number; created_at: string; payload_json: { summary?: string } }>;
};

function useResource<T>(loader: () => Promise<T>, dependencies: ReadonlyArray<unknown> = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    setError("");
    loader().then(setData).catch((reason: Error) => setError(reason.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, nonce]);
  return { data, error, refresh: () => setNonce((value) => value + 1), setError };
}

function RefreshButton({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 text-sm text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))]"><RefreshCw className="h-4 w-4" /> Atualizar</button>;
}

export function ServiceCatalogView() {
  const { data, error, refresh } = useResource(() => apiGet<ServiceOffering[]>("/api/v1/service-catalog/offerings"));
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando catálogo operacional…" />;
  return <div className="space-y-6">
    <PageHeader eyebrow="Portfólio versionado" title="Catálogo de serviços" description="Oito ofertas operacionais com etapas, entregáveis, Definition of Done e capacidades contratuais imutáveis por versão." actions={<RefreshButton onClick={refresh} />} />
    <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
      {data.map((offering) => <Surface key={offering.id} className="flex min-h-[330px] flex-col p-5">
        <div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-400">{offering.category.replaceAll("_", " ")}</p><h2 className="mt-2 text-lg font-semibold text-ink">{offering.name}</h2></div><span className="rounded-full border border-line px-2 py-1 text-[10px] text-[rgb(var(--muted))]">v{offering.version}</span></div>
        <p className="mt-3 text-sm leading-6 text-[rgb(var(--muted))]">{offering.description}</p>
        <div className="mt-4 flex flex-wrap gap-2 text-[11px]"><span className="rounded-full bg-blue-500/10 px-2.5 py-1 text-blue-300">{offering.duration_label}</span><span className="rounded-full bg-[rgb(var(--panel-soft))] px-2.5 py-1 text-[rgb(var(--muted))]">{offering.cadence === "monthly" ? "Mensal" : "Pontual"}</span></div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2"><div><h3 className="text-xs font-semibold text-ink">Etapas</h3><ol className="mt-2 space-y-1 text-xs text-[rgb(var(--muted))]">{offering.definition.stages?.slice(0, 6).map((stage, index) => <li key={stage}>{index + 1}. {stage}</li>)}</ol></div><div><h3 className="text-xs font-semibold text-ink">Entregáveis</h3><ul className="mt-2 space-y-1 text-xs text-[rgb(var(--muted))]">{offering.definition.deliverables?.slice(0, 5).map((item) => <li key={item}>• {item}</li>)}</ul></div></div>
        <div className="mt-auto pt-5"><Link href={`/engagements?offering=${offering.version_id}`} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white">Criar engajamento <ArrowRight className="h-4 w-4" /></Link></div>
      </Surface>)}
    </div>
  </div>;
}

export function ClientsView() {
  const { data, error, refresh } = useResource(() => apiGet<ServicePortfolio>("/api/v1/operator/service-portfolio"));
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando carteira autorizada…" />;
  const totalRisk = data.clients.reduce((sum, item) => sum + item.deliverables_at_risk, 0);
  const totalReview = data.clients.reduce((sum, item) => sum + item.deliverables_in_review, 0);
  return <div className="space-y-6"><PageHeader eyebrow="Carteira autorizada" title="Clientes" description="Resumo operacional por membership; nenhum conteúdo de negócio ou conhecimento é agregado entre tenants." actions={<RefreshButton onClick={refresh} />} />
    <div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Clientes acessíveis" value={data.clients.length} icon={<Users className="h-5 w-5" />} /><MetricCard label="Entregáveis em risco" value={totalRisk} icon={<AlertTriangle className="h-5 w-5" />} /><MetricCard label="Aguardando revisão" value={totalReview} icon={<ClipboardCheck className="h-5 w-5" />} /></div>
    {data.clients.length ? <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">{data.clients.map((client) => <Surface key={client.tenant_id} className="p-5"><div className="flex items-start justify-between gap-3"><div><h2 className="text-base font-semibold">{client.tenant_name}</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">{client.contracted_offerings} ofertas · {client.active_engagements} engajamentos ativos</p></div>{client.deliverables_at_risk ? <span className="rounded-full bg-red-500/10 px-2 py-1 text-[10px] font-semibold text-red-300">{client.deliverables_at_risk} EM RISCO</span> : <span className="rounded-full bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-300">SEM ATRASO</span>}</div><div className="mt-5 grid grid-cols-3 gap-2"><div className="rounded-lg bg-[rgb(var(--panel-soft))] p-3"><div className="text-lg font-semibold">{client.active_work_items}</div><div className="text-[10px] text-[rgb(var(--muted))]">WIP</div></div><div className="rounded-lg bg-[rgb(var(--panel-soft))] p-3"><div className="text-lg font-semibold">{client.deliverables_in_review}</div><div className="text-[10px] text-[rgb(var(--muted))]">revisões</div></div><div className="rounded-lg bg-[rgb(var(--panel-soft))] p-3"><div className="text-lg font-semibold">{client.latest_hrs == null ? "—" : Math.round(client.latest_hrs)}</div><div className="text-[10px] text-[rgb(var(--muted))]">HRS</div></div></div><div className="mt-4 min-h-14 rounded-lg border border-line p-3"><div className="text-[10px] uppercase tracking-wide text-[rgb(var(--muted))]">Próximo compromisso</div><div className="mt-1 text-xs font-semibold">{client.next_commitment?.title || "Sem compromisso pendente"}</div></div><Link href={`/clients/${client.tenant_id}`} className="mt-4 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white">Abrir Cliente 360 <ArrowRight className="h-4 w-4" /></Link></Surface>)}</div> : <EmptyState title="Nenhum cliente acessível" description="Conclua o onboarding e atribua membership operacional ao usuário." />}
  </div>;
}

export function EngagementsView() {
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
  const [offeringId, setOfferingId] = useState("");
  const [programId, setProgramId] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao criar engajamento");
    } finally { setSubmitting(false); }
  }

  if (error && !data) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando engajamentos…" />;
  return <div className="space-y-6">
    <PageHeader eyebrow="Serviços em operação" title="Engajamentos" description="Instâncias reais das ofertas contratadas, adaptadas por cliente sem alterar o catálogo global." actions={<RefreshButton onClick={refresh} />} />
    {error ? <ErrorState message={error} /> : null}
    <div className="grid gap-5 2xl:grid-cols-[390px_minmax(0,1fr)]">
      <Surface className="p-5"><h2 className="text-base font-semibold text-ink">Novo engajamento</h2><p className="mt-1 text-xs leading-5 text-[rgb(var(--muted))]">A ativação só ocorrerá após plano AI, aprovação humana, contrato ativo e entitlement.</p>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="grid gap-2 text-sm"><span className="font-medium">Nome</span><input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Ex.: Discovery — Operações 2026" /></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Oferta</span><select required value={offeringId} onChange={(event) => setOfferingId(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="">Selecione</option>{data.offerings.map((item) => <option key={item.version_id} value={item.version_id}>{item.name} · v{item.version}</option>)}</select></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Contrato</span><select required value={contractId} onChange={(event) => setContractId(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="">Selecione</option>{data.contracts.map((item) => <option key={item.id} value={item.id}>{item.contract_number} · {item.status}</option>)}</select></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Programa</span><select value={programId} onChange={(event) => setProgramId(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="">Sem programa</option>{data.programs.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="grid gap-2 text-sm"><span className="font-medium">Contexto</span><textarea rows={5} maxLength={10_000} value={description} onChange={(event) => setDescription(event.target.value)} className="rounded-lg border px-3 py-3" placeholder="Objetivo, áreas, restrições e resultado esperado" /></label>
          <button disabled={submitting} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-60"><BriefcaseBusiness className="h-4 w-4" />{submitting ? "Registrando…" : "Criar rascunho"}</button>
        </form>
      </Surface>
      <Surface>{data.engagements.length ? <div className="divide-y divide-line">{data.engagements.map((item) => <Link key={item.id} href={`/engagements/${item.id}`} className="grid min-h-24 gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] md:grid-cols-[minmax(0,1fr)_140px_repeat(2,90px)_28px] md:items-center"><div className="min-w-0"><h2 className="truncate text-sm font-semibold text-ink">{item.name}</h2><p className="mt-1 truncate text-xs text-[rgb(var(--muted))]">{item.offering?.name || "Oferta não carregada"} · {item.sponsor || "Sponsor pendente"}</p></div><StatusBadge status={item.status} /><div><div className="text-sm font-semibold">{item.counts?.deliverables || 0}</div><div className="text-[10px] text-[rgb(var(--muted))]">entregáveis</div></div><div><div className="text-sm font-semibold">{item.counts?.agent_assignments || 0}</div><div className="text-[10px] text-[rgb(var(--muted))]">agentes</div></div><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum engajamento" description="Selecione uma oferta e um contrato para estruturar a primeira operação deste cliente." /></div>}</Surface>
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

function EngagementTeamAndOutcomes({ data, refresh, reportError }: { data: EngagementWorkspaceData; refresh: () => void; reportError: (message: string) => void }) {
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

  return <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(330px,.75fr)]">
    <div className="space-y-5">
      <Surface className="p-5"><div className="flex items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">Resultados e valor realizado</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Baseline, meta, observação e proveniência permanecem auditáveis.</p></div><Provenance value="real" /></div>{data.outcomes.length ? <div className="mt-4 grid gap-3 md:grid-cols-2">{data.outcomes.map((metric) => <div key={metric.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-4"><div className="text-xs font-semibold">{metric.name}</div><div className="mt-2 text-xl font-semibold">{metric.current_value ?? "—"} <span className="text-xs font-normal text-[rgb(var(--muted))]">{metric.unit}</span></div><div className="mt-2 text-[10px] text-[rgb(var(--muted))]">baseline {metric.baseline_value ?? "—"} · meta {metric.target_value ?? "—"} · {metric.provenance}</div></div>)}</div> : <EmptyState title="Nenhum resultado registrado" description="Cadastre a baseline e a meta antes de declarar valor realizado." />}</Surface>
      <Surface className="p-5"><h2 className="text-sm font-semibold">Equipe AI aprovada</h2><div className="mt-4 grid gap-3 md:grid-cols-2">{data.agent_assignments.length ? data.agent_assignments.map((assignment) => <div key={assignment.id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="text-xs font-semibold">{assignment.agent?.name || "Versão aprovada"}</div><div className="mt-1 text-[10px] text-[rgb(var(--muted))]">{assignment.agent?.code} · v{assignment.agent?.version} · US$ {assignment.ai_budget_usd.toFixed(2)}</div></div>) : <p className="text-xs text-[rgb(var(--muted))]">Nenhum agente alocado.</p>}</div></Surface>
    </div>
    <Surface className="p-5"><h2 className="text-sm font-semibold">Nova métrica</h2><form onSubmit={createOutcome} className="mt-4 space-y-3"><input required value={name} onChange={(event) => setName(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Nome da métrica" /><div className="grid grid-cols-2 gap-3"><input value={baseline} onChange={(event) => setBaseline(event.target.value)} type="number" step="any" className="min-h-11 rounded-lg border px-3 text-sm" placeholder="Baseline" /><input value={target} onChange={(event) => setTarget(event.target.value)} type="number" step="any" className="min-h-11 rounded-lg border px-3 text-sm" placeholder="Meta" /></div><input required value={unit} onChange={(event) => setUnit(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Unidade" /><input required value={source} onChange={(event) => setSource(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Referência da fonte" /><button disabled={busy} className="min-h-11 w-full rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Registrando…" : "Registrar baseline"}</button></form></Surface>
  </div>;
}

export function EngagementWorkspace({ engagementId }: { engagementId: string }) {
  const { data, error, refresh, setError } = useResource(() => apiGet<EngagementWorkspaceData>(`/api/v1/engagements/${engagementId}`), [engagementId]);
  const [brief, setBrief] = useState("");
  const [knowledgeIds, setKnowledgeIds] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => {
    const stream = new EventSource(`${API_BASE}/api/v1/client-operations/events`);
    stream.onmessage = () => refresh();
    return () => stream.close();
    // refresh is intentionally bound to this workspace instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagementId]);
  const call = async (kind: string, action: () => Promise<unknown>) => { setBusy(kind); setError(""); try { await action(); refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na operação"); } finally { setBusy(""); } };
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Montando workspace do engajamento…" />;
  const plan = data.latest_plan;
  return <div className="space-y-6">
    <PageHeader eyebrow={data.offering?.name || "Engajamento"} title={data.name} description={data.description || "Operação adaptada ao contrato e ao contexto deste cliente."} actions={<><StatusBadge status={data.status} /><RefreshButton onClick={refresh} /></>} />
    {error ? <ErrorState message={error} /> : null}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Entregáveis" value={data.counts?.deliverables || 0} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard label="Concluídos" value={data.counts?.deliverables_completed || 0} icon={<CheckCircle2 className="h-5 w-5" />} /><MetricCard label="Workstreams" value={data.counts?.workstreams || 0} icon={<Layers3 className="h-5 w-5" />} /><MetricCard label="Equipe AI" value={data.counts?.agent_assignments || 0} icon={<Bot className="h-5 w-5" />} /></div>
    {data.status === "active" ? <EngagementTeamAndOutcomes data={data} refresh={refresh} reportError={setError} /> : null}
    {data.status === "draft" || (data.status === "awaiting_approval" && !plan) ? <Surface className="p-5"><h2 className="text-base font-semibold">Adaptar oferta com IA</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">O modelo deve preservar os entregáveis contratados. Nenhum plano será ativado sem sua aprovação.</p><div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]"><textarea value={brief} onChange={(event) => setBrief(event.target.value)} minLength={20} rows={6} className="rounded-lg border px-3 py-3" placeholder="Áreas, objetivos, restrições, stakeholders e critérios específicos…" /><div className="space-y-3"><input value={knowledgeIds} onChange={(event) => setKnowledgeIds(event.target.value)} className="min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="IDs das knowledge bases, separados por vírgula" /><button disabled={busy !== "" || brief.trim().length < 20} onClick={() => void call("plan", () => apiPost(`/api/v1/engagements/${data.id}/plans/generate`, { expected_version: data.record_version, adaptation_brief: brief, knowledge_base_ids: knowledgeIds.split(",").map((item) => item.trim()).filter(Boolean) }, { idempotencyKey: commandKey("engagement-plan") }))} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-50"><Sparkles className="h-4 w-4" />{busy === "plan" ? "Gerando…" : "Gerar plano"}</button></div></div></Surface> : null}
    {plan ? <Surface className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[.16em] text-blue-400">Plano v{plan.version}</p><h2 className="mt-2 text-lg font-semibold">{plan.plan_json.summary || "Plano do engajamento"}</h2>{plan.model_call_id ? <p className="mt-2 text-[10px] text-[rgb(var(--muted))]">Model call {plan.model_call_id}</p> : null}</div><StatusBadge status={plan.status} /></div><div className="mt-5 grid gap-5 lg:grid-cols-3"><div><h3 className="text-xs font-semibold">Etapas</h3><ol className="mt-2 space-y-2 text-xs text-[rgb(var(--muted))]">{plan.plan_json.stages?.map((item, index) => <li key={item}>{index + 1}. {item}</li>)}</ol></div><div><h3 className="text-xs font-semibold">Workstreams</h3><div className="mt-2 space-y-2">{plan.plan_json.workstreams?.map((item) => <div key={item.key} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="text-xs font-semibold">{item.name}</div><p className="mt-1 text-[11px] text-[rgb(var(--muted))]">{item.objective}</p></div>)}</div></div><div><h3 className="text-xs font-semibold">Riscos</h3><ul className="mt-2 space-y-2 text-xs text-[rgb(var(--muted))]">{plan.plan_json.risks?.map((item) => <li key={item} className="flex gap-2"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />{item}</li>)}</ul></div></div>{plan.status === "draft" ? <button disabled={busy !== ""} onClick={() => void call("approve", () => apiPost(`/api/v1/engagements/${data.id}/plans/${plan.version}/approve`, { expected_version: data.record_version, comment: "Plano revisado e aprovado pelo operador." }, { idempotencyKey: commandKey("engagement-plan-approve") }))} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-[#07110A]"><CheckCircle2 className="h-4 w-4" /> Aprovar plano</button> : null}{plan.status === "approved" && data.status !== "active" ? <button disabled={busy !== ""} onClick={() => void call("activate", () => apiPost(`/api/v1/engagements/${data.id}/activate`, { expected_version: data.record_version, comment: "Ativação confirmada pelo operador." }, { idempotencyKey: commandKey("engagement-activate") }))} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white"><Play className="h-4 w-4" /> Ativar operação</button> : null}</Surface> : null}
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
  async function transition(item: WorkItem, status: string) {
    if (!data || item.tenant_id !== data.session.active_tenant_id) return;
    setBusy(item.id); setError("");
    try {
      await apiPost(`/api/v1/service-work-items/${item.id}/transitions`, {
        status, expected_version: item.record_version, reason: "", override_reason: "",
      }, { idempotencyKey: commandKey("work-item-transition") });
      refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na transição"); }
    finally { setBusy(""); }
  }
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Priorizando fila dos clientes…" />;
  const { capacity, queue, session } = data;
  return <div className="space-y-6">
    <PageHeader eyebrow="WIP governado" title="Fila e capacidade" description="Prioridade, SLA e bloqueios dos clientes acessíveis. Ações detalhadas só ocorrem após selecionar o tenant correspondente." actions={<RefreshButton onClick={refresh} />} />
    {error ? <ErrorState message={error} /> : null}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="WIP global" value={`${capacity.active_total}/${capacity.global_limit}`} detail="Limite determinístico" icon={<Gauge className="h-5 w-5" />} /><MetricCard label="Slots disponíveis" value={capacity.available_slots} icon={<Boxes className="h-5 w-5" />} /><MetricCard label="Em fila" value={queue.items.filter((item) => item.status === "queued").length} icon={<CalendarClock className="h-5 w-5" />} /><MetricCard label="Bloqueados" value={queue.items.filter((item) => item.status === "blocked").length} icon={<AlertTriangle className="h-5 w-5" />} /></div>
    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,.65fr)]"><Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Próximas ações</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Bloqueios, prioridade e prazo ordenados no servidor</p></div>{queue.items.length ? <div className="divide-y divide-line">{queue.items.map((item) => {
      const activeTenant = item.tenant_id === session.active_tenant_id;
      return <article key={item.id} className={`grid gap-3 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_110px_120px_190px] lg:items-center ${activeTenant ? "bg-blue-500/[0.04]" : ""}`}><div className="min-w-0"><div className="flex items-center gap-2"><h3 className="truncate text-sm font-semibold">{item.title}</h3>{activeTenant ? <span className="rounded-full bg-blue-500/15 px-2 py-1 text-[9px] font-semibold text-blue-300">TENANT ATIVO</span> : null}</div><p className="mt-1 truncate text-xs text-[rgb(var(--muted))]">{item.tenant_name} · {item.engagement_name}</p>{item.blocked_reason ? <p className="mt-2 text-xs text-red-300">{item.blocked_reason}</p> : null}</div><StatusBadge status={item.status} /><div className="text-xs text-[rgb(var(--muted))]">{item.due_at ? fmtDate(item.due_at) : "Sem prazo"}</div><div className="flex justify-end gap-2">{activeTenant && item.status === "queued" ? <button disabled={busy === item.id} onClick={() => void transition(item, "in_progress")} className="min-h-11 rounded-lg bg-blue-500 px-3 text-xs font-semibold text-white">Iniciar</button> : null}{activeTenant && item.status === "in_progress" ? <button disabled={busy === item.id} onClick={() => void transition(item, "completed")} className="min-h-11 rounded-lg bg-emerald-500 px-3 text-xs font-semibold text-[#07110A]">Concluir</button> : null}{!activeTenant && item.tenant_id ? <Link href={`/clients/${item.tenant_id}`} className="inline-flex min-h-11 items-center rounded-lg border border-line px-3 text-xs">Selecionar cliente</Link> : null}</div></article>;
    })}</div> : <div className="p-5"><EmptyState title="Fila vazia" description="Work items serão materializados após ativação de um plano aprovado." /></div>}</Surface><Surface className="p-5"><h2 className="text-sm font-semibold">Capacidade por cliente</h2><div className="mt-4 space-y-3">{capacity.tenants.map((tenant) => <div key={tenant.tenant_id} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="flex items-center justify-between"><div className="text-xs font-semibold">{tenant.tenant_name}</div><span className="text-[10px] text-[rgb(var(--muted))]">{tenant.active}/{tenant.limit}</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[rgb(var(--panel))]"><div className={`h-full rounded-full ${tenant.over_capacity ? "bg-red-500" : "bg-blue-500"}`} style={{ width: `${Math.min(100, tenant.limit ? tenant.active / tenant.limit * 100 : 0)}%` }} /></div><div className="mt-2 text-[10px] text-[rgb(var(--muted))]">{tenant.queued} em fila · {tenant.blocked} bloqueados</div></div>)}</div></Surface></div>
  </div>;
}

export function ServiceDeliverablesView() {
  const { data, error, refresh } = useResource(() => apiGet<ServiceDeliverable[]>("/api/v1/service-deliverables"));
  const [filter, setFilter] = useState("all");
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando portfólio de entregáveis…" />;
  const visible = filter === "all" ? data : data.filter((item) => item.status === filter);
  return <div className="space-y-6"><PageHeader eyebrow="Entregas de negócio" title="Entregáveis" description="Cada item pertence a um cliente, oferta e engajamento; revisions, artifacts, evidências e model calls permanecem rastreáveis." actions={<RefreshButton onClick={refresh} />} />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Total" value={data.length} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard label="Em produção" value={data.filter((item) => item.status === "in_progress").length} /><MetricCard label="Em revisão" value={data.filter((item) => item.status === "review_ready").length} /><MetricCard label="Aprovados" value={data.filter((item) => ["approved", "delivered"].includes(item.status)).length} /></div>
    <Surface><div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Portfólio isolado do tenant ativo</h2><label className="flex items-center gap-2 text-xs text-[rgb(var(--muted))]">Status<select value={filter} onChange={(event) => setFilter(event.target.value)} className="min-h-11 rounded-lg border px-3"><option value="all">Todos</option><option value="planned">Planejado</option><option value="in_progress">Em produção</option><option value="review_ready">Em revisão</option><option value="approved">Aprovado</option><option value="delivered">Entregue</option></select></label></div>{visible.length ? <div className="divide-y divide-line">{visible.map((item) => <Link key={item.id} href={`/deliverables/${item.id}`} className="grid min-h-24 gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] lg:grid-cols-[minmax(0,1fr)_180px_120px_100px_28px] lg:items-center"><div className="min-w-0"><h2 className="truncate text-sm font-semibold">{item.title}</h2><p className="mt-1 truncate text-xs text-[rgb(var(--muted))]">{item.engagement?.name} · {item.offering?.name}</p></div><div className="text-xs text-[rgb(var(--muted))]">{item.due_at ? fmtDate(item.due_at) : "Sem prazo"}</div><StatusBadge status={item.status} /><div><div className="text-sm font-semibold">v{item.current_revision}</div><div className="text-[10px] text-[rgb(var(--muted))]">revisão</div></div><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum entregável neste estado" description="Entregáveis aparecem após a ativação do plano do engajamento." /></div>}</Surface>
  </div>;
}

export function DeliverablesExperience() {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getBrowserSession().then(setSession).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <ErrorState message={error} />;
  if (!session) return <LoadingState label="Carregando experiência de entrega…" />;
  if (["client_sponsor", "process_owner", "reviewer", "auditor"].includes(session.me.role)) return <DeliverablesCenter />;
  return <ServiceDeliverablesView />;
}

export function ServiceDeliverableWorkspace({ deliverableId }: { deliverableId: string }) {
  const { data, error, refresh, setError } = useResource(() => apiGet<ServiceDeliverable>(`/api/v1/service-deliverables/${deliverableId}`), [deliverableId]);
  const [instructions, setInstructions] = useState("");
  const [knowledgeIds, setKnowledgeIds] = useState("");
  const [busy, setBusy] = useState("");
  const [comment, setComment] = useState("");
  const act = async (kind: string, fn: () => Promise<unknown>) => { setBusy(kind); setError(""); try { await fn(); refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha na operação"); } finally { setBusy(""); } };
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando entregável e evidências…" />;
  const latest = data.latest_revision;
  return <div className="space-y-6"><PageHeader eyebrow={data.offering?.name || "Entregável"} title={data.title} description={data.description} actions={<><StatusBadge status={data.status} /><RefreshButton onClick={refresh} /></>} />{error ? <ErrorState message={error} /> : null}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Revisão" value={data.current_revision || "—"} /><MetricCard label="Audiência" value={data.audience} icon={<Users className="h-5 w-5" />} /><MetricCard label="Prazo" value={data.due_at ? fmtDate(data.due_at) : "—"} icon={<CalendarClock className="h-5 w-5" />} /><MetricCard label="Proveniência" value={latest?.model_call_id ? "IA rastreada" : latest ? "Operador" : "—"} icon={<LockKeyhole className="h-5 w-5" />} /></div>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(350px,.65fr)]"><Surface className="p-5">{latest?.content_json.content_markdown ? <><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">{latest.content_json.title || data.title}</h2><p className="mt-1 text-[10px] text-[rgb(var(--muted))]">Revision {latest.revision} · {latest.model_call_id ? `model call ${latest.model_call_id}` : "entrada humana"}</p></div><Provenance value={latest.model_call_id ? "real" : "declared"} /></div><MarkdownViewer content={latest.content_json.content_markdown} /></> : <EmptyState title="Conteúdo ainda não produzido" description="Gere uma revisão com IA usando apenas contexto autorizado ou registre uma revisão manual pela API." />}</Surface>
      <div className="space-y-5"><Surface className="p-5"><h2 className="text-sm font-semibold">Produção assistida</h2><p className="mt-1 text-xs leading-5 text-[rgb(var(--muted))]">A saída será persistida como nova revisão; ausência de evidência será explicitada pelo modelo.</p><textarea rows={4} value={instructions} onChange={(event) => setInstructions(event.target.value)} className="mt-4 w-full rounded-lg border px-3 py-3 text-sm" placeholder="Orientações específicas para esta revisão" /><input value={knowledgeIds} onChange={(event) => setKnowledgeIds(event.target.value)} className="mt-3 min-h-11 w-full rounded-lg border px-3 text-sm" placeholder="Knowledge base IDs, separados por vírgula" /><button disabled={busy !== "" || ["approved", "delivered"].includes(data.status)} onClick={() => void act("generate", () => apiPost(`/api/v1/service-deliverables/${data.id}/revisions/generate`, { instructions, knowledge_base_ids: knowledgeIds.split(",").map((item) => item.trim()).filter(Boolean) }, { idempotencyKey: commandKey("deliverable-generate") }))} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-50"><Sparkles className="h-4 w-4" />{busy === "generate" ? "Gerando…" : "Gerar nova revisão"}</button></Surface>
        <Surface className="p-5"><h2 className="text-sm font-semibold">Definition of Done</h2><ul className="mt-3 space-y-2">{data.definition_of_done_json.map((item) => <li key={item} className="flex gap-2 text-xs text-[rgb(var(--muted))]"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />{item}</li>)}</ul></Surface>
        {data.status === "in_progress" && latest ? <Surface className="p-5"><h2 className="text-sm font-semibold">Submeter à revisão humana</h2><textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} className="mt-3 w-full rounded-lg border px-3 py-3 text-sm" placeholder="Resumo para o aprovador" /><button disabled={busy !== ""} onClick={() => void act("submit", () => apiPost(`/api/v1/service-deliverables/${data.id}/submit`, { expected_version: data.record_version, comment }, { idempotencyKey: commandKey("deliverable-submit") }))} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white"><Send className="h-4 w-4" /> Submeter</button></Surface> : null}
        {data.status === "review_ready" ? <Surface className="p-5"><h2 className="text-sm font-semibold">Decisão humana</h2><textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} className="mt-3 w-full rounded-lg border px-3 py-3 text-sm" placeholder="Comentário da decisão" /><div className="mt-3 grid grid-cols-3 gap-2"><button onClick={() => void act("approve", () => apiPost(`/api/v1/service-deliverables/${data.id}/decisions`, { decision: "approve", comment, expected_version: data.record_version }, { idempotencyKey: commandKey("deliverable-approve") }))} className="min-h-11 rounded-lg bg-emerald-500 text-xs font-semibold text-[#07110A]">Aprovar</button><button onClick={() => void act("changes", () => apiPost(`/api/v1/service-deliverables/${data.id}/decisions`, { decision: "changes_requested", comment, expected_version: data.record_version }, { idempotencyKey: commandKey("deliverable-changes") }))} className="min-h-11 rounded-lg border border-amber-500/40 text-xs text-amber-200">Ajustes</button><button onClick={() => void act("reject", () => apiPost(`/api/v1/service-deliverables/${data.id}/decisions`, { decision: "reject", comment, expected_version: data.record_version }, { idempotencyKey: commandKey("deliverable-reject") }))} className="min-h-11 rounded-lg border border-red-500/40 text-xs text-red-200">Rejeitar</button></div></Surface> : null}
      </div></div>
    {data.status === "approved" ? <Surface className="p-5"><div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end"><div><h2 className="text-sm font-semibold">Entrega ao cliente</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Somente a revisão aprovada por humano pode ser marcada como entregue. O comentário fica no ledger.</p></div><div><textarea rows={2} value={comment} onChange={(event) => setComment(event.target.value)} className="w-full rounded-lg border px-3 py-3 text-sm" placeholder="Canal, destinatário ou observação" /><button disabled={busy !== "" || !comment.trim()} onClick={() => void act("deliver", () => apiPost(`/api/v1/service-deliverables/${data.id}/deliver`, { expected_version: data.record_version, comment }, { idempotencyKey: commandKey("deliverable-deliver") }))} className="mt-3 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:opacity-50"><Send className="h-4 w-4" /> Marcar como entregue</button></div></div></Surface> : null}
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
  if (error && !data) return <ErrorState message={error} />;
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
