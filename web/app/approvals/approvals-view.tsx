"use client";

// Mobile-first approvals queue (SPEC §9): approve, reject or redirect tasks awaiting approval,
// and 👍/👎 on recently finished tasks. Reads use the anon key; writes go through the passcode-gated routes.
import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Agent, Event, Json, Project, Reward, Task } from "@/lib/types";
import { PasscodeForm, post, useAuthed } from "@/components/live/write";
import { budgetLabel, capabilityLabel, statusLabel } from "@/components/live/labels";

type Row = Pick<
  Task,
  "id" | "project_id" | "agent_id" | "capability" | "status" | "input" | "created_at" | "finished_at"
>;
const FIELDS = "id,project_id,agent_id,capability,status,input,created_at,finished_at";
const FINISHED_LIMIT = 15;
const HISTORY_LIMIT = 30;

const obj = (j: Json | null | undefined) =>
  j && typeof j === "object" && !Array.isArray(j) ? (j as Record<string, Json>) : {};

export function ApprovalsView() {
  const [authed, setAuthed] = useAuthed();
  const [awaiting, setAwaiting] = useState<Row[]>([]);
  const [finished, setFinished] = useState<Row[]>([]);
  const [history, setHistory] = useState<Row[]>([]); // failed and rejected: folded under "Show history"
  const [names, setNames] = useState<Record<string, string>>({});
  const [projects, setProjects] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [rewards, setRewards] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const db = supabase();
    const [a, f, h] = await Promise.all([
      db.from("tasks").select(FIELDS).eq("status", "awaiting_approval").order("created_at"),
      db
        .from("tasks")
        .select(FIELDS)
        .eq("status", "done")
        .not("agent_id", "is", null)
        .order("finished_at", { ascending: false, nullsFirst: false })
        .limit(FINISHED_LIMIT),
      db
        .from("tasks")
        .select(FIELDS)
        .in("status", ["failed", "rejected"])
        .order("created_at", { ascending: false })
        .limit(HISTORY_LIMIT),
    ]);
    const err = a.error ?? f.error ?? h.error;
    if (err) return setError(err.message);
    const aw = (a.data ?? []) as Row[];
    const fin = (f.data ?? []) as Row[];
    const hist = (h.data ?? []) as Row[];
    setAwaiting(aw);
    setFinished(fin);
    setHistory(hist);

    const ids = [...aw, ...fin, ...hist].map((t) => t.id);
    if (ids.length === 0) return;
    const [ev, rw] = await Promise.all([
      db.from("events").select("task_id,type,reason,data,ts").in("task_id", ids).order("ts"),
      db.from("rewards").select("task_id,reward").in("task_id", ids),
    ]);
    const why: Record<string, string> = {};
    const fb: Record<string, string> = {};
    for (const e of (ev.data ?? []) as Pick<Event, "task_id" | "type" | "reason" | "data">[]) {
      if (!e.task_id) continue;
      if (e.type === "feedback") fb[e.task_id] = String(obj(e.data).value ?? "");
      else why[e.task_id] = e.reason; // newest wins (ordered by ts)
    }
    setReasons(why);
    setFeedback(fb);
    setRewards(
      Object.fromEntries(((rw.data ?? []) as Pick<Reward, "task_id" | "reward">[]).map((r) => [r.task_id, r.reward])),
    );
  }, []);

  useEffect(() => {
    const db = supabase();
    db.from("agents")
      .select("id,name")
      .then(({ data }) =>
        setNames(Object.fromEntries(((data ?? []) as Pick<Agent, "id" | "name">[]).map((a) => [a.id, a.name]))),
      );
    db.from("projects")
      .select("id,title")
      .then(({ data }) =>
        setProjects(Object.fromEntries(((data ?? []) as Pick<Project, "id" | "title">[]).map((p) => [p.id, p.title]))),
      );

    // Subscribe first, then load, so nothing falls in the gap. Rewards are not on Realtime; reward events are.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const reload = () => {
      clearTimeout(timer);
      timer = setTimeout(load, 300);
    };
    const channel = db
      .channel("approvals")
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks" }, reload)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "events" }, (p) => {
        if ((p.new as Event).task_id) reload();
      })
      .subscribe();
    const first = setTimeout(load, 0);
    return () => {
      clearTimeout(first);
      clearTimeout(timer);
      db.removeChannel(channel);
    };
  }, [load]);

  return (
    <div className="space-y-6">
      {authed === false && (
        <PasscodeForm onDone={() => setAuthed(true)} why="Needed to approve, reject, redirect or give feedback." />
      )}
      {error && <p className="text-sm text-red-600">Could not load tasks: {error}</p>}

      <section aria-labelledby="awaiting-heading">
        <h2 id="awaiting-heading" className="mb-2 text-sm font-semibold">
          Awaiting approval <span className="font-normal text-neutral-500">({awaiting.length})</span>
        </h2>
        {awaiting.length === 0 ? (
          <p className="text-sm text-neutral-500">Nothing waits for a decision.</p>
        ) : (
          <ul className="space-y-3">
            {awaiting.map((t) => (
              <li key={t.id}>
                <ApprovalCard
                  task={t}
                  agent={t.agent_id ? names[t.agent_id] : undefined}
                  project={t.project_id ? projects[t.project_id] : undefined}
                  reason={reasons[t.id]}
                  canAct={!!authed}
                  onDone={load}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="finished-heading">
        <h2 id="finished-heading" className="mb-2 text-sm font-semibold">
          Recently finished
        </h2>
        {finished.length === 0 ? (
          <p className="text-sm text-neutral-500">No finished tasks yet.</p>
        ) : (
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {finished.map((t) => (
              <li key={t.id}>
                <FeedbackRow
                  task={t}
                  agent={t.agent_id ? names[t.agent_id] : undefined}
                  current={feedback[t.id]}
                  reward={rewards[t.id]}
                  canAct={!!authed}
                  onDone={load}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      {history.length > 0 && (
        <details>
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
            Show history <span className="font-normal text-neutral-500">({history.length} failed or rejected)</span>
          </summary>
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {history.map((t) => (
              <li key={t.id}>
                <FeedbackRow
                  task={t}
                  agent={t.agent_id ? names[t.agent_id] : undefined}
                  current={feedback[t.id]}
                  reward={rewards[t.id]}
                  canAct={!!authed}
                  onDone={load}
                />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ApprovalCard({
  task: t,
  agent,
  project,
  reason,
  canAct,
  onDone,
}: {
  task: Row;
  agent?: string;
  project?: string;
  reason?: string;
  canAct: boolean;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = obj(t.input);
  const goal = typeof input.goal === "string" ? input.goal : null;
  const budget = budgetLabel(obj(input.budget));

  const decide = async (decision: "approve" | "reject" | "redirect") => {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/tasks/${t.id}/decision`, { decision, note: note || undefined });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="rounded-lg border border-amber-300 p-3 text-sm dark:border-amber-800">
      <header className="flex flex-wrap items-baseline gap-x-2">
        <h3 className="font-semibold">{capabilityLabel(t.capability)}</h3>
        {agent && <span className="text-xs text-neutral-500">by {agent}</span>}
      </header>
      {project && <p className="mt-0.5 break-words text-xs text-neutral-500">{project}</p>}

      {reason && (
        <p className="mt-2 break-words">
          <span className="font-medium">Why: </span>
          {reason}
        </p>
      )}
      {goal && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-neutral-600 dark:text-neutral-400">Proposal</summary>
          <p className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap break-words text-xs">{goal}</p>
        </details>
      )}
      {budget && (
        <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-400">
          <span className="font-medium">Cost estimate: </span>
          {budget}
        </p>
      )}

      <label htmlFor={`note-${t.id}`} className="mt-3 block text-xs text-neutral-500">
        Note (required to redirect)
      </label>
      <textarea
        id={`note-${t.id}`}
        rows={2}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        disabled={!canAct || busy}
        className="mt-1 w-full rounded border border-neutral-300 bg-transparent p-2 text-base dark:border-neutral-700"
      />
      <div className="mt-2 grid grid-cols-3 gap-2">
        <button
          type="button"
          onClick={() => decide("approve")}
          disabled={!canAct || busy}
          className="min-h-11 rounded bg-green-600 font-medium text-white disabled:opacity-50"
        >
          Approve
        </button>
        <button
          type="button"
          onClick={() => decide("reject")}
          disabled={!canAct || busy}
          className="min-h-11 rounded border border-red-400 font-medium text-red-700 disabled:opacity-50 dark:text-red-400"
        >
          Reject
        </button>
        <button
          type="button"
          onClick={() => decide("redirect")}
          disabled={!canAct || busy || !note.trim()}
          className="min-h-11 rounded border border-neutral-400 font-medium disabled:opacity-50"
        >
          Redirect
        </button>
      </div>
      {!canAct && <p className="mt-2 text-xs text-neutral-500">Log in with the passcode to decide.</p>}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </article>
  );
}

function FeedbackRow({
  task: t,
  agent,
  current,
  reward,
  canAct,
  onDone,
}: {
  task: Row;
  agent?: string;
  current?: string;
  reward?: number;
  canAct: boolean;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async (value: "up" | "down") => {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/tasks/${t.id}/feedback`, { value });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const thumb = (value: "up" | "down", label: string, emoji: string) => (
    <button
      type="button"
      onClick={() => send(value)}
      disabled={!canAct || busy}
      aria-pressed={current === value}
      aria-label={label}
      className={`min-h-11 min-w-11 rounded border text-lg disabled:opacity-50 ${
        current === value
          ? "border-sky-500 bg-sky-50 dark:bg-sky-950/40"
          : "border-neutral-300 dark:border-neutral-700"
      }`}
    >
      {emoji}
    </button>
  );
  return (
    <div className="flex items-center gap-2 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <p>
          {capabilityLabel(t.capability)}{" "}
          <span
            className={
              t.status === "done"
                ? "text-green-700 dark:text-green-400"
                : t.status === "failed"
                  ? "text-red-600"
                  : "text-neutral-500"
            }
          >
            {statusLabel(t.status)}
          </span>
        </p>
        <p className="truncate text-xs text-neutral-500">
          {agent ?? "no agent"}
          {t.status !== "rejected" && (
            <>
              {" "}
              · reward{" "}
              <span className="tabular-nums">{reward === undefined ? "not scored yet" : reward.toFixed(2)}</span>
            </>
          )}
        </p>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
      {/* Feedback is for finished work only (done or failed); a rejected task never ran. */}
      {t.status !== "rejected" && thumb("up", "Thumbs up", "👍")}
      {t.status !== "rejected" && thumb("down", "Thumbs down", "👎")}
    </div>
  );
}
