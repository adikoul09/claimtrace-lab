import { test } from "node:test";
import assert from "node:assert/strict";
import { isImported, lessonText, sortLessons } from "./lessons.ts";

const l = (over: Partial<{ id: string; text: string; tags: string[]; times_applied: number; created_at: string }>) => ({
  id: "x",
  text: "Check the model-selection rule",
  tags: [] as string[],
  times_applied: 0,
  created_at: "2026-10-10T10:00:00Z",
  ...over,
});

test("a lesson tagged round0 is imported from the Round 0 audit", () => {
  assert.equal(isImported(l({ tags: ["matchdg", "round0"] })), true);
  assert.equal(isImported(l({ tags: ["Round0"] })), true);
});

test("a lesson whose text carries the import label is imported, and the label is not repeated in the text", () => {
  const lesson = l({ text: "Imported from Round 0 audit: Check the model-selection rule" });
  assert.equal(isImported(lesson), true);
  assert.equal(lessonText(lesson), "Check the model-selection rule");
});

test("a lesson written by this run's Reporter is not imported, and its text is unchanged", () => {
  const lesson = l({ tags: ["distillation", "mnist"], text: "Pin torchvision with torch" });
  assert.equal(isImported(lesson), false);
  assert.equal(lessonText(lesson), "Pin torchvision with torch");
});

test("sortLessons puts the most-applied first, then the newest", () => {
  const out = sortLessons([
    l({ id: "old0", times_applied: 0, created_at: "2026-10-10T09:00:00Z" }),
    l({ id: "new0", times_applied: 0, created_at: "2026-10-10T11:00:00+00:00" }),
    l({ id: "used3", times_applied: 3 }),
  ]);
  assert.deepEqual(out.map((x) => x.id), ["used3", "new0", "old0"]);
});
