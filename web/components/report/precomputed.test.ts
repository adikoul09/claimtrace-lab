import { test } from "node:test";
import assert from "node:assert/strict";
import { isPrecomputed } from "./precomputed.ts";

test("isPrecomputed reads the status or a tag, and nothing else", () => {
  assert.equal(isPrecomputed({ status: "precomputed", tags: [] }), true);
  assert.equal(isPrecomputed({ status: "done", tags: ["matchdg", "precomputed"] }), true);
  assert.equal(isPrecomputed({ status: "reference", tags: ["matchdg", "round0"] }), true); // A1's lessons convention
  assert.equal(isPrecomputed({ status: "reference", tags: ["distillation"] }), false);
  assert.equal(isPrecomputed({ status: "new", tags: null }), false);
  assert.equal(isPrecomputed(null), false);
});
