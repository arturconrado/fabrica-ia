"use client";

import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { apiPost } from "@/lib/api";
import type { Dict } from "@/lib/types";

export function FeedbackPanel({ run, feedback, onReload }: { run: Dict; feedback: Dict[]; onReload: () => void }) {
  const [comment, setComment] = useState("");
  async function send(rating: number) {
    await apiPost("/feedback", { run_id: run.id, rating, comment, feedback_type: "run" });
    setComment("");
    onReload();
  }
  return (
    <div className="space-y-3">
      <textarea className="h-24 w-full rounded-md border border-line p-3 text-sm" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Feedback comment" />
      <div className="flex gap-2">
        <button className="inline-flex items-center gap-2 rounded-md border border-emerald-300 px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50" onClick={() => send(1)}>
          <ThumbsUp className="h-4 w-4" /> Positive
        </button>
        <button className="inline-flex items-center gap-2 rounded-md border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50" onClick={() => send(-1)}>
          <ThumbsDown className="h-4 w-4" /> Negative
        </button>
      </div>
      <div className="space-y-2">
        {feedback.map((item) => (
          <div key={item.id} className="rounded-md bg-slate-50 px-3 py-2 text-sm">{item.rating > 0 ? "+1" : "-1"} · {item.comment || "No comment"}</div>
        ))}
      </div>
    </div>
  );
}
