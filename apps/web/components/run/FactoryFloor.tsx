"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Bot, CheckCircle2, CircleDot, MessageSquareText, PackageCheck, Send, Wrench } from "lucide-react";
import type { Dict } from "@/lib/types";
import { fmtDate } from "@/lib/format";
import { StatusBadge, statusClass } from "@/lib/status";

const orderedAgents = [
  "Demand Classifier",
  "Acceptance Criteria Architect",
  "Scope Governor",
  "Product Manager",
  "UX UI Designer",
  "Architect",
  "Data Architect",
  "API Contract Engineer",
  "Project Manager",
  "Engineer",
  "Code Reviewer",
  "QA Engineer",
  "Visual QA Agent",
  "Accessibility QA Agent",
  "Security Engineer",
  "DevOps Engineer",
  "Release Manager",
  "Quality Governor",
  "Human Approval"
];

export function FactoryFloor({
  run,
  agentStates,
  agentMessages,
  workItems,
  artifacts,
  events
}: {
  run: Dict;
  agentStates: Dict[];
  agentMessages: Dict[];
  workItems: Dict[];
  artifacts: Dict[];
  events: Dict[];
}) {
  const states = useMemo(() => {
    const byName = new Map(agentStates.map((state) => [state.agent_name, state]));
    return orderedAgents.map((name) => byName.get(name) || { agent_name: name, role: name, status: "queued", progress: 0, current_sop_step: "queued", tools_json: [] });
  }, [agentStates]);
  const active = states.find((state) => state.status === "working") || states.find((state) => state.agent_name === run.current_node) || states[0];
  const [selectedName, setSelectedName] = useState("");
  const selected = states.find((state) => state.agent_name === (selectedName || active?.agent_name)) || active;
  const selectedItems = workItems.filter((item) => item.agent_name === selected?.agent_name).slice(-4);
  const selectedArtifacts = artifacts.filter((artifact) => artifact.node_id === selected?.agent_name);
  const selectedEvents = events.filter((event) => event.agent_name === selected?.agent_name || event.node_id === selected?.agent_name).slice(-6);

  return (
    <div className="space-y-4">
      {run.status === "waiting_for_human" && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Human Supervisor is waiting for a homologation decision.
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
        <section className="rounded-md border border-line bg-white">
          <h2 className="border-b border-line px-4 py-3 text-sm font-semibold">Agent Roster</h2>
          <div className="max-h-[680px] overflow-auto p-2">
            {states.map((state) => (
              <button
                key={state.agent_name}
                className={`mb-2 w-full rounded-md border px-3 py-3 text-left text-sm hover:bg-slate-50 ${selected?.agent_name === state.agent_name ? "border-slate-900" : "border-line"}`}
                onClick={() => setSelectedName(state.agent_name)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 items-start gap-2">
                    <Bot className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{state.agent_name}</div>
                      <div className="truncate text-xs text-slate-500">{state.role}</div>
                    </div>
                  </div>
                  <StatusBadge status={state.status} />
                </div>
                <div className="mt-2 h-1.5 rounded bg-slate-100">
                  <div className="h-1.5 rounded bg-slate-900" style={{ width: `${Math.max(0, Math.min(100, Number(state.progress) || 0))}%` }} />
                </div>
                <div className="mt-2 line-clamp-2 text-xs text-slate-600">{state.current_sop_step || "queued"}</div>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-line bg-white">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold">Live Workflow</h2>
            <div className="text-xs text-slate-500">{run.current_phase || "phase pending"}</div>
          </div>
          <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
            {states.map((state, index) => {
              const isActive = state.status === "working" || state.agent_name === run.current_node;
              const isDone = ["completed", "success", "approved", "passed"].includes(String(state.status));
              return (
                <button
                  key={state.agent_name}
                  className={`relative min-h-28 rounded-md border p-3 text-left text-sm transition ${isActive ? "border-blue-500 bg-blue-50" : "border-line bg-white hover:bg-slate-50"}`}
                  onClick={() => setSelectedName(state.agent_name)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      {isDone ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : isActive ? <CircleDot className="h-4 w-4 text-blue-600" /> : <CircleDot className="h-4 w-4 text-slate-400" />}
                      <div className="truncate font-medium">{state.agent_name}</div>
                    </div>
                    {isActive && <span className="h-2 w-2 rounded-full bg-blue-600 motion-safe:animate-pulse" />}
                  </div>
                  <div className="mt-2 line-clamp-2 text-xs text-slate-600">{state.current_sop_step}</div>
                  <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                    <span>Step {index + 1}</span>
                    <span>{Math.round(Number(state.progress) || 0)}%</span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="rounded-md border border-line bg-white">
          <h2 className="border-b border-line px-4 py-3 text-sm font-semibold">Agent Inspector</h2>
          {selected && (
            <div className="space-y-4 p-4 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-semibold">{selected.agent_name}</div>
                  <div className="text-slate-500">{selected.role}</div>
                </div>
                <StatusBadge status={selected.status} />
              </div>
              <p className="rounded-md bg-slate-50 p-3 text-slate-700">{selected.objective || "No objective registered."}</p>
              <InfoBlock icon={<Wrench className="h-4 w-4" />} title="Tools" items={selected.tools_json || []} />
              <InfoBlock icon={<PackageCheck className="h-4 w-4" />} title="Outputs" items={selected.outputs_json || selectedArtifacts.map((artifact) => artifact.name)} />
              <div>
                <div className="mb-2 font-medium">Recent Work</div>
                <div className="space-y-2">
                  {selectedItems.map((item) => (
                    <div key={item.id} className="rounded-md border border-line px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span>{item.sop_step}</span>
                        <span className={`rounded border px-2 py-0.5 text-xs ${statusClass(item.status)}`}>{item.status}</span>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">{item.summary}</div>
                    </div>
                  ))}
                  {!selectedItems.length && <div className="text-slate-500">No work item yet.</div>}
                </div>
              </div>
              <div>
                <div className="mb-2 font-medium">Recent Events</div>
                <div className="space-y-1">
                  {selectedEvents.map((event) => <div key={event.id} className="rounded bg-slate-50 px-2 py-1 text-xs">{event.event_type}: {event.summary}</div>)}
                  {!selectedEvents.length && <div className="text-slate-500">No events yet.</div>}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      <section className="rounded-md border border-line bg-white">
        <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm font-semibold">
          <MessageSquareText className="h-4 w-4" /> Agent Transcript
        </h2>
        <div className="max-h-[340px] space-y-3 overflow-auto p-4">
          {agentMessages.map((message) => (
            <div key={message.id} className="rounded-md border border-line px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="font-medium text-slate-800">{message.from_agent}</span>
                <Send className="h-3.5 w-3.5" />
                <span className="font-medium text-slate-800">{message.to_agent || "operator"}</span>
                <span>{message.message_type}</span>
                <span>{fmtDate(message.created_at)}</span>
              </div>
              <div className="mt-1 text-slate-700">{message.content}</div>
            </div>
          ))}
          {!agentMessages.length && <div className="text-sm text-slate-500">No agent messages yet. Start an enterprise build to watch handoffs.</div>}
        </div>
      </section>
    </div>
  );
}

function InfoBlock({ icon, title, items }: { icon: ReactNode; title: string; items: string[] }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 font-medium">{icon}{title}</div>
      <div className="flex flex-wrap gap-2">
        {items?.length ? items.map((item) => <span key={item} className="rounded-md border border-line bg-slate-50 px-2 py-1 text-xs">{item}</span>) : <span className="text-sm text-slate-500">None yet.</span>}
      </div>
    </div>
  );
}
