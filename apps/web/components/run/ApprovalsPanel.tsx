"use client";

import { useState } from "react";
import { Check, RotateCcw, X } from "lucide-react";
import { apiPost } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export function ApprovalsPanel({ run, approvals, onReload }: { run: Dict; approvals: Dict[]; onReload: () => void }) {
  const [comment, setComment] = useState("");
  async function decide(path: string) {
    await apiPost(path, { comment });
    setComment("");
    onReload();
  }
  return (
    <div className="space-y-3">
      {approvals.map((approval) => (
        <div key={approval.id} className="rounded-md border border-line p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">{approval.title}</span>
            <StatusBadge status={approval.status} />
          </div>
          <p className="mt-1 text-slate-600">{approval.description}</p>
        </div>
      ))}
      <textarea className="h-24 w-full rounded-md border border-line p-3 text-sm" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Human comment" />
      <div className="flex flex-wrap gap-2">
        <button className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-700" onClick={() => decide(`/runs/${run.id}/approve`)}>
          <Check className="h-4 w-4" /> Approve
        </button>
        <button className="inline-flex items-center gap-2 rounded-md border border-amber-300 px-3 py-2 text-sm text-amber-800 hover:bg-amber-50" onClick={() => decide(`/runs/${run.id}/request-changes`)}>
          <RotateCcw className="h-4 w-4" /> Request Changes
        </button>
        <button className="inline-flex items-center gap-2 rounded-md border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50" onClick={() => decide(`/runs/${run.id}/reject`)}>
          <X className="h-4 w-4" /> Reject
        </button>
      </div>
    </div>
  );
}
