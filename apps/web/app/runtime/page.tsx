"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  BadgeCheck,
  BrainCircuit,
  CircleAlert,
  Clock3,
  Coins,
  DatabaseZap,
  ServerCog,
} from "lucide-react";

import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  Surface,
} from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

type ModelCall = {
  id: string;
  run_id: string;
  agent_name: string;
  provider: string;
  model_name: string;
  status: string;
  estimated_cost_usd: number;
  duration_seconds: number;
  prompt_tokens: number;
  completion_tokens: number;
  cache_eligible_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  cache_savings_usd: number;
  provider_route?: string;
  finish_reason?: string;
  execution_unit_id?: string | null;
  created_at: string;
};

type Sandbox = {
  id: string;
  run_id: string;
  backend: string;
  command: string;
  status: string;
  duration_seconds: number;
  created_at: string;
};

type SLO = {
  status: string;
  metrics: Record<string, number | null>;
  criteria: Record<string, boolean>;
  unavailable: Record<string, string>;
  provenance: string;
};

const SLO_LABELS: Record<string, string> = {
  mission_review_without_intervention_gte_90: "90% chegam à revisão sem intervenção",
  mission_review_after_recovery_gte_95: "95% chegam à revisão após uma retomada",
  rpo_zero_confirmed_outputs: "RPO zero para outputs confirmados",
  rto_recovery_p95_lte_300_seconds: "RTO p95 de recuperação até 5 minutos",
  review_time_p95_lte_7200_seconds: "Tempo p95 até revisão até 120 minutos",
  schema_invalid_zero: "Nenhum schema final inválido",
  model_call_error_lte_5_percent: "Erro de model call até 5%",
  timeout_lte_3_percent: "Timeout até 3%",
  mission_cost_p95_lte_15_usd: "Custo p95 por missão até US$ 15",
  all_17_gates_passed: "17 gates aprovados",
  hrs_minimum_90: "HRS mínimo 90",
  cache_telemetry_coverage_100_percent: "Telemetria em 100% das chamadas elegíveis",
  warmed_cache_read_positive: "Cache aquecido com leitura positiva",
  reported_cache_savings_positive: "Economia líquida reportada pelo provider",
};

export default function RuntimePage() {
  const [calls, setCalls] = useState<ModelCall[] | null>(null);
  const [executions, setExecutions] = useState<Sandbox[] | null>(null);
  const [slo, setSlo] = useState<SLO | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      apiGet<ModelCall[]>("/model-calls"),
      apiGet<Sandbox[]>("/sandbox-executions"),
      apiGet<SLO>("/api/v1/operator/slo"),
    ])
      .then(([modelCalls, sandboxExecutions, sloResult]) => {
        setCalls(modelCalls);
        setExecutions(sandboxExecutions);
        setSlo(sloResult);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  if (error) return <ErrorState message={error} />;
  if (!calls || !executions || !slo) return <LoadingState label="Carregando telemetria do runtime…" />;

  const cost = calls.reduce((sum, call) => sum + Number(call.estimated_cost_usd || 0), 0);
  const tokens = calls.reduce(
    (sum, call) => sum + Number(call.prompt_tokens || 0) + Number(call.completion_tokens || 0),
    0,
  );
  const cacheRead = calls.reduce((sum, call) => sum + Number(call.cache_read_tokens || 0), 0);
  const cacheEligible = calls.reduce((sum, call) => sum + Number(call.cache_eligible_tokens || 0), 0);
  const cacheSavings = calls.reduce((sum, call) => sum + Number(call.cache_savings_usd || 0), 0);
  const passedCriteria = Object.values(slo.criteria).filter(Boolean).length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Telemetria real"
        title="Runtime e confiabilidade"
        description="Chamadas de modelo, cache reportado pelo provider, sandbox e SLOs calculados apenas com evidências persistidas do tenant ativo."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Chamadas de modelo" value={calls.length} icon={<BrainCircuit className="h-5 w-5" />} />
        <MetricCard label="Tokens registrados" value={tokens.toLocaleString("pt-BR")} />
        <MetricCard label="Custo estimado" value={calls.length ? usd(cost) : "—"} detail="Estimado a partir do uso real" icon={<Coins className="h-5 w-5" />} />
        <MetricCard label="Cache lido / elegível" value={`${integer(cacheRead)} / ${integer(cacheEligible)}`} detail="Somente contadores informados pelo provider" icon={<DatabaseZap className="h-5 w-5" />} />
        <MetricCard label="Economia de cache" value={cacheEligible ? usd(cacheSavings) : "—"} detail="Não inferida quando o provider não reporta" />
      </div>

      <Surface>
        <div className="flex flex-col gap-3 border-b border-line px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink">SLOs do piloto assistido</h2>
            <p className="mt-1 text-xs text-[rgb(var(--muted))]">{passedCriteria} de {Object.keys(slo.criteria).length} critérios atendidos na janela atual.</p>
          </div>
          <StatusBadge status={slo.status} />
        </div>
        <div className="grid gap-px bg-[rgb(var(--line))] sm:grid-cols-2 xl:grid-cols-3">
          {Object.entries(slo.criteria).map(([criterion, passed]) => (
            <div key={criterion} className="flex min-h-20 items-start gap-3 bg-[rgb(var(--panel))] px-5 py-4">
              {passed ? (
                <BadgeCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" aria-hidden="true" />
              ) : (
                <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" aria-hidden="true" />
              )}
              <div>
                <div className="text-sm font-medium text-ink">{SLO_LABELS[criterion] || criterion.replaceAll("_", " ")}</div>
                <div className="mt-1 text-xs text-[rgb(var(--muted))]">{passed ? "Evidência suficiente e meta atendida" : "Meta ainda não comprovada"}</div>
              </div>
            </div>
          ))}
        </div>
        {Object.keys(slo.unavailable).length ? (
          <div className="border-t border-line px-5 py-3 text-xs text-[rgb(var(--muted))]">
            Métricas externas pendentes: {Object.keys(slo.unavailable).map((item) => item.replaceAll("_", " ")).join(", ")}.
          </div>
        ) : null}
      </Surface>

      <div className="grid gap-5 xl:grid-cols-2">
        <Surface>
          <div className="border-b border-line px-5 py-4 text-sm font-semibold">Chamadas de modelo</div>
          {calls.length ? (
            <div className="max-h-[70vh] divide-y divide-line overflow-y-auto">
              {calls.map((call) => (
                <article key={call.id} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <BrainCircuit className="h-4 w-4 text-blue-400" aria-hidden="true" />
                        {call.model_name}
                      </div>
                      <div className="mt-1 text-xs text-[rgb(var(--muted))]">
                        {call.agent_name || "Agente não registrado"} · {call.provider_route || call.provider} · {fmtDate(call.created_at)}
                      </div>
                    </div>
                    <StatusBadge status={call.status} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-[rgb(var(--muted))]">
                    <span>{integer(call.prompt_tokens + call.completion_tokens)} tokens</span>
                    <span>{Number(call.duration_seconds || 0).toFixed(2)}s</span>
                    <span>{usd(Number(call.estimated_cost_usd || 0))}</span>
                    {call.execution_unit_id ? <span>unidade {call.execution_unit_id.slice(0, 8)}</span> : null}
                    {call.finish_reason ? <span>fim {call.finish_reason}</span> : null}
                  </div>
                  {call.cache_eligible_tokens > 0 ? (
                    <div className="mt-2 text-[11px] text-emerald-300">
                      Cache: {integer(call.cache_read_tokens)} lidos de {integer(call.cache_eligible_tokens)} elegíveis · {usd(call.cache_savings_usd)} economizados
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="p-5"><EmptyState title="Sem chamadas" description="Nenhuma chamada de modelo foi persistida neste tenant." /></div>
          )}
        </Surface>

        <Surface>
          <div className="border-b border-line px-5 py-4 text-sm font-semibold">Sandbox allowlisted</div>
          {executions.length ? (
            <div className="max-h-[70vh] divide-y divide-line overflow-y-auto">
              {executions.map((item) => (
                <article key={item.id} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <Activity className="h-4 w-4 text-blue-400" aria-hidden="true" />
                        {item.backend}
                      </div>
                      <div className="mt-1 break-all font-mono text-[11px] text-[rgb(var(--muted))]">{item.command}</div>
                    </div>
                    <StatusBadge status={item.status} />
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-[11px] text-[rgb(var(--muted))]">
                    <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                    {Number(item.duration_seconds || 0).toFixed(2)}s · {fmtDate(item.created_at)}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="p-5"><EmptyState title="Sem execuções" description="Nenhum comando allowlisted foi executado para este tenant." /></div>
          )}
        </Surface>
      </div>

      <div className="sr-only" aria-live="polite">
        {calls.length} chamadas de modelo e {executions.length} execuções de sandbox carregadas.
      </div>
    </div>
  );
}

function integer(value: number): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(value);
}

function usd(value: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", maximumFractionDigits: 6 }).format(value);
}
