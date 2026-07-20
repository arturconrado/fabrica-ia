"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Activity, ArrowRight, Bot, BrainCircuit, FileCheck2, FileText, Network, PackageCheck, ShieldCheck, Wrench } from "lucide-react";

import { MarkdownViewer } from "@/components/common/MarkdownViewer";
import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Provenance, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import type { components } from "@/lib/api.generated";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";


type Artifact = { id: string; run_id?: string; name: string; content: string; artifact_type: string; audience: string; evidence_classification: string; created_at: string };
type Deliverable = { id: string; run_id: string; status: string; path: string; manifest_json: { hrs?: number; tests?: { final_status?: string }; artifacts?: unknown[] }; created_at: string };
type AgentState = { id: string; run_id: string; agent_name: string; role: string; status: string; current_sop_step: string; progress: number; updated_at: string; run?: { id: string; status: string; current_phase: string } };
type McpTool = { server_name: string; tool_name: string; transport: string; allowed: boolean; constraints?: Record<string, unknown> };
type McpInvocation = { id: string; server_name: string; tool_name: string; status: string; created_at: string };
type AIActivity = { id: string; agent_name: string; activity_type: string; resource_type: string; status: string; confidence: number; estimated_cost_usd: number | null; prompt_code: string; prompt_version: string; created_at: string; output_json?: { facts?: string[]; risks?: string[]; recommendations?: string[] } };
type AICostAnalysis = components["schemas"]["AICostAnalysisResponse"];

function useRemote<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { loader().then(setData).catch((reason: Error) => setError(reason.message)); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error };
}

export function EvidenceCenter() {
  const { data, error } = useRemote(() => apiGet<Artifact[]>("/api/v1/review/evidence"));
  const [selected, setSelected] = useState<Artifact | null>(null);
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando artifacts autorizados…" />;
  const real = data.filter((item) => item.evidence_classification === "real").length;
  return <div className="space-y-6"><PageHeader eyebrow="Proveniência" title="Evidências" description="Artifacts explicitamente classificados e liberados para revisão." /><div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Artifacts autorizados" value={data.length} icon={<FileCheck2 className="h-5 w-5" />} /><MetricCard label="Evidência real" value={real} /><MetricCard label="Demais classificações" value={data.length - real} /></div><div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]"><Surface>{data.length ? <div className="max-h-[72vh] divide-y divide-line overflow-y-auto">{data.map((item) => <button key={item.id} onClick={() => setSelected(item)} className={`flex min-h-16 w-full items-center justify-between gap-3 px-4 py-3 text-left ${selected?.id === item.id ? "bg-blue-500/10" : "hover:bg-[rgb(var(--panel-raised))]"}`}><span className="min-w-0"><span className="block truncate text-sm font-semibold text-ink">{item.name}</span><span className="mt-1 flex items-center gap-2 text-[10px] uppercase text-[rgb(var(--muted))]"><Provenance value={item.evidence_classification} /> {item.audience}</span></span><ArrowRight className="h-4 w-4 shrink-0 text-blue-400" /></button>)}</div> : <div className="p-5"><EmptyState title="Nenhuma evidência liberada" description="Artifacts internos permanecem invisíveis até entrarem em um package de revisão." /></div>}</Surface><Surface className="p-4">{selected ? <><div className="mb-3"><h2 className="text-sm font-semibold text-ink">{selected.name}</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">{fmtDate(selected.created_at)}</p></div><MarkdownViewer content={selected.content} /></> : <EmptyState title="Selecione um artifact" description="O conteúdo markdown será renderizado com HTML bruto desativado." />}</Surface></div></div>;
}

export function DeliverablesCenter() {
  const { data, error } = useRemote(() => apiGet<Deliverable[]>("/api/v1/review/deliverables"));
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando packages de entrega…" />;
  const approved = data.filter((item) => ["approved", "delivered", "approved_for_homologation"].includes(item.status)).length;
  return <div className="space-y-6"><PageHeader eyebrow="Homologação" title="Entregas" description="Packages produzidos por runs reais, com manifest e HRS persistidos." /><div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Packages" value={data.length} icon={<PackageCheck className="h-5 w-5" />} /><MetricCard label="Aprovados" value={approved} /><MetricCard label="Em revisão" value={data.length - approved} /></div><Surface>{data.length ? <div className="divide-y divide-line">{data.map((item) => <article key={item.id} className="grid min-h-24 gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_120px_100px] sm:items-center"><div><div className="text-sm font-semibold text-ink">Package {item.id.slice(0, 8)}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{fmtDate(item.created_at)} · {item.manifest_json.artifacts?.length || 0} artifacts</div></div><StatusBadge status={item.status} /><div><div className="text-sm font-semibold text-ink">{item.manifest_json.hrs == null ? "—" : Number(item.manifest_json.hrs).toFixed(0)}</div><div className="text-[10px] text-[rgb(var(--muted))]">HRS</div></div></article>)}</div> : <div className="p-5"><EmptyState title="Nenhuma entrega" description="Packages aparecerão depois da execução dos quality gates." /></div>}</Surface></div>;
}

export function AgentOperations() {
  const { data, error } = useRemote(() => apiGet<{ states: AgentState[] }>("/api/v1/operator/agents"));
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando estados reais dos agentes…" />;
  const active = data.states.filter((item) => ["working", "running"].includes(item.status)).length;
  return <div className="space-y-6"><PageHeader eyebrow="MetaGPT operating model" title="Agentes" description="Papéis e SOPs registrados pelas execuções; agentes ausentes não são sintetizados." /><div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Estados registrados" value={data.states.length} icon={<Bot className="h-5 w-5" />} /><MetricCard label="Ativos" value={active} /><MetricCard label="Runs representadas" value={new Set(data.states.map((item) => item.run_id)).size} /></div><Surface>{data.states.length ? <div className="grid gap-3 p-4 md:grid-cols-2 2xl:grid-cols-3">{data.states.map((state) => <Link key={state.id} href={`/runs/${state.run_id}`} className="rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4 hover:border-blue-500/40"><div className="flex items-start justify-between gap-3"><div><div className="text-sm font-semibold text-ink">{state.agent_name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{state.role}</div></div><StatusBadge status={state.status} /></div><div className="mt-4 h-1.5 rounded-full bg-[rgb(var(--panel))]"><div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.max(0, Math.min(100, Number(state.progress || 0)))}%` }} /></div><p className="mt-3 line-clamp-2 text-xs leading-5 text-[rgb(var(--muted))]">{state.current_sop_step || "SOP ainda não iniciado"}</p></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum estado de agente" description="Inicie uma missão para observar os papéis e handoffs reais." /></div>}</Surface></div>;
}

export function ConnectorCenter() {
  const { data, error } = useRemote(async () => { const [tools, invocations] = await Promise.all([apiGet<McpTool[]>("/mcp/tools"), apiGet<McpInvocation[]>("/mcp/invocations")]); return { tools, invocations }; });
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Consultando allowlist MCP…" />;
  return <div className="space-y-6"><PageHeader eyebrow="Integrações allowlisted" title="Conectores" description="Somente ferramentas registradas e invocações persistidas no tenant ativo." /><div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Ferramentas" value={data.tools.length} icon={<Network className="h-5 w-5" />} /><MetricCard label="Permitidas" value={data.tools.filter((item) => item.allowed !== false).length} /><MetricCard label="Invocações" value={data.invocations.length} /></div><div className="grid gap-5 xl:grid-cols-2"><Surface><div className="border-b border-line px-5 py-4 text-sm font-semibold">Registry</div>{data.tools.length ? <div className="divide-y divide-line">{data.tools.map((tool) => <div key={`${tool.server_name}:${tool.tool_name}`} className="flex min-h-16 items-center justify-between gap-3 px-5 py-3"><div><div className="flex items-center gap-2 text-sm font-semibold"><Wrench className="h-4 w-4 text-blue-400" />{tool.tool_name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{tool.server_name} · {tool.transport}</div></div><StatusBadge status={tool.allowed === false ? "blocked" : "allowed"} /></div>)}</div> : <div className="p-5"><EmptyState title="Registry vazio" description="Nenhuma ferramenta MCP está allowlisted para este tenant." /></div>}</Surface><Surface><div className="border-b border-line px-5 py-4 text-sm font-semibold">Invocações recentes</div>{data.invocations.length ? <div className="divide-y divide-line">{data.invocations.map((item) => <div key={item.id} className="flex min-h-16 items-center justify-between gap-3 px-5 py-3"><div><div className="text-sm font-semibold">{item.tool_name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{item.server_name} · {fmtDate(item.created_at)}</div></div><StatusBadge status={item.status} /></div>)}</div> : <div className="p-5"><EmptyState title="Sem invocações" description="As chamadas reais aparecerão depois do uso de um conector." /></div>}</Surface></div></div>;
}

export function AIActivityCenter() {
  const { data, error } = useRemote(async () => {
    const [activities, costs] = await Promise.all([
      apiGet<AIActivity[]>("/api/v1/ai-activity"),
      apiGet<AICostAnalysis>("/api/v1/operator/ai-cost-analysis?group_by=agent")
    ]);
    return { activities, costs };
  });
  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label="Carregando atividade de IA…" />;
  const confidence = data.activities.length ? data.activities.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / data.activities.length : null;
  const tokenTotal = data.costs.totals.prompt_tokens == null ? null : data.costs.totals.prompt_tokens + Number(data.costs.totals.completion_tokens || 0);
  return <div className="space-y-6"><PageHeader eyebrow="Governança v2.13" title="Atividade de IA" description="Invocações, roteamento, tokens e custo real atribuídos ao tenant e à operação." /><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Invocações" value={data.costs.totals.invocations || "—"} icon={<BrainCircuit className="h-5 w-5" />} detail={`${data.costs.totals.attempts || 0} tentativas`} /><MetricCard label="Tokens reais" value={tokenTotal == null ? "—" : new Intl.NumberFormat("pt-BR").format(tokenTotal)} detail={`Cache reportado: ${data.costs.totals.cache_read_tokens == null ? "—" : new Intl.NumberFormat("pt-BR").format(data.costs.totals.cache_read_tokens)}`} /><MetricCard label="Custo real" value={data.costs.totals.actual_cost_usd == null ? "—" : `$ ${data.costs.totals.actual_cost_usd.toFixed(6)}`} detail="Uso informado pelo provider" /><MetricCard label="Confiança média" value={confidence == null ? "—" : `${Math.round(confidence * 100)}%`} detail="Atividades persistidas" /></div><div className="grid gap-5 xl:grid-cols-2"><Surface><div className="border-b border-line px-5 py-4"><div className="text-sm font-semibold">Custo por agente</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">Proveniência: uso real do provider</div></div>{data.costs.groups.length ? <div className="divide-y divide-line">{data.costs.groups.map((group) => <article key={group.key} className="grid min-h-20 gap-2 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div><div className="text-sm font-semibold text-ink">{group.key}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{new Intl.NumberFormat("pt-BR").format(group.prompt_tokens + group.completion_tokens)} tokens · {group.invocations} invocações · {group.retries} retries</div></div><div className="text-sm font-semibold text-ink">$ {group.actual_cost_usd.toFixed(6)}</div></article>)}</div> : <div className="p-5"><EmptyState title="Sem custo atribuído" description="A v2.13 não inventa valores quando o provider ainda não registrou uso." /></div>}</Surface><Surface><div className="border-b border-line px-5 py-4 text-sm font-semibold">Atividades recentes</div>{data.activities.length ? <div className="divide-y divide-line">{data.activities.map((item) => <article key={item.id} className="px-5 py-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-semibold"><Activity className="h-4 w-4 text-blue-400" />{item.agent_name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{item.activity_type} · {item.resource_type} · {fmtDate(item.created_at)}</div></div><StatusBadge status={item.status} /></div>{item.output_json?.facts?.length ? <div className="mt-3 grid gap-2 md:grid-cols-2">{item.output_json.facts.slice(0, 4).map((fact, index) => <div key={`${item.id}-${index}`} className="rounded-lg border border-line bg-[rgb(var(--panel-soft))] px-3 py-2 text-xs text-[rgb(var(--muted))]">{fact}</div>)}</div> : null}</article>)}</div> : <div className="p-5"><EmptyState title="Nenhuma atividade" description="Não há atividade de IA registrada neste tenant." /></div>}</Surface></div></div>;
}
