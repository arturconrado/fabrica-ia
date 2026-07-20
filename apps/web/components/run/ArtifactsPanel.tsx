"use client";

import { useState } from "react";
import type { Dict } from "@/lib/types";
import { MarkdownViewer } from "@/components/common/MarkdownViewer";
import { EmptyState, Provenance } from "@/components/common/OperationalUI";
import { shortId } from "@/lib/format";

export function ArtifactsPanel({ artifacts }: { artifacts: Dict[] }) {
  const [selectedId, setSelectedId] = useState(artifacts[0]?.id || "");
  const selected = artifacts.find((artifact) => artifact.id === selectedId) || artifacts[0];
  return (
    <div className="grid gap-3 md:grid-cols-[260px_1fr]">
      <div className="max-h-[520px] overflow-auto rounded-md border border-line">
        {artifacts.map((artifact) => (
          <button key={artifact.id} className={`block w-full border-b border-line px-3 py-2 text-left text-xs hover:bg-slate-50 ${selected?.id === artifact.id ? "bg-slate-100" : ""}`} onClick={() => setSelectedId(artifact.id)}>
            <span className="block truncate font-medium">{artifact.name}</span>
            <span className="mt-1 flex items-center justify-between gap-2"><Provenance value={artifact.evidence_classification || "não informada"} /><span className="font-mono text-[10px] text-[rgb(var(--muted))]">call {artifact.model_call_id ? shortId(artifact.model_call_id) : "—"}</span></span>
          </button>
        ))}
      </div>
      {selected ? <div><div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--muted))]"><span>Audience: {selected.audience || "—"}</span><span>Model call: {selected.model_call_id || "—"}</span></div><MarkdownViewer content={selected.content} /></div> : <EmptyState title="Nenhum artifact" description="Artifacts aparecem somente depois de persistidos pela fábrica." />}
    </div>
  );
}
