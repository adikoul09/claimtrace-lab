import { test } from "node:test";
import assert from "node:assert/strict";
import { formatTokens, sumTokens, TOKEN_BUDGET, tokenDayStart, tokenLevel } from "./tokens.ts";

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

test("levels: amber above 500k, red above 700k of the 800k budget", () => {
  assert.equal(TOKEN_BUDGET, 800_000);
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
