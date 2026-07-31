"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ClipboardCheck, FileText, RotateCcw, ShieldCheck, XCircle } from "lucide-react";

import { MarkdownViewer } from "@/components/common/MarkdownViewer";
import { EmptyState, ErrorState, LoadingState, MetricCard, Surface } from "@/components/common/OperationalUI";
import { apiGet, apiPost } from "@/lib/api";
import type { Engagement, ReviewInbox, ReviewInboxItem, ServiceDeliverable } from "@/lib/contracts";
import { fmtDate } from "@/lib/format";
import { getBrowserSession, type BrowserSession } from "@/lib/session-client";
import { StatusBadge } from "@/lib/status";


type Artifact = { id: string; name: string; content: string; audience: string; evidence_classification: string };
type Gate = { id: string; name: string; status: string; score: number; blockers_json: string[] };
type ReviewDetail = {
  approval: ReviewInboxItem;
  review: null | {
    run: { id: string; status: string; current_phase: string; homologation_readiness_score: number | null };
    quality_gates: Gate[];
    traceability: unknown[];
    artifacts: Artifact[];
    packages: { id: string; status: string; manifest_json: Record<string, unknown> }[];
    reports: { id: string; status: string; summary: string; blockers_json: string[] }[];
  };
};

export function ReviewCenter() {
  const searchParams = useSearchParams();
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [inbox, setInbox] = useState<ReviewInbox | null>(null);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [serviceDeliverables, setServiceDeliverables] = useState<ServiceDeliverable[]>([]);
  const [selectedId, setSelectedId] = useState(searchParams.get("item") || "");
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadInbox(preferred = selectedId) {
    const data = await apiGet<ReviewInbox>("/api/v1/review/inbox");
    setInbox(data);
    const reviewItems = data.items.filter((item) => item.resource_type !== "service_deliverable");
    const preferredReviewId = reviewItems.some((item) => item.id === preferred) ? preferred : "";
    const nextId = preferredReviewId || reviewItems.find((item) => item.status === "pending")?.id || reviewItems[0]?.id || "";
    setSelectedId(nextId);
    if (nextId) setDetail(await apiGet<ReviewDetail>(`/api/v1/review/items/${nextId}`));
    else setDetail(null);
  }

  useEffect(() => {
    setLoading(true);
    setError("");
    getBrowserSession()
      .then(async (value) => {
        setSession(value);
        const tasks: Promise<unknown>[] = [loadInbox(searchParams.get("item") || "")];
        if (value.me.role === "engagement_manager") {
          tasks.push(apiGet<Engagement[]>("/api/v1/engagements").then(setEngagements));
          tasks.push(apiGet<ServiceDeliverable[]>("/api/v1/service-deliverables").then(setServiceDeliverables));
        }
        await Promise.all(tasks);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  async function select(item: ReviewInboxItem) {
    setSelectedId(item.id);
    setArtifact(null);
    setComment("");
    setError("");
    try { setDetail(await apiGet<ReviewDetail>(`/api/v1/review/items/${item.id}`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao abrir aprovação"); }
  }

  async function decide(decision: "approve" | "reject" | "changes_requested") {
    if (!selectedId) return;
    if ((decision === "reject" || decision === "changes_requested") && !comment.trim()) {
      setError("Informe um comentário para rejeitar ou solicitar mudanças.");
      return;
    }
    setDeciding(true);
    setError("");
    setMessage("");
    try {
      await apiPost(`/api/v1/review/items/${selectedId}/decisions`, { decision, comment: comment.trim() }, { idempotencyKey: crypto.randomUUID() });
      setMessage("Decisão registrada no ledger.");
      setComment("");
      await loadInbox(selectedId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível registrar a decisão");
    } finally {
      setDeciding(false);
    }
  }

  const reviewItems = useMemo(() => inbox?.items.filter((item) => item.resource_type !== "service_deliverable") || [], [inbox]);
  const pending = useMemo(() => reviewItems.filter((item) => item.status === "pending").length, [reviewItems]);
  const approved = useMemo(() => reviewItems.filter((item) => item.status === "approved").length, [reviewItems]);
  const pendingPlans = useMemo(() => engagements.filter((item) => item.status === "awaiting_approval" && item.latest_plan?.status === "draft"), [engagements]);
  const deliverableDecisions = useMemo(() => serviceDeliverables.filter((item) => ["review_ready", "approved"].includes(item.status)), [serviceDeliverables]);
  const blockers = detail?.review?.quality_gates.filter((gate) => ["blocked", "failed"].includes(gate.status)).length || 0;
  if (error && !session) return <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} />;
  if (loading) return <LoadingState label="Carregando fila de decisão…" />;
  if (!session) return <ErrorState message="A sessão não está disponível." onRetry={() => setReloadKey((value) => value + 1)} />;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Pendentes" value={pending + pendingPlans.length + deliverableDecisions.length} detail="Planos, qualidade, entregáveis e entrega" icon={<ClipboardCheck className="h-5 w-5" />} />
        <MetricCard label="Aprovadas" value={approved} detail="Decisões registradas" icon={<CheckCircle2 className="h-5 w-5" />} />
        <MetricCard label="Bloqueios técnicos" value={blockers} detail="Não podem ser anulados por aprovação" icon={<AlertTriangle className="h-5 w-5" />} />
        <MetricCard label="HRS" value={detail?.review?.run.homologation_readiness_score == null ? "—" : Number(detail.review.run.homologation_readiness_score).toFixed(0)} detail="Score calculado da missão selecionada" icon={<ShieldCheck className="h-5 w-5" />} />
      </div>
      {error ? <ErrorState message={error} onRetry={() => setReloadKey((value) => value + 1)} /> : null}
      {message ? <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200" role="status">{message}</div> : null}
      {session.me.role === "engagement_manager" ? <Surface>
        <div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold text-ink">Planos de serviço</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Sua aprovação libera o owner para materializar e executar a entrega.</p></div>
        {pendingPlans.length ? <div className="divide-y divide-line">{pendingPlans.map((engagement) => <Link key={engagement.id} href={`/engagements/${engagement.id}`} className="flex min-h-20 items-center justify-between gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))]"><div className="min-w-0"><div className="truncate text-sm font-semibold text-ink">{engagement.name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">Plano v{engagement.latest_plan?.version} · revisão executiva pendente</div></div><span className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-500 px-3 text-xs font-semibold text-[#07110A]">Revisar plano <ArrowRight className="h-3.5 w-3.5" /></span></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum plano pendente" description="A fila será atualizada quando o owner concluir um planejamento." /></div>}
      </Surface> : null}
      {session.me.role === "engagement_manager" ? <Surface>
        <div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold text-ink">Entregáveis de serviço</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">A decisão acontece no próprio entregável para manter conteúdo, evidências, status e ledger sincronizados.</p></div>
        {deliverableDecisions.length ? <div className="divide-y divide-line">{deliverableDecisions.map((item) => <Link key={item.id} href={`/deliverables/${item.id}`} className="grid min-h-20 gap-3 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div className="min-w-0"><div className="truncate text-sm font-semibold text-ink">{item.title}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{item.engagement?.name || "Engajamento"} · revisão {item.current_revision} · {item.status === "review_ready" ? "validar conteúdo" : "confirmar entrega"}</div></div><span className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-500 px-3 text-xs font-semibold text-[#07110A]">{item.status === "review_ready" ? "Validar entregável" : "Confirmar entrega"} <ArrowRight className="h-3.5 w-3.5" /></span></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum entregável aguardando o VP" description="Itens aparecem aqui depois que o owner os submete ou quando aguardam confirmação final de entrega." /></div>}
      </Surface> : null}

      <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Surface className="overflow-hidden">
          <div className="border-b border-line px-4 py-4"><h2 className="text-sm font-semibold text-ink">Qualidade e artifacts</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">{reviewItems.length} solicitações técnicas</p></div>
          {reviewItems.length ? <div className="max-h-[70vh] divide-y divide-line overflow-y-auto">{reviewItems.map((item) => <button key={item.id} onClick={() => void select(item)} className={`flex min-h-20 w-full items-center justify-between gap-3 px-4 py-3 text-left ${selectedId === item.id ? "bg-blue-500/10" : "hover:bg-[rgb(var(--panel-raised))]"}`}><div className="min-w-0"><div className="truncate text-sm font-semibold text-ink">{item.title}</div><div className="mt-1 flex items-center gap-2 text-[11px] text-[rgb(var(--muted))]"><StatusBadge status={item.status} /><span>{fmtDate(item.created_at)}</span></div></div><ArrowRight className="h-4 w-4 shrink-0 text-blue-400" /></button>)}</div> : <div className="p-4"><EmptyState title="Nenhuma revisão técnica" description="Planos e entregáveis permanecem nas filas executivas acima." /></div>}
        </Surface>

        <div className="space-y-5">
          {detail ? <>
            <Surface className="p-5"><div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex items-center gap-2"><StatusBadge status={detail.approval.status} /><span className="text-xs text-[rgb(var(--muted))]">Risco {detail.approval.risk_level}</span></div><h2 className="mt-3 text-lg font-semibold text-ink">{detail.approval.title}</h2><p className="mt-2 text-sm leading-6 text-[rgb(var(--muted))]">{detail.approval.description}</p></div></div></Surface>
            {detail.review ? <div className="grid gap-5 2xl:grid-cols-2">
              <Surface><div className="border-b border-line px-4 py-3 text-sm font-semibold text-ink">Quality gates</div><div className="divide-y divide-line">{detail.review.quality_gates.map((gate) => <div key={gate.id} className="flex items-center justify-between gap-3 px-4 py-3 text-xs"><div><div className="font-semibold text-ink">{gate.name}</div><div className="mt-1 text-[rgb(var(--muted))]">Score {Number(gate.score).toFixed(0)}</div></div><StatusBadge status={gate.status} /></div>)}</div></Surface>
              <Surface><div className="border-b border-line px-4 py-3 text-sm font-semibold text-ink">Artifacts autorizados</div>{detail.review.artifacts.length ? <div className="divide-y divide-line">{detail.review.artifacts.map((item) => <button key={item.id} onClick={() => setArtifact(item)} className="flex min-h-14 w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[rgb(var(--panel-raised))]"><span className="flex min-w-0 items-center gap-2 text-sm font-medium text-ink"><FileText className="h-4 w-4 shrink-0 text-blue-400" /><span className="truncate">{item.name}</span></span><span className="text-[10px] uppercase text-[rgb(var(--muted))]">{item.audience}</span></button>)}</div> : <div className="p-4"><EmptyState title="Nenhum artifact liberado" description="Artifacts internos não são expostos neste workspace." /></div>}</Surface>
            </div> : null}
            {artifact ? <Surface className="p-4"><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold text-ink">{artifact.name}</h3><button onClick={() => setArtifact(null)} className="min-h-11 rounded-lg px-3 text-xs text-[rgb(var(--muted))]">Fechar</button></div><MarkdownViewer content={artifact.content} /></Surface> : null}
            {detail.approval.status === "pending" ? <Surface className="p-5"><label className="grid gap-2 text-sm"><span className="font-medium text-ink">Comentário da decisão</span><textarea rows={4} value={comment} onChange={(event) => setComment(event.target.value)} className="rounded-lg border px-3 py-3" placeholder="Contexto, restrições ou mudanças necessárias…" /></label><div className="mt-4 grid gap-2 sm:grid-cols-3"><button disabled={deciding || blockers > 0} onClick={() => void decide("approve")} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 text-sm font-semibold text-white disabled:opacity-40"><CheckCircle2 className="h-4 w-4" /> Aprovar</button><button disabled={deciding} onClick={() => void decide("changes_requested")} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 text-sm font-semibold text-amber-200"><RotateCcw className="h-4 w-4" /> Solicitar mudanças</button><button disabled={deciding} onClick={() => void decide("reject")} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 text-sm font-semibold text-red-200"><XCircle className="h-4 w-4" /> Rejeitar</button></div>{blockers > 0 ? <p className="mt-3 text-xs text-red-300">A aprovação está bloqueada por gates técnicos.</p> : null}</Surface> : null}
          </> : <Surface className="p-5"><EmptyState title="Selecione uma aprovação" description="Escolha um item da fila para conferir suas evidências." /></Surface>}
        </div>
      </div>
    </div>
  );
}
