"use client";

import { useParams } from "next/navigation";
import { BatchDashboard } from "@/components/batch/BatchDashboard";
import { useBatchData } from "@/hooks/useBatchData";

export default function BatchPage() {
  const params = useParams<{ batchId: string }>();
  const { batch, items, metrics } = useBatchData(params.batchId);
  if (!batch) return <div className="panel px-4 py-8 text-sm text-slate-500">Loading batch...</div>;
  return <BatchDashboard batch={batch} items={items} metrics={metrics} />;
}
