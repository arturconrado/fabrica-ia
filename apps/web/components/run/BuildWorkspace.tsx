"use client";

import type { ReactNode } from "react";
import {
  Bot,
  CheckCircle2,
  CircleDot,
  Clock3,
  FileText,
  GitBranch,
  MessageSquareText,
  Send,
  ShieldCheck,
  TestTube2,
  UserCheck
} from "lucide-react";
import { LivePreviewPanel } from "@/components/run/LivePreviewPanel";
import type { Dict } from "@/lib/types";
import { fmtDate } from "@/lib/format";
import { StatusBadge, statusClass } from "@/lib/status";

const agentOrder = [
  "Demand Classifier",
  "Product Manager",
  "Architect",
  "Engineer",
  "Code Reviewer",
  "QA Engineer",
  "Quality Governor",
  "Human Approval"
];

export function BuildWorkspace({
  run,
  agentStates,
  agentMessages,
  workItems,
  artifacts,
  files,
  tests,
  gates,
  events,
  homologation
}: {
  run: Dict;
  agentStates: Dict[];
  agentMessages: Dict[];
  workItems: Dict[];
  artifacts: Dict[];
  files: Dict[];
  tests: Dict[];
  gates: Dict[];
  events: Dict[];
  homologation: Dict;
}) {
  const stateByName = new Map(agentStates.map((state) => [state.agent_name, state]));
  const agents = agentOrder.map((name) => stateByName.get(name)).filter((state): state is Dict => Boolean(state));
  const activeAgent = agentStates.find((state) => state.status === "working") || stateByName.get(run.current_node);
  const recentMessages = agentMessages.slice(-10);
  const recentWork = workItems.slice(-8).reverse();
  const finalPassed = tests.some((test) => test.status === "passed");
  const failedObserved = tests.some((test) => test.status === "failed");
  const passedGates = gates.filter((gate) => gate.status === "passed").length;

  return (
    <div className="space-y-4">
      {run.status === "waiting_for_human" && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Human approval is waiting for a release decision.
        </div>
      )}
      <section className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
        <aside className="rounded-lg border border-line bg-white">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <MessageSquareText className="h-4 w-4" />
              Build Chat
            </h2>
            <StatusBadge status={run.status} />
          </div>
          <div className="max-h-[620px] space-y-3 overflow-auto p-3">
            <div className="rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm text-cyan-950">
              <div className="mb-1 text-xs font-medium text-cyan-700">Enterprise demand</div>
              {run.demand}
            </div>
            {recentMessages.map((message) => (
              <div key={message.id} className="rounded-md border border-line px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="font-medium text-slate-800">{message.from_agent}</span>
                  <Send className="h-3.5 w-3.5" />
                  <span className="font-medium text-slate-800">{message.to_agent || "operator"}</span>
                  <span>{fmtDate(message.created_at)}</span>
                </div>
                <div className="mt-1 leading-6 text-slate-700">{message.content}</div>
              </div>
            ))}
            {!recentMessages.length && <div className="text-sm text-slate-500">Waiting for agent messages.</div>}
          </div>
        </aside>

        <main className="space-y-4">
          <section className="rounded-lg border border-line bg-white">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">Agent Activity</h2>
                <div className="text-xs text-slate-500">{activeAgent?.agent_name || "Queue"} · {run.current_phase || "pending"}</div>
              </div>
              <div className="rounded-md border border-line bg-slate-50 px-3 py-2 text-sm">
                HRS <span className="font-semibold">{run.homologation_readiness_score || 0}</span>
              </div>
            </div>
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
              {agents.map((agent) => {
                const active = agent.status === "working" || agent.agent_name === run.current_node;
                const done = ["completed", "success", "approved", "passed"].includes(String(agent.status));
                return (
                  <div key={agent.id} className={`rounded-md border p-3 ${active ? "border-cyan-300 bg-cyan-50" : "border-line bg-white"}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        {done ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" /> : active ? <CircleDot className="h-4 w-4 shrink-0 text-cyan-700" /> : <Bot className="h-4 w-4 shrink-0 text-slate-400" />}
                        <div className="truncate text-sm font-medium">{agent.agent_name}</div>
                      </div>
                      {active && <span className="h-2 w-2 rounded-full bg-cyan-500 motion-safe:animate-pulse" />}
                    </div>
                    <div className="mt-2 line-clamp-2 min-h-9 text-xs text-slate-600">{agent.current_sop_step || "queued"}</div>
                    <div className="mt-3 h-1.5 rounded bg-slate-100">
                      <div className="h-1.5 rounded bg-slate-900" style={{ width: `${Math.max(0, Math.min(100, Number(agent.progress) || 0))}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <LivePreviewPanel files={files} tests={tests} artifacts={artifacts} run={run} />
        </main>

        <aside className="space-y-4">
          <section className="rounded-lg border border-line bg-white">
            <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4" />
              Quality Rail
            </h2>
            <div className="space-y-3 p-4 text-sm">
              <QualityMetric label="Quality gates" value={`${passedGates}/${gates.length || 17}`} state={passedGates ? "passed" : "pending"} />
              <QualityMetric label="Initial failure" value={failedObserved ? "recorded" : "pending"} state={failedObserved ? "passed" : "pending"} />
              <QualityMetric label="Final tests" value={finalPassed ? "passing" : "pending"} state={finalPassed ? "passed" : "pending"} />
              <QualityMetric label="Approval" value={run.status === "waiting_for_human" ? "waiting" : run.status} state={run.status === "approved_for_homologation" ? "passed" : "pending"} />
            </div>
          </section>

          <section className="rounded-lg border border-line bg-white">
            <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm font-semibold">
              <Clock3 className="h-4 w-4" />
              Work Queue
            </h2>
            <div className="max-h-[360px] space-y-2 overflow-auto p-3">
              {recentWork.map((item) => (
                <div key={item.id} className="rounded-md border border-line px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{item.agent_name}</span>
                    <span className={`rounded border px-2 py-0.5 text-xs ${statusClass(item.status)}`}>{item.status}</span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs text-slate-500">{item.sop_step}</div>
                </div>
              ))}
              {!recentWork.length && <div className="text-sm text-slate-500">No work item yet.</div>}
            </div>
          </section>

          <section className="rounded-lg border border-line bg-white">
            <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm font-semibold">
              <FileText className="h-4 w-4" />
              Evidence
            </h2>
            <div className="grid grid-cols-2 gap-2 p-3 text-sm">
              <EvidenceTile icon={<GitBranch className="h-4 w-4" />} label="Events" value={String(events.length)} />
              <EvidenceTile icon={<FileText className="h-4 w-4" />} label="Artifacts" value={String(artifacts.length)} />
              <EvidenceTile icon={<TestTube2 className="h-4 w-4" />} label="Tests" value={String(tests.length)} />
              <EvidenceTile icon={<UserCheck className="h-4 w-4" />} label="Approvals" value={String(homologation.approvals?.length || 0)} />
            </div>
          </section>
        </aside>
      </section>
    </div>
  );
}

function QualityMetric({ label, value, state }: { label: string; value: string; state: "passed" | "pending" }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-line bg-slate-50 px-3 py-2">
      <span className="text-slate-500">{label}</span>
      <span className={state === "passed" ? "font-medium text-emerald-700" : "font-medium text-amber-700"}>{value}</span>
    </div>
  );
}

function EvidenceTile({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-slate-50 p-3">
      <div className="flex items-center gap-2 text-slate-500">{icon}<span className="text-xs">{label}</span></div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}
