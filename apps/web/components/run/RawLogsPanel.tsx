import type { Dict } from "@/lib/types";

export function RawLogsPanel({ events }: { events: Dict[] }) {
  return <pre className="mono max-h-[520px] overflow-auto rounded-md bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(events, null, 2)}</pre>;
}
