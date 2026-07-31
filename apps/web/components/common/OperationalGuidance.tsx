"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, CheckCircle2, ShieldAlert, Sparkles } from "lucide-react";

import type { OperationalGuidance as Guidance } from "@/lib/contracts";
import { fmtDate } from "@/lib/format";


export function OperationalGuidance({ guidance, onUseDraft }: { guidance: Guidance; onUseDraft?: (draft: string) => void }) {
  const [showDraft, setShowDraft] = useState(false);

  function useDraft() {
    setShowDraft(true);
    onUseDraft?.(guidance.draft);
  }

  return (
    <section className="rounded-2xl border border-blue-500/30 bg-gradient-to-br from-blue-500/10 to-transparent p-5" aria-labelledby="operational-guidance-title">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-blue-300"><Sparkles className="h-4 w-4" /> Agora</div>
          <h2 id="operational-guidance-title" className="mt-2 text-xl font-semibold text-ink">{guidance.action.title}</h2>
          <p className="mt-2 text-sm leading-6 text-[rgb(var(--muted))]">{guidance.why_now}</p>
        </div>
        <Link href={guidance.action.href} className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white">
          {guidance.action.title} <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="flex items-center gap-2 text-xs font-semibold text-ink"><CheckCircle2 className="h-4 w-4 text-emerald-400" /> Confira antes</h3>
          <ul className="mt-2 space-y-2 text-sm text-[rgb(var(--muted))]">{guidance.checks.map((item) => <li key={item}>• {item}</li>)}</ul>
        </div>
        <div>
          <h3 className="flex items-center gap-2 text-xs font-semibold text-ink"><ShieldAlert className="h-4 w-4 text-amber-400" /> Riscos</h3>
          {guidance.risks.length ? <ul className="mt-2 space-y-2 text-sm text-[rgb(var(--muted))]">{guidance.risks.map((item) => <li key={item}>• {item}</li>)}</ul> : <p className="mt-2 text-sm text-[rgb(var(--muted))]">Nenhum risco adicional respaldado pelas evidências atuais.</p>}
        </div>
      </div>

      {guidance.draft ? <div className="mt-5 border-t border-line pt-4">
        {!showDraft ? <button type="button" className="min-h-11 rounded-lg border border-line px-4 text-sm font-semibold text-ink" onClick={useDraft}>Usar rascunho</button> : <div><label className="text-xs font-semibold text-ink" htmlFor={`guidance-${guidance.state_hash}`}>Rascunho preparado — confirme antes de enviar</label><textarea id={`guidance-${guidance.state_hash}`} className="mt-2 min-h-28 w-full rounded-lg border px-3 py-3 text-sm" defaultValue={guidance.draft} /></div>}
      </div> : null}

      <details className="mt-4 border-t border-line pt-3 text-xs text-[rgb(var(--muted))]">
        <summary className="min-h-11 cursor-pointer py-3 font-semibold">Proveniência e referências</summary>
        <p>{guidance.provenance.source === "ai" ? "Explicação produzida na chamada de IA que alterou o estado." : "Fallback determinístico; a operação não depende do provider."} · {fmtDate(guidance.generated_at)}</p>
        <p className="mt-1 break-all">Estado {guidance.state_hash.slice(0, 12)} · {guidance.evidence_refs.length} referências{guidance.provenance.model_call_id ? ` · model call ${guidance.provenance.model_call_id}` : ""}</p>
      </details>
    </section>
  );
}
