import { test } from "node:test";
import assert from "node:assert/strict";
import { checkInboxSecret, extractPoints, findArxivIds, planInboxEvent } from "./inbox.ts";

test("the inbox secret must match exactly, and an unset secret refuses everything", () => {
  assert.equal(checkInboxSecret("s3cret", "s3cret"), true);
  assert.equal(checkInboxSecret("s3cre", "s3cret"), false);
  assert.equal(checkInboxSecret("s3creT", "s3cret"), false);
  assert.equal(checkInboxSecret(null, "s3cret"), false);
  assert.equal(checkInboxSecret("", ""), false);
  assert.equal(checkInboxSecret("anything", undefined), false);
});

test("findArxivIds finds new-style ids in order, without the version, once each", () => {
  assert.deepEqual(findArxivIds("Re: arXiv:1503.02531v2 review", "see 1503.02531 and 1412.6980"), [
    "1503.02531",
    "1412.6980",
  ]);
  assert.deepEqual(findArxivIds("no paper here", "version 2.5 and 12.34"), []);
});

test("extractPoints keeps bullet and numbered lines, without their markers", () => {
  const body = [
    "Dear authors,",
    "",
    "The reviewers raise these points:",
    "  - The baseline uses too few seeds.  ",
    "* Report the temperature you used.",
    "1. Compare against label smoothing.",
    "2) Release the code.",
    "Thanks.",
  ].join("\n");
  assert.deepEqual(extractPoints(body), [
    "The baseline uses too few seeds.",
    "Report the temperature you used.",
    "Compare against label smoothing.",
    "Release the code.",
  ]);
});

test("extractPoints ignores lines that only look like markers", () => {
  const body = ["1503.02531 is the paper", "-5% accuracy", "**bold** text", "-- ", "> - quoted reply", "-", "3."].join(
    "\r\n",
  );
  assert.deepEqual(extractPoints(body), []);
});

test("planInboxEvent builds the email_received event from the n8n body", () => {
  const p = planInboxEvent({
    from: "editor@journal.org",
    subject: "Decision on 1503.02531",
    body: "Please address:\n- more seeds\n- report T",
    received_at: "2026-10-10T09:00:00Z",
  });
  assert.ok(p.ok);
  assert.deepEqual(p.arxivIds, ["1503.02531"]);
  assert.deepEqual(p.event, {
    type: "email_received",
    message: "Decision on 1503.02531",
    reason: "journal email via n8n",
    data: {
      from: "editor@journal.org",
      subject: "Decision on 1503.02531",
      received_at: "2026-10-10T09:00:00.000Z",
      points: ["more seeds", "report T"],
    },
  });
});

test("planInboxEvent passes on a valid project_id and ignores anything else", () => {
  const base = { from: "a@b", subject: "x", body: "y", received_at: "2026-10-10T09:00:00Z" };
  const id = "A97EB78B-BC4D-4E2D-AB5B-6B2FFD287AE4";
  const p = planInboxEvent({ ...base, project_id: ` ${id} ` });
  assert.ok(p.ok);
  assert.equal(p.projectId, id.toLowerCase());
  for (const bad of [undefined, null, "", "not-a-uuid", 42, "a97eb78b-bc4d-4e2d-ab5b-6b2ffd287ae4,arxiv_id.eq.1"]) {
    const q = planInboxEvent({ ...base, project_id: bad });
    assert.ok(q.ok);
    assert.equal(q.projectId, null);
  }
});

test("planInboxEvent refuses a body that is not the email shape", () => {
  assert.equal(planInboxEvent({ subject: "x", body: "y", received_at: "2026-10-10T09:00:00Z" }).ok, false);
  assert.equal(planInboxEvent({ from: "a@b", subject: "x", body: 5, received_at: "2026-10-10" }).ok, false);
  assert.equal(planInboxEvent({ from: "a@b", subject: "x", body: "y", received_at: "yesterday" }).ok, false);
  assert.equal(planInboxEvent({ from: "a@b", subject: "x", body: "y".repeat(50_001), received_at: "2026-10-10" }).ok, false);
});

test("planInboxEvent gives an empty subject a placeholder message", () => {
  const p = planInboxEvent({ from: "a@b", subject: "  ", body: "hi", received_at: "2026-10-10T09:00:00Z" });
  assert.ok(p.ok);
  assert.equal(p.event.message, "(no subject)");
  assert.equal(p.event.data.subject, "");
});
