"use client";

// Header "AI tokens today: N / 700k cap" from live llm_calls since 05:30 IST (replayed calls use no quota).
// llm_calls is not on Realtime, so this polls.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { sumTokens, TOKEN_CAP, tokenDayStart, tokenLevel, tokenMeterText } from "./tokens";

const TOOLTIP = "Daily gateway quota 800k. New AI work pauses at our safety cap; runs and grading continue. Resets 05:30 IST.";

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
      .eq("mode", "live")
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
  const pct = Math.min(100, (tokens / TOKEN_CAP) * 100);

  return (
    <span
      className={`flex items-center gap-1.5 whitespace-nowrap ${STYLE[level].text}`}
      title={`${TOOLTIP} (${tokens.toLocaleString("en-US")} live tokens so far.)`}
    >
      <span className={`tabular-nums ${level === "ok" ? "text-neutral-600 dark:text-neutral-400" : ""}`}>
        {tokenMeterText(tokens)}
      </span>
      <span
        role="meter"
        aria-label="Live AI tokens used today, against our cap"
        aria-valuemin={0}
        aria-valuemax={TOKEN_CAP}
        aria-valuenow={tokens}
        className="inline-block h-1.5 w-12 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800"
      >
        <span className={`block h-full ${STYLE[level].bar}`} style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}
