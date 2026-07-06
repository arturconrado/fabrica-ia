"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { RunBundle } from "@/lib/types";

const emptyBundle: RunBundle = {
  run: null,
  nodes: [],
  events: [],
  artifacts: [],
  files: [],
  diffs: [],
  tests: [],
  requirements: [],
  criteria: [],
  traceability: [],
  gates: [],
  homologation: { reports: [], packages: [], scores: [], approvals: [] },
  feedback: [],
  agentStates: [],
  agentMessages: [],
  workItems: []
};

export function useRunData(runId: string) {
  const [data, setData] = useState<RunBundle>(emptyBundle);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      const [run, nodes, events, artifacts, files, diffs, tests, requirements, criteria, traceability, gates, homologation, feedback, agentStates, agentMessages, workItems] =
        await Promise.all([
          apiGet(`/runs/${runId}`),
          apiGet(`/runs/${runId}/nodes`),
          apiGet(`/runs/${runId}/events`),
          apiGet(`/runs/${runId}/artifacts`),
          apiGet(`/runs/${runId}/files`),
          apiGet(`/runs/${runId}/diffs`),
          apiGet(`/runs/${runId}/test-reports`),
          apiGet(`/runs/${runId}/requirements`),
          apiGet(`/runs/${runId}/acceptance-criteria`),
          apiGet(`/runs/${runId}/traceability`),
          apiGet(`/runs/${runId}/quality-gates`),
          apiGet(`/runs/${runId}/homologation`),
          apiGet(`/runs/${runId}/feedback`),
          apiGet(`/runs/${runId}/agent-states`),
          apiGet(`/runs/${runId}/agent-messages`),
          apiGet(`/runs/${runId}/work-items`)
        ]);
      setData({ run, nodes, events, artifacts, files, diffs, tests, requirements, criteria, traceability, gates, homologation, feedback, agentStates, agentMessages, workItems } as RunBundle);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  return { data, loading, error, reload: load };
}
