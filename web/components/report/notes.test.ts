import { test } from "node:test";
import assert from "node:assert/strict";
import { notesObject, planNotes, NOTES_MAX_BYTES } from "./notes.ts";

test("planNotes accepts Markdown text and keeps it as written", () => {
  assert.deepEqual(planNotes({ markdown: "# Notes\n\n- lr 0.03 |x|\n" }), { ok: true, markdown: "# Notes\n\n- lr 0.03 |x|\n" });
});

test("planNotes refuses a missing, blank or oversized body with a reason", () => {
  for (const body of [{}, { markdown: 3 }, { markdown: "  \n " }]) {
    const r = planNotes(body);
    assert.equal(r.ok, false);
    assert.equal(!r.ok && r.status, 400);
  }
  const big = planNotes({ markdown: "é".repeat(NOTES_MAX_BYTES) });
  assert.deepEqual([big.ok, !big.ok && big.status], [false, 413]);
});

test("notesObject names the Storage object notes/<project id>.md", () => {
  assert.equal(notesObject("55068bf5-4292-4639-954d-5cd1b54acee0"), "55068bf5-4292-4639-954d-5cd1b54acee0.md");
});
