import { test } from "node:test";
import assert from "node:assert/strict";
import { executorState, STALE_AFTER_S } from "./executors.ts";

const now = Date.parse("2026-10-10T12:00:00Z");
const ex = (last_heartbeat: string | null, busy = false) => ({ name: "laptop-a", caps: [], busy, last_heartbeat });

test("an executor with a fresh heartbeat is idle, or busy when it is running a task", () => {
  assert.equal(executorState(ex("2026-10-10T11:59:55Z"), now), "idle");
  assert.equal(executorState(ex("2026-10-10T11:59:55Z", true), now), "busy");
});

test("a heartbeat over 30 s old is stale, even if the row says busy", () => {
  assert.equal(STALE_AFTER_S, 30);
  assert.equal(executorState(ex("2026-10-10T11:59:30Z"), now), "idle"); // exactly 30 s: still fresh
  assert.equal(executorState(ex("2026-10-10T11:59:29Z", true), now), "stale");
});

test("an executor that never sent a heartbeat is stale", () => {
  assert.equal(executorState(ex(null), now), "stale");
});

test("staleness compares instants, not strings (+05:30 offset)", () => {
  // 17:29:50+05:30 is 11:59:50Z: 10 s old.
  assert.equal(executorState(ex("2026-10-10T17:29:50+05:30"), now), "idle");
});
