import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildTree,
  formatDuration,
  groupMetrics,
  latestTaskByExperiment,
  runTime,
  upsertRows,
} from "./experiments.ts";

const exp = (id: string, parent_id: string | null = null, created_at = "2026-10-10T10:00:00Z") => ({
  id,
  parent_id,
  created_at,
});
const ids = (nodes: { exp: { id: string }; children: unknown[] }[]): unknown =>
  nodes.map((n) => [n.exp.id, ids(n.children as typeof nodes)]);

test("buildTree nests branches under their parent, oldest first", () => {
  const out = buildTree([
    exp("b2", "root", "2026-10-10T12:00:00Z"),
    exp("root"),
    exp("b1", "root", "2026-10-10T11:00:00+00:00"),
    exp("b1a", "b1"),
  ]);
  assert.deepEqual(ids(out), [["root", [["b1", [["b1a", []]]], ["b2", []]]]]);
});

test("buildTree shows an experiment whose parent is missing as a root", () => {
  const out = buildTree([exp("orphan", "gone"), exp("r", null, "2026-10-10T09:00:00Z")]);
  assert.deepEqual(ids(out), [["r", []], ["orphan", []]]);
});

test("buildTree keeps every row even when parent links form a cycle", () => {
  const out = buildTree([exp("a", "b"), exp("b", "a")]);
  const seen: string[] = [];
  const walk = (ns: typeof out) => ns.forEach((n) => (seen.push(n.exp.id), walk(n.children)));
  walk(out);
  assert.deepEqual(seen.sort(), ["a", "b"]);
});

const m = (id: string, name: string, step: number, value: unknown, log_line: number) => ({
  id,
  name,
  step,
  value: value as number,
  log_line,
});

test("groupMetrics splits multi-step curves from single-value scalars, in log order", () => {
  const { curves, scalars } = groupMetrics([
    m("3", "loss", 2, 0.5, 30),
    m("1", "loss", 1, 0.9, 10),
    m("2", "final_errors", 0, 121, 40),
    m("0", "acc", 1, 0.1, 5),
    m("4", "acc", 2, 0.2, 31),
  ]);
  assert.deepEqual(curves.map((s) => s.name), ["acc", "loss"]);
  assert.deepEqual(curves[1].points.map((p) => [p.step, p.value, p.log_line]), [
    [1, 0.9, 10],
    [2, 0.5, 30],
  ]);
  assert.deepEqual(scalars.map((s) => [s.name, s.points[0].value, s.points[0].log_line]), [
    ["final_errors", 121, 40],
  ]);
});

test("groupMetrics keeps NaN values as gaps with their raw text, never as numbers", () => {
  const { curves } = groupMetrics([m("1", "loss", 1, "NaN", 7), m("2", "loss", 2, 0.3, 9)]);
  assert.equal(curves[0].points[0].value, null);
  assert.equal(curves[0].points[0].text, "NaN");
  assert.equal(curves[0].points[1].text, "0.3");
});

test("upsertRows replaces by id and appends new rows", () => {
  const out = upsertRows([{ id: "a", v: 1 }, { id: "b", v: 1 }], [{ id: "a", v: 2 }, { id: "c", v: 1 }]);
  assert.deepEqual(out, [{ id: "a", v: 2 }, { id: "b", v: 1 }, { id: "c", v: 1 }]);
});

test("latestTaskByExperiment maps each experiment to its newest task", () => {
  const t = (id: string, experiment_id: string | null, created_at: string) => ({
    id,
    created_at,
    output: experiment_id ? { experiment_id } : { error: "bad task" },
  });
  const map = latestTaskByExperiment([
    t("old", "e1", "2026-10-10T10:00:00Z"),
    t("new", "e1", "2026-10-10T11:00:00Z"),
    t("other", "e2", "2026-10-10T10:00:00Z"),
    t("none", null, "2026-10-10T12:00:00Z"),
  ]);
  assert.equal(map.get("e1")?.id, "new");
  assert.equal(map.get("e2")?.id, "other");
  assert.equal(map.size, 2);
});

test("runTime labels CPU time as wall-clock when the worker could not measure it (Windows)", () => {
  const r = runTime({ wall_s: 5119.3, cpu_s: null, cpu_seconds_source: "wall_clock" });
  assert.deepEqual(r, { wall_s: 5119.3, cpu_s: 5119.3, cpuIsWallClock: true });
});

test("runTime uses measured CPU time when the source is rusage", () => {
  const r = runTime({ wall_s: 60, cpu_s: 240.5, cpu_seconds_source: "rusage" });
  assert.deepEqual(r, { wall_s: 60, cpu_s: 240.5, cpuIsWallClock: false });
});

test("runTime reports no CPU time when the source is not recorded (pre-fix rows)", () => {
  assert.deepEqual(runTime({ wall_s: 449, cpu_s: 0.1 }), { wall_s: 449, cpu_s: null, cpuIsWallClock: false });
  assert.deepEqual(runTime(null), { wall_s: null, cpu_s: null, cpuIsWallClock: false });
});

test("formatDuration renders seconds, minutes and hours", () => {
  assert.equal(formatDuration(4.7), "4.7 s");
  assert.equal(formatDuration(449), "7 min 29 s");
  assert.equal(formatDuration(5119.3), "1 h 25 min");
});
