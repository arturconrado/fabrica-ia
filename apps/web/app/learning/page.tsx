"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import type { Dict } from "@/lib/types";
import { StatusBadge } from "@/lib/status";

export default function LearningPage() {
  const [lessons, setLessons] = useState<Dict[]>([]);
  const [rewards, setRewards] = useState<Dict[]>([]);
  async function load() {
    const [lessonRows, rewardRows] = await Promise.all([apiGet<Dict[]>("/learning/lessons"), apiGet<Dict[]>("/learning/reward-signals")]);
    setLessons(lessonRows);
    setRewards(rewardRows);
  }
  async function approve(id: string) {
    await apiPost(`/learning/lessons/${id}/approve`);
    load();
  }
  useEffect(() => {
    load().catch(() => undefined);
  }, []);
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="panel">
        <div className="border-b border-line px-4 py-3 font-semibold">Lesson Candidates</div>
        <div className="divide-y divide-line">
          {lessons.map((lesson) => (
            <div key={lesson.id} className="px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span>{lesson.lesson}</span>
                <StatusBadge status={lesson.status} />
              </div>
              {lesson.status !== "approved" && <button className="mt-2 rounded-md border border-line px-3 py-1 text-xs hover:bg-slate-50" onClick={() => approve(lesson.id)}>Approve lesson</button>}
            </div>
          ))}
          {!lessons.length && <div className="px-4 py-8 text-sm text-slate-500">No lessons yet. Submit feedback on a run.</div>}
        </div>
      </section>
      <section className="panel">
        <div className="border-b border-line px-4 py-3 font-semibold">Reward Signals</div>
        <div className="divide-y divide-line">
          {rewards.map((reward) => (
            <div key={reward.id} className="px-4 py-3 text-sm">
              <div className="font-medium">{reward.reward_value}</div>
              <div className="text-slate-600">{reward.reason}</div>
            </div>
          ))}
          {!rewards.length && <div className="px-4 py-8 text-sm text-slate-500">No reward signals yet.</div>}
        </div>
      </section>
    </div>
  );
}
