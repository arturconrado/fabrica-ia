"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { AgentStepSummary, AIWorkspaceSummary, Dict, ExecutionUnitSummary, RunBundle, ValidationManifest } from "@/lib/types";


type Workspace = {
  run: Dict;
  topology: Dict | null;
  nodes: Dict[];
  agent_states: Dict[];
  work_items: Dict[];
  recent_events: Dict[];
  gates: Dict[];
  homologation: Dict;
  ai: AIWorkspaceSummary;
  step_executions: AgentStepSummary[];
  execution_units: ExecutionUnitSummary[];
  artifact_fragments: Dict[];
  validation: ValidationManifest;
};

const emptyBundle: RunBundle = {
  run: null,
  topology: null,
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
  homologation: { reports: [], packages: [], scores: [], approvals: [] } as unknown as Dict,
  feedback: [],
  agentStates: [],
  agentMessages: [],
  workItems: [],
  ai: {},
  stepExecutions: [],
  executionUnits: [],
  artifactFragments: [],
  validation: {}
};

export function useRunData(runId: string) {
  const [data, setData] = useState<RunBundle>(emptyBundle);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadWorkspace = useCallback(async () => {
    const workspace = await apiGet<Workspace>(`/runs/${runId}/workspace`);
    setData((current) => ({
      ...current,
      run: workspace.run,
      topology: workspace.topology,
      nodes: workspace.nodes,
      events: workspace.recent_events,
      gates: workspace.gates,
      homologation: { ...current.homologation, ...workspace.homologation },
      agentStates: workspace.agent_states,
      workItems: workspace.work_items,
      ai: workspace.ai,
      stepExecutions: workspace.step_executions,
      executionUnits: workspace.execution_units,
      artifactFragments: workspace.artifact_fragments,
      validation: workspace.validation
    }));
  }, [runId]);

  const loadEvidence = useCallback(async () => {
    const [artifacts, files, diffs, tests, requirements, criteria, traceability, homologation, feedback, agentMessages] = await Promise.all([
      apiGet<Dict[]>(`/runs/${runId}/artifacts`),
      apiGet<Dict[]>(`/runs/${runId}/files`),
      apiGet<Dict[]>(`/runs/${runId}/diffs`),
      apiGet<Dict[]>(`/runs/${runId}/test-reports`),
      apiGet<Dict[]>(`/runs/${runId}/requirements`),
      apiGet<Dict[]>(`/runs/${runId}/acceptance-criteria`),
      apiGet<Dict[]>(`/runs/${runId}/traceability`),
      apiGet<Dict>(`/runs/${runId}/homologation`),
      apiGet<Dict[]>(`/runs/${runId}/feedback`),
      apiGet<Dict[]>(`/runs/${runId}/agent-messages`)
    ]);
    setData((current) => ({ ...current, artifacts, files, diffs, tests, requirements, criteria, traceability, homologation, feedback, agentMessages }));
  }, [runId]);

  const load = useCallback(async () => {
    try {
      setError("");
      await Promise.all([loadWorkspace(), loadEvidence()]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  }, [loadEvidence, loadWorkspace]);

  const refreshFromEvent = useCallback(async (event?: Dict) => {
    try {
      await loadWorkspace();
      const type = String(event?.event_type || "");
      if (/^(artifact|file|test|requirement|criteria|traceability|quality|homologation|approval|human\.feedback)/.test(type)) {
        await loadEvidence();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao sincronizar evento");
    }
  }, [loadEvidence, loadWorkspace]);

  useEffect(() => { void load(); }, [load]);
  return { data, loading, error, reload: refreshFromEvent, reloadAll: load };
}
