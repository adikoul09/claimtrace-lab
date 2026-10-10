"use client";

// Lessons panel (SPEC §6): what the team has learned, with the event that proves each lesson.
// lessons is not in the Realtime publication; lesson events (which are) trigger a refetch.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Event, Lesson } from "@/lib/types";
import { isImported, lessonText, sortLessons } from "./lessons";

type Evidence = Pick<Event, "id" | "project_id" | "type" | "message" | "reason">;

const KIND_LABEL: Record<Lesson["kind"], string> = {
  failure_fix: "failure fix",
  setting_mattered: "setting mattered",
  budget: "budget",
  agent_choice: "agent choice",
};

export function LessonsPanel() {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [evidence, setEvidence] = useState<Record<string, Evidence>>({});
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const db = supabase();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      const { data, error } = await db.from("lessons").select("*");
      setLoaded(true);
      if (error) return setError(error.message);
      const rows = (data ?? []) as Lesson[];
      setLessons(rows);
      const ids = [...new Set(rows.map((l) => l.evidence_event_id))];
      if (ids.length === 0) return;
      const { data: evs } = await db.from("events").select("id,project_id,type,message,reason").in("id", ids);
      setEvidence(Object.fromEntries(((evs ?? []) as Evidence[]).map((e) => [e.id, e])));
    };
    const channel = db
      .channel("lessons-panel")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "events" }, (p) => {
        if ((p.new as Event).type?.startsWith("lesson")) {
          clearTimeout(timer);
          timer = setTimeout(load, 500);
        }
      })
      .subscribe();
    const first = setTimeout(load, 0);
    return () => {
      clearTimeout(first);
      clearTimeout(timer);
      db.removeChannel(channel);
    };
  }, []);

  return (
    <section aria-labelledby="lessons-heading">
      <h3 id="lessons-heading" className="mb-2 text-sm font-semibold">
        Lessons <span className="font-normal text-neutral-500">({lessons.length})</span>
      </h3>
      {error && <p className="text-sm text-red-600">Could not load lessons: {error}</p>}
      {lessons.length === 0 ? (
        !loaded ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : (
          !error && (
            <p className="text-sm text-neutral-500">
              No lessons yet. The Reporter proposes them after a finished experiment or a failure-then-recovery.
            </p>
          )
        )
      ) : (
        <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {sortLessons(lessons).map((l) => {
            const ev = evidence[l.evidence_event_id];
            return (
              <li key={l.id} className="py-2 text-sm">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                    {KIND_LABEL[l.kind] ?? l.kind}
                  </span>
                  {isImported(l) && (
                    <span className="rounded border border-amber-400 px-1.5 py-0.5 text-amber-700 dark:border-amber-600 dark:text-amber-400">
                      Imported from Round 0 audit
                    </span>
                  )}
                  <span className="ml-auto tabular-nums text-neutral-500">
                    applied {l.times_applied}×
                  </span>
                </div>
                <p className="mt-1 break-words">{lessonText(l)}</p>
                {l.tags.length > 0 && (
                  <ul aria-label="Tags" className="mt-1 flex flex-wrap gap-1">
                    {l.tags.map((t) => (
                      <li key={t} className="font-mono text-xs text-neutral-500">
                        #{t}
                      </li>
                    ))}
                  </ul>
                )}
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-neutral-600 dark:text-neutral-400">Evidence</summary>
                  {ev ? (
                    <div className="mt-1 border-l-2 border-neutral-300 pl-2 dark:border-neutral-700">
                      <p className="break-words">
                        <span className="font-mono">{ev.type}</span>: {ev.message}
                      </p>
                      <p className="break-words text-neutral-500">Why: {ev.reason}</p>
                      {ev.project_id && (
                        <a
                          href={`/p/${ev.project_id}?tab=live#ev-${ev.id}`}
                          className="text-sky-700 hover:underline dark:text-sky-400"
                        >
                          Open in Live
                        </a>
                      )}
                    </div>
                  ) : (
                    <p className="mt-1 font-mono text-neutral-500">event {l.evidence_event_id}</p>
                  )}
                </details>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
