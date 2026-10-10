import { test } from "node:test";
import assert from "node:assert/strict";
import { lessonUse, skipReasonLabel } from "./lesson-events.ts";

const applied = (id: string, lesson: string, data: Record<string, unknown>, ts = "2026-10-11T10:00:00Z") => ({
  id,
  type: "lesson_applied",
  ts,
  message: `lesson applied to the planner: text of ${lesson}`,
  reason: "tags matched: x",
  data: { lesson_id: lesson, ...data },
});
const skipped = (id: string, lesson: string, data: Record<string, unknown>) => ({
  id,
  type: "lesson_skipped",
  ts: "2026-10-11T09:00:00Z",
  message: `lesson not used in the planner: text of ${lesson}`,
  reason: "the detail",
  data: { lesson_id: lesson, ...data },
});

test("lessonUse groups applied events per lesson: where it was used, matched tags, best rank", () => {
  const { applied: a } = lessonUse([
    applied("e1", "L1", { tags: ["write_code"], where: "planner", rank: 2 }),
    applied("e2", "L1", { tags: ["debug", "write_code"], where: "debug task", rank: 1 }),
    applied("e3", "L2", { tags: ["budget"], where: "planner" }), // pre-MEM-1 events have no rank
  ]);
  assert.equal(a.length, 2);
  assert.deepEqual(a[0], {
    lessonId: "L1",
    message: "text of L1",
    uses: 2,
    where: ["planner", "debug task"],
    tags: ["write_code", "debug"],
    rank: 1,
    eventId: "e1",
  });
  assert.equal(a[1].rank, null);
});

test("lessonUse keeps one skipped row per lesson and reason, with the controller's detail", () => {
  const { skipped: s } = lessonUse([
    skipped("s1", "L3", { reason: "other_paper", detail: "from another paper (lesson: round0:matchdg)" }),
    skipped("s2", "L3", { reason: "other_paper", detail: "from another paper (lesson: round0:matchdg)" }),
    skipped("s3", "L4", { reason: "over_limit" }),
  ]);
  assert.deepEqual(
    s.map((x) => [x.lessonId, x.reason, x.detail]),
    [
      ["L3", "other_paper", "from another paper (lesson: round0:matchdg)"],
      ["L4", "over_limit", "the detail"],
    ],
  );
});

test("lessonUse ignores other events and events without a lesson id", () => {
  const r = lessonUse([
    { id: "x", type: "feedback", ts: "t", message: "m", reason: "r", data: {} },
    { id: "y", type: "lesson_applied", ts: "t", message: "m", reason: "r", data: {} },
  ]);
  assert.deepEqual(r, { applied: [], skipped: [] });
});

test("skip reasons read as plain words; unknown codes are humanized", () => {
  assert.equal(skipReasonLabel("no_evidence"), "No evidence event");
  assert.equal(skipReasonLabel("over_limit"), "Over the limit of 5 per plan");
  assert.equal(skipReasonLabel("brand_new"), "Brand new");
});
