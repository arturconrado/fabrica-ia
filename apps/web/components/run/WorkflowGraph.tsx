"use client";

import { Background, Controls, MarkerType, ReactFlow } from "@xyflow/react";
import type { Edge, Node } from "@xyflow/react";
import type { WorkflowTopology } from "@/lib/contracts";
import type { Dict } from "@/lib/types";


const colorByStatus: Record<string, string> = {
  success: "#22C55E",
  completed: "#22C55E",
  passed: "#22C55E",
  approved: "#22C55E",
  approved_for_homologation: "#22C55E",
  running: "#3B82F6",
  working: "#3B82F6",
  failed: "#EF4444",
  needs_changes: "#EF4444",
  blocked: "#EF4444",
  pending: "#F59E0B",
  waiting_for_human: "#F59E0B",
  not_started: "#475569"
};

export function WorkflowGraph({ topology, nodes, currentNode, onSelect }: { topology: WorkflowTopology | null; nodes: Dict[]; currentNode?: string; onSelect: (node: Dict) => void }) {
  if (!topology) return <div className="flex h-[440px] items-center justify-center rounded-xl border border-dashed border-line text-sm text-[rgb(var(--muted))]">Topologia persistida indisponível.</div>;
  const latest = new Map<string, Dict>();
  nodes.forEach((node) => latest.set(String(node.node_id), node));
  const phaseIndex = new Map(topology.phases.map((phase, index) => [phase.id, index]));
  const definitionById = new Map(topology.nodes.map((node) => [node.id, node]));
  const flowNodes: Node[] = topology.nodes.map((definition, index) => {
    const state = latest.get(definition.id);
    const status = String(state?.status || "not_started");
    const phase = phaseIndex.get(definition.phase) ?? index;
    return {
      id: definition.id,
      position: { x: (phase % 5) * 235, y: Math.floor(phase / 5) * 150 },
      data: { label: `${definition.id}\n${status === "not_started" ? "não iniciado" : status}` },
      style: {
        border: `1px solid ${colorByStatus[status] || "#475569"}`,
        borderRadius: 12,
        minWidth: 190,
        background: status === "running" || definition.id === currentNode ? "#12264B" : "#0F172A",
        color: "#F8FAFC",
        whiteSpace: "pre-line",
        fontSize: 11,
        lineHeight: 1.5,
        boxShadow: definition.id === currentNode ? "0 0 0 3px rgba(59,130,246,.2)" : "none"
      }
    };
  });
  const flowEdges: Edge[] = topology.edges.map((edge, index) => ({
    id: `${edge.from}-${edge.to}-${index}`,
    source: edge.from,
    target: edge.to,
    label: String(edge.condition),
    animated: edge.to === currentNode,
    markerEnd: { type: MarkerType.ArrowClosed, color: edge.to === currentNode ? "#60A5FA" : "#475569" },
    style: { stroke: edge.to === currentNode ? "#60A5FA" : "#475569", strokeWidth: edge.max_iterations ? 2 : 1 },
    labelStyle: { fill: "#94A3B8", fontSize: 9 },
    labelBgStyle: { fill: "#0B1220", fillOpacity: 0.9 }
  }));

  return (
    <div className="h-[520px] overflow-hidden rounded-xl border border-line bg-[#0B1220]">
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView minZoom={0.25} onNodeClick={(_, node) => onSelect(latest.get(node.id) || ({ ...definitionById.get(node.id), node_id: node.id, status: "not_started" } as unknown as Dict))}>
        <Background color="#24324A" gap={24} size={1} />
        <Controls className="!border-line !bg-[#0F172A] !text-white" />
      </ReactFlow>
    </div>
  );
}
