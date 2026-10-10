"use client";

// Header "tokens today: N / 800k" from llm_calls since 05:30 IST. llm_calls is not on Realtime, so this polls.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { formatTokens, sumTokens, TOKEN_BUDGET, tokenDayStart, tokenLevel } from "./tokens";

const POLL_MS = 30_000;
const PAGE = 1000; // PostgREST's default max rows per request
const MAX_PAGES = 50;

const STYLE = {
  ok: { text: "", bar: "bg-green-500" },
  amber: { text: "text-amber-700 dark:text-amber-400", bar: "bg-amber-500" },
  red: { text: "text-red-700 dark:text-red-400 font-semibold", bar: "bg-red-500" },
};

async function tokensSince(startIso: string): Promise<number | null> {
  let total = 0;
  for (let page = 0; page < MAX_PAGES; page++) {
    const { data, error } = await supabase()
      .from("llm_calls")
      .select("tokens_in,tokens_out")
      .gte("ts", startIso)
      .order("ts")
      .range(page * PAGE, page * PAGE + PAGE - 1);
    if (error) return null;
    total += sumTokens(data ?? []);
    if (!data || data.length < PAGE) break;
  }
  return total;
}

export function TokenMeter() {
  const [tokens, setTokens] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      tokensSince(new Date(tokenDayStart(Date.now())).toISOString()).then((n) => {
        if (alive && n !== null) setTokens(n);
      });
    const first = setTimeout(load, 0);
    const poll = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearTimeout(first);
      clearInterval(poll);
    };
  }, []);

  if (tokens === null) return null;
  const level = tokenLevel(tokens);
  const pct = Math.min(100, (tokens / TOKEN_BUDGET) * 100);

  return (
    <span
      className={`flex items-center gap-1.5 whitespace-nowrap ${STYLE[level].text}`}
      title={`${tokens.toLocaleString("en-US")} LLM tokens (in + out) since 05:30 IST; budget ${TOKEN_BUDGET.toLocaleString("en-US")}`}
    >
      <span className={level === "ok" ? "text-neutral-500" : ""}>tokens today:</span>
      <span className="tabular-nums">
        {formatTokens(tokens)} / {formatTokens(TOKEN_BUDGET)}
      </span>
      <span
        role="meter"
        aria-label="LLM tokens used today"
        aria-valuemin={0}
        aria-valuemax={TOKEN_BUDGET}
        aria-valuenow={tokens}
        className="inline-block h-1.5 w-12 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800"
      >
        <span className={`block h-full ${STYLE[level].bar}`} style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}
