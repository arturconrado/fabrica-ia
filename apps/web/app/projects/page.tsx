"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { fmtDate } from "@/lib/format";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Dict[]>([]);
  useEffect(() => {
    apiGet<Dict[]>("/projects").then(setProjects).catch(() => setProjects([]));
  }, []);
  return (
    <div className="panel">
      <div className="border-b border-line px-4 py-3">
        <h1 className="font-semibold">Projects</h1>
      </div>
      <div className="divide-y divide-line">
        {projects.map((project) => (
          <a key={project.id} href={`/projects/${project.id}`} className="block px-4 py-3 hover:bg-slate-50">
            <div className="font-medium">{project.name}</div>
            <div className="text-sm text-slate-500">{fmtDate(project.created_at)}</div>
          </a>
        ))}
        {!projects.length && <div className="px-4 py-8 text-sm text-slate-500">No projects yet. Start an enterprise build.</div>}
      </div>
    </div>
  );
}
