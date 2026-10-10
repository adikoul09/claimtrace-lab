import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeEvents, latestTs, formatAgo } from "./live.ts";

const ev = (id: string, ts: string) => ({ id, ts });

test("mergeEvents sorts newest-first", () => {
  const out = mergeEvents(
    [ev("a", "2026-10-10T10:00:00Z"), ev("b", "2026-10-10T12:00:00Z")],
    [ev("c", "2026-10-10T11:00:00Z")],
  );
  assert.deepEqual(out.map((e) => e.id), ["b", "c", "a"]);
});

test("mergeEvents drops duplicates by id, keeping the incoming row", () => {
  const out = mergeEvents(
    [{ id: "a", ts: "2026-10-10T10:00:00Z", v: 1 }],
    [{ id: "a", ts: "2026-10-10T10:00:00Z", v: 2 }],
  );
  assert.equal(out.length, 1);
  assert.equal(out[0].v, 2);
});

test("mergeEvents caps the list at the limit, keeping the newest", () => {
  const out = mergeEvents(
    [ev("a", "2026-10-10T10:00:00Z"), ev("b", "2026-10-10T11:00:00Z")],
    [ev("c", "2026-10-10T12:00:00Z")],
    2,
  );
  assert.deepEqual(out.map((e) => e.id), ["c", "b"]);
});

test("mergeEvents compares timestamps as instants, not strings", () => {
  // Postgres returns "+00:00" offsets; a later instant can sort lower as a string.
  const out = mergeEvents(
    [ev("utc", "2026-10-10T10:30:00+00:00")],
    [ev("ist", "2026-10-10T15:45:00+05:30")], // 10:15 UTC
  );
  assert.deepEqual(out.map((e) => e.id), ["utc", "ist"]);
});

test("latestTs returns the later instant and tolerates null", () => {
  assert.equal(latestTs(null, "2026-10-10T10:00:00Z"), "2026-10-10T10:00:00Z");
  assert.equal(latestTs("2026-10-10T10:00:00Z", null), "2026-10-10T10:00:00Z");
  assert.equal(latestTs(null, null), null);
  assert.equal(
    latestTs("2026-10-10T11:00:00Z", "2026-10-10T10:00:00Z"),
    "2026-10-10T11:00:00Z",
  );
});

test("formatAgo renders seconds, minutes, hours and days", () => {
  const now = Date.parse("2026-10-10T12:00:00Z");
  assert.equal(formatAgo(null, now), "never");
  assert.equal(formatAgo("2026-10-10T11:59:58Z", now), "2 s ago");
  assert.equal(formatAgo("2026-10-10T12:00:03Z", now), "0 s ago"); // clock skew
  assert.equal(formatAgo("2026-10-10T11:55:00Z", now), "5 min ago");
  assert.equal(formatAgo("2026-10-10T09:00:00Z", now), "3 h ago");
  assert.equal(formatAgo("2026-10-08T12:00:00Z", now), "2 d ago");
});
