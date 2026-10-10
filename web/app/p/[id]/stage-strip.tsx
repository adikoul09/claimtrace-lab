"use client";

// Stage strip under the project header: Reading paper → … → Report, derived by code (./stages.ts) from the project's
// tasks, with stored results as evidence. Updates over Realtime. A failed stage opens its plain reason on tap.
import { useEffect, useRef, useState } from "react";
import { retry } from "@/components/exp/experiments";
import { supabase } from "@/lib/supabase";
import { deriveStages, type Stage, type StageInput, type StageState } from "./stages";

const RELOAD_MS = 1000;

async function loadStages(projectId: string): Promise<Stage[]> {
  const db = supabase();
  const [project, tasks, failures, papers, experiments] = await Promise.all([
    db.from("projects").select("status").eq("id", projectId).maybeSingle(),
    db
      .from("tasks")
      .select("id,capability,status,created_at,scale:input->>scale,whatif:input->>whatif_of,error:output->>error")
      .eq("project_id", projectId),
    db.from("events").select("task_id,reason").eq("project_id", projectId).eq("type", "task_failed"),
    db.from("papers").select("claims").eq("project_id", projectId),
    db.from("experiments").select("status,parent_id,scale:config->>scale,whatif:config->whatif,verdicts").eq("project_id", projectId),
  ]);
  const err = project.error ?? tasks.error ?? failures.error ?? papers.error ?? experiments.error;
  if (err) throw new Error(err.message);

  const claims = (papers.data ?? []).flatMap((p) => (Array.isArray(p.claims) ? (p.claims as unknown[]) : []));
  const tagged = claims.filter((c) => {
    const status = (c as { runnable?: { status?: unknown } } | null)?.runnable?.status;
    return status === "runnable" || status === "not_runnable";
  });
  const input: StageInput = {
    projectStatus: project.data?.status ?? "",
    tasks: (tasks.data ?? []) as StageInput["tasks"],
    failures: (failures.data ?? []) as StageInput["failures"],
    claims: claims.length,
    sortedClaims: tagged.length,
    experiments: (experiments.data ?? []).map((e) => ({
      status: e.status as string,
      scale: (e.scale as string | null) ?? null,
      graded: e.verdicts !== null && e.verdicts !== undefined,
      branch: !!e.parent_id || !!e.whatif,
    })),
  };
  return deriveStages(input);
}

const STYLE: Record<StageState, { box: string; icon: string; text: string }> = {
  done: {
    box: "border-green-300 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950/40 dark:text-green-300",
    icon: "✓",
    text: "done",
  },
  running: {
    box: "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300",
    icon: "●",
    text: "running",
  },
  failed: {
    box: "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300",
    icon: "✗",
    text: "failed",
  },
  "not started": {
    box: "border-neutral-200 text-neutral-500 dark:border-neutral-800",
    icon: "○",
    text: "not started",
  },
};

export function StageStrip({ projectId }: { projectId: string }) {
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [open, setOpen] = useState<string | null>(null); // the failed stage whose reason is shown
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const db = supabase();
    let cancelled = false;
    const load = () =>
      retry(() => loadStages(projectId))
        .then((s) => !cancelled && setStages(s))
        .catch(() => {}); // the strip is a summary: on error it keeps what it showed (or stays hidden)
    const soon = () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(load, RELOAD_MS);
    };
    const filter = `project_id=eq.${projectId}`;
    const channel = db
      .channel(`stages-${projectId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks", filter }, soon)
      .on("postgres_changes", { event: "*", schema: "public", table: "experiments", filter }, soon)
      .on("postgres_changes", { event: "*", schema: "public", table: "papers", filter }, soon)
      .subscribe();
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer.current);
      db.removeChannel(channel);
    };
  }, [projectId]);

  if (!stages) return <div className="mb-4 h-[4.5rem] sm:h-9" aria-hidden />; // reserve the space; no false "not started"
  const shown = stages.find((s) => s.id === open && s.state === "failed");

  return (
    <div className="mb-4">
      <ol aria-label="Stages" className="grid grid-cols-4 gap-1 sm:grid-cols-8">
        {stages.map((s, i) => {
          const st = STYLE[s.state];
          const body = (
            <>
              <span aria-hidden className="shrink-0">
                {st.icon}
              </span>
              <span className="min-w-0 leading-tight">
                {s.label}
                <span className="sr-only">
                  : {st.text}
                  {s.inferred && ", inferred"}
                </span>
              </span>
            </>
          );
          // Done without a task of its own: lighter, and the tooltip says how it was inferred.
          const light = s.inferred ? "border-dashed opacity-60" : "";
          const how =
            s.inferred === "later"
              ? " (inferred from later stages)"
              : s.inferred === "results"
                ? ` (inferred from stored results: ${s.note})`
                : "";
          const cls = `flex min-h-9 w-full items-center gap-1 rounded border px-1.5 py-1 text-left text-[11px] font-medium ${st.box} ${light}`;
          return (
            <li key={s.id} title={`${i + 1}. ${s.label}: ${st.text}${how}`}>
              {s.state === "failed" ? (
                <button
                  type="button"
                  className={`${cls} cursor-pointer underline decoration-dotted underline-offset-2`}
                  aria-expanded={open === s.id}
                  aria-controls="stage-reason"
                  onClick={() => setOpen(open === s.id ? null : s.id)}
                >
                  {body}
                </button>
              ) : (
                <div className={cls}>{body}</div>
              )}
            </li>
          );
        })}
      </ol>
      {shown && (
        <div id="stage-reason" role="status" className="mt-2 rounded border border-red-300 p-2 text-sm dark:border-red-900">
          <p>
            <span className="font-semibold">{shown.label} failed.</span> {shown.reason}
          </p>
          {shown.detail && (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer text-neutral-500">Error text</summary>
              <p className="mt-1 break-words font-mono text-neutral-500">{shown.detail.slice(0, 600)}</p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
