"use client";

// Header executor status dots: green idle, blue busy, grey when the heartbeat is over 30 s old.
// executors is not in the Realtime publication, so this polls at the heartbeat cadence.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { formatAgo } from "@/lib/live";
import type { Executor } from "@/lib/types";
import { executorState, type ExecutorState } from "./executors";

const POLL_MS = 10_000;

const DOT: Record<ExecutorState, string> = {
  idle: "bg-green-500",
  busy: "bg-sky-500 animate-pulse",
  stale: "bg-neutral-400 dark:bg-neutral-600",
};

export function ExecutorDots({ now }: { now: number | null }) {
  const [executors, setExecutors] = useState<Executor[]>([]);

  useEffect(() => {
    const load = () =>
      supabase()
        .from("executors")
        .select("*")
        .order("name")
        .then(({ data }) => {
          if (data) setExecutors(data as Executor[]);
        });
    load();
    const poll = setInterval(load, POLL_MS);
    return () => clearInterval(poll);
  }, []);

  if (executors.length === 0) return null;

  return (
    <ul aria-label="Executors" className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {executors.map((e) => {
        // Before the clock starts (prerender), show every dot as stale rather than guess.
        const state = now === null ? "stale" : executorState(e, now);
        const label = `${e.name}: ${state}, heartbeat ${formatAgo(e.last_heartbeat, now ?? undefined)}`;
        return (
          <li key={e.name} className="flex items-center gap-1 whitespace-nowrap" title={label}>
            <span className={`inline-block h-2 w-2 rounded-full ${DOT[state]}`} aria-hidden />
            <span className={state === "stale" ? "text-neutral-500" : ""}>{e.name}</span>
            <span className="sr-only">{label}</span>
          </li>
        );
      })}
    </ul>
  );
}
