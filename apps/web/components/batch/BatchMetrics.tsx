import type { Dict } from "@/lib/types";

export function BatchMetrics({ metrics }: { metrics: Dict[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {metrics.map((metric) => (
        <div key={metric.id} className="rounded-md border border-line bg-white px-4 py-3">
          <div className="text-xs text-slate-500">{metric.name}</div>
          <div className="text-2xl font-semibold">{metric.value}</div>
        </div>
      ))}
    </div>
  );
}
