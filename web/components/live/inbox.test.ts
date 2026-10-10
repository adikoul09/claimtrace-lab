import { test } from "node:test";
import assert from "node:assert/strict";
import { inboxEmail, projectIdFromPath } from "./inbox.ts";

const ID = "a97eb78b-bc4d-4e2d-ab5b-6b2ffd287ae4";

test("projectIdFromPath finds the project on any project page and nowhere else", () => {
  assert.equal(projectIdFromPath(`/p/${ID}`), ID);
  assert.equal(projectIdFromPath(`/p/${ID}/`), ID);
  assert.equal(projectIdFromPath("/approvals"), null);
  assert.equal(projectIdFromPath("/p/not-a-uuid"), null);
  assert.equal(projectIdFromPath(null), null);
});

test("inboxEmail reads an email_received event, falling back to the event time", () => {
  const e = {
    type: "email_received",
    message: "Decision",
    ts: "2026-10-10T10:00:05Z",
    data: { from: "ed@j.org", subject: "Decision", received_at: "2026-10-10T10:00:00.000Z", points: ["a", "b"] },
  };
  assert.deepEqual(inboxEmail(e), {
    from: "ed@j.org",
    subject: "Decision",
    receivedAt: "2026-10-10T10:00:00.000Z",
    points: ["a", "b"],
  });
  assert.equal(inboxEmail({ ...e, data: { ...e.data, received_at: null } })?.receivedAt, "2026-10-10T10:00:05Z");
});

test("inboxEmail ignores other events and tolerates odd data", () => {
  assert.equal(inboxEmail({ type: "feedback", message: "x", ts: "t", data: {} }), null);
  assert.deepEqual(inboxEmail({ type: "email_received", message: "Hi", ts: "t", data: { points: [1, "ok"] } }), {
    from: "unknown sender",
    subject: "Hi",
    receivedAt: "t",
    points: ["ok"],
  });
});
