import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function HomologationReadinessPanel({ run, homologation }: { run: Dict; homologation: Dict }) {
  const report = homologation.reports?.[0];
  const blockers = report?.blockers_json || [];
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-xs text-slate-500">Homologation Readiness Score</div>
          <div className="text-4xl font-semibold">{run.homologation_readiness_score}</div>
        </div>
        <StatusBadge status={report?.status || run.status} />
      </div>
      <div className="grid grid-cols-1 gap-2">
        {homologation.scores?.map((score: Dict) => (
          <div key={score.id} className="flex items-center justify-between rounded-md border border-line px-3 py-2">
            <span>{score.category}</span>
            <span className="font-medium">{score.weighted_score}</span>
          </div>
        ))}
      </div>
      <div className="rounded-md bg-slate-50 p-3">
        <div className="font-medium">Hard blockers</div>
        <div className="text-slate-600">{blockers.length ? blockers.join(", ") : "0"}</div>
      </div>
    </div>
  );
}
