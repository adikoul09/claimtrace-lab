import { test } from "node:test";
import assert from "node:assert/strict";
import { applyAgentChange, sortAgents } from "./agents.ts";

type A = { id: string; name: string; status: "active" | "retired" | "merged"; created_at: string };
const ag = (id: string, status: A["status"] = "active", created_at = "2026-10-10T10:00:00Z"): A => ({
  id,
  name: id,
  status,
  created_at,
});

test("INSERT adds the new agent", () => {
  const out = applyAgentChange([ag("a")], { eventType: "INSERT", new: ag("b"), old: {} });
  assert.deepEqual(out.map((a) => a.id).sort(), ["a", "b"]);
});

test("UPDATE replaces the row with the same id", () => {
  const out = applyAgentChange([ag("a"), ag("b")], {
    eventType: "UPDATE",
    new: ag("a", "retired"),
    old: { id: "a" },
  });
  assert.equal(out.length, 2);
  assert.equal(out.find((a) => a.id === "a")?.status, "retired");
});

test("UPDATE for an unseen agent adds it (initial fetch may lag the subscription)", () => {
  const out = applyAgentChange([], { eventType: "UPDATE", new: ag("x", "merged"), old: {} });
  assert.deepEqual(out.map((a) => a.id), ["x"]);
});

test("DELETE removes by id from the old record", () => {
  const out = applyAgentChange([ag("a"), ag("b")], { eventType: "DELETE", new: {}, old: { id: "a" } });
  assert.deepEqual(out.map((a) => a.id), ["b"]);
});

test("sortAgents puts active first, then retired, then merged; oldest first within a status", () => {
  const out = sortAgents([
    ag("m", "merged"),
    ag("r", "retired"),
    ag("a2", "active", "2026-10-10T12:00:00Z"),
    ag("a1", "active", "2026-10-10T09:00:00+00:00"),
  ]);
  assert.deepEqual(out.map((a) => a.id), ["a1", "a2", "r", "m"]);
});
