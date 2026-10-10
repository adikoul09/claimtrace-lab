"use client";

// Header "Replay" badge (PLAN T26, SPEC §14.5): shown while the newest LLM call was replayed from the cache.
// llm_calls is not on Realtime, so this polls the newest row.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { isReplaying } from "./replay";

const POLL_MS = 15_000;

export const REPLAY_PILL =
  "rounded border border-amber-500 bg-amber-100 px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";

export function ReplayBadge() {
  const [replay, setReplay] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      supabase()
        .from("llm_calls")
        .select("mode")
        .order("ts", { ascending: false })
        .limit(1)
        .then(({ data, error }) => {
          if (alive && !error) setReplay(isReplaying(data?.[0] ?? null));
        });
    const first = setTimeout(load, 0);
    const poll = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearTimeout(first);
      clearInterval(poll);
    };
  }, []);

  if (!replay) return null;
  return (
    <span
      className={REPLAY_PILL}
      title="LLM_MODE=replay: answers come from a cache of real earlier LLM calls, not new calls"
    >
      Replay
    </span>
  );
}
