import { Pause, Play, SkipForward, Square } from "lucide-react";
import { apiPost } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { fmtDate, shortId } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

export function RunHeader({ run, onReload }: { run: Dict; onReload: () => void }) {
  async function action(path: string) {
    await apiPost(path);
    onReload();
  }

  return (
    <section className="panel px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span>Run {shortId(run.id)}</span>
            <StatusBadge status={run.status} />
          </div>
          <h1 className="mt-2 text-2xl font-semibold text-ink">{run.project?.name || "Software Factory Run"}</h1>
          <p className="mt-1 max-w-4xl text-sm text-slate-600">{run.demand}</p>
        </div>
        <div className="grid min-w-64 grid-cols-2 gap-2 text-sm">
          <Metric label="HRS" value={String(run.homologation_readiness_score ?? 0)} />
          <Metric label="Cost" value={`$${run.cost_estimate ?? 0}`} />
          <Metric label="Phase" value={run.current_phase} />
          <Metric label="Node" value={run.current_node} />
          <Metric label="Started" value={fmtDate(run.started_at)} />
          <Metric label="Finished" value={fmtDate(run.finished_at)} />
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm hover:bg-slate-100" onClick={() => action(`/runs/${run.id}/pause`)}>
          <Pause className="h-4 w-4" /> Pause
        </button>
        <button className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm hover:bg-slate-100" onClick={() => action(`/runs/${run.id}/resume`)}>
          <Play className="h-4 w-4" /> Resume
        </button>
        <button className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm hover:bg-slate-100" onClick={() => action(`/runs/${run.id}/step`)}>
          <SkipForward className="h-4 w-4" /> Step
        </button>
        <button className="inline-flex items-center gap-2 rounded-md border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50" onClick={() => action(`/runs/${run.id}/cancel`)}>
          <Square className="h-4 w-4" /> Cancel
        </button>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="truncate text-sm font-medium">{value || "-"}</div>
    </div>
  );
}
