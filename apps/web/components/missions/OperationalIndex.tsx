"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, ListChecks } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

type EntityKind = "program" | "opportunity" | "component" | "mvp_run" | "run";
type Entity = {
  id: string;
  name?: string | null;
  title?: string | null;
  demand?: string | null;
  component_code?: string | null;
  status: string;
  stage?: string | null;
  current_phase?: string | null;
  progress?: number | null;
  created_at: string;
  project?: { name?: string | null } | null;
  prospect?: { company?: string | null; name?: string | null } | null;
  opportunity?: { title?: string | null } | null;
  definition?: { name?: string | null } | null;
};

const activeStatuses = new Set(["active", "running", "working", "queued", "in_progress", "waiting_for_human"]);

function primaryLabel(item: Entity, kind: EntityKind): string {
  if (kind === "component") return item.definition?.name || item.component_code || "Componente sem nome";
  if (kind === "mvp_run") return item.opportunity?.title || "MVP run sem título";
  if (kind === "run") return item.demand || "Run sem demanda";
  return item.name || item.title || "Registro sem título";
}

function secondaryLabel(item: Entity, kind: EntityKind): string {
  if (kind === "run") return item.project?.name || "Projeto não informado";
  if (kind === "opportunity") return item.prospect?.company || item.prospect?.name || "Prospect não informado";
  if (kind === "component") return item.current_phase || item.component_code || "Etapa não iniciada";
  if (kind === "mvp_run") return item.current_phase || "Etapa não iniciada";
  return item.stage || item.current_phase || "Sem etapa registrada";
}

export function OperationalIndex({ endpoint, title, description, emptyDescription, hrefPrefix, kind }: { endpoint: string; title: string; description: string; emptyDescription: string; hrefPrefix: string; kind: EntityKind }) {
  const [items, setItems] = useState<Entity[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { apiGet<Entity[]>(endpoint).then(setItems).catch((reason: Error) => setError(reason.message)); }, [endpoint]);
  if (error) return <ErrorState message={error} />;
  if (!items) return <LoadingState label={`Carregando ${title.toLocaleLowerCase("pt-BR")} do tenant…`} />;
  const active = items.filter((item) => activeStatuses.has(item.status)).length;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Dados persistidos" title={title} description={description} />
      <div className="grid gap-3 sm:grid-cols-2">
        <MetricCard label="Registros" value={items.length} icon={<ListChecks className="h-5 w-5" />} detail="Consulta vinculada ao tenant ativo" />
        <MetricCard label="Em andamento" value={active} detail="Calculado pelos status persistidos" />
      </div>
      <Surface>
        {items.length ? <div className="divide-y divide-line">{items.map((item) => (
          <Link key={item.id} href={`${hrefPrefix}/${item.id}`} className="grid min-h-20 gap-3 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] sm:grid-cols-[minmax(0,1fr)_140px_120px_28px] sm:items-center">
            <div className="min-w-0"><div className="truncate text-sm font-semibold text-ink">{primaryLabel(item, kind)}</div><div className="mt-1 truncate text-xs text-[rgb(var(--muted))]">{secondaryLabel(item, kind)}</div></div>
            <StatusBadge status={item.status} />
            <span className="text-xs text-[rgb(var(--muted))]">{fmtDate(item.created_at)}</span>
            <ArrowRight className="h-4 w-4 text-blue-400" />
          </Link>
        ))}</div> : <div className="p-5"><EmptyState title={`${title}: nenhum registro`} description={emptyDescription} /></div>}
      </Surface>
    </div>
  );
}
