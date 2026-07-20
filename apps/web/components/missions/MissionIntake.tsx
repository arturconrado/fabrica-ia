"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { ArrowRight, BriefcaseBusiness, Building2, FileText, Gauge, RefreshCw, Sparkles } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet, apiPost } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";


type Prospect = { id: string; name: string; company: string };
type Opportunity = {
  id: string;
  title: string;
  status: string;
  stage: string;
  priority: string;
  validation_score: number | null;
  value_potential: number | null;
  created_at: string;
  prospect?: Prospect;
  mvp_run?: { id: string } | null;
};

export function MissionIntake() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [company, setCompany] = useState("");
  const [sector, setSector] = useState("");
  const [title, setTitle] = useState("");
  const [briefing, setBriefing] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const [prospectRows, opportunityRows] = await Promise.all([
        apiGet<Prospect[]>("/api/v1/prospects"),
        apiGet<Opportunity[]>("/api/v1/opportunities")
      ]);
      setProspects(prospectRows);
      setOpportunities(opportunityRows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao carregar missões");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      const prospect = await apiPost<Prospect>("/api/v1/prospects", {
        name: company.trim(),
        company: company.trim(),
        sector: sector.trim(),
        source: "operator_ui"
      });
      const opportunity = await apiPost<Opportunity>("/api/v1/opportunities", {
        prospect_id: prospect.id,
        title: title.trim(),
        summary: briefing.trim()
      });
      await apiPost(`/api/v1/opportunities/${opportunity.id}/briefing`, { raw_text: briefing.trim() });
      await apiPost(`/api/v1/opportunities/${opportunity.id}/validate`);
      await apiPost(`/api/v1/opportunities/${opportunity.id}/scope-mvp`);
      const run = await apiPost<{ id: string }>(`/api/v1/opportunities/${opportunity.id}/generate-mvp`);
      setMessage(`Escopo e package registrados no ledger (${run.id.slice(0, 8)}).`);
      setCompany("");
      setSector("");
      setTitle("");
      setBriefing("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível criar a missão");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingState label="Carregando pipeline real…" />;

  const packages = opportunities.filter((row) => row.mvp_run).length;
  const priority = opportunities.filter((row) => row.priority === "high").length;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Intake operacional" title="Nova missão" description="Registre uma demanda real; cada passo gera artifacts e eventos auditáveis no tenant ativo." actions={<button type="button" onClick={() => void load()} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 text-sm text-[rgb(var(--muted))] hover:bg-[rgb(var(--panel-raised))]"><RefreshCw className="h-4 w-4" /> Atualizar</button>} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Clientes registrados" value={prospects.length} detail="Prospects reais deste tenant" icon={<Building2 className="h-5 w-5" />} />
        <MetricCard label="Oportunidades" value={opportunities.length} detail="Demandas no pipeline" icon={<BriefcaseBusiness className="h-5 w-5" />} />
        <MetricCard label="Prioridade alta" value={priority} detail="Classificação calculada" icon={<Gauge className="h-5 w-5" />} />
        <MetricCard label="Packages" value={packages} detail="Escopos materializados" icon={<FileText className="h-5 w-5" />} />
      </div>

      {error ? <ErrorState message={error} /> : null}
      {message ? <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200" role="status">{message}</div> : null}

      <div className="grid gap-5 2xl:grid-cols-[minmax(360px,.75fr)_minmax(0,1.25fr)]">
        <Surface className="p-5">
          <div className="mb-5"><h2 className="text-base font-semibold text-ink">Briefing da missão</h2><p className="mt-1 text-xs leading-5 text-[rgb(var(--muted))]">Os campos começam vazios e serão persistidos exatamente como informados.</p></div>
          <form onSubmit={submit} className="space-y-4">
            <label className="grid gap-2 text-sm"><span className="font-medium text-ink">Cliente</span><input required maxLength={160} value={company} onChange={(event) => setCompany(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Nome do cliente" /></label>
            <label className="grid gap-2 text-sm"><span className="font-medium text-ink">Setor</span><input maxLength={120} value={sector} onChange={(event) => setSector(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Setor ou domínio (opcional)" /></label>
            <label className="grid gap-2 text-sm"><span className="font-medium text-ink">Objetivo</span><input required maxLength={220} value={title} onChange={(event) => setTitle(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Resultado que precisa ser alcançado" /></label>
            <label className="grid gap-2 text-sm"><span className="font-medium text-ink">Contexto e critérios</span><textarea required minLength={30} maxLength={20_000} rows={8} value={briefing} onChange={(event) => setBriefing(event.target.value)} className="rounded-lg border px-3 py-3" placeholder="Problema, usuários, restrições, integrações e critérios de sucesso…" /><span className="text-right text-[11px] text-[rgb(var(--muted))]">{briefing.length}/20.000</span></label>
            <button disabled={submitting} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-orange-500 px-4 text-sm font-semibold text-[#070B14] disabled:cursor-not-allowed disabled:opacity-60"><Sparkles className="h-4 w-4" /> {submitting ? "Registrando no ledger…" : "Estruturar missão"}</button>
          </form>
        </Surface>

        <Surface>
          <div className="border-b border-line px-5 py-4"><h2 className="text-sm font-semibold text-ink">Pipeline do tenant</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Oportunidades persistidas, sem exemplos demonstrativos</p></div>
          {opportunities.length ? <div className="divide-y divide-line">{opportunities.map((opportunity) => <Link key={opportunity.id} href={`/opportunities/${opportunity.id}`} className="grid min-h-24 gap-4 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] md:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(90px,.45fr))_32px] md:items-center"><div className="min-w-0"><div className="truncate text-sm font-semibold text-ink">{opportunity.title}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{opportunity.prospect?.company || opportunity.prospect?.name || "Cliente não carregado"} · {fmtDate(opportunity.created_at)}</div></div><div><StatusBadge status={opportunity.status} /></div><div><div className="text-sm font-semibold text-ink">{opportunity.validation_score == null ? "—" : Number(opportunity.validation_score).toFixed(0)}</div><div className="text-[11px] text-[rgb(var(--muted))]">score</div></div><div><div className="text-sm font-semibold text-ink">{opportunity.stage || "—"}</div><div className="text-[11px] text-[rgb(var(--muted))]">etapa</div></div><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div> : <div className="p-5"><EmptyState title="Pipeline vazio" description="Preencha o briefing ao lado para registrar a primeira missão real deste cliente." /></div>}
        </Surface>
      </div>
    </div>
  );
}
