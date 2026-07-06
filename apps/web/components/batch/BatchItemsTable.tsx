import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function BatchItemsTable({ items }: { items: Dict[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full min-w-[780px] text-left text-sm">
        <thead className="text-xs text-slate-500">
          <tr><th className="py-2">Demand</th><th>Status</th><th>Run</th><th>Complexity</th><th>Phase</th><th>HRS</th></tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-t border-line">
              <td className="py-2">{item.demand}</td>
              <td><StatusBadge status={item.status} /></td>
              <td>{item.run_id ? <a className="text-blue-700 underline" href={`/runs/${item.run_id}`}>{item.run_id.slice(0, 8)}</a> : "-"}</td>
              <td>{item.complexity}</td>
              <td>{item.current_phase}</td>
              <td>{item.hrs}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
