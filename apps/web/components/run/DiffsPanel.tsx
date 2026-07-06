import type { Dict } from "@/lib/types";

export function DiffsPanel({ diffs }: { diffs: Dict[] }) {
  return (
    <div className="max-h-[520px] overflow-auto space-y-3">
      {diffs.map((diff) => (
        <div key={diff.id}>
          <div className="mb-1 text-sm font-medium">{diff.file_path}</div>
          <pre className="mono overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{diff.diff}</pre>
        </div>
      ))}
    </div>
  );
}
