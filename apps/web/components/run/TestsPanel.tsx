import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function TestsPanel({ tests }: { tests: Dict[] }) {
  return (
    <div className="space-y-4">
      {tests.map((test) => (
        <div key={test.id} className="rounded-md border border-line p-3">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="mono">{test.command}</span>
            <StatusBadge status={test.status} />
          </div>
          <div className="mb-2 text-xs text-slate-500">Passed {test.passed_count} · Failed {test.failed_count} · {test.duration_seconds}s</div>
          <pre className="mono max-h-[280px] overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{test.stdout}{test.stderr}</pre>
        </div>
      ))}
    </div>
  );
}
