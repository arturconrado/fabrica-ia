"use client";

import { useParams } from "next/navigation";
import { BatchDashboard } from "@/components/batch/BatchDashboard";
import { ErrorState, LoadingState } from "@/components/common/OperationalUI";
import { useBatchData } from "@/hooks/useBatchData";

export default function BatchPage() {
  const params = useParams<{ batchId: string }>();
  const { batch, items, metrics, loading, error, reload } = useBatchData(params.batchId);
  if (loading && !batch) return <LoadingState label="Carregando batch…" />;
  if (error && !batch) return <ErrorState message={error} onRetry={() => void reload()} />;
  if (!batch) return <ErrorState message="Batch não encontrado neste tenant." onRetry={() => void reload()} />;
  return <div className="space-y-4">{error ? <ErrorState message={error} onRetry={() => void reload()} /> : null}<BatchDashboard batch={batch} items={items} metrics={metrics} /></div>;
}
