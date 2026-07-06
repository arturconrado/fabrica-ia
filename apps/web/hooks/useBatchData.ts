"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { Dict } from "@/lib/types";

export function useBatchData(batchId: string) {
  const [batch, setBatch] = useState<Dict | null>(null);
  const [items, setItems] = useState<Dict[]>([]);
  const [metrics, setMetrics] = useState<Dict[]>([]);

  const load = useCallback(async () => {
    const [batchData, itemData, metricData] = await Promise.all([
      apiGet<Dict>(`/batches/${batchId}`),
      apiGet<Dict[]>(`/batches/${batchId}/items`),
      apiGet<Dict[]>(`/batches/${batchId}/metrics`)
    ]);
    setBatch(batchData);
    setItems(itemData);
    setMetrics(metricData);
  }, [batchId]);

  useEffect(() => {
    load();
  }, [load]);

  return { batch, items, metrics, reload: load };
}
