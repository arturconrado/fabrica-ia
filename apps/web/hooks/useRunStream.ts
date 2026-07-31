"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { Dict } from "@/lib/types";

export function useRunStream(runId: string, onEvent: (event?: Dict) => void) {
  const [status, setStatus] = useState<"connecting" | "connected" | "paused">("connecting");

  useEffect(() => {
    const controller = new AbortController();
    setStatus("connecting");

    async function connect() {
      try {
        const response = await fetch(`${API_BASE}/runs/${runId}/stream`, {
          credentials: "same-origin",
          signal: controller.signal
        });
        if (!response.ok || !response.body) {
          setStatus("paused");
          return;
        }
        setStatus("connected");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let pending = "";
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) {
            if (!controller.signal.aborted) setStatus("paused");
            break;
          }
          pending += decoder.decode(value, { stream: true });
          const frames = pending.split("\n\n");
          pending = frames.pop() || "";
          for (const frame of frames) {
            const line = frame.split("\n").find((item) => item.startsWith("data:"));
            if (!line) continue;
            try { onEvent(JSON.parse(line.slice(5).trim()) as Dict); }
            catch { onEvent(); }
          }
        }
      } catch {
        if (!controller.signal.aborted) setStatus("paused");
      }
    }

    void connect();
    return () => controller.abort();
  }, [runId, onEvent]);

  return status;
}
