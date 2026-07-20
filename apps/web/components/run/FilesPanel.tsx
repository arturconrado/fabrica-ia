"use client";

import { useState } from "react";
import { apiGetText } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { EmptyState } from "@/components/common/OperationalUI";
import { shortId } from "@/lib/format";

export function FilesPanel({ runId, files }: { runId: string; files: Dict[] }) {
  const [selected, setSelected] = useState(files[0]?.file_path || "");
  const [content, setContent] = useState("");

  async function open(path: string) {
    setSelected(path);
    setContent(await apiGetText(`/runs/${runId}/files/content?path=${encodeURIComponent(path)}`));
  }

  return (
    <div className="grid gap-3 md:grid-cols-[260px_1fr]">
      <div className="max-h-[420px] overflow-auto rounded-md border border-line">
        {files.length ? files.map((file) => (
          <button key={`${file.id}-${file.file_path}`} className={`block w-full border-b border-line px-3 py-2 text-left text-xs hover:bg-slate-50 ${selected === file.file_path ? "bg-slate-100" : ""}`} onClick={() => open(file.file_path)}>
            <span className="block truncate">{file.file_path}</span>
            <span className="mt-1 block font-mono text-[10px] text-[rgb(var(--muted))]">call {file.model_call_id ? shortId(file.model_call_id) : "—"}</span>
          </button>
        )) : <div className="p-3"><EmptyState title="Nenhum arquivo gerado" description="Arquivos aparecerão após uma operação validada do Engineer." /></div>}
      </div>
      <pre className="mono max-h-[420px] overflow-auto rounded-md bg-slate-950 p-4 text-xs text-slate-100">{content || "Selecione um arquivo."}</pre>
    </div>
  );
}
