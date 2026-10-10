import { test } from "node:test";
import assert from "node:assert/strict";
import { projectBadge } from "./project-badge.ts";

test("precomputed and reference projects get a badge on the home list", () => {
  assert.equal(projectBadge("precomputed")?.label, "Precomputed");
  assert.equal(projectBadge("reference")?.label, "Reference");
});

test("live project statuses get no badge", () => {
  for (const s of ["new", "planning", "running", "done", "blocked", "stopped", "plan_failed", "test"])
    assert.equal(projectBadge(s), null);
});
