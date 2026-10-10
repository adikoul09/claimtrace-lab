"use client";

// Live tab: the project's events, newest-first, updated over Realtime.
// Every row shows what happened (message) and why (reason).
import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import { mergeEvents } from "@/lib/live";
import type { Agent, Event } from "@/lib/types";
import { REPLAY_PILL } from "./replay-badge";
import { eventIsReplay } from "./replay";
import { WhatIfForm } from "./whatif-form";

const LIMIT = 200;

type Status = "connecting" | "live" | "error";

export function EventStream({ projectId }: { projectId: string }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [agents, setAgents] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<Status>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const jumped = useRef(false);

  // Rows arrive after the first fetch, so a #ev-<id> link (from a lesson's evidence) can't scroll on load; do it here.
  useEffect(() => {
    if (jumped.current || !window.location.hash.startsWith("#ev-")) return;
    const el = document.getElementById(window.location.hash.slice(1));
    if (el) {
      el.scrollIntoView({ block: "center" });
      el.dataset.highlight = ""; // :target does not apply to rows rendered after load
      jumped.current = true;
    }
  }, [events]);

  useEffect(() => {
    const db = supabase();

    // Subscribe before the initial fetch so no insert falls in the gap; mergeEvents dedupes.
    const channel = db
      .channel(`events-${projectId}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events", filter: `project_id=eq.${projectId}` },
        (p) => setEvents((cur) => mergeEvents(cur, [p.new as Event], LIMIT)),
      )
      .subscribe((s) => {
        if (s === "SUBSCRIBED") setStatus("live");
        else if (s === "CHANNEL_ERROR" || s === "TIMED_OUT") setStatus("error");
      });

    db.from("events")
      .select("*")
      .eq("project_id", projectId)
      .order("ts", { ascending: false })
      .limit(LIMIT)
      .then(({ data, error }) => {
        setLoaded(true);
        if (error) setError(error.message);
        else setEvents((cur) => mergeEvents(cur, (data ?? []) as Event[], LIMIT));
      });

    db.from("agents")
      .select("id,name")
      .then(({ data }) => {
        const names: Record<string, string> = {};
        for (const a of (data ?? []) as Pick<Agent, "id" | "name">[]) names[a.id] = a.name;
        setAgents(names);
      });

    return () => {
      db.removeChannel(channel);
    };
  }, [projectId]);

  return (
    <section aria-labelledby="live-heading">
      <div className="mb-4">
        <WhatIfForm projectId={projectId} />
      </div>
      <div className="mb-3 flex items-center gap-2">
        <h2 id="live-heading" className="text-sm font-semibold">
          Events
        </h2>
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            status === "live" ? "bg-green-500" : status === "error" ? "bg-red-500" : "bg-neutral-400"
          }`}
          aria-hidden
        />
        <span className="text-xs text-neutral-500">
          {status === "live" ? "Realtime connected" : status === "error" ? "Realtime error" : "Connecting…"}
        </span>
      </div>

      {error && <p className="mb-3 text-sm text-red-600">Could not load events: {error}</p>}

      {events.length === 0 ? (
        !loaded ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : (
          !error && <p className="text-sm text-neutral-500">No events yet. New ones appear here as they happen.</p>
        )
      ) : (
        <ol className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {events.map((e) => (
            <li key={e.id} id={`ev-${e.id}`} className="scroll-mt-4 py-2 text-sm data-[highlight]:bg-amber-50 dark:data-[highlight]:bg-amber-950/30">
              <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-neutral-500">
                <time dateTime={e.ts} className="tabular-nums">
                  {new Date(e.ts).toLocaleTimeString()}
                </time>
                <span className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                  {e.type}
                </span>
                {e.agent_id && <span>{agents[e.agent_id] ?? e.agent_id.slice(0, 8)}</span>}
                {eventIsReplay(e.data) && (
                  <span className={REPLAY_PILL} title="This step's LLM call was replayed from the cache of real calls">
                    Replay
                  </span>
                )}
              </div>
              <p className="mt-1 break-words">{e.message}</p>
              <p className="mt-0.5 break-words text-neutral-600 dark:text-neutral-400">
                <span className="font-medium">Why: </span>
                {e.reason}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
