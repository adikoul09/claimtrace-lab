"use client";

// Team tab: one card per agent, updated over Realtime when an agents row changes.
// Agents are shared across projects, so this lists the whole roster.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Agent, AgentOrigin, AgentStatus } from "@/lib/types";
import { applyAgentChange, sortAgents, type AgentChange } from "./agents";

type Status = "connecting" | "live" | "error";

const STATUS_STYLE: Record<AgentStatus, string> = {
  active: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  retired: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  merged: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
};

const ORIGIN_STYLE: Record<AgentOrigin, string> = {
  seed: "border-neutral-300 text-neutral-600 dark:border-neutral-700 dark:text-neutral-400",
  spawned: "border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-400",
  refined: "border-sky-400 text-sky-700 dark:border-sky-600 dark:text-sky-400",
};

export function TeamView() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const db = supabase();

    // Subscribe before the initial fetch so no change falls in the gap; the fetch then upserts.
    const channel = db
      .channel("agents-team")
      .on("postgres_changes", { event: "*", schema: "public", table: "agents" }, (p) =>
        setAgents((cur) => applyAgentChange(cur, p as unknown as AgentChange<Agent>)),
      )
      .subscribe((s) => {
        if (s === "SUBSCRIBED") setStatus("live");
        else if (s === "CHANNEL_ERROR" || s === "TIMED_OUT") setStatus("error");
      });

    db.from("agents")
      .select("*")
      .then(({ data, error }) => {
        if (error) setError(error.message);
        else
          setAgents((cur) =>
            ((data ?? []) as Agent[]).reduce(
              (acc, row) => applyAgentChange(acc, { eventType: "UPDATE", new: row, old: {} }),
              cur,
            ),
          );
      });

    return () => {
      db.removeChannel(channel);
    };
  }, []);

  const names: Record<string, string> = Object.fromEntries(agents.map((a) => [a.id, a.name]));

  return (
    <section aria-labelledby="team-heading">
      <div className="mb-3 flex items-center gap-2">
        <h2 id="team-heading" className="text-sm font-semibold">
          Agents <span className="font-normal text-neutral-500">({agents.length})</span>
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

      {error && <p className="mb-3 text-sm text-red-600">Could not load agents: {error}</p>}

      {agents.length === 0 ? (
        <p className="text-sm text-neutral-500">No agents yet.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sortAgents(agents).map((a) => (
            <li key={a.id}>
              <AgentCard agent={a} names={names} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AgentCard({ agent: a, names }: { agent: Agent; names: Record<string, string> }) {
  const ref = (id: string | null) => (id ? names[id] ?? id.slice(0, 8) : null);
  const parent = ref(a.parent_id);
  const mergedInto = ref(a.merged_into);

  return (
    <article
      className={`h-full rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-800 ${
        a.status === "active" ? "" : "opacity-70"
      }`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="break-all font-mono font-semibold">{a.name}</h3>
        <span className="text-xs text-neutral-500">v{a.version}</span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLE[a.status]}`}>
          {a.status}
        </span>
        <span className={`rounded border px-1.5 py-0.5 text-xs capitalize ${ORIGIN_STYLE[a.origin]}`}>
          {a.origin}
        </span>
      </header>

      <p className="mt-1 break-words text-xs text-neutral-600 dark:text-neutral-400">
        <span className="font-medium">Why: </span>
        {a.origin_reason}
      </p>
      {(parent || mergedInto) && (
        <p className="mt-0.5 text-xs text-neutral-500">
          {parent && <>from {parent}</>}
          {parent && mergedInto && " · "}
          {mergedInto && <>merged into {mergedInto}</>}
        </p>
      )}

      <ul aria-label="Capabilities" className="mt-2 flex flex-wrap gap-1">
        {a.capabilities.map((c) => (
          <li
            key={c}
            className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-xs text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
          >
            {c}
          </li>
        ))}
      </ul>

      {/* Rolling reward arrives with T08 (scored by lab/controller/reward.py). */}
      <p className="mt-2 text-xs text-neutral-500">
        Rolling reward: <span className="tabular-nums">—</span>
      </p>
    </article>
  );
}
