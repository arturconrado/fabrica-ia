"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { ArrowRight, Boxes, Plus, Trash2 } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet, apiPost } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";


type Project = { id: string; name: string };
type Batch = { id: string; name: string; status: string; total_items: number; completed_items: number; failed_items: number; created_at: string };
type ItemDraft = { id: string; project_id: string; demand: string };

export function BatchList() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [name, setName] = useState("");
  const [items, setItems] = useState<ItemDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [projectRows, batchRows] = await Promise.all([apiGet<Project[]>("/projects"), apiGet<Batch[]>("/batches")]);
      setProjects(projectRows);
      setBatches(batchRows);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao carregar batches"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  function addItem() {
    setItems((current) => [...current, { id: crypto.randomUUID(), project_id: projects[0]?.id || "", demand: "" }]);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await apiPost<Batch>("/batches", { name: name.trim(), items: items.map(({ project_id, demand }) => ({ project_id, demand: demand.trim() })) });
      setName("");
      setItems([]);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao iniciar batch"); }
    finally { setSubmitting(false); }
  }

  if (loading) return <LoadingState label="Carregando execuções reais…" />;
  const active = batches.filter((batch) => ["running", "pending"].includes(batch.status)).length;
  const completed = batches.reduce((sum, batch) => sum + Number(batch.completed_items || 0), 0);
  const failed = batches.reduce((sum, batch) => sum + Number(batch.failed_items || 0), 0);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Orquestração" title="Execuções em lote" description="Agrupe demandas reais de projetos existentes; nenhum projeto é criado implicitamente." />
      <div className="grid gap-3 sm:grid-cols-3"><MetricCard label="Batches ativos" value={active} icon={<Boxes className="h-5 w-5" />} /><MetricCard label="Itens concluídos" value={completed} /><MetricCard label="Itens com falha" value={failed} /></div>
      {error ? <ErrorState message={error} /> : null}
      <div className="grid gap-5 2xl:grid-cols-[420px_minmax(0,1fr)]">
        <Surface className="p-5"><h2 className="text-sm font-semibold text-ink">Novo batch</h2><p className="mt-1 text-xs text-[rgb(var(--muted))]">Selecione projetos persistidos e informe a demanda de cada execução.</p><form onSubmit={submit} className="mt-5 space-y-4"><label className="grid gap-2 text-sm"><span className="font-medium">Nome</span><input required value={name} onChange={(event) => setName(event.target.value)} className="min-h-11 rounded-lg border px-3" placeholder="Identificação operacional" /></label><div className="space-y-3">{items.map((item, index) => <div key={item.id} className="rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-3"><div className="mb-3 flex items-center justify-between"><span className="text-xs font-semibold text-ink">Item {index + 1}</span><button type="button" onClick={() => setItems((current) => current.filter((row) => row.id !== item.id))} className="flex h-11 w-11 items-center justify-center rounded-lg text-red-300" aria-label={`Remover item ${index + 1}`}><Trash2 className="h-4 w-4" /></button></div><select required value={item.project_id} onChange={(event) => setItems((current) => current.map((row) => row.id === item.id ? { ...row, project_id: event.target.value } : row))} className="min-h-11 w-full rounded-lg border px-3"><option value="">Selecione o projeto</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><textarea required minLength={10} rows={4} value={item.demand} onChange={(event) => setItems((current) => current.map((row) => row.id === item.id ? { ...row, demand: event.target.value } : row))} className="mt-3 w-full rounded-lg border px-3 py-2" placeholder="Demanda desta execução…" /></div>)}</div><button type="button" disabled={!projects.length || items.length >= 10} onClick={addItem} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-line text-sm text-[rgb(var(--muted))]"><Plus className="h-4 w-4" /> Adicionar projeto</button><button disabled={submitting || !items.length} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-500 text-sm font-semibold text-white disabled:opacity-40"><Boxes className="h-4 w-4" /> {submitting ? "Agendando…" : "Iniciar batch"}</button></form></Surface>
        <Surface><div className="border-b border-line px-5 py-4 text-sm font-semibold text-ink">Histórico</div>{batches.length ? <div className="divide-y divide-line">{batches.map((batch) => <Link key={batch.id} href={`/batches/${batch.id}`} className="grid min-h-20 gap-3 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] sm:grid-cols-[minmax(0,1fr)_100px_120px_28px] sm:items-center"><div><div className="text-sm font-semibold text-ink">{batch.name}</div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{fmtDate(batch.created_at)}</div></div><StatusBadge status={batch.status} /><div className="text-xs text-[rgb(var(--muted))]">{batch.completed_items}/{batch.total_items} concluídos</div><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum batch" description="Crie um lote somente quando houver projetos reais a executar." /></div>}</Surface>
      </div>
    </div>
  );
}
