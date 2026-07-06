import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function NodeInspector({ node, events, artifacts }: { node: Dict | null; events: Dict[]; artifacts: Dict[] }) {
  if (!node) return <p className="text-sm text-slate-500">Select a workflow node to inspect its evidence.</p>;
  const recent = events.filter((event) => event.node_id === node.node_id).slice(-8);
  const produced = artifacts.filter((artifact) => artifact.node_id === node.node_id);
  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold">{node.node_id}</div>
          <div className="text-slate-500">{node.phase}</div>
        </div>
        <StatusBadge status={node.status} />
      </div>
      <p className="rounded-md bg-slate-50 p-3">{node.summary || "No summary yet."}</p>
      <div>
        <div className="mb-1 font-medium">Artifacts</div>
        {produced.length ? produced.map((artifact) => <div key={artifact.id} className="text-slate-600">{artifact.name}</div>) : <div className="text-slate-500">No artifacts.</div>}
      </div>
      <div>
        <div className="mb-1 font-medium">Recent Events</div>
        <div className="space-y-1">
          {recent.map((event) => <div key={event.id} className="rounded bg-slate-50 px-2 py-1 text-xs">{event.event_type}: {event.summary}</div>)}
        </div>
      </div>
    </div>
  );
}
