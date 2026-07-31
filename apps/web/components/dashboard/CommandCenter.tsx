"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, ListTodo, ShieldAlert, Users } from "lucide-react";

import { OperationalGuidance } from "@/components/common/OperationalGuidance";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import type { Engagement, OperatorOverview, OperationalGuidance as Guidance, ReviewInbox, ServiceDeliverable, ServicePortfolio } from "@/lib/contracts";
import { BROWSER_SESSION_RETRY_EVENT, getBrowserSession, requestBrowserSessionRetry, type BrowserSession } from "@/lib/session-client";


const reviewerRoles = new Set(["client_sponsor", "process_owner", "reviewer", "auditor"]);
type DecisionTask = { id: string; stage: string; title: string; detail: string; href: string; action: string; guidance?: Guidance | null };

export function CommandCenter() {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [servicePortfolio, setServicePortfolio] = useState<ServicePortfolio | null>(null);
  const [overview, setOverview] = useState<OperatorOverview | null>(null);
  const [reviewInbox, setReviewInbox] = useState<ReviewInbox | null>(null);
  const [engagements, setEngagements] = useState<Engagement[] | null>(null);
  const [serviceDeliverables, setServiceDeliverables] = useState<ServiceDeliverable[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const retry = () => setReloadKey((value) => value + 1);
    window.addEventListener(BROWSER_SESSION_RETRY_EVENT, retry);
    return () => window.removeEventListener(BROWSER_SESSION_RETRY_EVENT, retry);
  }, []);

  useEffect(() => {
    setLoading(true);
    setError("");
    getBrowserSession()
      .then(async (value) => {
        setSession(value);
        if (value.me.role === "engagement_manager") {
          const [inbox, engagementData, deliverableData] = await Promise.all([
            apiGet<ReviewInbox>("/api/v1/review/inbox"),
            apiGet<Engagement[]>("/api/v1/engagements"),
            apiGet<ServiceDeliverable[]>("/api/v1/service-deliverables"),
          ]);
          setReviewInbox(inbox);
          setEngagements(engagementData);
          setServiceDeliverables(deliverableData);
        } else if (reviewerRoles.has(value.me.role)) {
          setReviewInbox(await apiGet<ReviewInbox>("/api/v1/review/inbox"));
        } else {
          const [serviceData, overviewData] = await Promise.all([
            apiGet<ServicePortfolio>("/api/v1/operator/service-portfolio"),
            apiGet<OperatorOverview>("/api/v1/operator/overview"),
          ]);
          setServicePortfolio(serviceData);
          setOverview(overviewData);
        }
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Não foi possível carregar a próxima ação."))
      .finally(() => setLoading(false));
  }, [reloadKey]);

  const pendingReview = useMemo(() => reviewInbox?.items.filter((item) => item.status === "pending") || [], [reviewInbox]);
  const vpTasks = useMemo<DecisionTask[]>(() => {
    const pendingPlans = engagements?.filter((item) => item.status === "awaiting_approval" && item.latest_plan?.status === "draft") || [];
    const technical = pendingReview.filter((item) => item.resource_type !== "service_deliverable");
    const deliverables = serviceDeliverables || [];
    return [
      ...pendingPlans.map((item) => ({ id: `plan:${item.id}`, stage: "Plano", title: item.name, detail: `Plano v${item.latest_plan?.version} · ${item.offering?.name || "Oferta contratada"}`, href: `/engagements/${item.id}`, action: "Revisar plano", guidance: item.guidance })),
      ...technical.map((item) => ({ id: `review:${item.id}`, stage: "Qualidade", title: item.title, detail: `Gates e evidências · risco ${item.risk_level}`, href: `/approvals?item=${item.id}`, action: "Validar evidências" })),
      ...deliverables.filter((item) => item.status === "review_ready").map((item) => ({ id: `deliverable:${item.id}`, stage: "Entregável", title: item.title, detail: `${item.engagement?.name || "Engajamento"} · revisão ${item.current_revision}`, href: `/deliverables/${item.id}`, action: "Validar entregável", guidance: item.guidance })),
      ...deliverables.filter((item) => item.status === "approved").map((item) => ({ id: `delivery:${item.id}`, stage: "Entrega", title: item.title, detail: "Conteúdo aprovado · confirmação final pendente", href: `/deliverables/${item.id}`, action: "Confirmar entrega", guidance: item.guidance })),
    ];
  }, [engagements, pendingReview, serviceDeliverables]);

  const executiveView = session?.me.role === "engagement_manager";
  const reviewerView = Boolean(session && reviewerRoles.has(session.me.role));
  const pageTitle = executiveView || reviewerView ? "Minha fila" : "Hoje";
  const pageEyebrow = executiveView ? "Governança executiva" : reviewerView ? "Workspace de decisão" : "Operação assistida";
  if (error) return <div className="space-y-6"><PageHeader eyebrow={pageEyebrow} title={pageTitle} description="A página continua disponível para você recuperar a consulta sem perder o contexto." /><ErrorState message={error} onRetry={requestBrowserSessionRetry} /></div>;
  if (loading || !session) return <div className="space-y-6"><PageHeader eyebrow={pageEyebrow} title={pageTitle} description="Estamos identificando seu papel e a próxima ação segura." /><LoadingState label="Determinando a próxima ação segura…" /></div>;

  if (session.me.role === "engagement_manager") {
    if (!reviewInbox || !engagements || !serviceDeliverables) return <ErrorState message="A fila executiva não retornou todos os dados." onRetry={() => setReloadKey((value) => value + 1)} />;
    const first = vpTasks[0];
    return <div className="space-y-6">
      <PageHeader eyebrow="Governança executiva" title="Minha fila" description="Plano → Qualidade → Entregável → Entrega. A primeira decisão segura aparece sempre no topo." />
      {first?.guidance ? <OperationalGuidance guidance={first.guidance} /> : first ? <Surface className="p-5"><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-400">Agora · {first.stage}</p><h2 className="mt-2 text-xl font-semibold">{first.title}</h2><p className="mt-2 text-sm text-[rgb(var(--muted))]">{first.detail}</p><Link href={first.href} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-[#07110A]">{first.action} <ArrowRight className="h-4 w-4" /></Link></Surface> : <EmptyState title="Nenhuma decisão aguardando você" description="O owner está produzindo ou todas as decisões já foram registradas." />}
      <div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Decisões pendentes" value={vpTasks.length} icon={<Clock3 className="h-5 w-5" />} /><MetricCard label="Entregáveis em decisão" value={serviceDeliverables.filter((item) => ["review_ready", "approved"].includes(item.status)).length} icon={<CheckCircle2 className="h-5 w-5" />} /><MetricCard label="Ordem da fila" value="4 gates" detail="Plano, qualidade, entregável e entrega" icon={<ListTodo className="h-5 w-5" />} /></div>
      {vpTasks.length > 1 ? <details className="panel p-5"><summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold">Ver as próximas {vpTasks.length - 1} decisões</summary><div className="divide-y divide-line">{vpTasks.slice(1).map((task) => <Link key={task.id} href={task.href} className="flex min-h-16 items-center justify-between gap-3 py-3 text-sm"><span><span className="block font-semibold">{task.title}</span><span className="text-xs text-[rgb(var(--muted))]">{task.stage} · {task.detail}</span></span><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div></details> : null}
    </div>;
  }

  if (reviewerRoles.has(session.me.role)) {
    const first = pendingReview[0];
    return <div className="space-y-6"><PageHeader eyebrow="Workspace de decisão" title="Minha fila" description="Somente evidências e artifacts autorizados deste cliente." />{first ? <Surface className="p-5"><h2 className="text-lg font-semibold">{first.title}</h2><p className="mt-2 text-sm text-[rgb(var(--muted))]">Risco {first.risk_level}. Confira as evidências antes de decidir.</p><Link href={`/approvals?item=${first.id}`} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white">Abrir decisão <ArrowRight className="h-4 w-4" /></Link></Surface> : <EmptyState title="Nenhuma decisão pendente" description="Novas solicitações aparecerão quando os gates permitirem revisão humana." />}</div>;
  }

  if (!overview || !servicePortfolio) return <ErrorState message="O resumo operacional não retornou todos os dados." onRetry={() => setReloadKey((value) => value + 1)} />;
  const current = overview.client;
  const attention = servicePortfolio.clients.filter((client) => client.deliverables_at_risk || client.pending_approvals || client.active_work_items).sort((a, b) => b.deliverables_at_risk - a.deliverables_at_risk);
  const totalAtRisk = servicePortfolio.clients.reduce((sum, client) => sum + client.deliverables_at_risk, 0);
  const totalWip = servicePortfolio.clients.reduce((sum, client) => sum + client.active_work_items, 0);
  const totalApprovals = servicePortfolio.clients.reduce((sum, client) => sum + client.pending_approvals, 0);

  return <div className="space-y-6">
    <PageHeader eyebrow="Operação assistida" title="Hoje" description="Comece pela próxima ação segura; detalhes técnicos permanecem em Diagnóstico." />
    {current.guidance ? <OperationalGuidance guidance={current.guidance} /> : <EmptyState title="Nenhuma ação operacional pendente" description="A carteira está estável ou ainda não há trabalho materializado." />}
    <div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Exceções de prazo" value={totalAtRisk} detail="Entregáveis vencidos sem aceite" icon={<ShieldAlert className="h-5 w-5" />} /><MetricCard label="Aprovações pendentes" value={totalApprovals} detail="Decisões humanas na carteira" icon={<CheckCircle2 className="h-5 w-5" />} /><MetricCard label="Capacidade em uso" value={totalWip} detail="Itens de serviço em andamento" icon={<Users className="h-5 w-5" />} /></div>
    <Surface><div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold">Clientes que exigem atenção</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Somente sinais operacionais autorizados; nenhum dado cru cruza tenants.</p></div>{attention.length ? <div className="divide-y divide-line">{attention.slice(0, 8).map((client) => <article key={client.tenant_id} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-center"><div><h3 className="text-sm font-semibold">{client.tenant_name}</h3><p className="mt-1 text-xs text-[rgb(var(--muted))]">{client.active_engagements} engajamentos ativos</p></div><span className="text-xs text-red-300">{client.deliverables_at_risk} em risco</span><span className="text-xs text-[rgb(var(--muted))]">{client.pending_approvals} aprovações</span><Link href={`/clients/${client.tenant_id}`} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-3 text-xs font-semibold">Abrir cliente <ArrowRight className="h-4 w-4" /></Link></article>)}</div> : <div className="p-5"><EmptyState title="Nenhum cliente exige atenção" description="Não há atraso, aprovação ou WIP ativo na carteira acessível." /></div>}</Surface>
  </div>;
}
