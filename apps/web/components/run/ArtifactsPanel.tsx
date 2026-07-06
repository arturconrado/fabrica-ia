"use client";

import { useState } from "react";
import type { Dict } from "@/lib/types";
import { MarkdownViewer } from "@/components/common/MarkdownViewer";

export function ArtifactsPanel({ artifacts }: { artifacts: Dict[] }) {
  const [selectedId, setSelectedId] = useState(artifacts[0]?.id || "");
  const selected = artifacts.find((artifact) => artifact.id === selectedId) || artifacts[0];
  return (
    <div className="grid gap-3 md:grid-cols-[260px_1fr]">
      <div className="max-h-[520px] overflow-auto rounded-md border border-line">
        {artifacts.map((artifact) => (
          <button key={artifact.id} className={`block w-full border-b border-line px-3 py-2 text-left text-xs hover:bg-slate-50 ${selected?.id === artifact.id ? "bg-slate-100" : ""}`} onClick={() => setSelectedId(artifact.id)}>
            {artifact.name}
          </button>
        ))}
      </div>
      {selected ? <MarkdownViewer content={selected.content} /> : <p className="text-sm text-slate-500">No artifacts.</p>}
    </div>
  );
}
