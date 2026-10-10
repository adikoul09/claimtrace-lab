import { test } from "node:test";
import assert from "node:assert/strict";
import { lineageEdges, layoutLineage, rollingReward, scoreboard } from "./lineage.ts";

type A = {
  id: string;
  parent_id: string | null;
  merged_into: string | null;
  created_by_task: string | null;
  created_at: string;
};
const ag = (id: string, over: Partial<A> = {}): A => ({
  id,
  parent_id: null,
  merged_into: null,
  created_by_task: null,
  created_at: "2026-10-10T10:00:00Z",
  ...over,
});
const rw = (agent_id: string, reward: number, ts: string) => ({ agent_id, reward, ts });

test("lineageEdges draws parent → refined child", () => {
  const edges = lineageEdges([ag("v1"), ag("v2", { parent_id: "v1" })], {});
  assert.deepEqual(edges, [{ id: "parent:v1-v2", source: "v1", target: "v2", kind: "parent" }]);
});

test("lineageEdges draws merged agent → the agent it merged into", () => {
  const edges = lineageEdges([ag("a"), ag("b", { merged_into: "a" })], {});
  assert.deepEqual(edges, [{ id: "merged:b-a", source: "b", target: "a", kind: "merged" }]);
});

test("lineageEdges draws spawned_by from the agent of the triggering task", () => {
  const edges = lineageEdges([ag("runner"), ag("debugger", { created_by_task: "t1" })], { t1: "runner" });
  assert.deepEqual(edges, [{ id: "spawned:runner-debugger", source: "runner", target: "debugger", kind: "spawned" }]);
});

test("lineageEdges skips a spawn whose triggering task had no agent, or is unknown", () => {
  const edges = lineageEdges(
    [ag("x", { created_by_task: "gap-task" }), ag("y", { created_by_task: "missing" })],
    { "gap-task": null },
  );
  assert.deepEqual(edges, []);
});

test("lineageEdges skips edges to agents that are not loaded", () => {
  const edges = lineageEdges([ag("v2", { parent_id: "gone", merged_into: "gone" })], {});
  assert.deepEqual(edges, []);
});

test("layoutLineage puts roots in row 0 and children one row below their source", () => {
  const agents = [ag("a"), ag("b"), ag("a2", { parent_id: "a" }), ag("a3", { parent_id: "a2" })];
  const pos = layoutLineage(agents, lineageEdges(agents, {}));
  assert.equal(pos.a.row, 0);
  assert.equal(pos.b.row, 0);
  assert.equal(pos.a2.row, 1);
  assert.equal(pos.a3.row, 2);
  assert.notEqual(pos.a.col, pos.b.col);
});

test("layoutLineage survives a cycle (merge back into an ancestor)", () => {
  const agents = [ag("a", { merged_into: "b" }), ag("b", { parent_id: "a" })];
  const pos = layoutLineage(agents, lineageEdges(agents, {}));
  assert.equal(Object.keys(pos).length, 2);
});

test("rollingReward is the mean of the agent's last 3 rewards by time", () => {
  const r = rollingReward(
    [
      rw("a", 0.1, "2026-10-10T10:00:00Z"), // oldest: outside the window
      rw("a", 0.9, "2026-10-10T11:00:00Z"),
      rw("b", 0.0, "2026-10-10T11:30:00Z"),
      rw("a", 0.6, "2026-10-10T12:00:00Z"),
      rw("a", 0.3, "2026-10-10T13:00:00+00:00"),
    ],
    "a",
  );
  assert.ok(r);
  assert.equal(r.count, 4);
  assert.deepEqual(r.window.map((x) => x.reward), [0.3, 0.6, 0.9]);
  assert.ok(Math.abs(r.mean - 0.6) < 1e-9);
});

test("rollingReward is null for an agent with no scored task", () => {
  assert.equal(rollingReward([rw("b", 1, "2026-10-10T10:00:00Z")], "a"), null);
});

test("scoreboard ranks by rolling reward, unscored agents last", () => {
  const out = scoreboard(
    [ag("none"), ag("low"), ag("high")],
    [rw("low", 0.2, "2026-10-10T10:00:00Z"), rw("high", 0.8, "2026-10-10T10:00:00Z")],
  );
  assert.deepEqual(out.map((r) => r.agent.id), ["high", "low", "none"]);
  assert.equal(out[2].rolling, null);
});

test("layoutLineage wraps a wide generation at 4 columns and starts the next one below it", () => {
  const roots = ["r1", "r2", "r3", "r4", "r5"].map((id, i) =>
    ag(id, { created_at: `2026-10-10T10:0${i}:00Z` }),
  );
  const agents = [...roots, ag("child", { parent_id: "r1", created_at: "2026-10-10T11:00:00Z" })];
  const pos = layoutLineage(agents, lineageEdges(agents, {}));
  assert.deepEqual(pos.r4, { row: 0, col: 3 });
  assert.deepEqual(pos.r5, { row: 1, col: 0 });
  assert.equal(pos.child.row, 2);
});
