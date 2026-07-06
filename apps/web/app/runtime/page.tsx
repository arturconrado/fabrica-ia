"use client";

import { useEffect, useState } from "react";
import { Activity, Boxes, BrainCircuit } from "lucide-react";
import { Panel } from "@/components/common/Panel";
import { apiGet } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export default function RuntimePage() {
  const [modelCalls, setModelCalls] = useState<Dict[]>([]);
  const [sandboxExecutions, setSandboxExecutions] = useState<Dict[]>([]);
  const [tools, setTools] = useState<Dict[]>([]);

  useEffect(() => {
    Promise.all([
      apiGet<Dict[]>("/model-calls"),
      apiGet<Dict[]>("/sandbox-executions"),
      apiGet<Dict[]>("/mcp/tools")
    ])
      .then(([calls, executions, mcpTools]) => {
        setModelCalls(calls);
        setSandboxExecutions(executions);
        setTools(mcpTools);
      })
      .catch(() => undefined);
  }, []);

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel title="Model Calls">
        <div className="space-y-3">
          {modelCalls.map((call) => (
            <div key={call.id} className="rounded-md border border-line p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-medium"><BrainCircuit className="h-4 w-4" />{call.model_name}</span>
                <StatusBadge status={call.status} />
              </div>
              <div className="mt-2 text-xs text-slate-500">{call.agent_name || "unknown agent"} · {call.duration_seconds}s</div>
            </div>
          ))}
          {!modelCalls.length && <div className="text-sm text-slate-500">No real model calls recorded yet.</div>}
        </div>
      </Panel>
      <Panel title="Sandbox">
        <div className="space-y-3">
          {sandboxExecutions.map((execution) => (
            <div key={execution.id} className="rounded-md border border-line p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-medium"><Activity className="h-4 w-4" />{execution.backend}</span>
                <StatusBadge status={execution.status} />
              </div>
              <div className="mt-2 break-words text-xs text-slate-500">{execution.command}</div>
            </div>
          ))}
          {!sandboxExecutions.length && <div className="text-sm text-slate-500">No sandbox executions recorded yet.</div>}
        </div>
      </Panel>
      <Panel title="MCP Tools">
        <div className="space-y-3">
          {tools.map((tool) => (
            <div key={`${tool.server_name}:${tool.tool_name}`} className="rounded-md border border-line p-3 text-sm">
              <div className="flex items-center gap-2 font-medium"><Boxes className="h-4 w-4" />{tool.tool_name}</div>
              <div className="mt-2 text-xs text-slate-500">{tool.server_name || "server not configured"} · {tool.transport}</div>
            </div>
          ))}
          {!tools.length && <div className="text-sm text-slate-500">No MCP tools allowlisted for this tenant.</div>}
        </div>
      </Panel>
    </div>
  );
}
