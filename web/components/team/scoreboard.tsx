"use client";

// Scoreboard (agents ranked by rolling reward) and the reward breakdown of one agent.
// Every number here is a stored rewards row (lab/controller/reward.py); the UI only averages the window.
import type { Agent, Reward } from "@/lib/types";
import { latestPerRole, ROLLING_WINDOW, scoreboard, rollingReward } from "./lineage";
import { ORIGIN_STYLE, STATUS_STYLE } from "./styles";
import { agentLabel, capabilityLabel, statusLabel } from "@/components/live/labels";

const OUTCOME: Record<number, string> = { 0: "failed", 0.5: "partial", 1: "passed" };
const FEEDBACK: Record<number, string> = { 0: "👎", 0.5: "none", 1: "👍" };

export function Scoreboard({
  agents,
  rewards,
  selectedId,
  onSelect,
}: {
  agents: Agent[];
  rewards: Reward[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  // Each role's newest version is ranked; older versions fold under "History (N)", like the graph.
  const { latest, older, spawnedRoot } = latestPerRole(agents);
  return (
    <div>
      <ScoreTable
        rows={scoreboard(latest, rewards)}
        spawnedRoot={spawnedRoot}
        selectedId={selectedId}
        onSelect={onSelect}
        caption="Each role's newest agent version, ranked by rolling reward"
      />
      {older.length > 0 && (
        <details className="mt-2">
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
            History ({older.length}) <span className="font-normal text-neutral-500">older versions</span>
          </summary>
          <ScoreTable
            rows={scoreboard(older, rewards)}
            spawnedRoot={{}}
            selectedId={selectedId}
            onSelect={onSelect}
            caption="Older agent versions, ranked by rolling reward"
          />
        </details>
      )}
    </div>
  );
}

function ScoreTable({
  rows,
  spawnedRoot,
  selectedId,
  onSelect,
  caption,
}: {
  rows: ReturnType<typeof scoreboard<Agent, Reward>>;
  spawnedRoot: Record<string, Agent | undefined>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  caption: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="text-xs text-neutral-500">
          <tr className="border-b border-neutral-200 dark:border-neutral-800">
            <th className="py-1.5 pr-2 font-medium">#</th>
            <th className="py-1.5 pr-2 font-medium">Agent</th>
            <th className="py-1.5 pr-2 font-medium">Status</th>
            <th className="py-1.5 pr-2 text-right font-medium">Rolling ({ROLLING_WINDOW})</th>
            <th className="py-1.5 text-right font-medium">Scored</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ agent: a, rolling }, i) => {
            const spawned = spawnedRoot[a.id];
            return (
              <tr
                key={a.id}
                className={`border-b border-neutral-100 align-top dark:border-neutral-900 ${
                  a.id === selectedId ? "bg-sky-50 dark:bg-sky-950/40" : ""
                }`}
              >
                <td className="py-1.5 pr-2 tabular-nums text-neutral-500">{rolling ? i + 1 : "–"}</td>
                <td className="py-1.5 pr-2">
                  <button
                    type="button"
                    onClick={() => onSelect(a.id)}
                    className="text-left hover:underline"
                    aria-pressed={a.id === selectedId}
                    title={a.name}
                  >
                    {agentLabel(a)}
                  </button>
                  {spawned && (
                    <span
                      className={`ml-1.5 rounded border px-1 py-0.5 text-[10px] ${ORIGIN_STYLE.spawned}`}
                      title={`Spawned: ${spawned.origin_reason}`}
                    >
                      Spawned
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLE[a.status]}`}>
                    {statusLabel(a.status)}
                  </span>
                </td>
                <td className="py-1.5 pr-2 text-right tabular-nums">{rolling ? rolling.mean.toFixed(2) : "—"}</td>
                <td className="py-1.5 text-right tabular-nums text-neutral-500">{rolling?.count ?? 0}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RewardBreakdown({
  agent,
  rewards,
  taskCapability,
  reasons,
  onClose,
}: {
  agent: Agent;
  rewards: Reward[];
  taskCapability: Record<string, string>;
  /** task id → the reason text of its latest reward event, written by the controller. */
  reasons: Record<string, string>;
  onClose: () => void;
}) {
  const rolling = rollingReward(rewards, agent.id);
  const inWindow = new Set(rolling?.window.map((r) => r.id));
  const all = rewards
    .filter((r) => r.agent_id === agent.id)
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));

  return (
    <section
      aria-labelledby="breakdown-heading"
      className="rounded-lg border border-sky-300 p-3 text-sm dark:border-sky-800"
    >
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 id="breakdown-heading" className="font-semibold">
          Reward breakdown: <span title={agent.name}>{agentLabel(agent)}</span>
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded px-2 py-0.5 text-xs text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          Close
        </button>
      </header>
      <p className="mt-1 text-xs text-neutral-500">
        reward = 0.6 · outcome + 0.2 · (1 − cost_norm) + 0.2 · feedback
      </p>
      {rolling ? (
        <p className="mt-1">
          Rolling mean over the last {rolling.window.length}:{" "}
          <span className="font-semibold tabular-nums">{rolling.mean.toFixed(2)}</span>{" "}
          <span className="text-xs text-neutral-500">
            ({rolling.window.map((r) => r.reward.toFixed(2)).join(", ")})
          </span>
        </p>
      ) : (
        <p className="mt-2 text-neutral-500">No scored tasks yet.</p>
      )}

      {all.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-neutral-500">
              <tr className="border-b border-neutral-200 dark:border-neutral-800">
                <th className="py-1 pr-2 font-medium">When</th>
                <th className="py-1 pr-2 font-medium">Task</th>
                <th className="py-1 pr-2 font-medium">Outcome</th>
                <th className="py-1 pr-2 font-medium">Cost</th>
                <th className="py-1 pr-2 font-medium">Feedback</th>
                <th className="py-1 text-right font-medium">Reward</th>
              </tr>
            </thead>
            <tbody>
              {all.map((r) => (
                <tr
                  key={r.id}
                  className={`border-b border-neutral-100 align-top dark:border-neutral-900 ${
                    inWindow.has(r.id) ? "" : "text-neutral-500"
                  }`}
                >
                  <td className="py-1 pr-2 tabular-nums">
                    <time dateTime={r.ts}>{new Date(r.ts).toLocaleTimeString()}</time>
                  </td>
                  <td className="py-1 pr-2">
                    <span>{taskCapability[r.task_id] ? capabilityLabel(taskCapability[r.task_id]) : "A task"}</span>
                    {reasons[r.task_id] && (
                      <p className="mt-0.5 max-w-xs break-words text-neutral-500">{reasons[r.task_id]}</p>
                    )}
                  </td>
                  <td className="py-1 pr-2 tabular-nums">
                    {r.outcome} <span className="text-neutral-500">{OUTCOME[r.outcome] ?? ""}</span>
                  </td>
                  <td className="py-1 pr-2 tabular-nums">{r.cost_norm.toFixed(2)}</td>
                  <td className="py-1 pr-2 tabular-nums">
                    {r.feedback} <span className="text-neutral-500">{FEEDBACK[r.feedback] ?? ""}</span>
                  </td>
                  <td className="py-1 text-right font-semibold tabular-nums">{r.reward.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-neutral-500">Greyed rows are outside the rolling window.</p>
        </div>
      )}
    </section>
  );
}
