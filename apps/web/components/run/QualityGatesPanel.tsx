import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function QualityGatesPanel({ gates }: { gates: Dict[] }) {
  return (
    <div className="max-h-[420px] overflow-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500">
          <tr><th className="py-2">Gate</th><th>Status</th><th>Score</th></tr>
        </thead>
        <tbody>
          {gates.map((gate) => (
            <tr key={gate.id} className="border-t border-line">
              <td className="py-2">{gate.name}</td>
              <td><StatusBadge status={gate.status} /></td>
              <td>{gate.score}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
