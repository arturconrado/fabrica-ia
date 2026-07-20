"use client";

import { useEffect, useState } from "react";
import { Bot, CheckCircle2, CircleAlert, Fingerprint, Gauge, Link2 } from "lucide-react";
import { EmptyState, MetricCard, Surface } from "@/components/common/OperationalUI";
import { apiGet } from "@/lib/api";
import type { components } from "@/lib/api.generated";
import type { AgentStepSummary, AIWorkspaceSummary, Dict, ExecutionUnitSummary, ValidationManifest } from "@/lib/types";
import { fmtDate, shortId } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

export function AINativeProvenancePanel({
  runId,
  ai,
  steps,
  units,
  fragments,
  validation
}: {
  runId: string;
  ai: AIWorkspaceSummary;
  steps: AgentStepSummary[];
  units: ExecutionUnitSummary[];
  fragments: Dict[];
  validation: ValidationManifest;
}) {
  const [analysis, setAnalysis] = useState<TokenAnalysis | null>(null);
  const [analysisError, setAnalysisError] = useState("");
  useEffect(() => {
    let active = true;
    apiGet<TokenAnalysis>(`/runs/${runId}/token-analysis`)
      .then((value) => { if (active) setAnalysis(value); })
      .catch((reason) => { if (active) setAnalysisError(reason instanceof Error ? reason.message : "Falha ao carregar análise de tokens"); });
    return () => { active = false; };
  }, [runId]);
  const calls = validation.model_calls || [];
  const invariants = Object.entries(validation.invariants || {});
  const budget = validation.budget || {};
  const actual = budget.actual_usd ?? ai.cost_usd;
  const limit = budget.limit_usd ?? ai.budget_usd;
  const withinBudget = budget.within_budget ?? ai.within_budget;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Protocolo" value={validation.executor_protocol_version || ai.executor_protocol_version || validation.generation_mode || ai.generation_mode || "—"} icon={<Bot className="h-5 w-5" />} />
        <MetricCard label="Chamadas reais" value={calls.length || ai.model_calls || "—"} detail="Proveniência persistida por etapa" icon={<Link2 className="h-5 w-5" />} />
        <MetricCard label="Custo observado" value={money(actual)} detail={limit == null ? "Limite não carregado" : `Limite ${money(limit)}`} icon={<Gauge className="h-5 w-5" />} />
        <MetricCard label="Orçamento" value={withinBudget == null ? "—" : withinBudget ? "Dentro do limite" : "Bloqueado"} icon={withinBudget === false ? <CircleAlert className="h-5 w-5 text-red-400" /> : <CheckCircle2 className="h-5 w-5 text-emerald-400" />} />
      </div>

      <Surface>
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Checkpoints e unidades duráveis</h2>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Cada unidade tem identidade idempotente, tentativas, heartbeat, hash e vínculo com a chamada que a produziu.</p>
        </div>
        {units.length ? <div className="divide-y divide-line">{units.map((unit) => (
          <article key={unit.id} className="grid gap-3 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-ink">{unit.node_id} · {unit.unit_key}</span><StatusBadge status={unit.status} /></div>
              <div className="mt-1 text-xs text-[rgb(var(--muted))]">{unit.strategy} / {unit.unit_type} · iteração {unit.iteration} · ordem {unit.order_index} · {unit.attempt_count} tentativas · {unit.continuation_count} continuações</div>
              {unit.targets_json?.length ? <div className="mt-2 truncate font-mono text-[10px] text-[rgb(var(--muted))]" title={unit.targets_json.join(", ")}>{unit.targets_json.join(" · ")}</div> : null}
            </div>
            <div className="text-xs text-[rgb(var(--muted))] lg:text-right">
              <div>finish {unit.finish_reason || "—"} · heartbeat {fmtDate(unit.last_heartbeat_at || "")}</div>
              <div className="mt-1 font-mono text-[10px]">call {unit.model_call_id ? shortId(unit.model_call_id) : "—"} · hash {unit.output_hash ? shortId(unit.output_hash) : "—"}</div>
            </div>
          </article>
        ))}</div> : <div className="p-4"><EmptyState title="Sem unidades segmentadas" description="Runs históricas continuam no executor legado; novas runs AI-native registrarão os checkpoints aqui." /></div>}
        <div className="border-t border-line px-4 py-3 text-xs text-[rgb(var(--muted))]">{fragments.length} fragmentos de artifact persistidos · trace {validation.trace_id || ai.trace_id || "—"}</div>
      </Surface>

      <Surface>
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Eficiência e orçamento v2.13</h2>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Contexto e roteamento são calculados; tokens, cache e custo vêm do provider real.</p>
        </div>
        {analysis ? (
          <>
            <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Tokens úteis" value={integer(analysis.totals.context_selected_tokens)} detail="Contexto selecionado" />
              <MetricCard label="Tokens citados" value={integer(analysis.efficiency.context_cited_tokens)} detail={`${integer(analysis.efficiency.context_selected_not_cited_tokens)} selecionados sem citação`} />
              <MetricCard label="Contexto descartado" value={integer(analysis.totals.context_discarded_tokens)} detail="Fora do orçamento do papel" />
              <MetricCard label="Uso da saída" value={percent(analysis.efficiency.output_utilization)} detail="Resposta real sobre limite concedido" />
              <MetricCard label="Cache provider" value={integer(analysis.efficiency.actual_cache_read_tokens)} detail={`${integer(analysis.efficiency.cache_eligible_tokens)} elegíveis · ${integer(analysis.efficiency.cache_write_tokens)} escritos`} />
              <MetricCard label="Custo de retries" value={money(analysis.efficiency.retry_cost_usd)} detail={`${integer(analysis.efficiency.retry_tokens)} tokens`} />
              <MetricCard label="Orçamento restante" value={money(analysis.budget.remaining_usd)} detail={`Limite ${money(analysis.budget.hard_limit_usd)} · reserva ${money(analysis.budget.reserved_usd)}`} />
              <MetricCard label="Tokens totais" value={integer(analysis.totals.total_tokens)} detail={`${money(analysis.totals.cost_usd)} · ${analysis.totals.retries} retries`} />
            </div>
            <div className="divide-y divide-line border-t border-line">
              {analysis.nodes.map((node, index) => (
                <details key={`${node.node_id}-${node.iteration}-${node.attempt}-${index}`} className="group px-4 py-3">
                  <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 text-sm">
                    <span className="font-semibold text-ink">{node.node_id} · tentativa {node.attempt}</span>
                    <span className="text-xs text-[rgb(var(--muted))]">{integer(node.prompt_tokens + node.completion_tokens)} tokens · {money(node.cost_usd)} · saída {percent(node.output_utilization)}</span>
                  </summary>
                  <div className="grid gap-3 pb-2 pt-3 lg:grid-cols-2">
                    <div className="rounded-lg border border-line bg-[rgb(var(--panel-raised))] p-3 text-xs text-[rgb(var(--muted))]">
                      <div>Política {node.context.policy_version || "—"} · orçamento {integer(node.context.budget_tokens)} · selecionados {integer(node.context.selected_tokens)} · citados {integer(node.context.cited_tokens)} · descartados {integer(node.context.discarded_tokens)}</div>
                      <div className="mt-2">Rota: {node.provider_route || node.routing_reason || "—"} · retry: {node.retry_classification || "inicial"} · finish: {node.finish_reason || "—"} · projetado {money(node.projected_cost_usd)}</div>
                      {node.unit_key ? <div className="mt-2">Unidade: {node.unit_key} · cache {integer(node.cache_read_tokens)} lidos / {integer(node.cache_write_tokens)} escritos</div> : null}
                      {node.budget ? <div className="mt-2">Envelope: limite {money(node.budget.hard_usd)} · reserva {money(node.budget.reserved_usd)}</div> : null}
                    </div>
                    <div className="space-y-2">
                      {(node.context.references || []).map((reference) => (
                        <div key={`${node.node_id}-${reference.ref_id}`} className="rounded-lg border border-line px-3 py-2 text-xs">
                          <div className="flex items-center justify-between gap-2"><span className="font-medium text-ink">{reference.label}</span><span className={(node.context.cited_references || []).includes(reference.ref_id) ? "text-emerald-300" : "text-amber-300"}>{(node.context.cited_references || []).includes(reference.ref_id) ? "citada" : "não citada"}</span></div>
                          <div className="mt-1 text-[rgb(var(--muted))]">{reference.kind} · {integer(reference.estimated_tokens)} tokens · {reference.reason}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </details>
              ))}
            </div>
          </>
        ) : analysisError ? <div className="p-4 text-sm text-red-300" role="alert">{analysisError}</div> : <div className="p-4 text-sm text-[rgb(var(--muted))]" aria-live="polite">Calculando seleção e descarte…</div>}
      </Surface>

      <Surface>
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Manifesto de validação</h2>
          <p className="mt-1 text-xs text-[rgb(var(--muted))]">Vínculos verificáveis entre contexto, modelo, artifact, diff e evidência.</p>
        </div>
        {invariants.length ? (
          <div className="grid gap-2 p-4 sm:grid-cols-2 xl:grid-cols-3">
            {invariants.map(([name, valid]) => (
              <div key={name} className="flex min-h-12 items-center gap-2 rounded-lg border border-line bg-[rgb(var(--panel-raised))] px-3 py-2 text-xs">
                {valid ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" /> : <CircleAlert className="h-4 w-4 shrink-0 text-amber-400" />}
                <span className="break-words text-ink">{invariantLabel(name)}</span>
              </div>
            ))}
          </div>
        ) : <div className="p-4"><EmptyState title="Manifesto ainda não produzido" description="Os invariantes aparecerão assim que a run AI-native persistir a primeira etapa." /></div>}
        {validation.generation_fingerprint ? (
          <div className="flex items-center gap-2 border-t border-line px-4 py-3 font-mono text-[11px] text-[rgb(var(--muted))]">
            <Fingerprint className="h-4 w-4 shrink-0" />
            <span className="truncate" title={validation.generation_fingerprint}>Fingerprint {validation.generation_fingerprint}</span>
          </div>
        ) : null}
      </Surface>

      <div className="grid gap-4 xl:grid-cols-2">
        <Surface>
          <div className="border-b border-line px-4 py-3 text-sm font-semibold text-ink">Etapas AI-native</div>
          {steps.length ? <div className="max-h-[620px] divide-y divide-line overflow-y-auto">{steps.map((step) => (
            <article key={step.id} className="grid gap-2 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-ink">{step.node_id}</span><StatusBadge status={step.status} /></div>
                <div className="mt-1 text-xs text-[rgb(var(--muted))]">{step.phase} · iteração {step.iteration} · passe {step.attempt} · {fmtDate(step.started_at || "")}</div>
                <div className="mt-2 truncate font-mono text-[10px] text-[rgb(var(--muted))]">entrada {step.input_hash || "—"}</div>
              </div>
              <div className="text-left sm:text-right">
                <div className="text-xs font-medium text-ink">{step.decision || "—"}</div>
                <div className="mt-1 font-mono text-[10px] text-[rgb(var(--muted))]">call {step.model_call_id ? shortId(step.model_call_id) : "—"}</div>
              </div>
            </article>
          ))}</div> : <div className="p-4"><EmptyState title="Nenhuma etapa executada" description="A linha será preenchida somente por execuções persistidas." /></div>}
        </Surface>

        <Surface>
          <div className="border-b border-line px-4 py-3 text-sm font-semibold text-ink">Uso por modelo</div>
          {calls.length ? <div className="max-h-[620px] divide-y divide-line overflow-y-auto">{calls.map((call) => (
            <article key={call.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold text-ink">{call.agent_name}</span><StatusBadge status={call.status} /></div>
              <div className="mt-1 text-xs text-[rgb(var(--muted))]">{call.model} · rota {call.model_role}</div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-[rgb(var(--muted))]"><span>Entrada {call.prompt_tokens ?? "—"}</span><span>Saída {call.completion_tokens ?? "—"}</span><span>{money(call.cost_usd)}</span></div>
              <div className="mt-2 text-[10px] text-[rgb(var(--muted))]">provider {call.provider_route || "—"} · cache {call.cache_read_tokens ?? 0}/{call.cache_write_tokens ?? 0} · finish {call.finish_reason || "—"}</div>
              <div className="mt-2 truncate font-mono text-[10px] text-[rgb(var(--muted))]" title={call.id}>call {call.id}</div>
            </article>
          ))}</div> : <div className="p-4"><EmptyState title="Nenhuma chamada registrada" description="Não exibimos estimativas ou chamadas fictícias." /></div>}
        </Surface>
      </div>
    </div>
  );
}

type TokenAnalysis = components["schemas"]["TokenAnalysisResponse"];

function integer(value?: number | null) {
  return value == null ? "—" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }).format(value);
}

function money(value?: number | null) {
  return value == null ? "—" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value);
}

function percent(value?: number | null) {
  return value == null ? "—" : new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function invariantLabel(value: string) {
  return ({
    no_failed_model_calls: "Chamadas de modelo sem falha",
    model_usage_recorded: "Tokens e custo real registrados",
    artifacts_linked_to_model: "Artifacts ligados ao modelo",
    generated_files_linked_to_model: "Arquivos ligados ao modelo",
    tests_are_sandbox_backed: "Testes ligados ao sandbox",
    all_non_human_steps_have_model_call: "Etapas intelectuais ligadas à IA",
    all_ai_workflow_nodes_completed: "Todos os papéis AI-native concluídos",
    generated_application_initializes: "Backend inicializa e frontend compila",
    ai_native_workflow_only: "Workflow v2 sem executor legado"
  } as Record<string, string>)[value] || value.replaceAll("_", " ");
}
