"use client";

// React Flow lineage graph: one node per role (a refine chain shows its newest version; "refined N×" opens the
// version history as a list under the graph, readable on a phone); edges for spawning and merging.
// Two columns on a phone, four on a laptop.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Agent } from "@/lib/types";
import { agentLabel, humanize, statusLabel } from "@/components/live/labels";
import { collapseLineage, layoutLineage, type LineageEdge } from "./lineage";
import { EDGE_STYLE, ORIGIN_STYLE, STATUS_STYLE } from "./styles";

const COL_W = 190;
const ROW_H = 120;
const NARROW = 520; // below this container width (a phone), lay out 2 columns instead of 4

type AgentNodeData = {
  agent: Agent;
  rolling: number | null;
  selected: boolean;
  refined: number; // refinements in this agent's chain (0 = none)
  expanded: boolean;
  isHead: boolean;
  spawned: Agent | null; // the chain's spawned root, for the badge and its reason
  onToggle: () => void;
};
type AgentNode = Node<AgentNodeData, "agent">;

function AgentNodeView({
  data: { agent: a, rolling, selected, refined, expanded, isHead, spawned, onToggle },
}: NodeProps<AgentNode>) {
  return (
    <div
      className={`w-40 rounded-md border bg-white px-2 py-1.5 text-xs shadow-sm dark:bg-neutral-900 ${
        selected ? "border-sky-500 ring-2 ring-sky-500/40" : "border-neutral-300 dark:border-neutral-700"
      } ${a.status === "active" ? "" : "opacity-70"}`}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div className="truncate font-semibold" title={`${agentLabel(a)} (${a.name})`}>
        {agentLabel(a)}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        <span className={`rounded px-1 py-0.5 ${STATUS_STYLE[a.status]}`}>{statusLabel(a.status)}</span>
        {spawned && (
          <span
            className={`rounded border px-1 py-0.5 ${ORIGIN_STYLE.spawned}`}
            title={`Spawned: ${spawned.origin_reason}`}
          >
            Spawned
          </span>
        )}
        <span className="ml-auto tabular-nums text-neutral-600 dark:text-neutral-400">
          {rolling === null ? "—" : rolling.toFixed(2)}
        </span>
      </div>
      {spawned && isHead && (
        <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-neutral-500" title={spawned.origin_reason}>
          {spawned.origin_reason}
        </p>
      )}
      {refined > 0 && isHead && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          aria-expanded={expanded}
          className="nodrag mt-1 text-[11px] text-sky-700 hover:underline dark:text-sky-400"
        >
          {expanded ? "hide history" : `refined ${refined}×`}
        </button>
      )}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { agent: AgentNodeView };

export function LineageGraph({
  agents,
  edges,
  rolling,
  selectedId,
  onSelect,
}: {
  agents: Agent[];
  edges: LineageEdge[];
  rolling: Record<string, number | null>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null); // chain whose history is listed under the graph
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  const cols = width > 0 && width < NARROW ? 2 : 4;

  const graph = useMemo(() => collapseLineage(agents, edges, new Set()), [agents, edges]);

  const { nodes, rows } = useMemo(() => {
    const byId = new Map(agents.map((a) => [a.id, a]));
    const pos = layoutLineage(graph.visible, graph.edges, cols);
    const nodes: AgentNode[] = graph.visible.map((a) => {
      const chain = graph.chains[graph.chainOf[a.id]];
      const root = byId.get(chain.root)!;
      return {
        id: a.id,
        type: "agent",
        position: { x: pos[a.id].col * COL_W, y: pos[a.id].row * ROW_H },
        data: {
          agent: a,
          rolling: rolling[a.id] ?? null,
          selected: a.id === selectedId,
          refined: chain.members.length - 1,
          expanded: open === chain.id,
          isHead: a.id === chain.head,
          spawned: root.origin === "spawned" ? root : null,
          onToggle: () => setOpen((cur) => (cur === chain.id ? null : chain.id)),
        },
        draggable: false,
        connectable: false,
      };
    });
    const rows = Math.max(1, ...Object.values(pos).map((p) => p.row + 1));
    return { nodes, rows };
  }, [agents, graph, cols, rolling, selectedId, open]);

  const flowEdges = useMemo<Edge[]>(
    () =>
      graph.edges.map((e) => {
        const s = EDGE_STYLE[e.kind];
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          animated: e.kind === "spawned",
          style: { stroke: s.stroke, strokeWidth: 2, strokeDasharray: s.dash },
          markerEnd: { type: MarkerType.ArrowClosed, color: s.stroke },
          ariaLabel: s.label,
        };
      }),
    [graph.edges],
  );

  return (
    <div>
      <div
        ref={box}
        // Tall enough for the rows that are shown, so fitView does not shrink the cards to unreadable.
        style={{ height: Math.min(560, Math.max(220, rows * ROW_H + 60)) }}
        className="rounded-lg border border-neutral-200 dark:border-neutral-800"
        role="figure"
        aria-label="Agent lineage graph"
      >
        <ReactFlow
          // Re-fit when a node appears or leaves, a history opens or closes, or the column count changes.
          key={`${nodes.length}-${cols}`}
          nodes={nodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => onSelect(n.id)}
          nodesConnectable={false}
          colorMode="system"
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.3}
        >
          <Background />
          {/* On a phone the buttons would cover cards; pinch-zoom does the same job there. */}
          {cols === 4 && <Controls showInteractive={false} />}
        </ReactFlow>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500" aria-label="Edge legend">
        {Object.values(EDGE_STYLE).map((s) => (
          <li key={s.label} className="flex items-center gap-1.5">
            <svg width="24" height="6" aria-hidden>
              <line x1="0" y1="3" x2="24" y2="3" stroke={s.stroke} strokeWidth="2" strokeDasharray={s.dash} />
            </svg>
            {s.label}
          </li>
        ))}
      </ul>
      {open && graph.chains[open] && (
        <ChainHistory
          versions={graph.chains[open].members
            .map((id) => agents.find((a) => a.id === id)!)
            .reverse()}
          rolling={rolling}
          selectedId={selectedId}
          onSelect={onSelect}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

/** A role's versions, newest first, with why each one was made. */
function ChainHistory({
  versions,
  rolling,
  selectedId,
  onSelect,
  onClose,
}: {
  versions: Agent[];
  rolling: Record<string, number | null>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const head = versions[0];
  return (
    <section aria-labelledby="chain-history-heading" className="mt-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
      <div className="mb-2 flex items-center gap-2">
        <h4 id="chain-history-heading" className="text-sm font-semibold">
          {agentLabel(head).split(" · ")[0]}: {versions.length} versions
        </h4>
        <button type="button" onClick={onClose} className="ml-auto text-xs text-neutral-500 hover:underline">
          hide history
        </button>
      </div>
      <ol className="divide-y divide-neutral-200 dark:divide-neutral-800">
        {versions.map((a) => (
          <li key={a.id}>
            <button
              type="button"
              onClick={() => onSelect(a.id)}
              aria-pressed={a.id === selectedId}
              className={`w-full py-2 text-left text-sm ${a.id === selectedId ? "bg-sky-50 dark:bg-sky-950/30" : ""}`}
            >
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-medium">version {a.version}</span>
                <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLE[a.status]}`}>{statusLabel(a.status)}</span>
                <span className={`rounded border px-1.5 py-0.5 text-xs ${ORIGIN_STYLE[a.origin]}`}>
                  {humanize(a.origin)}
                </span>
                <span className="ml-auto tabular-nums text-xs text-neutral-500">
                  {rolling[a.id] == null ? "not scored" : `rolling ${rolling[a.id]!.toFixed(2)}`}
                </span>
              </span>
              <span className="mt-0.5 block break-words text-xs text-neutral-600 dark:text-neutral-400">
                <span className="font-medium">Why: </span>
                {a.origin_reason}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
