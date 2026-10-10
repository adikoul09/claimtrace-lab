import { test } from "node:test";
import assert from "node:assert/strict";
import { eventIsReplay, isReplaying } from "./replay.ts";

test("the header says Replay while the latest LLM call was replayed", () => {
  assert.equal(isReplaying({ mode: "replay" }), true);
});

test("a live latest call, or no calls at all, is not Replay", () => {
  assert.equal(isReplaying({ mode: "live" }), false);
  assert.equal(isReplaying(null), false);
});

test("an event whose data records mode 'replay' is labelled Replay", () => {
  assert.equal(eventIsReplay({ mode: "replay", model: "gemini" }), true);
  assert.equal(eventIsReplay({ mode: "live" }), false);
  assert.equal(eventIsReplay(null), false);
  assert.equal(eventIsReplay(["replay"]), false);
});
