"use client";

import { useEffect, useMemo, useState } from "react";
import { BookCheck, BrainCircuit, FlaskConical, ShieldCheck, Signal, Undo2 } from "lucide-react";

import { EmptyState, ErrorState, LoadingState, MetricCard, PageHeader, Surface } from "@/components/common/OperationalUI";
import { apiGet, apiPost, commandKey } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

type Lesson = { id: string; lesson: string; status: string; agent_name: string; evidence_json?: Record<string, unknown>; created_at: string };
type Reward = { id: string; reward_value: number; reason: string; created_at: string };
type SignalItem = { id: string; signal_type: string; agent_name: string; value: number; evidence_json?: Record<string, unknown>; created_at: string };
type Metrics = { medians?: Record<string, number | null>; run_count?: number; missions?: Record<string, number> };
type Candidate = {
  id: string;
  title: string;
  abstract_pattern: string;
  candidate_type: string;
  status: string;
  target_agents_json: string[];
  evidence_run_count: number;
  evidence_tenant_count: number;
  anonymization_json?: { method?: string; redaction_counts?: Record<string, number>; contains_raw_source?: boolean };
  evaluation_json?: { status?: string; baseline?: Metrics; candidate?: Metrics; gate_results?: Record<string, boolean | string[]> };
  created_at: string;
};
type Policy = { id: string; policy_type: string; version: string; status: string; configuration_json?: Record<string, unknown>; previous_policy_id?: string | null; created_at: string };
type GlobalDeployment = { id: string; rollout_stage: "shadow" | "internal" | "canary" | "active"; status: string; record_version: number; previous_deployment_id?: string | null };
type GlobalPolicy = { id: string; policy_type: string; version: string; title: string; abstract_pattern: string; status: string; evidence_run_count: number; evidence_tenant_count: number; target_agents_json?: string[]; tenant_deployment?: GlobalDeployment | null; created_at: string };
type EffectivePolicy = {
  precedence: string[];
  platform_controls: { immutable: string[] };
  global: Array<{ policy_id: string; type: string; version: string; pattern: string; target_agents: string[] }>;
  tenant_private: Array<{ policy_id: string; type: string; version: string; configuration: Record<string, unknown> }>;
};

export default function LearningPage() {
  const [lessons, setLessons] = useState<Lesson[] | null>(null);
  const [rewards, setRewards] = useState<Reward[] | null>(null);
  const [signals, setSignals] = useState<SignalItem[] | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [policies, setPolicies] = useState<Policy[] | null>(null);
  const [globalPolicies, setGlobalPolicies] = useState<GlobalPolicy[]>([]);
  const [effectivePolicy, setEffectivePolicy] = useState<EffectivePolicy | null>(null);
  const [globalRegistryAllowed, setGlobalRegistryAllowed] = useState(true);
  const [comments, setComments] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      setError("");
      const [lessonRows, rewardRows, signalRows, candidateRows, policyRows, effectiveRows, globalRows] = await Promise.all([
        apiGet<Lesson[]>("/learning/lessons"),
        apiGet<Reward[]>("/learning/reward-signals"),
        apiGet<SignalItem[]>("/learning/signals"),
        apiGet<Candidate[]>("/learning/candidates"),
        apiGet<Policy[]>("/learning/policies"),
        apiGet<EffectivePolicy>("/api/v1/learning/effective-policy"),
        apiGet<GlobalPolicy[]>("/api/v1/admin/global-learning/policies")
          .then((rows) => ({ rows, allowed: true }))
          .catch(() => ({ rows: [], allowed: false })),
      ]);
      setLessons(lessonRows);
      setRewards(rewardRows);
      setSignals(signalRows);
      setCandidates(candidateRows);
      setPolicies(policyRows);
      setEffectivePolicy(effectiveRows);
      setGlobalPolicies(globalRows.rows);
      setGlobalRegistryAllowed(globalRows.allowed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao carregar aprendizado");
    }
  }

  useEffect(() => { void load(); }, []);

  async function command(key: string, action: () => Promise<unknown>) {
    try {
      setBusy(key);
      setError("");
      await action();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha na operação de curadoria");
    } finally {
      setBusy("");
    }
  }

  const agentMetrics = useMemo(() => {
    const groups = new Map<string, { count: number; value: number; tokens: number; cost: number }>();
    for (const item of signals || []) {
      const key = item.agent_name || "Sem agente";
      const current = groups.get(key) || { count: 0, value: 0, tokens: 0, cost: 0 };
      const evidence = item.evidence_json || {};
      current.count += 1;
      current.value += Number(item.value || 0);
      current.tokens += Number(evidence.prompt_tokens || 0) + Number(evidence.completion_tokens || 0);
      current.cost += Number(evidence.cost_usd || 0);
      groups.set(key, current);
    }
    return [...groups.entries()].map(([agent, value]) => ({ agent, ...value })).sort((a, b) => b.count - a.count);
  }, [signals]);

  if (error && !lessons) return <ErrorState message={error} />;
  if (!lessons || !rewards || !signals || !candidates || !policies || !effectivePolicy) return <LoadingState label="Carregando sinais e políticas de aprendizado…" />;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Curadoria humana" title="Aprendizado contínuo" description="Sinais privados viram padrões abstratos somente após anonimização, benchmark repetido e decisão humana. Nenhum prompt é alterado automaticamente." />
      {error ? <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200" role="alert">{error}</div> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Lessons privadas" value={lessons.length} icon={<BookCheck className="h-5 w-5" />} />
        <MetricCard label="Sinais auditáveis" value={signals.length} icon={<Signal className="h-5 w-5" />} />
        <MetricCard label="Candidatas globais" value={candidates.length} icon={<FlaskConical className="h-5 w-5" />} />
        <MetricCard label="Políticas ativas" value={policies.filter((item) => item.status === "active").length} icon={<BrainCircuit className="h-5 w-5" />} />
        <MetricCard label="Rewards neutros" value={rewards.filter((item) => Number(item.reward_value) === 0).length} detail="Neutro não é positivo" />
      </div>

      <Surface>
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-sm font-semibold text-ink">Política efetiva e precedência</h2>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Controles determinísticos prevalecem; políticas globais e privadas somente orientam a execução intelectual.</p>
        </div>
        <div className="grid gap-px bg-[rgb(var(--line))] lg:grid-cols-4">
          {effectivePolicy.precedence.map((scope, index) => {
            const values = scope === "platform_controls"
              ? effectivePolicy.platform_controls.immutable
              : scope === "approved_global"
                ? effectivePolicy.global.map((item) => `${item.type} ${item.version}`)
                : scope === "approved_tenant_private"
                  ? effectivePolicy.tenant_private.map((item) => `${item.type} ${item.version}`)
                  : ["briefing, artifacts, RAG e Definition of Done"];
            return (
              <div key={scope} className="min-h-32 bg-[rgb(var(--panel))] p-4">
                <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-400">Prioridade {index + 1}</div>
                <div className="mt-2 text-sm font-semibold text-ink">{scope.replaceAll("_", " ")}</div>
                <div className="mt-3 text-xs leading-5 text-[rgb(var(--muted))]">{values.length ? values.join(" · ") : "Nenhuma política ativa neste escopo"}</div>
              </div>
            );
          })}
        </div>
      </Surface>

      <div className="grid gap-5 xl:grid-cols-2">
        <Surface>
          <div className="border-b border-line px-5 py-4">
            <h2 className="text-sm font-semibold text-ink">Lessons privadas do tenant</h2>
            <p className="mt-1 text-xs text-[rgb(var(--muted))]">O texto permanece isolado; a proposta global passa pelo extrator local.</p>
          </div>
          {lessons.length ? <div className="divide-y divide-line">{lessons.map((lesson) => (
            <article key={lesson.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-3"><p className="text-sm leading-6 text-ink">{lesson.lesson}</p><StatusBadge status={lesson.status} /></div>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-[rgb(var(--muted))]">{lesson.agent_name} · {fmtDate(lesson.created_at)}</span>
                <div className="flex gap-2">
                  {lesson.status !== "approved" ? <button disabled={busy === lesson.id} onClick={() => void command(lesson.id, () => apiPost(`/learning/lessons/${lesson.id}/approve`))} className="min-h-11 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-semibold text-blue-200 disabled:opacity-50">Aprovar privada</button> : null}
                  {lesson.status === "approved" ? <button disabled={busy === lesson.id} onClick={() => void command(lesson.id, () => apiPost(`/learning/lessons/${lesson.id}/propose-global`, { title: "Padrão abstrato curado", target_agents: [lesson.agent_name], critical_security: false }))} className="min-h-11 rounded-lg border border-orange-500/30 bg-orange-500/10 px-3 text-xs font-semibold text-orange-200 disabled:opacity-50">Propor global</button> : null}
                </div>
              </div>
            </article>
          ))}</div> : <div className="p-5"><EmptyState title="Nenhuma lesson privada" description="Feedback, testes e gates produzirão sinais sem compartilhar conteúdo entre clientes." /></div>}
        </Surface>

        <Surface>
          <div className="border-b border-line px-5 py-4">
            <h2 className="text-sm font-semibold text-ink">Qualidade e custo por agente</h2>
            <p className="mt-1 text-xs text-[rgb(var(--muted))]">Agregação do tenant ativo com proveniência em model calls reais.</p>
          </div>
          {agentMetrics.length ? <div className="divide-y divide-line">{agentMetrics.map((row) => (
            <div key={row.agent} className="grid gap-2 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_repeat(3,auto)] sm:items-center">
              <div className="text-sm font-semibold text-ink">{row.agent}</div>
              <div className="text-xs text-[rgb(var(--muted))]">qualidade média {(row.value / row.count).toFixed(2)}</div>
              <div className="text-xs text-[rgb(var(--muted))]">{integer(row.tokens)} tokens</div>
              <div className="text-xs text-[rgb(var(--muted))]">{money(row.cost)}</div>
            </div>
          ))}</div> : <div className="p-5"><EmptyState title="Sem execução AI-native" description="As métricas aparecem após model calls persistidas." /></div>}
        </Surface>
      </div>

      <Surface>
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-sm font-semibold text-ink">Candidatas e benchmark</h2>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Aprovação exige redução de 40%, schemas válidos, 17 gates, isolamento, qualidade não inferior e três repetições.</p>
        </div>
        {candidates.length ? <div className="divide-y divide-line">{candidates.map((candidate) => {
          const baseline = candidate.evaluation_json?.baseline?.medians || {};
          const optimized = candidate.evaluation_json?.candidate?.medians || {};
          const gateResults = candidate.evaluation_json?.gate_results || {};
          return (
            <article key={candidate.id} className="space-y-4 px-5 py-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-ink">{candidate.title}</h3><StatusBadge status={candidate.status} /></div><p className="mt-2 max-w-4xl text-sm leading-6 text-[rgb(var(--muted))]">{candidate.abstract_pattern}</p></div>
                <div className="text-right text-xs text-[rgb(var(--muted))]">{candidate.evidence_run_count} runs · {candidate.evidence_tenant_count} tenants</div>
              </div>
              <div className="grid gap-3 lg:grid-cols-3">
                <div className="rounded-lg border border-line bg-[rgb(var(--panel-raised))] p-3 text-xs text-[rgb(var(--muted))]"><ShieldCheck className="mb-2 h-4 w-4 text-emerald-400" />Anonimização: {candidate.anonymization_json?.method || "—"}<br />Fonte bruta incluída: {candidate.anonymization_json?.contains_raw_source ? "sim" : "não"}</div>
                <div className="rounded-lg border border-line bg-[rgb(var(--panel-raised))] p-3 text-xs text-[rgb(var(--muted))]">Baseline v2.11<br /><span className="text-sm font-semibold text-ink">{integer(baseline.tokens)} tokens · {money(baseline.cost_usd)}</span></div>
                <div className="rounded-lg border border-line bg-[rgb(var(--panel-raised))] p-3 text-xs text-[rgb(var(--muted))]">Candidata v2.12<br /><span className="text-sm font-semibold text-ink">{integer(optimized.tokens)} tokens · {money(optimized.cost_usd)}</span></div>
              </div>
              {Object.keys(gateResults).length ? <div className="flex flex-wrap gap-2">{Object.entries(gateResults).filter(([name]) => name !== "failed").map(([name, passed]) => <span key={name} className={`rounded-full border px-2.5 py-1 text-[10px] ${passed ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-amber-500/30 bg-amber-500/10 text-amber-200"}`}>{name.replaceAll("_", " ")}</span>)}</div> : null}
              <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
                <label className="flex-1 text-xs text-[rgb(var(--muted))]">Comentário obrigatório<input value={comments[candidate.id] || ""} onChange={(event) => setComments((current) => ({ ...current, [candidate.id]: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border border-line bg-[rgb(var(--panel-raised))] px-3 text-sm text-ink outline-none focus:border-blue-500" /></label>
                <button disabled={busy === candidate.id} onClick={() => void command(candidate.id, () => apiPost(`/learning/candidates/${candidate.id}/evaluate`))} className="min-h-11 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-xs font-semibold text-blue-200 disabled:opacity-50">Executar benchmark</button>
                <button disabled={busy === candidate.id || !comments[candidate.id]} onClick={() => void command(candidate.id, () => apiPost(`/learning/candidates/${candidate.id}/decisions`, { decision: "approve", comment: comments[candidate.id] }))} className="min-h-11 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-xs font-semibold text-emerald-200 disabled:opacity-50">Aprovar</button>
                <button disabled={busy === candidate.id || !comments[candidate.id]} onClick={() => void command(candidate.id, () => apiPost(`/learning/candidates/${candidate.id}/decisions`, { decision: "reject", comment: comments[candidate.id] }))} className="min-h-11 rounded-lg border border-red-500/30 bg-red-500/10 px-4 text-xs font-semibold text-red-200 disabled:opacity-50">Rejeitar</button>
                {candidate.status === "approved" && globalRegistryAllowed ? <button disabled={busy === candidate.id || !comments[candidate.id]} onClick={() => void command(candidate.id, () => apiPost(`/api/v1/admin/global-learning/candidates/${candidate.id}/promote`, { comment: comments[candidate.id] }, { idempotencyKey: commandKey(`global-promote:${candidate.id}`) }))} className="min-h-11 rounded-lg border border-orange-500/30 bg-orange-500/10 px-4 text-xs font-semibold text-orange-200 disabled:opacity-50">Promover ao registro global</button> : null}
              </div>
            </article>
          );
        })}</div> : <div className="p-5"><EmptyState title="Nenhuma candidata global" description="Aprove uma lesson privada e proponha apenas o padrão abstrato anonimizado." /></div>}
      </Surface>

      <Surface>
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-sm font-semibold text-ink">Registro global sanitizado</h2>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Somente padrões abstratos aprovados. O deployment é um ponteiro tenant-scoped com rollout e rollback humanos.</p>
        </div>
        {!globalRegistryAllowed ? (
          <div className="p-5"><EmptyState title="Registro administrativo restrito" description="O operador pode consultar a política efetiva; promoção e deployment exigem owner ou super_admin." /></div>
        ) : globalPolicies.length ? (
          <div className="divide-y divide-line">
            {globalPolicies.map((policy) => {
              const deployment = policy.tenant_deployment;
              const upcoming = nextStage(deployment?.rollout_stage);
              const commentKey = `global:${policy.id}`;
              return (
                <article key={policy.id} className="space-y-3 px-5 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-ink">{policy.title}</h3><StatusBadge status={deployment?.rollout_stage || "approved"} /></div>
                      <p className="mt-2 max-w-4xl text-sm leading-6 text-[rgb(var(--muted))]">{policy.abstract_pattern}</p>
                      <div className="mt-2 text-xs text-[rgb(var(--muted))]">{policy.version} · {policy.evidence_run_count} runs · {policy.evidence_tenant_count} tenants · {policy.target_agents_json?.join(", ") || "todos os agentes aplicáveis"}</div>
                    </div>
                  </div>
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
                    <label className="flex-1 text-xs text-[rgb(var(--muted))]">Comentário administrativo<input value={comments[commentKey] || ""} onChange={(event) => setComments((current) => ({ ...current, [commentKey]: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border border-line bg-[rgb(var(--panel-raised))] px-3 text-sm text-ink outline-none focus:border-blue-500" /></label>
                    {upcoming ? <button disabled={busy === commentKey || !comments[commentKey]} onClick={() => void command(commentKey, () => apiPost(`/api/v1/admin/global-learning/policies/${policy.id}/deployments`, { rollout_stage: upcoming, expected_version: deployment?.record_version || 0, comment: comments[commentKey] }, { idempotencyKey: commandKey(`global-deploy:${policy.id}:${upcoming}`) }))} className="min-h-11 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-xs font-semibold text-blue-200 disabled:opacity-50">Avançar para {upcoming}</button> : null}
                    {deployment?.previous_deployment_id ? <button disabled={busy === commentKey || !comments[commentKey]} onClick={() => void command(commentKey, () => apiPost(`/api/v1/admin/global-learning/deployments/${deployment.id}/rollback`, { expected_version: deployment.record_version, comment: comments[commentKey] }, { idempotencyKey: commandKey(`global-rollback:${deployment.id}`) }))} className="min-h-11 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 text-xs font-semibold text-amber-200 disabled:opacity-50"><Undo2 className="mr-2 inline h-4 w-4" />Rollback do deployment</button> : null}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="p-5"><EmptyState title="Registro global vazio" description="Nenhum padrão sanitizado concluiu corroboração, benchmark e promoção administrativa." /></div>
        )}
      </Surface>

      <Surface>
        <div className="border-b border-line px-5 py-4 text-sm font-semibold text-ink">Políticas imutáveis e rollback</div>
        {policies.length ? <div className="divide-y divide-line">{policies.map((policy) => (
          <div key={policy.id} className="flex flex-wrap items-end justify-between gap-3 px-5 py-4">
            <div><div className="flex items-center gap-2"><span className="text-sm font-semibold text-ink">{policy.policy_type} · {policy.version}</span><StatusBadge status={policy.status} /></div><div className="mt-1 text-xs text-[rgb(var(--muted))]">{fmtDate(policy.created_at)} · anterior {policy.previous_policy_id || "—"}</div></div>
            {["shadow", "internal", "canary"].includes(policy.status) ? <div className="flex flex-1 flex-wrap items-end justify-end gap-2"><label className="min-w-64 text-xs text-[rgb(var(--muted))]">Evidência e motivo da promoção<input value={comments[policy.id] || ""} onChange={(event) => setComments((current) => ({ ...current, [policy.id]: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border border-line bg-[rgb(var(--panel-raised))] px-3 text-sm text-ink outline-none focus:border-blue-500" /></label><button disabled={busy === policy.id || !comments[policy.id]} onClick={() => void command(policy.id, () => apiPost(`/learning/policies/${policy.id}/promote-stage`, { comment: comments[policy.id] }))} className="min-h-11 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 text-xs font-semibold text-blue-200 disabled:opacity-50">Avançar rollout</button></div> : null}
            {policy.status === "active" && policy.previous_policy_id ? <div className="flex flex-1 flex-wrap items-end justify-end gap-2"><label className="min-w-64 text-xs text-[rgb(var(--muted))]">Motivo do rollback<input value={comments[policy.id] || ""} onChange={(event) => setComments((current) => ({ ...current, [policy.id]: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border border-line bg-[rgb(var(--panel-raised))] px-3 text-sm text-ink outline-none focus:border-blue-500" /></label><button disabled={busy === policy.id || !comments[policy.id]} onClick={() => void command(policy.id, () => apiPost(`/learning/policies/${policy.id}/rollback`, { comment: comments[policy.id] }))} className="min-h-11 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 text-xs font-semibold text-amber-200 disabled:opacity-50"><Undo2 className="mr-2 inline h-4 w-4" />Rollback</button></div> : null}
          </div>
        ))}</div> : <div className="p-5"><EmptyState title="Nenhuma política promovida" description="A versão ativa só nasce após benchmark aprovado e decisão humana." /></div>}
      </Surface>
    </div>
  );
}

function integer(value?: number | null) { return value == null ? "—" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(value); }
function money(value?: number | null) { return value == null ? "—" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", maximumFractionDigits: 4 }).format(value); }
function nextStage(current?: GlobalDeployment["rollout_stage"]): GlobalDeployment["rollout_stage"] | null {
  if (!current) return "shadow";
  return ({ shadow: "internal", internal: "canary", canary: "active", active: null } as const)[current];
}
