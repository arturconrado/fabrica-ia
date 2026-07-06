"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight,
  Boxes,
  BrainCircuit,
  Building2,
  CheckCircle2,
  ChevronRight,
  Database,
  FileCode2,
  Layers3,
  LockKeyhole,
  Paperclip,
  Play,
  Rocket,
  ShieldCheck,
  Sparkles,
  Workflow,
  Zap
} from "lucide-react";
import { apiPost } from "@/lib/api";

type Template = {
  id: string;
  name: string;
  description: string;
  prompt: string;
  metrics: string[];
};

const templates: Template[] = [
  {
    id: "enterprise-saas",
    name: "Enterprise SaaS",
    description: "Multi-tenant product, RBAC, billing controls and executive dashboards.",
    prompt: "Crie uma plataforma SaaS enterprise com multi-tenant, RBAC, auditoria, billing interno, APIs administrativas e dashboards executivos.",
    metrics: ["RBAC", "Audit", "SLA"]
  },
  {
    id: "internal-operations",
    name: "Internal Operations",
    description: "Workflow cockpit for approvals, queues, SLA and ERP-backed operations.",
    prompt: "Crie uma ferramenta interna para aprovar solicitacoes, gerir filas operacionais, controlar SLA e integrar com ERP e data warehouse.",
    metrics: ["Workflow", "ERP", "SLA"]
  },
  {
    id: "regulated-portal",
    name: "Regulated Portal",
    description: "Secure portal with onboarding, sensitive documents and human approval.",
    prompt: "Crie um portal regulado para clientes enterprise com onboarding, documentos sensiveis, trilha de auditoria e aprovacao humana.",
    metrics: ["LGPD", "Audit", "HITL"]
  }
];

const industries = [
  { id: "financial_services", name: "Financial Services" },
  { id: "healthcare", name: "Healthcare" },
  { id: "manufacturing", name: "Manufacturing" },
  { id: "retail_enterprise", name: "Retail Enterprise" }
];

const stacks = ["FastAPI + Next.js", "Django + React", "Node API + Next.js"];
const qualityProfiles = [
  { id: "regulated_enterprise", name: "Regulated Enterprise" },
  { id: "mission_critical", name: "Mission Critical" },
  { id: "internal_control", name: "Internal Control" }
];

const complianceOptions = ["SOC2", "LGPD", "ISO27001", "SOX", "HIPAA"];
const integrationOptions = ["SSO/OIDC", "ERP", "CRM", "Data Warehouse", "ServiceNow", "Slack"];

const recentBuilds = [
  { name: "ContractOps", status: "HRS 93.45", tone: "emerald" },
  { name: "Inventory Control", status: "Risk review", tone: "amber" },
  { name: "Helpdesk Core", status: "Ready", tone: "cyan" }
];

export function EnterpriseBuilderHome() {
  const [selectedTemplate, setSelectedTemplate] = useState(templates[0]);
  const [projectName, setProjectName] = useState("Enterprise Quality Platform");
  const [prompt, setPrompt] = useState(templates[0].prompt);
  const [industry, setIndustry] = useState(industries[0].id);
  const [stack, setStack] = useState(stacks[0]);
  const [qualityProfile, setQualityProfile] = useState(qualityProfiles[0].id);
  const [compliance, setCompliance] = useState(["SOC2", "LGPD", "ISO27001"]);
  const [integrations, setIntegrations] = useState(["SSO/OIDC", "ERP", "Data Warehouse"]);
  const [starting, setStarting] = useState(false);

  const selectedIndustry = useMemo(() => industries.find((item) => item.id === industry)?.name || industry, [industry]);
  const selectedQuality = useMemo(() => qualityProfiles.find((item) => item.id === qualityProfile)?.name || qualityProfile, [qualityProfile]);

  function chooseTemplate(template: Template) {
    setSelectedTemplate(template);
    setPrompt(template.prompt);
    setProjectName(template.name);
  }

  function toggle(value: string, values: string[], setValues: (next: string[]) => void) {
    setValues(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  }

  async function startEnterpriseRun() {
    setStarting(true);
    try {
      const run = await apiPost<{ id: string }>("/runs/enterprise", {
        prompt: `${prompt}\n\nPreferred stack: ${stack}`,
        project_name: projectName,
        template: selectedTemplate.id,
        industry,
        quality_profile: qualityProfile,
        compliance,
        integrations,
        data_sensitivity: "confidential"
      });
      window.location.assign(`/runs/${run.id}`);
    } finally {
      setStarting(false);
    }
  }

  async function startBatch() {
    const batch = await apiPost<{ id: string }>("/batches");
    window.location.assign(`/batches/${batch.id}`);
  }

  return (
    <div className="space-y-5">
      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="overflow-hidden rounded-lg border border-slate-800 bg-[#101417] text-white">
          <div className="grid min-h-[560px] gap-0 lg:grid-cols-[minmax(0,1fr)_310px]">
            <div className="flex flex-col p-5 sm:p-6">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                <span className="inline-flex items-center gap-1 rounded border border-cyan-400/40 bg-cyan-400/10 px-2 py-1 text-cyan-100">
                  <Sparkles className="h-3.5 w-3.5" /> Enterprise AI Builder
                </span>
                <span className="rounded border border-white/10 px-2 py-1">Tenant {process.env.NEXT_PUBLIC_DEFAULT_TENANT_ID || "local-dev"}</span>
                <span className="rounded border border-emerald-400/40 bg-emerald-400/10 px-2 py-1 text-emerald-100">Quality gate HRS &gt;= 90</span>
              </div>

              <div className="mt-8 max-w-3xl">
                <h1 className="text-4xl font-semibold leading-tight tracking-normal text-white sm:text-5xl">
                  Build enterprise software with governed agent teams.
                </h1>
              </div>

              <div className="mt-6 rounded-lg border border-white/10 bg-white/[0.04] p-3">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
                  <div>
                    <label className="text-xs font-medium text-slate-300" htmlFor="builder-project">Project</label>
                    <input
                      id="builder-project"
                      className="mt-2 w-full rounded-md border border-white/10 bg-[#151b1f] px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300"
                      value={projectName}
                      onChange={(event) => setProjectName(event.target.value)}
                    />
                    <label className="mt-4 block text-xs font-medium text-slate-300" htmlFor="builder-demand">What should the factory build?</label>
                    <textarea
                      id="builder-demand"
                      className="mt-2 min-h-44 w-full resize-y rounded-md border border-white/10 bg-[#151b1f] px-3 py-3 text-sm leading-6 text-white outline-none placeholder:text-slate-500 focus:border-cyan-300"
                      value={prompt}
                      onChange={(event) => setPrompt(event.target.value)}
                    />
                  </div>
                  <div className="rounded-md border border-white/10 bg-black/20 p-3">
                    <BuilderSelect label="Stack" value={stack} onChange={setStack} options={stacks.map((item) => ({ id: item, name: item }))} dark />
                    <BuilderSelect label="Industry" value={industry} onChange={setIndustry} options={industries} dark />
                    <BuilderSelect label="Quality" value={qualityProfile} onChange={setQualityProfile} options={qualityProfiles} dark />
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    className="inline-flex items-center gap-2 rounded-md bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-500"
                    onClick={() => startEnterpriseRun()}
                    disabled={starting || !prompt.trim()}
                  >
                    <Play className="h-4 w-4" /> {starting ? "Starting..." : "Start Enterprise Build"}
                  </button>
                  <button className="inline-flex items-center gap-2 rounded-md border border-white/15 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-white/10" onClick={startBatch}>
                    <Boxes className="h-4 w-4" /> Start Batch
                  </button>
                  <button className="inline-flex items-center gap-2 rounded-md border border-white/15 px-3 py-2 text-sm text-slate-200 hover:bg-white/10">
                    <Paperclip className="h-4 w-4" /> Attach context
                  </button>
                </div>
              </div>

              <div className="mt-5 grid gap-3 md:grid-cols-3">
                {templates.map((template) => (
                  <button
                    key={template.id}
                    className={`rounded-md border p-3 text-left transition ${selectedTemplate.id === template.id ? "border-cyan-300 bg-cyan-300/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.07]"}`}
                    onClick={() => chooseTemplate(template)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-medium">{template.name}</div>
                      <ChevronRight className="h-4 w-4 text-slate-400" />
                    </div>
                    <div className="mt-2 min-h-10 text-xs leading-5 text-slate-300">{template.description}</div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {template.metrics.map((metric) => (
                        <span key={metric} className="rounded border border-white/10 px-2 py-1 text-[11px] text-slate-300">{metric}</span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <aside className="border-t border-white/10 bg-[#0c1114] p-4 lg:border-l lg:border-t-0">
              <div className="rounded-md border border-white/10 bg-white/[0.03] p-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold">AI Team</div>
                  <span className="rounded bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200">ready</span>
                </div>
                <div className="mt-3 space-y-2">
                  {["Product", "Architecture", "Engineering", "QA", "Release"].map((agent, index) => (
                    <div key={agent} className="flex items-center gap-2 rounded border border-white/10 px-2 py-2 text-sm">
                      <span className="flex h-6 w-6 items-center justify-center rounded bg-cyan-300/10 text-xs text-cyan-100">A{index + 1}</span>
                      <span>{agent}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-3 rounded-md border border-white/10 bg-white/[0.03] p-3">
                <div className="text-sm font-semibold">Quality readiness</div>
                <div className="mt-3 flex items-end gap-2">
                  <div className="text-4xl font-semibold text-emerald-200">93+</div>
                  <div className="pb-1 text-xs text-slate-400">target HRS</div>
                </div>
                <div className="mt-3 space-y-2 text-sm">
                  <QualityLine icon={<ShieldCheck className="h-4 w-4" />} label={compliance.join(", ")} />
                  <QualityLine icon={<Database className="h-4 w-4" />} label={integrations.join(", ")} />
                  <QualityLine icon={<Rocket className="h-4 w-4" />} label="Delivery package + approval" />
                </div>
              </div>

              <div className="mt-3 rounded-md border border-white/10 bg-white/[0.03] p-3">
                <div className="text-sm font-semibold">Recent builds</div>
                <div className="mt-3 space-y-2">
                  {recentBuilds.map((build) => (
                    <div key={build.name} className="flex items-center justify-between rounded border border-white/10 px-2 py-2 text-sm">
                      <span>{build.name}</span>
                      <span className={`text-xs ${build.tone === "emerald" ? "text-emerald-200" : build.tone === "amber" ? "text-amber-200" : "text-cyan-200"}`}>{build.status}</span>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        </div>

        <div className="space-y-5">
          <section className="rounded-lg border border-line bg-white p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Workflow className="h-4 w-4" />
              Build Contract
            </div>
            <div className="mt-4 grid gap-3">
              <ContractRow label="Template" value={selectedTemplate.name} />
              <ContractRow label="Industry" value={selectedIndustry} />
              <ContractRow label="Quality" value={selectedQuality} />
              <ContractRow label="Stack" value={stack} />
            </div>
          </section>

          <section className="rounded-lg border border-line bg-white p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <LockKeyhole className="h-4 w-4" />
              Enterprise Controls
            </div>
            <TogglePanel title="Compliance" options={complianceOptions} values={compliance} onToggle={(value) => toggle(value, compliance, setCompliance)} />
            <TogglePanel title="Integrations" options={integrationOptions} values={integrations} onToggle={(value) => toggle(value, integrations, setIntegrations)} />
          </section>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <ModeCard icon={<BrainCircuit className="h-4 w-4" />} title="Agent Build" detail="Planner, architect, engineer, QA and release roles work as a traceable team." />
        <ModeCard icon={<FileCode2 className="h-4 w-4" />} title="Preview + Files" detail="Generated app files, diffs, artifacts and test evidence stay tied to the run." />
        <ModeCard icon={<Layers3 className="h-4 w-4" />} title="Homologation" detail="HRS, quality gates, package, approval and learning close the release loop." />
      </section>
    </div>
  );
}

function ContractRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-medium">{value || "-"}</div>
    </div>
  );
}

function BuilderSelect({
  label,
  value,
  options,
  onChange,
  dark = false
}: {
  label: string;
  value: string;
  options: { id: string; name: string }[];
  onChange: (value: string) => void;
  dark?: boolean;
}) {
  return (
    <div className="mb-3 last:mb-0">
      <label className={`text-xs ${dark ? "text-slate-400" : "text-slate-500"}`} htmlFor={label}>{label}</label>
      <select
        id={label}
        className={`mt-2 w-full rounded-md border px-3 py-2 text-sm outline-none ${dark ? "border-white/10 bg-[#151b1f] text-white focus:border-cyan-300" : "border-line bg-white focus:border-slate-900"}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </div>
  );
}

function TogglePanel({
  title,
  options,
  values,
  onToggle
}: {
  title: string;
  options: string[];
  values: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="mt-4">
      <div className="text-xs text-slate-500">{title}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((option) => {
          const active = values.includes(option);
          return (
            <button
              key={option}
              className={`rounded-md border px-2.5 py-1.5 text-xs ${active ? "border-slate-900 bg-slate-900 text-white" : "border-line bg-white hover:bg-slate-50"}`}
              onClick={() => onToggle(option)}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function QualityLine({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 text-slate-300">
      <span className="text-cyan-200">{icon}</span>
      <span className="truncate">{label}</span>
    </div>
  );
}

function ModeCard({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <span className="rounded-md bg-slate-100 p-2 text-slate-700">{icon}</span>
        {title}
      </div>
      <div className="mt-3 text-sm leading-6 text-slate-600">{detail}</div>
      <div className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-slate-500">
        Open in workspace <ArrowRight className="h-3.5 w-3.5" />
      </div>
    </div>
  );
}
