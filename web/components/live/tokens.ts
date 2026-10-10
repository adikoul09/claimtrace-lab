// Pure helpers for the header's "tokens today" meter (from llm_calls).

export const TOKEN_BUDGET = 800_000;
const AMBER_ABOVE = 500_000;
const RED_ABOVE = 700_000;

const DAY_MS = 24 * 60 * 60 * 1000;
const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;
const RESET_IST_MS = (5 * 60 + 30) * 60 * 1000; // the token day resets at 05:30 IST (= 00:00 UTC)

/** The latest 05:30 IST at or before `now`, as epoch ms. */
export function tokenDayStart(now: number): number {
  const sinceReset = now + IST_OFFSET_MS - RESET_IST_MS;
  return Math.floor(sinceReset / DAY_MS) * DAY_MS - IST_OFFSET_MS + RESET_IST_MS;
}

export type TokenLevel = "ok" | "amber" | "red";

export function tokenLevel(tokens: number): TokenLevel {
  return tokens > RED_ABOVE ? "red" : tokens > AMBER_ABOVE ? "amber" : "ok";
}

export function sumTokens(rows: { tokens_in: number | null; tokens_out: number | null }[]): number {
  return rows.reduce((s, r) => s + (r.tokens_in ?? 0) + (r.tokens_out ?? 0), 0);
}

/** 950, 12.3k, 532k */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 100_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${Math.round(n / 1000)}k`;
}
