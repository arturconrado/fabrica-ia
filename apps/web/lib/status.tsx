export function statusClass(status?: string) {
  const normalized = status || "pending";
  if (["success", "approved", "approved_for_homologation", "passed"].includes(normalized)) return "bg-emerald-100 text-emerald-800 border-emerald-200";
  if (["running"].includes(normalized)) return "bg-blue-100 text-blue-800 border-blue-200";
  if (["waiting_for_human", "pending", "queued"].includes(normalized)) return "bg-amber-100 text-amber-900 border-amber-200";
  if (["failed", "rejected", "needs_changes"].includes(normalized)) return "bg-red-100 text-red-800 border-red-200";
  return "bg-slate-100 text-slate-700 border-slate-200";
}

export function StatusBadge({ status }: { status?: string }) {
  return <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${statusClass(status)}`}>{status || "pending"}</span>;
}
