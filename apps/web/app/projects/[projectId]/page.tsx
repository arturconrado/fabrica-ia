"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export default function ProjectPage() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Dict | null>(null);
  const [runs, setRuns] = useState<Dict[]>([]);
  useEffect(() => {
    apiGet<Dict>(`/projects/${params.projectId}`).then(setProject);
    apiGet<Dict[]>("/runs").then((rows) => setRuns(rows.filter((run) => run.project_id === params.projectId)));
  }, [params.projectId]);
  return (
    <div className="space-y-4">
      <section className="panel px-4 py-4">
        <h1 className="text-xl font-semibold">{project?.name || "Project"}</h1>
        <p className="mt-1 text-sm text-slate-600">{project?.description}</p>
      </section>
      <section className="panel">
        <div className="border-b border-line px-4 py-3 font-semibold">Runs</div>
        <div className="divide-y divide-line">
          {runs.map((run) => (
            <a href={`/runs/${run.id}`} key={run.id} className="flex items-center justify-between px-4 py-3 hover:bg-slate-50">
              <span>{run.current_node}</span>
              <StatusBadge status={run.status} />
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
