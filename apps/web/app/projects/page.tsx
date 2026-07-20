"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, FolderKanban } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

type Project = { id: string; name: string; description: string; status: string; scope: string; created_at: string };

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { apiGet<Project[]>("/projects").then(setProjects).catch((reason: Error) => setError(reason.message)); }, []);
  if (error) return <ErrorState message={error} />;
  if (!projects) return <LoadingState label="Carregando projetos do tenant…" />;
  return <div className="space-y-6"><PageHeader eyebrow="Portfólio do tenant" title="Projetos" description="Projetos persistidos e suas missões associadas." /><div className="grid gap-3 sm:grid-cols-2"><MetricCard label="Projetos" value={projects.length} icon={<FolderKanban className="h-5 w-5" />} /><MetricCard label="Ativos" value={projects.filter((item) => item.status === "active").length} /></div><Surface>{projects.length ? <div className="divide-y divide-line">{projects.map((project) => <Link key={project.id} href={`/projects/${project.id}`} className="grid min-h-20 gap-3 px-5 py-4 hover:bg-[rgb(var(--panel-raised))] sm:grid-cols-[minmax(0,1fr)_120px_120px_28px] sm:items-center"><div><div className="text-sm font-semibold text-ink">{project.name}</div><div className="mt-1 line-clamp-1 text-xs text-[rgb(var(--muted))]">{project.description || "Descrição não informada"}</div></div><StatusBadge status={project.status} /><span className="text-xs text-[rgb(var(--muted))]">{fmtDate(project.created_at)}</span><ArrowRight className="h-4 w-4 text-blue-400" /></Link>)}</div> : <div className="p-5"><EmptyState title="Nenhum projeto" description="Projetos reais serão criados pelo intake ou onboarding assistido." /></div>}</Surface></div>;
}
