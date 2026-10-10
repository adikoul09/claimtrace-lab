import { test } from "node:test";
import assert from "node:assert/strict";
import { TOKEN_CAP, formatTokens, sumTokens, tokenDayStart, tokenLevel, tokenMeterText } from "./tokens.ts";

test("the token day starts at 05:30 IST (00:00 UTC) on the same day once it has passed", () => {
  // 06:00 IST on 10 Oct = 00:30 UTC
  assert.equal(tokenDayStart(Date.parse("2026-10-10T00:30:00Z")), Date.parse("2026-10-10T00:00:00Z"));
  // exactly 05:30 IST
  assert.equal(tokenDayStart(Date.parse("2026-10-10T00:00:00Z")), Date.parse("2026-10-10T00:00:00Z"));
});

test("before 05:30 IST the token day is still yesterday's", () => {
  // 05:20 IST on 10 Oct = 23:50 UTC on 9 Oct
  assert.equal(tokenDayStart(Date.parse("2026-10-09T23:50:00Z")), Date.parse("2026-10-09T00:00:00Z"));
});

test("levels: amber above 500k, red above our 700k cap", () => {
  assert.equal(TOKEN_CAP, 700_000);
  assert.equal(tokenLevel(500_000), "ok");
  assert.equal(tokenLevel(500_001), "amber");
  assert.equal(tokenLevel(700_000), "amber");
  assert.equal(tokenLevel(700_001), "red");
});

test("sumTokens adds input and output tokens, treating missing values as 0", () => {
  assert.equal(sumTokens([{ tokens_in: 100, tokens_out: 20 }, { tokens_in: 5, tokens_out: null }]), 125);
});

test("formatTokens is compact: 950, 12.3k, 532k", () => {
  assert.equal(formatTokens(950), "950");
  assert.equal(formatTokens(12_345), "12.3k");
  assert.equal(formatTokens(532_400), "532k");
});

test("the meter shows live tokens against our 700k cap", () => {
  assert.equal(tokenMeterText(473_210), "AI tokens today: 473k / 700k cap");
  assert.equal(tokenMeterText(950), "AI tokens today: 950 / 700k cap");
});
