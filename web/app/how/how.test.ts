import { test } from "node:test";
import assert from "node:assert/strict";
import { howSteps, NO_EVIDENCE, type Evidence } from "./how.ts";

const ev = (over: Partial<Evidence> = {}): Evidence => ({ ...NO_EVIDENCE, ...over });
const labels = (e: Evidence) => Object.fromEntries(howSteps(e).map((s) => [s.id, s.live ? "live" : "next"]));

test("a step is live only once it has worked here at least once", () => {
  const l = labels(
    ev({ projects: 8, readerDone: 3, designerDone: 2, runsDone: 6, graded: 1, rewards: 29, evolved: 39, lessons: 13, emails: 7 }),
  );
  assert.deepEqual(l, {
    paper: "live",
    reader: "live",
    designer: "live",
    implementer: "next",
    worker: "live",
    grading: "live",
    report: "live",
    scores: "live",
    evolve: "live",
    lessons: "live",
    email: "live",
    inbox: "live",
    engine: "next",
  });
});

test("nothing is live without evidence, and Send to engine stays next even with every count set", () => {
  assert.ok(howSteps(NO_EVIDENCE).every((s) => !s.live));
  const all = ev({ projects: 1, readerDone: 1, designerDone: 1, implementerDone: 1, runsDone: 1, graded: 1, rewards: 1, evolved: 1, lessons: 1, emails: 1 });
  assert.deepEqual(howSteps(all).filter((s) => !s.live).map((s) => s.id), ["engine"]);
});

test("a live step says how often it has worked, in plain words", () => {
  const s = howSteps(ev({ readerDone: 3, runsDone: 1 }));
  assert.equal(s.find((x) => x.id === "reader")!.proof, "done 3 times here");
  assert.equal(s.find((x) => x.id === "worker")!.proof, "done once here");
  assert.equal(s.find((x) => x.id === "implementer")!.proof, null);
});
