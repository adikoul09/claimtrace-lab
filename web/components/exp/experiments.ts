// Pure helpers for the Experiments tab: the reproduction → branches tree, metric curves and run times.

const ms = (ts: string) => Date.parse(ts);
const byCreated = <T extends { created_at: string }>(a: T, b: T) => ms(a.created_at) - ms(b.created_at);

type ExpRow = { id: string; parent_id: string | null; created_at: string };
export type TreeNode<T> = { exp: T; children: TreeNode<T>[] };

/** Nest experiments by parent_id, oldest first. A missing parent (or a cycle) makes the row a root. */
export function buildTree<T extends ExpRow>(rows: T[]): TreeNode<T>[] {
  const sorted = [...rows].sort(byCreated);
  const ids = new Set(sorted.map((r) => r.id));
  const kids = new Map<string, T[]>();
  for (const r of sorted)
    if (r.parent_id && ids.has(r.parent_id)) kids.set(r.parent_id, [...(kids.get(r.parent_id) ?? []), r]);

  const placed = new Set<string>();
  const node = (r: T): TreeNode<T> => {
    placed.add(r.id);
    return { exp: r, children: (kids.get(r.id) ?? []).filter((c) => !placed.has(c.id)).map(node) };
  };
  const roots = sorted.filter((r) => !r.parent_id || !ids.has(r.parent_id)).map(node);
  // Rows only reachable through a cycle would vanish; show them as roots instead.
  for (const r of sorted) if (!placed.has(r.id)) roots.push(node(r));
  return roots;
}

type MetricRow = { id: string; name: string; step: number; value: number; log_line: number };
/** value is null when the run logged a non-finite number (NaN, inf); text keeps what was stored. */
export type Point = { step: number; value: number | null; text: string; log_line: number };
export type Series = { name: string; points: Point[] };

/** Group metrics by name. Names with one point are scalars (final results), the rest are curves.
 *  Both keep the order their first line appeared in the log. */
export function groupMetrics(rows: MetricRow[]): { curves: Series[]; scalars: Series[] } {
  const byName = new Map<string, Point[]>();
  for (const r of rows) {
    const v = typeof r.value === "number" && Number.isFinite(r.value) ? r.value : null;
    const p = { step: r.step, value: v, text: String(r.value), log_line: r.log_line };
    byName.set(r.name, [...(byName.get(r.name) ?? []), p]);
  }
  const series = [...byName].map(([name, points]) => ({
    name,
    points: points.sort((a, b) => a.step - b.step || a.log_line - b.log_line),
  }));
  const firstLine = (s: Series) => Math.min(...s.points.map((p) => p.log_line));
  series.sort((a, b) => firstLine(a) - firstLine(b));
  return {
    curves: series.filter((s) => s.points.length > 1),
    scalars: series.filter((s) => s.points.length === 1),
  };
}

/** Upsert rows by id: incoming replaces a row in place, new ids are appended. */
export function upsertRows<T extends { id: string }>(current: T[], incoming: T[]): T[] {
  const byId = new Map(current.map((r) => [r.id, r]));
  for (const r of incoming) byId.set(r.id, r);
  return [...byId.values()];
}

type TaskRow = { id: string; created_at: string; output: unknown };

/** The newest task whose output names each experiment (the worker writes output.experiment_id). */
export function latestTaskByExperiment<T extends TaskRow>(tasks: T[]): Map<string, T> {
  const map = new Map<string, T>();
  for (const t of [...tasks].sort(byCreated)) {
    const id = (t.output as { experiment_id?: unknown } | null)?.experiment_id;
    if (typeof id === "string") map.set(id, t);
  }
  return map;
}

export type RunTime = { wall_s: number | null; cpu_s: number | null; cpuIsWallClock: boolean };

/** Run times from a run task's output. On Windows the worker cannot measure CPU time and records
 *  cpu_seconds_source = "wall_clock": the CPU figure is then the wall-clock time and must say so. */
export function runTime(output: unknown): RunTime {
  const o = (output ?? {}) as { wall_s?: unknown; cpu_s?: unknown; cpu_seconds_source?: unknown };
  const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : null);
  const wall_s = num(o.wall_s);
  if (o.cpu_seconds_source === "rusage") return { wall_s, cpu_s: num(o.cpu_s), cpuIsWallClock: false };
  if (o.cpu_seconds_source === "wall_clock") return { wall_s, cpu_s: wall_s, cpuIsWallClock: true };
  return { wall_s, cpu_s: null, cpuIsWallClock: false };
}

/** "4.7 s", "7 min 29 s", "1 h 25 min". */
export function formatDuration(s: number): string {
  if (s < 60) return `${Math.round(s * 10) / 10} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
