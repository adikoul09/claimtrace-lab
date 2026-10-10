import { test } from "node:test";
import assert from "node:assert/strict";
import { isUuid, lineFromHash, logObject, splitLog } from "./log-lines.ts";

test("splitLog numbers lines as the worker does: one per newline, CRs stripped, no phantom last line", () => {
  assert.deepEqual(splitLog("a\r\nb\nMETRIC x=1 step=0\n"), ["a", "b", "METRIC x=1 step=0"]);
  assert.deepEqual(splitLog("a\n\nb"), ["a", "", "b"]);
  assert.deepEqual(splitLog(""), []);
});

test("lineFromHash reads #L<n> and rejects anything else", () => {
  assert.equal(lineFromHash("#L12"), 12);
  assert.equal(lineFromHash("#L0"), null);
  assert.equal(lineFromHash("#l12"), null);
  assert.equal(lineFromHash("#L12abc"), null);
  assert.equal(lineFromHash(""), null);
});

test("logObject accepts only logs/<name>.log and returns the object name", () => {
  assert.equal(
    logObject("logs/7adc866e-a17f-41e9-b64e-c6948a979f7d.log"),
    "7adc866e-a17f-41e9-b64e-c6948a979f7d.log",
  );
  assert.equal(logObject("papers/x.log"), null);
  assert.equal(logObject("logs/../secrets.log"), null);
  assert.equal(logObject("logs/a/b.log"), null);
  assert.equal(logObject("logs/x.txt"), null);
  assert.equal(logObject(null), null);
});

test("isUuid accepts experiment ids only", () => {
  assert.equal(isUuid("7adc866e-a17f-41e9-b64e-c6948a979f7d"), true);
  assert.equal(isUuid("7ADC866E-A17F-41E9-B64E-C6948A979F7D"), true);
  assert.equal(isUuid("../etc/passwd"), false);
  assert.equal(isUuid("7adc866e"), false);
});
