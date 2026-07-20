"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ClipboardCheck, FileText, RotateCcw, ShieldCheck, XCircle } from "lucide-react";

import { MarkdownViewer } from "@/components/common/MarkdownViewer";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet, apiPost } from "@/lib/api";
import type { ReviewInbox, ReviewInboxItem } from "@/lib/contracts";
import { fmtDate } from "@/lib/format";
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
  const [inbox, setInbox] = useState<ReviewInbox | null>(null);
  const [selectedId, setSelectedId] = useState(searchParams.get("item") || "");
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadInbox(preferred = selectedId) {
    const data = await apiGet<ReviewInbox>("/api/v1/review/inbox");
    setInbox(data);
    const nextId = preferred || data.items.find((item) => item.status === "pending")?.id || data.items[0]?.id || "";
    setSelectedId(nextId);
    if (nextId) setDetail(await apiGet<ReviewDetail>(`/api/v1/review/items/${nextId}`));
    else setDetail(null);
  }

  useEffect(() => {
    loadInbox(searchParams.get("item") || "")
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const pending = useMemo(() => inbox?.items.filter((item) => item.status === "pending").length || 0, [inbox]);
  const approved = useMemo(() => inbox?.items.filter((item) => item.status === "approved").length || 0, [inbox]);
  const blockers = detail?.review?.quality_gates.filter((gate) => ["blocked", "failed"].includes(gate.status)).length || 0;
  if (loading) return <LoadingState label="Carregando fila de decisão…" />;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Human-in-the-loop" title="Aprovações" description="Decida somente depois de conferir gates, rastreabilidade e artifacts autorizados." />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Pendentes" value={pending} detail="Aguardando decisão humana" icon={<ClipboardCheck className="h-5 w-5" />} />
        <MetricCard label="Aprovadas" value={approved} detail="Decisões registradas" icon={<CheckCircle2 className="h-5 w-5" />} />
        <MetricCard label="Bloqueios técnicos" value={blockers} detail="Não podem ser anulados por aprovação" icon={<AlertTriangle className="h-5 w-5" />} />
        <MetricCard label="HRS" value={detail?.review?.run.homologation_readiness_score == null ? "—" : Number(detail.review.run.homologation_readiness_score).toFixed(0)} detail="Score calculado da missão selecionada" icon={<ShieldCheck className="h-5 w-5" />} />
      </div>
      {error ? <ErrorState message={error} /> : null}
      {message ? <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200" role="status">{message}</div> : null}

      <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Surface className="overflow-hidden">
          <div className="border-b border-line px-4 py-4"><h2 className="text-sm font-semibold text-ink">Fila do tenant</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">{inbox?.items.length || 0} solicitações</p></div>
          {inbox?.items.length ? <div className="max-h-[70vh] divide-y divide-line overflow-y-auto">{inbox.items.map((item) => <button key={item.id} onClick={() => void select(item)} className={`flex min-h-20 w-full items-center justify-between gap-3 px-4 py-3 text-left ${selectedId === item.id ? "bg-blue-500/10" : "hover:bg-[rgb(var(--panel-raised))]"}`}><div className="min-w-0"><div className="truncate text-sm font-semibold text-ink">{item.title}</div><div className="mt-1 flex items-center gap-2 text-[11px] text-[rgb(var(--muted))]"><StatusBadge status={item.status} /><span>{fmtDate(item.created_at)}</span></div></div><ArrowRight className="h-4 w-4 shrink-0 text-blue-400" /></button>)}</div> : <div className="p-4"><EmptyState title="Fila vazia" description="As solicitações aparecerão quando uma etapa exigir decisão humana." /></div>}
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
