import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function TraceabilityMatrix({ rows }: { rows: Dict[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="text-xs text-slate-500">
          <tr><th>ID</th><th>File</th><th>Test</th><th>Evidence</th><th>Status</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-line">
              <td className="py-2 font-medium">{row.requirement_id}</td>
              <td>{row.file_path}</td>
              <td>{row.test_name}</td>
              <td>{row.evidence}</td>
              <td><StatusBadge status={row.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
