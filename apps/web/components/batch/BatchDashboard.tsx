import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";
import { BatchItemsTable } from "@/components/batch/BatchItemsTable";
import { BatchMetrics } from "@/components/batch/BatchMetrics";

export function BatchDashboard({ batch, items, metrics }: { batch: Dict; items: Dict[]; metrics: Dict[] }) {
  return (
    <div className="space-y-4">
      <section className="panel px-4 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">{batch.name}</h1>
            <p className="text-sm text-slate-500">{batch.completed_items}/{batch.total_items} completed · average HRS {batch.average_hrs}</p>
          </div>
          <StatusBadge status={batch.status} />
        </div>
      </section>
      <BatchMetrics metrics={metrics} />
      <section className="panel p-4">
        <BatchItemsTable items={items} />
      </section>
    </div>
  );
}
