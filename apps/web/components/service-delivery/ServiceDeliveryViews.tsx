"use client";

import Link from "next/link";
import type { FormEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Award,
  BadgeCheck,
  Ban,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Gauge,
  Layers3,
  LockKeyhole,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Users
} from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import type { Dict } from "@/lib/types";

function statusTone(status: string) {
  if (["active", "approved", "granted", "completed"].includes(status)) return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (["pending", "awaiting_prerequisites", "ready"].includes(status)) return "border-amber-200 bg-amber-50 text-amber-900";
  if (["blocked", "rejected", "suspended", "expired", "revoked"].includes(status)) return "border-rose-200 bg-rose-50 text-rose-800";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function StatusPill({ status }: { status: string }) {
  return <span className={`inline-flex rounded border px-2 py-1 text-xs font-medium ${statusTone(status)}`}>{status || "unknown"}</span>;
}

function EvidenceBadge({ classification }: { classification: string }) {
  const tones: Record<string, string> = {
    real: "border-emerald-200 bg-emerald-50 text-emerald-800",
    declared: "border-sky-200 bg-sky-50 text-sky-800",
    calculated: "border-indigo-200 bg-indigo-50 text-indigo-800",
    estimated: "border-amber-200 bg-amber-50 text-amber-900",
    recommendation: "border-slate-200 bg-slate-50 text-slate-700"
  };
  const value = classification || "declared";
  return <span className={`rounded border px-2 py-1 text-xs font-medium ${tones[value] || tones.declared}`}>{value}</span>;
}

function ProgressBar({ value }: { value: number }) {
  const bounded = Math.max(0, Math.min(100, value || 0));
  return (
    <div className="h-2 w-full rounded bg-slate-100">
      <div className="h-2 rounded bg-cyan-600" style={{ width: `${bounded}%` }} />
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-md border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500">{label}</div>;
}

function ScoreBreakdown({ scores }: { scores: Dict[] }) {
  const score = scores?.[0];
  const components = score?.explanation_json?.components || {};
  return (
    <section className="panel p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-semibold">
          <Gauge className="h-4 w-4" /> Project Health Score
        </div>
        <div className="text-3xl font-semibold text-slate-950">{score ? Number(score.value).toFixed(2) : "0.00"}</div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {Object.entries(components).map(([key, value]) => {
          const item = value as Dict;
          return (
            <div key={key} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="capitalize text-slate-600">{key.replaceAll("_", " ")}</span>
                <span className="font-medium">{Number(item.value || 0).toFixed(0)}%</span>
              </div>
              <div className="mt-2"><ProgressBar value={Number(item.value || 0)} /></div>
              <div className="mt-1 text-xs text-slate-500">Weight {Math.round(Number(item.weight || 0) * 100)}%</div>
            </div>
          );
        })}
      </div>
      {!score && <div className="mt-3 text-sm text-slate-500">No score recorded yet.</div>}
    </section>
  );
}

function ActivityList({ activity }: { activity: Dict[] }) {
  return (
    <div className="space-y-2">
      {activity.map((event) => (
        <div key={event.id} className="rounded-md border border-line bg-white px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium">{event.action}</div>
            <div className="text-xs text-slate-500">{event.resource_type}</div>
          </div>
          <div className="mt-1 text-xs text-slate-500">{event.summary}</div>
        </div>
      ))}
      {!activity.length && <EmptyState label="No activity recorded." />}
    </div>
  );
}

function ComponentRows({ components }: { components: Dict[] }) {
  return (
    <div className="overflow-hidden rounded-md border border-line bg-white">
      <div className="grid grid-cols-[1.4fr_1fr_120px_120px] gap-3 border-b border-line bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500">
        <div>Component</div>
        <div>Phase</div>
        <div>Status</div>
        <div>Progress</div>
      </div>
      {components.map((component) => (
        <Link
          key={component.id}
          href={`/components/${component.id}`}
          className="grid grid-cols-[1.4fr_1fr_120px_120px] items-center gap-3 border-b border-line px-3 py-3 text-sm hover:bg-slate-50 last:border-b-0"
        >
          <div>
            <div className="font-medium">{component.definition?.name || component.component_code}</div>
            <div className="text-xs text-slate-500">{component.component_code}</div>
          </div>
          <div className="text-slate-600">{component.current_phase || "Queued"}</div>
          <div><StatusPill status={component.status} /></div>
          <div>
            <div className="mb-1 text-xs text-slate-500">{Number(component.progress || 0).toFixed(0)}%</div>
            <ProgressBar value={Number(component.progress || 0)} />
          </div>
        </Link>
      ))}
      {!components.length && <div className="p-4"><EmptyState label="No components available." /></div>}
    </div>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string | number }) {
  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-slate-500">{label}</div>
        <div className="text-slate-500">{icon}</div>
      </div>
      <div className="mt-3 text-3xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}

export function ProgramView({ programId }: { programId: string }) {
  const [program, setProgram] = useState<Dict | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    apiGet<Dict>(`/api/v1/programs/${programId}`).then(setProgram).catch((err: Error) => setError(err.message));
  }, [programId]);
  if (error) return <div className="panel p-4 text-sm text-rose-700">{error}</div>;
  if (!program) return <div className="panel p-4 text-sm text-slate-500">Loading program...</div>;
  return (
    <div className="space-y-5">
      <header className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{program.name}</h1>
            <p className="mt-1 text-sm text-slate-600">{program.description}</p>
          </div>
          <StatusPill status={program.status} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <Metric icon={<Users className="h-4 w-4" />} label="Sponsor" value={program.sponsor || "N/A"} />
          <Metric icon={<CalendarClock className="h-4 w-4" />} label="Target" value={program.target_end_date || "N/A"} />
          <Metric icon={<Layers3 className="h-4 w-4" />} label="Projects" value={(program.projects || []).length} />
        </div>
      </header>
      <ScoreBreakdown scores={program.scores || []} />
      <section className="panel p-4">
        <div className="mb-3 font-semibold">Program Components</div>
        <ComponentRows components={program.components || []} />
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Projects</div>
          {(program.projects || []).map((project: Dict) => (
            <div key={project.id} className="rounded-md border border-line p-3">
              <div className="font-medium">{project.name}</div>
              <div className="mt-1 text-sm text-slate-500">{project.scope || project.description}</div>
            </div>
          ))}
        </div>
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Contracts</div>
          {(program.contracts || []).map((contract: Dict) => (
            <div key={contract.id} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium">{contract.contract_number}</div>
                <StatusPill status={contract.status} />
              </div>
              <div className="mt-1 text-sm text-slate-500">{contract.scope_summary}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function ComponentView({ componentId }: { componentId: string }) {
  const [component, setComponent] = useState<Dict | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = () => apiGet<Dict>(`/api/v1/component-instances/${componentId}`).then(setComponent).catch((err: Error) => setError(err.message));
  useEffect(() => { load(); }, [componentId]);

  async function start() {
    setError("");
    setMessage("");
    try {
      await apiPost(`/api/v1/component-instances/${componentId}/start`, { reason: "Operator requested start" });
      setMessage("Component start accepted.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start component");
    }
  }

  async function decide(approvalId: string, decision: "approve" | "reject") {
    await apiPost(`/api/v1/approvals/${approvalId}/${decision}`, { comment: `${decision} from component workspace` });
    load();
  }

  if (error && !component) return <div className="panel p-4 text-sm text-rose-700">{error}</div>;
  if (!component) return <div className="panel p-4 text-sm text-slate-500">Loading component...</div>;
  const entitlement = component.entitlement;
  return (
    <div className="space-y-5">
      <header className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{component.definition?.name || component.component_code}</h1>
            <p className="mt-1 text-sm text-slate-600">{component.definition?.description}</p>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill status={component.status} />
            <button onClick={start} className="inline-flex items-center gap-2 rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800">
              <Play className="h-4 w-4" /> Start
            </button>
          </div>
        </div>
        {error && <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
        {message && <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div>}
      </header>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="space-y-4">
          <div className="panel p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="font-semibold">Operational Progress</div>
              <div className="text-sm text-slate-500">{Number(component.progress || 0).toFixed(0)}%</div>
            </div>
            <ProgressBar value={Number(component.progress || 0)} />
            <div className="mt-3 text-sm text-slate-600">Current phase: {component.current_phase || "N/A"}</div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><Award className="h-4 w-4" /> Milestones</div>
            <div className="grid gap-2 md:grid-cols-2">
              {(component.milestones_json || []).map((item: Dict) => (
                <div key={item.name} className="rounded-md border border-line p-3">
                  <div className="flex items-center justify-between">
                    <div className="font-medium">{item.name}</div>
                    <StatusPill status={String(item.status || "")} />
                  </div>
                  <div className="mt-2 text-xs text-slate-500">{item.points || 0} points</div>
                </div>
              ))}
            </div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><ClipboardCheck className="h-4 w-4" /> Tasks</div>
            <div className="space-y-2">
              {(component.tasks_json || []).map((task: Dict) => (
                <div key={task.name} className="flex items-center justify-between rounded-md border border-line px-3 py-2">
                  <span className="text-sm">{task.name}</span>
                  <StatusPill status={String(task.status || "")} />
                </div>
              ))}
            </div>
          </div>
        </section>
        <aside className="space-y-4">
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><LockKeyhole className="h-4 w-4" /> Entitlement</div>
            {entitlement ? (
              <div className="space-y-3">
                <StatusPill status={entitlement.status} />
                <div className="text-sm text-slate-600">Valid until {entitlement.valid_until || "N/A"}</div>
                <div className="grid gap-2">
                  {Object.entries(entitlement.limits_json || {}).map(([key, value]) => (
                    <div key={key} className="flex justify-between rounded border border-line px-2 py-1 text-sm">
                      <span className="capitalize text-slate-500">{key.replaceAll("_", " ")}</span>
                      <span>{String((component.limits_consumed_json || {})[key] || 0)} / {String(value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">No granted entitlement.</div>
            )}
          </div>
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><ClipboardCheck className="h-4 w-4" /> Approvals</div>
            <div className="space-y-2">
              {(component.approvals || []).map((approval: Dict) => (
                <div key={approval.id} className="rounded-md border border-line p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium">{approval.title}</div>
                    <StatusPill status={approval.status} />
                  </div>
                  {approval.status === "pending" && (
                    <div className="mt-3 flex gap-2">
                      <button onClick={() => decide(approval.id, "approve")} className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white">Approve</button>
                      <button onClick={() => decide(approval.id, "reject")} className="rounded-md border border-line px-3 py-1.5 text-xs font-medium">Reject</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><Activity className="h-4 w-4" /> Events</div>
            <ActivityList activity={component.events || []} />
          </div>
        </aside>
      </div>
    </div>
  );
}

export function AdminContractsView() {
  const [contracts, setContracts] = useState<Dict[]>([]);
  const [entitlements, setEntitlements] = useState<Dict[]>([]);
  const [error, setError] = useState("");
  const load = () => {
    Promise.all([apiGet<Dict[]>("/api/v1/contracts"), apiGet<Dict[]>("/api/v1/entitlements")])
      .then(([nextContracts, nextEntitlements]) => {
        setContracts(nextContracts);
        setEntitlements(nextEntitlements);
      })
      .catch((err: Error) => setError(err.message));
  };
  useEffect(() => { load(); }, []);
  if (error) return <div className="panel p-4 text-sm text-rose-700">{error}</div>;
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold">Contracts & Entitlements</h1>
      <section className="panel p-4">
        <div className="mb-3 font-semibold">Contracts</div>
        <div className="grid gap-3">
          {contracts.map((contract) => (
            <div key={contract.id} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium">{contract.contract_number}</div>
                <StatusPill status={contract.status} />
              </div>
              <div className="mt-1 text-sm text-slate-500">{contract.scope_summary}</div>
            </div>
          ))}
        </div>
      </section>
      <section className="panel p-4">
        <div className="mb-3 font-semibold">Entitlements</div>
        <div className="grid gap-3 md:grid-cols-2">
          {entitlements.map((entitlement) => (
            <div key={entitlement.id} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium">{entitlement.component_code}</div>
                <StatusPill status={entitlement.status} />
              </div>
              <div className="mt-2 text-xs text-slate-500">Valid {entitlement.valid_from || "N/A"} to {entitlement.valid_until || "N/A"}</div>
              <div className="mt-3 flex flex-wrap gap-1">
                {(entitlement.capabilities_json || []).map((capability: string) => (
                  <span key={capability} className="rounded border border-line px-2 py-1 text-[11px] text-slate-600">{capability}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function money(value: number) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(value || 0);
}

function confidence(value: number) {
  return `${Math.round((value || 0) * 100)}%`;
}

function AICopilotPanel({ activities }: { activities: Dict[] }) {
  const latest = activities[0];
  const recommendations = activities.flatMap((activity) => activity.output_json?.recommendations || []).slice(0, 4);
  return (
    <section className="panel p-4">
      <div className="mb-3 flex items-center gap-2 font-semibold"><Sparkles className="h-4 w-4" /> AI Copilot</div>
      {latest ? (
        <div className="rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm text-cyan-950">
          {latest.agent_name} concluded {latest.activity_type} with {confidence(Number(latest.confidence || 0))} confidence.
        </div>
      ) : (
        <EmptyState label="No AI activity recorded yet." />
      )}
      <div className="mt-3 grid gap-2">
        {recommendations.map((item, index) => (
          <div key={`${item}-${index}`} className="rounded-md border border-line bg-white px-3 py-2 text-sm text-slate-700">{String(item)}</div>
        ))}
      </div>
    </section>
  );
}

function AIActivityRows({ activities }: { activities: Dict[] }) {
  return (
    <div className="space-y-2">
      {activities.map((activity) => (
        <div key={activity.id} className="rounded-md border border-line bg-white p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="font-medium">{activity.agent_name}</div>
              <div className="mt-1 text-sm text-slate-500">{activity.activity_type} on {activity.resource_type}</div>
            </div>
            <div className="text-right text-xs text-slate-500">
              <div>{confidence(Number(activity.confidence || 0))} confidence</div>
              <div>${Number(activity.estimated_cost_usd || 0).toFixed(6)}</div>
            </div>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {(activity.output_json?.facts || []).slice(0, 2).map((fact: string, index: number) => (
              <div key={`fact-${activity.id}-${index}`} className="rounded border border-line px-2 py-1 text-xs text-slate-600">{fact}</div>
            ))}
            {(activity.output_json?.risks || []).slice(0, 2).map((risk: string, index: number) => (
              <div key={`risk-${activity.id}-${index}`} className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900">{risk}</div>
            ))}
          </div>
        </div>
      ))}
      {!activities.length && <EmptyState label="No AI activities found." />}
    </div>
  );
}

export function OpportunityView({ opportunityId }: { opportunityId: string }) {
  const [opportunity, setOpportunity] = useState<Dict | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function load() {
    apiGet<Dict>(`/api/v1/opportunities/${opportunityId}`).then(setOpportunity).catch((err: Error) => setError(err.message));
  }

  useEffect(() => { load(); }, [opportunityId]);

  async function command(path: string, done: string, body?: Record<string, unknown>, idempotent = false) {
    setError("");
    setMessage("");
    try {
      await apiPost<Dict>(path, body, idempotent ? { idempotencyKey: crypto.randomUUID() } : undefined);
      setMessage(done);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Command failed");
    }
  }

  if (error && !opportunity) return <div className="panel p-4 text-sm text-rose-700">{error}</div>;
  if (!opportunity) return <div className="panel p-4 text-sm text-slate-500">Loading opportunity...</div>;
  const structured = opportunity.briefing?.structured_json || {};
  const activities = opportunity.ai_activities || [];

  return (
    <div className="space-y-5">
      <header className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{opportunity.title}</h1>
            <p className="mt-1 text-sm text-slate-600">{opportunity.summary || "No summary yet."}</p>
          </div>
          <StatusPill status={opportunity.status} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <Metric icon={<Users className="h-4 w-4" />} label="Prospect" value={opportunity.prospect?.company || "N/A"} />
          <Metric icon={<Gauge className="h-4 w-4" />} label="Validation" value={opportunity.validation_score == null ? "—" : Number(opportunity.validation_score).toFixed(0)} />
          <Metric icon={<AlertTriangle className="h-4 w-4" />} label="Risk" value={opportunity.risk_level || "N/A"} />
          <Metric icon={<BriefcaseBusiness className="h-4 w-4" />} label="Potential" value={money(Number(opportunity.value_potential || 0))} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={() => command(`/api/v1/opportunities/${opportunity.id}/validate`, "Idea validation refreshed.")} className="rounded-md border border-line bg-white px-3 py-2 text-sm font-medium">Validate</button>
          <button onClick={() => command(`/api/v1/opportunities/${opportunity.id}/scope-mvp`, "MVP scope refreshed.")} className="rounded-md border border-line bg-white px-3 py-2 text-sm font-medium">Scope MVP</button>
          <button onClick={() => command(`/api/v1/opportunities/${opportunity.id}/generate-mvp`, "MVP package generated.")} className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white">Generate MVP</button>
          <button onClick={() => command(`/api/v1/opportunities/${opportunity.id}/generate-proposal`, "Proposal generated.", undefined, true)} className="rounded-md border border-line bg-white px-3 py-2 text-sm font-medium">Generate Proposal</button>
          <button onClick={() => {
            const comment = window.prompt("Approval rationale (required)");
            if (comment) command(`/api/v1/opportunities/${opportunity.id}/approve`, "Opportunity approved.", { comment }, true);
          }} className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800">Approve Package</button>
          <button onClick={() => {
            if (window.confirm("Activate the approved contract, entitlement and delivery project?")) {
              command(`/api/v1/opportunities/${opportunity.id}/convert-to-delivery`, "Opportunity converted to contracted delivery.", { confirmation: "activate approved proposal" }, true);
            }
          }} className="rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-medium text-cyan-900">Convert to Delivery</button>
          {opportunity.mvp_run && <Link href={`/mvp-runs/${opportunity.mvp_run.id}`} className="rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-medium text-cyan-900">Open Run</Link>}
        </div>
        {message && <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div>}
        {error && <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
        <section className="space-y-4">
          <div className="panel p-4">
            <div className="mb-3 font-semibold">Structured Briefing</div>
            <div className="grid gap-3 md:grid-cols-2">
              {["facts", "assumptions", "unknowns", "risks", "recommendations"].map((key) => (
                <div key={key} className="rounded-md border border-line p-3">
                  <div className="mb-2 text-sm font-medium capitalize">{key}</div>
                  <div className="space-y-1">
                    {(structured[key] || []).map((item: string, index: number) => (
                      <div key={`${key}-${index}`} className="text-sm text-slate-600">{item}</div>
                    ))}
                    {!(structured[key] || []).length && <div className="text-sm text-slate-400">None recorded.</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 font-semibold">MVP Scope</div>
            {opportunity.mvp_spec ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm text-slate-600">Blueprint <span className="font-medium text-slate-900">{opportunity.mvp_spec.blueprint_ref}</span></div>
                  <StatusPill status={opportunity.mvp_spec.status} />
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  {Object.entries(opportunity.mvp_spec.scope_json || {}).map(([key, value]) => (
                    <div key={key} className="rounded-md border border-line p-3">
                      <div className="mb-2 text-sm font-medium uppercase text-slate-500">{key}</div>
                      {(Array.isArray(value) ? value : [value]).map((item, index) => (
                        <div key={`${key}-${index}`} className="text-sm text-slate-600">{String(item)}</div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState label="MVP scope has not been generated." />
            )}
          </div>
          {opportunity.proposal && (
            <div className="panel p-4">
              <div className="mb-3 font-semibold">Commercial Proposal</div>
              <pre className="whitespace-pre-wrap rounded-md border border-line bg-slate-50 p-3 text-sm text-slate-700">{opportunity.proposal.content}</pre>
            </div>
          )}
        </section>
        <aside className="space-y-4">
          <AICopilotPanel activities={activities} />
          <section className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><Activity className="h-4 w-4" /> AI History</div>
            <AIActivityRows activities={activities} />
          </section>
        </aside>
      </div>
    </div>
  );
}

export function MvpRunView({ mvpRunId }: { mvpRunId: string }) {
  const [run, setRun] = useState<Dict | null>(null);
  const [pkg, setPkg] = useState<Dict | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  function load() {
    Promise.all([apiGet<Dict>(`/api/v1/mvp-runs/${mvpRunId}`), apiGet<Dict>(`/api/v1/mvp-runs/${mvpRunId}/package`)])
      .then(([nextRun, nextPackage]) => {
        setRun(nextRun);
        setPkg(nextPackage);
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => { load(); }, [mvpRunId]);

  async function decide(action: "approve" | "reject" | "request-changes") {
    setError("");
    setMessage("");
    try {
      await apiPost<Dict>(`/api/v1/mvp-runs/${mvpRunId}/${action}`, { comment: `${action} from MVP run workspace` });
      setMessage(`MVP run ${action} recorded.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to decide MVP run");
    }
  }

  async function createAsfRun() {
    setError("");
    setMessage("");
    try {
      const workflow = await apiPost<Dict>(`/api/v1/mvp-runs/${mvpRunId}/create-asf-run`, undefined, { idempotencyKey: crypto.randomUUID() });
      setMessage(`ASF run ${workflow.id} created.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create ASF run");
    }
  }

  if (error && !run) return <div className="panel p-4 text-sm text-rose-700">{error}</div>;
  if (!run) return <div className="panel p-4 text-sm text-slate-500">Loading MVP run...</div>;
  const gates = run.quality_gates_json || [];
  const activities = run.ai_activities || [];
  const artifacts = run.artifacts || pkg?.artifact_records || [];

  return (
    <div className="space-y-5">
      <header className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{run.opportunity?.title || "MVP Run"}</h1>
            <p className="mt-1 text-sm text-slate-600">Package, tests, gates, proposal and human approval.</p>
          </div>
          <StatusPill status={run.status} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <Metric icon={<Gauge className="h-4 w-4" />} label="Progress" value={`${Number(run.progress || 0).toFixed(0)}%`} />
          <Metric icon={<FileText className="h-4 w-4" />} label="Tests" value={run.test_summary_json?.status === "not_run" ? "Not run" : `${Number(run.test_summary_json?.passed || 0)} passed`} />
          <Metric icon={<ShieldCheck className="h-4 w-4" />} label="Gates" value={gates.length} />
          <Metric icon={<Sparkles className="h-4 w-4" />} label="AI Activities" value={activities.length} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={() => decide("approve")} className="inline-flex items-center gap-2 rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white"><CheckCircle2 className="h-4 w-4" /> Approve</button>
          <button onClick={() => decide("request-changes")} className="inline-flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm font-medium"><AlertTriangle className="h-4 w-4" /> Request Changes</button>
          <button onClick={() => decide("reject")} className="inline-flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700"><Ban className="h-4 w-4" /> Reject</button>
          {run.status === "approved" && !run.workflow_run_id && <button onClick={createAsfRun} className="inline-flex items-center gap-2 rounded-md bg-cyan-700 px-3 py-2 text-sm font-medium text-white"><Play className="h-4 w-4" /> Create ASF Run</button>}
          {run.workflow_run_id && <Link href={`/runs/${run.workflow_run_id}`} className="inline-flex items-center gap-2 rounded-md border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-medium text-cyan-900">Open ASF Run</Link>}
        </div>
        {message && <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div>}
        {error && <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
        <section className="space-y-4">
          <div className="panel p-4">
            <div className="mb-3 font-semibold">Quality Gates</div>
            <div className="grid gap-3 md:grid-cols-2">
              {gates.map((gate: Dict) => (
                <div key={gate.id} className="rounded-md border border-line p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium">{gate.id}</div>
                    <StatusPill status={gate.status} />
                  </div>
                  <div className="mt-3"><ProgressBar value={Number(gate.score || 0)} /></div>
                </div>
              ))}
            </div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 font-semibold">Homologation Package</div>
            {pkg ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <StatusPill status={pkg.status || "created"} />
                  <div className="text-sm text-slate-500">{pkg.blueprint_ref}</div>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  {(pkg.artifacts || []).map((artifact: Dict | string) => (
                    <div key={typeof artifact === "string" ? artifact : artifact.id || artifact.name} className="flex items-center justify-between gap-2 rounded-md border border-line px-3 py-2 text-sm">
                      <span>{typeof artifact === "string" ? artifact : artifact.name}</span>
                      {typeof artifact !== "string" && <EvidenceBadge classification={artifact.classification} />}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState label="Package not loaded." />
            )}
          </div>
          <div className="panel p-4">
            <div className="mb-3 font-semibold">Evidence Artifacts</div>
            <div className="space-y-2">
              {artifacts.map((artifact: Dict) => (
                <details key={artifact.id} className="rounded-md border border-line bg-white p-3">
                  <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-medium">
                    <span>{artifact.name}</span>
                    <EvidenceBadge classification={artifact.evidence_classification} />
                  </summary>
                  <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs text-slate-700">{artifact.content}</pre>
                  <div className="mt-2 text-xs text-slate-500">Sources: {(artifact.source_refs_json || []).join(", ") || "not recorded"}</div>
                </details>
              ))}
              {!artifacts.length && <EmptyState label="No evidence artifacts materialized." />}
            </div>
          </div>
          {run.proposal && (
            <div className="panel p-4">
              <div className="mb-3 font-semibold">Proposal</div>
              <pre className="whitespace-pre-wrap rounded-md border border-line bg-slate-50 p-3 text-sm text-slate-700">{run.proposal.content}</pre>
            </div>
          )}
        </section>
        <aside className="space-y-4">
          <AICopilotPanel activities={activities} />
          <section className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold"><Activity className="h-4 w-4" /> Run AI Activity</div>
            <AIActivityRows activities={activities} />
          </section>
        </aside>
      </div>
    </div>
  );
}
