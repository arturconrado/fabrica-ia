"use client";

import { Background, Controls, Edge, Node, ReactFlow } from "@xyflow/react";
import type { Dict } from "@/lib/types";

const colorByStatus: Record<string, string> = {
  success: "#10B981",
  approved: "#10B981",
  approved_for_homologation: "#10B981",
  running: "#2563EB",
  failed: "#DC2626",
  needs_changes: "#DC2626",
  pending: "#D97706"
};

export function WorkflowGraph({ nodes, onSelect }: { nodes: Dict[]; onSelect: (node: Dict) => void }) {
  const latest = new Map<string, Dict>();
  nodes.forEach((node) => latest.set(node.node_id, node));
  const ordered = Array.from(latest.values());
  const flowNodes: Node[] = ordered.map((node, index) => ({
    id: node.node_id,
    position: { x: (index % 4) * 260, y: Math.floor(index / 4) * 130 },
    data: { label: `${node.node_id}\n${node.status}` },
    style: {
      border: `2px solid ${colorByStatus[node.status] || "#94A3B8"}`,
      borderRadius: 8,
      minWidth: 190,
      background: "#fff",
      color: "#172026",
      whiteSpace: "pre-line",
      fontSize: 12
    }
  }));
  const flowEdges: Edge[] = flowNodes.slice(1).map((node, index) => ({
    id: `${flowNodes[index].id}-${node.id}`,
    source: flowNodes[index].id,
    target: node.id,
    animated: node.id === ordered[ordered.length - 1]?.node_id
  }));

  return (
    <div className="h-[440px] overflow-hidden rounded-md border border-line">
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView onNodeClick={(_, node) => onSelect(latest.get(node.id) || {})}>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
