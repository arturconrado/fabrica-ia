"use client";

import { useEffect } from "react";
import { API_BASE } from "@/lib/api";

export function useRunStream(runId: string, onEvent: () => void) {
  useEffect(() => {
    const token =
      typeof window !== "undefined"
        ? window.localStorage.getItem("asf_bearer_token") || ""
        : "";
    const tenant = process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID || "local-dev";
    const params = new URLSearchParams({ tenant_id: tenant });
    if (token) params.set("access_token", token);
    const source = new EventSource(`${API_BASE}/runs/${runId}/stream?${params.toString()}`);
    source.onmessage = () => onEvent();
    source.onerror = () => source.close();
    return () => source.close();
  }, [runId, onEvent]);
}
