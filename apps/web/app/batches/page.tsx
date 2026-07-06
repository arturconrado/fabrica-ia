"use client";

import { useEffect, useState } from "react";
import { Boxes } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export default function BatchesPage() {
  const [batches, setBatches] = useState<Dict[]>([]);
  async function load() {
    setBatches(await apiGet<Dict[]>("/batches"));
  }
  async function start() {
    const batch = await apiPost<Dict>("/batches");
    setBatches([batch, ...batches]);
  }
  useEffect(() => {
    load().catch(() => setBatches([]));
  }, []);
  return (
    <div className="space-y-4">
      <button className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm text-white" onClick={start}>
        <Boxes className="h-4 w-4" /> Start Batch
      </button>
      <section className="panel divide-y divide-line">
        {batches.map((batch) => (
          <a key={batch.id} className="flex items-center justify-between px-4 py-3 hover:bg-slate-50" href={`/batches/${batch.id}`}>
            <div>
              <div className="font-medium">{batch.name}</div>
              <div className="text-sm text-slate-500">{batch.completed_items}/{batch.total_items} completed</div>
            </div>
            <StatusBadge status={batch.status} />
          </a>
        ))}
      </section>
    </div>
  );
}
