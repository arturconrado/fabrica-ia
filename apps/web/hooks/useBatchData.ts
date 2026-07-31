"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { Dict } from "@/lib/types";

export function useBatchData(batchId: string) {
  const [batch, setBatch] = useState<Dict | null>(null);
  const [items, setItems] = useState<Dict[]>([]);
  const [metrics, setMetrics] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [batchData, itemData, metricData] = await Promise.all([
        apiGet<Dict>(`/batches/${batchId}`),
        apiGet<Dict[]>(`/batches/${batchId}/items`),
        apiGet<Dict[]>(`/batches/${batchId}/metrics`)
      ]);
      setBatch(batchData);
      setItems(itemData);
      setMetrics(metricData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível carregar o batch.");
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    load();
  }, [load]);

  return { batch, items, metrics, loading, error, reload: load };
}
