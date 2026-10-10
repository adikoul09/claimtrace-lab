"use client";

// Team tab: lineage graph, scoreboard and one card per agent, all live over Realtime.
// Agents are shared across projects, so this lists the whole roster.
// Rewards are not in the Realtime publication; the controller's reward events (which are) trigger a refetch.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Agent, Event, Reward, Task } from "@/lib/types";
import { applyAgentChange, sortAgents, type AgentChange } from "./agents";
import { LessonsPanel } from "./lessons-panel";
import { LineageGraph } from "./lineage-graph";
import { lineageEdges, rollingReward } from "./lineage";
import { RewardBreakdown, Scoreboard } from "./scoreboard";
import { ORIGIN_STYLE, STATUS_STYLE } from "./styles";

type Status = "connecting" | "live" | "error";
type TaskRef = Pick<Task, "id" | "agent_id" | "capability">;

const REWARD_EVENTS = ["reward", "reward_updated"];

export function TeamView() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Record<string, TaskRef>>({});
  const [rewards, setRewards] = useState<Reward[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<Status>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const breakdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const db = supabase();
    const loadRewards = () =>
      db
        .from("rewards")
        .select("*")
        .then(({ data, error }) => {
          if (error) setError(error.message);
          else setRewards((data ?? []) as Reward[]);
        });
    const addTasks = (rows: TaskRef[]) =>
      setTasks((cur) => ({ ...cur, ...Object.fromEntries(rows.map((t) => [t.id, t])) }));
    const addReasons = (rows: Pick<Event, "task_id" | "reason">[]) =>
      setReasons((cur) => ({
        ...cur,
        ...Object.fromEntries(rows.filter((e) => e.task_id).map((e) => [e.task_id, e.reason])),
      }));

    // Subscribe before the initial fetches so no change falls in the gap; the fetches then upsert.
    const channel = db
      .channel("agents-team")
      .on("postgres_changes", { event: "*", schema: "public", table: "agents" }, (p) =>
        setAgents((cur) => applyAgentChange(cur, p as unknown as AgentChange<Agent>)),
      )
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks" }, (p) => {
        const t = p.new as Partial<TaskRef>;
        if (t.id) addTasks([{ id: t.id, agent_id: t.agent_id ?? null, capability: t.capability ?? "" }]);
      })
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events", filter: `type=in.(${REWARD_EVENTS.join(",")})` },
        (p) => {
          addReasons([p.new as Event]);
          loadRewards();
        },
      )
      .subscribe((s) => {
        if (s === "SUBSCRIBED") setStatus("live");
        else if (s === "CHANNEL_ERROR" || s === "TIMED_OUT") setStatus("error");
      });

    db.from("agents")
      .select("*")
      .then(({ data, error }) => {
        setLoaded(true);
        if (error) setError(error.message);
        else
          setAgents((cur) =>
            ((data ?? []) as Agent[]).reduce(
              (acc, row) => applyAgentChange(acc, { eventType: "UPDATE", new: row, old: {} }),
              cur,
            ),
          );
      });
    db.from("tasks")
      .select("id,agent_id,capability")
      .then(({ data }) => addTasks((data ?? []) as TaskRef[]));
    db.from("events")
      .select("task_id,reason")
      .in("type", REWARD_EVENTS)
      .order("ts", { ascending: true })
      .then(({ data }) => addReasons((data ?? []) as Pick<Event, "task_id" | "reason">[]));
    loadRewards();

    return () => {
      db.removeChannel(channel);
    };
  }, []);

  const sorted = useMemo(() => sortAgents(agents), [agents]);
  const edges = useMemo(
    () => lineageEdges(sorted, Object.fromEntries(Object.values(tasks).map((t) => [t.id, t.agent_id]))),
    [sorted, tasks],
  );
  const rolling = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.id, rollingReward(rewards, a.id)?.mean ?? null])),
    [agents, rewards],
  );
  const taskCapability = useMemo(
    () => Object.fromEntries(Object.values(tasks).map((t) => [t.id, t.capability])),
    [tasks],
  );
  const names: Record<string, string> = Object.fromEntries(agents.map((a) => [a.id, a.name]));
  const selected = agents.find((a) => a.id === selectedId) ?? null;

  const select = useCallback((id: string) => {
    setSelectedId(id);
    // Cards sit below the fold on a phone: bring the breakdown into view.
    requestAnimationFrame(() => breakdownRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }, []);

  return (
    <section aria-labelledby="team-heading" className="space-y-6">
      <div className="flex items-center gap-2">
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

      {error && <p className="text-sm text-red-600">Could not load the team: {error}</p>}

      {agents.length === 0 ? (
        <p className="text-sm text-neutral-500">{loaded ? "No agents yet." : "Loading…"}</p>
      ) : (
        <>
          <div>
            <h3 className="mb-2 text-sm font-semibold">Lineage</h3>
            <LineageGraph
              agents={sorted}
              edges={edges}
              rolling={rolling}
              selectedId={selectedId}
              onSelect={select}
            />
          </div>

          <div ref={breakdownRef} className="scroll-mt-4">
            {selected && (
              <RewardBreakdown
                agent={selected}
                rewards={rewards}
                taskCapability={taskCapability}
                reasons={reasons}
                onClose={() => setSelectedId(null)}
              />
            )}
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold">Scoreboard</h3>
            <Scoreboard agents={agents} rewards={rewards} selectedId={selectedId} onSelect={select} />
          </div>

          <LessonsPanel />

          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {sorted.map((a) => (
              <li key={a.id}>
                <AgentCard
                  agent={a}
                  names={names}
                  rolling={rolling[a.id]}
                  selected={a.id === selectedId}
                  onSelect={select}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function AgentCard({
  agent: a,
  names,
  rolling,
  selected,
  onSelect,
}: {
  agent: Agent;
  names: Record<string, string>;
  rolling: number | null;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const ref = (id: string | null) => (id ? names[id] ?? id.slice(0, 8) : null);
  const parent = ref(a.parent_id);
  const mergedInto = ref(a.merged_into);

  return (
    <article
      onClick={() => onSelect(a.id)}
      className={`h-full cursor-pointer rounded-lg border p-3 text-sm ${
        selected ? "border-sky-500" : "border-neutral-200 dark:border-neutral-800"
      } ${a.status === "active" ? "" : "opacity-70"}`}
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

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onSelect(a.id);
        }}
        aria-pressed={selected}
        className="mt-2 text-xs text-neutral-500 hover:underline"
      >
        Rolling reward:{" "}
        <span className="tabular-nums text-current">{rolling === null ? "—" : rolling.toFixed(2)}</span> ·
        breakdown
      </button>
    </article>
  );
}
