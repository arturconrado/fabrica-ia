import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function RequirementsPanel({ requirements, criteria }: { requirements: Dict[]; criteria: Dict[] }) {
  return (
    <div className="space-y-4">
      <div className="max-h-[260px] overflow-auto">
        {requirements.map((req) => (
          <div key={req.id} className="mb-2 rounded-md border border-line p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{req.requirement_id} · {req.title}</span>
              <StatusBadge status={req.status} />
            </div>
            <div className="mt-1 text-xs text-slate-500">{req.priority}</div>
          </div>
        ))}
      </div>
      <div className="max-h-[260px] overflow-auto rounded-md bg-slate-50 p-3 text-xs">
        {criteria.map((criterion) => (
          <div key={criterion.id} className="mb-2">
            <div className="font-medium">{criterion.criterion_id} · {criterion.requirement_id}</div>
            <pre className="mono whitespace-pre-wrap text-slate-600">{criterion.gherkin}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}
