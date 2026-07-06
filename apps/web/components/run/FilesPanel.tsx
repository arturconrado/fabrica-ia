"use client";

import { useState } from "react";
import { apiGet } from "@/lib/api";
import type { Dict } from "@/lib/types";

export function FilesPanel({ runId, files }: { runId: string; files: Dict[] }) {
  const [selected, setSelected] = useState(files[0]?.file_path || "");
  const [content, setContent] = useState("");

  async function open(path: string) {
    setSelected(path);
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/runs/${runId}/files/content?path=${encodeURIComponent(path)}`);
    setContent(await response.text());
  }

  return (
    <div className="grid gap-3 md:grid-cols-[260px_1fr]">
      <div className="max-h-[420px] overflow-auto rounded-md border border-line">
        {files.map((file) => (
          <button key={`${file.id}-${file.file_path}`} className={`block w-full border-b border-line px-3 py-2 text-left text-xs hover:bg-slate-50 ${selected === file.file_path ? "bg-slate-100" : ""}`} onClick={() => open(file.file_path)}>
            {file.file_path}
          </button>
        ))}
      </div>
      <pre className="mono max-h-[420px] overflow-auto rounded-md bg-slate-950 p-4 text-xs text-slate-100">{content || "Select a file."}</pre>
    </div>
  );
}
