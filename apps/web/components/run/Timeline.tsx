"use client";

import { useMemo, useState } from "react";
import type { Dict } from "@/lib/types";
import { fmtDate } from "@/lib/format";
import { StatusBadge } from "@/lib/status";

const filters = ["all", "agent", "tool", "file", "test", "quality", "approval", "feedback", "error"];

export function Timeline({ events }: { events: Dict[] }) {
  const [filter, setFilter] = useState("all");
  const rows = useMemo(() => {
    return events.filter((event) => {
      if (filter === "all") return true;
      if (filter === "error") return event.severity === "error" || event.status === "failed";
      return String(event.event_type).includes(filter);
    });
  }, [events, filter]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {filters.map((item) => (
          <button key={item} className={`rounded-md border px-2 py-1 text-xs ${filter === item ? "border-slate-900 bg-slate-900 text-white" : "border-line bg-white"}`} onClick={() => setFilter(item)}>
            {item}
          </button>
        ))}
      </div>
      <div className="max-h-[420px] space-y-2 overflow-auto">
        {rows.map((event) => (
          <div key={event.id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{event.event_type}</span>
              <StatusBadge status={event.status} />
            </div>
            <p className="mt-1 text-slate-600">{event.summary}</p>
            <div className="mt-1 text-xs text-slate-500">{fmtDate(event.created_at)} · {event.node_id || "run"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
