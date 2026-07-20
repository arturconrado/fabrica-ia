"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BookOpen, CheckCircle2, Clock3, Coins, Gauge, LockKeyhole, ShieldAlert, Sparkles, Trophy, Users } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Provenance, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import type { GamificationProfile, OperatorOverview, PortfolioResponse, ReviewInbox, ServicePortfolio } from "@/lib/contracts";
import { fmtDate } from "@/lib/format";
import { getBrowserSession, type BrowserSession } from "@/lib/session-client";


const reviewerRoles = new Set(["client_sponsor", "process_owner", "reviewer", "auditor"]);

export function CommandCenter() {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [servicePortfolio, setServicePortfolio] = useState<ServicePortfolio | null>(null);
  const [overview, setOverview] = useState<OperatorOverview | null>(null);
  const [gamification, setGamification] = useState<GamificationProfile | null>(null);
  const [reviewInbox, setReviewInbox] = useState<ReviewInbox | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getBrowserSession()
      .then(async (value) => {
        setSession(value);
        const reviewer = reviewerRoles.has(value.me.role);
        if (reviewer) {
          const [inbox, profile] = await Promise.all([
            apiGet<ReviewInbox>("/api/v1/review/inbox"),
            apiGet<GamificationProfile>("/api/v1/gamification/profile")
          ]);
          setReviewInbox(inbox);
          setGamification(profile);
        } else {
          const [portfolioData, serviceData, overviewData, profile] = await Promise.all([
            apiGet<PortfolioResponse>("/api/v1/operator/portfolio"),
            apiGet<ServicePortfolio>("/api/v1/operator/service-portfolio"),
            apiGet<OperatorOverview>("/api/v1/operator/overview"),
            apiGet<GamificationProfile>("/api/v1/gamification/profile")
          ]);
          setPortfolio(portfolioData);
          setServicePortfolio(serviceData);
          setOverview(overviewData);
          setGamification(profile);
        }
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const pendingReview = useMemo(() => reviewInbox?.items.filter((item) => item.status === "pending") || [], [reviewInbox]);
  if (error) return <ErrorState message={error} />;
  if (!session || !gamification || ((!portfolio || !servicePortfolio) && !reviewInbox)) return <LoadingState label="Sincronizando command center com o ledger…" />;

  if (reviewerRoles.has(session.me.role)) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Workspace de decisão" title="Sua fila de aprovação" description="Somente evidências e artifacts autorizados deste cliente são exibidos aqui." actions={<Link className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-blue-500 px-4 text-sm font-semibold text-white" href="/approvals">Abrir aprovações <ArrowRight className="h-4 w-4" /></Link>} />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Pendências" value={pendingReview.length} detail="Decisões aguardando sua análise" icon={<Clock3 className="h-5 w-5" />} />
          <MetricCard label="Nível do cliente" value={gamification.level.name} detail={`${gamification.xp_total} XP auditável`} icon={<Trophy className="h-5 w-5" />} />
          <MetricCard label="Conquistas" value={gamification.achievements.filter((item) => item.unlocked).length} detail="Marcos comprovados pelo ledger" icon={<CheckCircle2 className="h-5 w-5" />} />
          <MetricCard label="Isolamento" value="Ativo" detail="Dados limitados ao tenant atual" icon={<LockKeyhole className="h-5 w-5" />} />
        </div>
        <Surface className="p-4 sm:p-5">
          {pendingReview.length ? <div className="divide-y divide-line">{pendingReview.map((item) => <Link key={item.id} href={`/approvals?item=${item.id}`} className="flex min-h-16 items-center justify-between gap-4 py-3"><div><div className="text-sm font-semibold text-ink">{item.title}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">Risco {item.risk_level} · {fmtDate(item.created_at)}</div></div><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div> : <EmptyState title="Nenhuma decisão pendente" description="Novas solicitações aparecerão aqui quando os gates técnicos permitirem revisão humana." />}
        </Surface>
      </div>
    );
  }

  const current = overview?.client;
  const clientCount = servicePortfolio?.clients.length || 0;
  const totalActive = portfolio?.clients.reduce((sum, client) => sum + client.active_runs, 0) || 0;
  const totalEngagements = servicePortfolio?.clients.reduce((sum, client) => sum + client.active_engagements, 0) || 0;
  const totalAtRisk = servicePortfolio?.clients.reduce((sum, client) => sum + client.deliverables_at_risk, 0) || 0;
  const totalWip = servicePortfolio?.clients.reduce((sum, client) => sum + client.active_work_items, 0) || 0;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Operação multi-tenant" title="Command Center" description="Priorize a próxima ação de cada cliente sem atravessar a fronteira de seus dados." actions={<Link className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] shadow-lg shadow-orange-500/15" href="/mvp-factory"><Sparkles className="h-4 w-4" /> Nova missão</Link>} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Clientes acessíveis" value={clientCount} detail="Memberships operacionais ativas" icon={<Users className="h-5 w-5" />} />
        <MetricCard label="Engajamentos ativos" value={totalEngagements} detail={`${totalActive} runs técnicas ativas`} icon={<Gauge className="h-5 w-5" />} />
        <MetricCard label="WIP do operador" value={totalWip} detail="Itens em andamento nos clientes" icon={<Clock3 className="h-5 w-5" />} />
        <MetricCard label="Entregáveis em risco" value={totalAtRisk} detail="Prazo vencido sem aceite" icon={<ShieldAlert className="h-5 w-5" />} />
      </div>

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.7fr)_minmax(330px,0.7fr)]">
        <Surface>
          <div className="flex items-center justify-between border-b border-line px-4 py-4 sm:px-5"><div><h2 className="text-sm font-semibold text-ink">Portfólio de clientes</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Somente resumos operacionais autorizados</p></div><LockKeyhole className="h-4 w-4 text-emerald-400" /></div>
          <div className="divide-y divide-line">
            {servicePortfolio?.clients.map((client) => (
              <article key={client.tenant_id} className={`grid gap-4 px-4 py-4 sm:px-5 xl:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(90px,.5fr))_minmax(160px,.8fr)] xl:items-center ${client.tenant_id === session.active_tenant_id ? "bg-blue-500/[0.06]" : ""}`}>
                <div className="min-w-0"><div className="flex items-center gap-2"><h3 className="truncate text-sm font-semibold text-ink">{client.tenant_name}</h3>{client.tenant_id === session.active_tenant_id ? <span className="rounded-full bg-blue-500/15 px-2 py-1 text-[10px] font-semibold text-blue-300">ATIVO</span> : null}</div><div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--muted))]"><span>{client.contracted_offerings} ofertas</span><span>·</span><span>{client.active_runs} runs</span><span>·</span><span>{client.pending_approvals} aprovações</span></div></div>
                <div><div className="text-lg font-semibold text-ink">{client.active_engagements}</div><div className="text-[11px] text-[rgb(var(--muted))]">engajamentos</div></div>
                <div><div className={`text-lg font-semibold ${client.deliverables_at_risk ? "text-red-300" : "text-ink"}`}>{client.deliverables_at_risk}</div><div className="text-[11px] text-[rgb(var(--muted))]">em risco</div></div>
                <div><div className="flex items-center gap-2 text-lg font-semibold text-ink">{client.latest_hrs == null ? "—" : client.latest_hrs.toFixed(0)} <Provenance value="calculated" /></div><div className="text-[11px] text-[rgb(var(--muted))]">HRS mais recente</div></div>
                <div className="xl:text-right"><Link href={`/clients/${client.tenant_id}`} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-300">{client.next_commitment?.title || "Abrir Cliente 360"}<ArrowRight className="h-3.5 w-3.5" /></Link></div>
              </article>
            ))}
            {!servicePortfolio?.clients.length ? <div className="p-5"><EmptyState title="Nenhum cliente acessível" description="Use o onboarding assistido para criar o primeiro tenant e conceder membership ao operador." /></div> : null}
          </div>
        </Surface>

        <div className="space-y-5">
          <Surface className="p-5">
            <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-400">Maturidade</p><h2 className="mt-2 text-xl font-semibold text-ink">{gamification.level.name}</h2></div><Trophy className="h-6 w-6 text-amber-300" /></div>
            <div className="mt-5 flex items-end justify-between"><span className="text-3xl font-semibold text-ink">{gamification.xp_total}</span><span className="text-xs text-[rgb(var(--muted))]">{gamification.level.next_threshold ? `${gamification.level.next_threshold} XP para o próximo nível` : "Nível máximo"}</span></div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[rgb(var(--panel-soft))]"><div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-cyan-400" style={{ width: `${gamification.level.progress_percent}%` }} /></div>
            <div className="mt-5 grid grid-cols-5 gap-2" aria-label="Conquistas">{gamification.achievements.map((achievement) => <div key={achievement.code} title={achievement.name} className={`flex aspect-square items-center justify-center rounded-lg border ${achievement.unlocked ? "border-amber-400/30 bg-amber-400/10 text-amber-300" : "border-line bg-[rgb(var(--panel-soft))] text-[rgb(var(--muted))] opacity-50"}`}><CheckCircle2 className="h-4 w-4" /><span className="sr-only">{achievement.name}: {achievement.unlocked ? "conquistada" : "bloqueada"}</span></div>)}</div>
          </Surface>
          <Surface className="p-5">
            <div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-ink">Cliente ativo</h2><BookOpen className="h-4 w-4 text-blue-400" /></div>
            <div className="mt-4 text-sm font-semibold text-ink">{current?.tenant_name || "—"}</div>
            <dl className="mt-4 space-y-3 text-xs"><div className="flex justify-between gap-3"><dt className="text-[rgb(var(--muted))]">Knowledge bases</dt><dd className="font-semibold text-ink">{current?.knowledge_bases ?? "—"}</dd></div><div className="flex justify-between gap-3"><dt className="text-[rgb(var(--muted))]">Documentos indexados</dt><dd className="font-semibold text-ink">{current?.knowledge_documents ?? "—"}</dd></div><div className="flex justify-between gap-3"><dt className="text-[rgb(var(--muted))]">Custo do modelo</dt><dd className="flex items-center gap-2 font-semibold text-ink">{current?.model_cost_usd.value == null ? "Sem uso registrado" : `$ ${current.model_cost_usd.value.toFixed(4)}`} {current ? <Provenance value={current.model_cost_usd.provenance} /> : null}</dd></div></dl>
          </Surface>
        </div>
      </div>

      <Surface>
        <div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold text-ink">Atividade recente do tenant ativo</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Sequência imutável do ledger</p></div>
        {overview?.recent_events.length ? <div className="divide-y divide-line">{overview.recent_events.slice(0, 10).map((event) => <div key={event.id} className="grid min-w-0 gap-2 px-5 py-3 text-xs sm:grid-cols-[72px_minmax(0,1fr)_auto]"><span className="min-w-0 break-all font-mono text-[rgb(var(--muted))]">#{event.tenant_sequence}</span><div className="min-w-0"><div className="break-words font-semibold text-ink">{event.event_type}</div><div className="mt-1 break-words text-[rgb(var(--muted))]">{String(event.payload_json.summary || event.aggregate_type)}</div></div><span className="min-w-0 break-words text-[rgb(var(--muted))]">{fmtDate(event.created_at)}</span></div>)}</div> : <div className="p-5"><EmptyState title="Ledger sem eventos" description="Os eventos reais aparecerão após o primeiro onboarding ou missão." /></div>}
      </Surface>
    </div>
  );
}
