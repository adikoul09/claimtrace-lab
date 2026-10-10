"use client";

// Lessons panel (SPEC §6): which lessons this project's plan and steps used or left out (MEM-1), and everything the
// team has learned, with the event that proves each lesson.
// lessons is not in the Realtime publication; lesson events (which are) trigger a refetch.
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Event, Lesson } from "@/lib/types";
import { projectIdFromPath } from "@/components/live/inbox";
import { capabilityLabel, humanize } from "@/components/live/labels";
import { lessonUse, skipReasonLabel, type AppliedLesson, type SkippedLesson } from "./lesson-events";
import { isImported, lessonText, sortLessons } from "./lessons";

type Evidence = Pick<Event, "id" | "project_id" | "type" | "message" | "reason">;

const KIND_LABEL: Record<Lesson["kind"], string> = {
  failure_fix: "failure fix",
  setting_mattered: "setting mattered",
  budget: "budget",
  agent_choice: "agent choice",
};

export function LessonsPanel() {
  // The Team tab is a project page; the project comes from the URL (/p/<id>), so the page needs no new props.
  const projectId = projectIdFromPath(usePathname());
  const [use, setUse] = useState<{ applied: AppliedLesson[]; skipped: SkippedLesson[] } | null>(null);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [evidence, setEvidence] = useState<Record<string, Evidence>>({});
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const db = supabase();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loadUse = async () => {
      if (!projectId) return;
      const { data } = await db
        .from("events")
        .select("id,type,ts,message,reason,data")
        .eq("project_id", projectId)
        .in("type", ["lesson_applied", "lesson_skipped"])
        .order("ts")
        .limit(1000);
      setUse(lessonUse((data ?? []) as Event[]));
    };
    const load = async () => {
      loadUse();
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
  }, [projectId]);

  const byId = Object.fromEntries(lessons.map((l) => [l.id, l]));
  const text = (id: string, fallback: string) => (byId[id] ? lessonText(byId[id]) : fallback);

  return (
    <section aria-labelledby="lessons-heading" className="space-y-4">
      {projectId && <ProjectLessons use={use} text={text} />}
      <h3 id="lessons-heading" className="mb-2 text-sm font-semibold">
        All lessons <span className="font-normal text-neutral-500">({lessons.length})</span>
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
                      <li key={t} className="text-xs text-neutral-500">
                        #{t.replace(/_/g, " ")}
                      </li>
                    ))}
                  </ul>
                )}
                <details className="mt-1 text-xs">
                  <summary className="cursor-pointer text-neutral-600 dark:text-neutral-400">Evidence</summary>
                  {ev ? (
                    <div className="mt-1 border-l-2 border-neutral-300 pl-2 dark:border-neutral-700">
                      <p className="break-words">
                        <span className="font-medium">{humanize(ev.type)}</span>: {ev.message}
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
                    <p className="mt-1 text-neutral-500">The evidence event is not available.</p>
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

/** "planner" → "Planner"; "write_code task" → "Write code step". */
const whereLabel = (w: string) => (w.endsWith(" task") ? `${capabilityLabel(w.slice(0, -5))} step` : humanize(w));

function ProjectLessons({
  use,
  text,
}: {
  use: { applied: AppliedLesson[]; skipped: SkippedLesson[] } | null;
  text: (lessonId: string, fallback: string) => string;
}) {
  return (
    <section aria-labelledby="project-lessons-heading">
      <h3 id="project-lessons-heading" className="text-sm font-semibold">
        Lessons in this project
      </h3>
      <p className="mb-2 text-xs text-neutral-500">Kept: has evidence · ranked by relevance · max 5 per plan</p>
      {use === null ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : use.applied.length === 0 && use.skipped.length === 0 ? (
        <p className="text-sm text-neutral-500">No lessons applied yet.</p>
      ) : (
        <>
          <h4 className="text-xs font-semibold">Applied ({use.applied.length})</h4>
          {use.applied.length === 0 ? (
            <p className="text-sm text-neutral-500">No lessons applied yet.</p>
          ) : (
            <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {use.applied.map((a) => (
                <li key={a.lessonId} className="py-2 text-sm">
                  <p className="break-words">{text(a.lessonId, a.message)}</p>
                  <p className="mt-0.5 break-words text-xs text-neutral-500">
                    <span className="font-medium">Why it matched: </span>
                    {a.tags.length ? `tags ${a.tags.map((t) => t.replace(/_/g, " ")).join(", ")}` : "matching tags"}
                    {a.rank !== null && ` · rank ${a.rank}`}
                    {` · used in ${a.where.map(whereLabel).join(", ") || "a prompt"}`}
                    {a.uses > 1 && ` (${a.uses}×)`}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {use.skipped.length > 0 && (
            <details className="mt-2">
              <summary className="min-h-11 cursor-pointer py-2 text-xs font-semibold">
                Skipped ({use.skipped.length})
              </summary>
              <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {use.skipped.map((s) => (
                  <li key={`${s.lessonId}:${s.reason}`} className="py-2 text-sm">
                    <p className="break-words">{text(s.lessonId, s.message)}</p>
                    <p className="mt-0.5 break-words text-xs text-neutral-500">
                      <span className="font-medium">{skipReasonLabel(s.reason)}: </span>
                      {s.detail}
                    </p>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
