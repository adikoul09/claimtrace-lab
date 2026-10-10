"use client";

// Experiments tab (SPEC §10): the reproduction → branches tree from experiments.parent_id, each with
// status, executor, budget reason and run time, plus live metric curves for the selected experiment.
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Experiment, Metric, Task } from "@/lib/types";
import {
  buildTree,
  formatDuration,
  groupMetrics,
  latestTaskByExperiment,
  runTime,
  upsertRows,
  type TreeNode,
} from "./experiments";
import { MetricChart } from "./metric-chart";

type Status = "connecting" | "live" | "error";
type TaskRow = Pick<Task, "id" | "created_at" | "status" | "executor" | "output">;

const PAGE = 1000;

const STATUS_STYLE: Record<string, string> = {
  planned: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  running: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  done: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  pruned: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
};
const statusStyle = (s: string) => STATUS_STYLE[s] ?? STATUS_STYLE.planned;

/** All metrics for these experiments, paged past the API's row cap. */
async function fetchMetrics(experimentIds: string[]): Promise<Metric[]> {
  const out: Metric[] = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await supabase()
      .from("metrics")
      .select("*")
      .in("experiment_id", experimentIds)
      .order("id")
      .range(from, from + PAGE - 1);
    if (error) throw error;
    out.push(...((data ?? []) as Metric[]));
    if (!data || data.length < PAGE) return out;
  }
}

export function ExperimentsView({ projectId }: { projectId: string }) {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const db = supabase();
    const fail = (e: { message: string }) => setError(e.message);

    // Subscribe before the initial fetch so no change falls in the gap; upserts dedupe by id.
    // Metrics have no project_id, so inserts are kept for every experiment and filtered at render.
    const channel = db
      .channel(`experiments-${projectId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "experiments", filter: `project_id=eq.${projectId}` },
        (p) => p.eventType !== "DELETE" && setExperiments((cur) => upsertRows(cur, [p.new as Experiment])),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "tasks", filter: `project_id=eq.${projectId}` },
        (p) => p.eventType !== "DELETE" && setTasks((cur) => upsertRows(cur, [p.new as TaskRow])),
      )
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "metrics" }, (p) =>
        setMetrics((cur) => upsertRows(cur, [p.new as Metric])),
      )
      .subscribe((s) => {
        if (s === "SUBSCRIBED") setStatus("live");
        else if (s === "CHANNEL_ERROR" || s === "TIMED_OUT") setStatus("error");
      });

    db.from("experiments")
      .select("*")
      .eq("project_id", projectId)
      .then(({ data, error }) => {
        if (error) return fail(error);
        const rows = (data ?? []) as Experiment[];
        setExperiments((cur) => upsertRows(cur, rows));
        if (rows.length)
          fetchMetrics(rows.map((r) => r.id))
            .then((ms) => setMetrics((cur) => upsertRows(ms, cur)))
            .catch(fail);
      });

    db.from("tasks")
      .select("id,created_at,status,executor,output")
      .eq("project_id", projectId)
      .not("output", "is", null)
      .then(({ data, error }) => {
        if (error) fail(error);
        else setTasks((cur) => upsertRows((data ?? []) as TaskRow[], cur));
      });

    return () => {
      db.removeChannel(channel);
    };
  }, [projectId]);

  const tree = useMemo(() => buildTree(experiments), [experiments]);
  const taskFor = useMemo(() => latestTaskByExperiment(tasks), [tasks]);
  const metricsByExp = useMemo(() => {
    const map = new Map<string, Metric[]>();
    for (const m of metrics) map.set(m.experiment_id, [...(map.get(m.experiment_id) ?? []), m]);
    return map;
  }, [metrics]);

  // Default to a running experiment, else the newest; keep the user's pick while it exists.
  const current =
    experiments.find((e) => e.id === selected) ??
    experiments.find((e) => e.status === "running") ??
    [...experiments].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];

  return (
    <section aria-labelledby="exp-heading">
      <div className="mb-3 flex items-center gap-2">
        <h2 id="exp-heading" className="text-sm font-semibold">
          Experiments <span className="font-normal text-neutral-500">({experiments.length})</span>
        </h2>
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            status === "live" ? "bg-green-500" : status === "error" ? "bg-red-500" : "bg-neutral-400"
          }`}
          aria-hidden
        />
        <span className="text-xs text-neutral-500">
          {status === "live" ? "Realtime connected" : status === "error" ? "Realtime error" : "Connecting…"}
        </span>
      </div>

      {error && <p className="mb-3 text-sm text-red-600">Could not load experiments: {error}</p>}

      {experiments.length === 0 ? (
        <p className="text-sm text-neutral-500">No experiments yet. Runs appear here when they start.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
          <nav aria-label="Experiment tree">
            <ExpTree
              nodes={tree}
              selectedId={current?.id}
              onSelect={setSelected}
              counts={(id) => metricsByExp.get(id)?.length ?? 0}
            />
          </nav>
          {current && (
            <ExpDetail exp={current} task={taskFor.get(current.id)} metrics={metricsByExp.get(current.id) ?? []} />
          )}
        </div>
      )}
    </section>
  );
}

function ExpTree({
  nodes,
  selectedId,
  onSelect,
  counts,
}: {
  nodes: TreeNode<Experiment>[];
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  counts: (id: string) => number;
}) {
  return (
    <ul className="space-y-1 text-sm [&_ul]:mt-1 [&_ul]:ml-3 [&_ul]:border-l [&_ul]:border-neutral-200 [&_ul]:pl-2 dark:[&_ul]:border-neutral-800">
      {nodes.map(({ exp: e, children }) => (
        <li key={e.id}>
          <button
            type="button"
            onClick={() => onSelect(e.id)}
            aria-current={e.id === selectedId ? "true" : undefined}
            className={`w-full rounded px-2 py-1.5 text-left ${
              e.id === selectedId
                ? "bg-neutral-100 dark:bg-neutral-800"
                : "hover:bg-neutral-50 dark:hover:bg-neutral-900"
            }`}
          >
            <span className="block break-words font-medium">{e.label}</span>
            <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-neutral-500">
              <span className={`rounded px-1.5 py-0.5 font-medium ${statusStyle(e.status)}`}>{e.status}</span>
              {e.changed_key && <span className="font-mono">Δ {e.changed_key}</span>}
              <span className="tabular-nums">{counts(e.id)} metrics</span>
            </span>
          </button>
          {children.length > 0 && <ExpTree nodes={children} selectedId={selectedId} onSelect={onSelect} counts={counts} />}
        </li>
      ))}
    </ul>
  );
}

function ExpDetail({ exp: e, task, metrics }: { exp: Experiment; task: TaskRow | undefined; metrics: Metric[] }) {
  const { curves, scalars } = useMemo(() => groupMetrics(metrics), [metrics]);
  const t = runTime(task?.output);

  return (
    <article className="min-w-0">
      <header className="mb-3 space-y-1 text-sm">
        <h3 className="flex flex-wrap items-center gap-2">
          <span className="break-words font-semibold">{e.label}</span>
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${statusStyle(e.status)}`}>{e.status}</span>
        </h3>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
          <dt className="text-neutral-500">Executor</dt>
          <dd>{e.executor ?? "not assigned"}</dd>
          <dt className="text-neutral-500">Budget</dt>
          <dd className="break-words">{e.budget_reason ?? <span className="text-neutral-500">no budget reason recorded</span>}</dd>
          {e.changed_key && (
            <>
              <dt className="text-neutral-500">Changes</dt>
              <dd className="font-mono">{e.changed_key}</dd>
            </>
          )}
          {e.margin !== null && (
            <>
              <dt className="text-neutral-500">Margin</dt>
              <dd className="tabular-nums">± {e.margin} (declared before the run)</dd>
            </>
          )}
          {e.pruned_reason && (
            <>
              <dt className="text-neutral-500">Pruned</dt>
              <dd className="break-words">{e.pruned_reason}</dd>
            </>
          )}
          {t.wall_s !== null && (
            <>
              <dt className="text-neutral-500">Run time</dt>
              <dd className="tabular-nums">
                wall {formatDuration(t.wall_s)}
                {" · "}
                {t.cpu_s === null ? (
                  <span className="text-neutral-500">CPU time not recorded</span>
                ) : t.cpuIsWallClock ? (
                  <span title="CPU time cannot be measured on this executor (Windows); the CPU figure is wall-clock time">
                    CPU {formatDuration(t.cpu_s)} (wall-clock)
                  </span>
                ) : (
                  <>CPU {formatDuration(t.cpu_s)}</>
                )}
              </dd>
            </>
          )}
          {e.log_path && (
            <>
              <dt className="text-neutral-500">Log</dt>
              <dd>
                <a href={`/logs/${e.id}`} className="underline">
                  open log
                </a>
              </dd>
            </>
          )}
        </dl>
      </header>

      {curves.length === 0 && scalars.length === 0 ? (
        <p className="text-sm text-neutral-500">No metrics yet. Curves appear here as METRIC lines arrive.</p>
      ) : (
        <>
          {curves.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {curves.map((s) => (
                <MetricChart key={s.name} series={s} experimentId={e.id} />
              ))}
            </div>
          )}
          {scalars.length > 0 && (
            <table className="mt-4 w-full text-left text-xs">
              <caption className="mb-1 text-left text-sm font-semibold">Final values</caption>
              <thead className="text-neutral-500">
                <tr>
                  <th className="py-1 pr-2 font-medium">Metric</th>
                  <th className="py-1 pr-2 text-right font-medium">Value</th>
                  <th className="py-1 text-right font-medium">Log line</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {scalars.map(({ name, points: [p] }) => (
                  <tr key={name}>
                    <td className="break-all py-1 pr-2 font-mono">{name}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{p.text}</td>
                    <td className="py-1 text-right tabular-nums">
                      <a href={`/logs/${e.id}#L${p.log_line}`} className="underline">
                        L{p.log_line}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </article>
  );
}
