"use client";

// React Flow lineage graph: one node per agent; edges for refinement, spawning and merging.
import { useMemo } from "react";
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
import { layoutLineage, type LineageEdge } from "./lineage";
import { EDGE_STYLE, STATUS_STYLE } from "./styles";

const COL_W = 190;
const ROW_H = 110;

type AgentNodeData = { agent: Agent; rolling: number | null; selected: boolean };
type AgentNode = Node<AgentNodeData, "agent">;

function AgentNodeView({ data: { agent: a, rolling, selected } }: NodeProps<AgentNode>) {
  return (
    <div
      className={`w-40 rounded-md border bg-white px-2 py-1.5 text-xs shadow-sm dark:bg-neutral-900 ${
        selected ? "border-sky-500 ring-2 ring-sky-500/40" : "border-neutral-300 dark:border-neutral-700"
      } ${a.status === "active" ? "" : "opacity-70"}`}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div className="truncate font-mono font-semibold" title={a.name}>
        {a.name} <span className="font-normal text-neutral-500">v{a.version}</span>
      </div>
      <div className="mt-1 flex items-center gap-1">
        <span className={`rounded px-1 py-0.5 capitalize ${STATUS_STYLE[a.status]}`}>{a.status}</span>
        <span className="ml-auto tabular-nums text-neutral-600 dark:text-neutral-400">
          {rolling === null ? "—" : rolling.toFixed(2)}
        </span>
      </div>
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
  const nodes = useMemo<AgentNode[]>(() => {
    const pos = layoutLineage(agents, edges);
    return agents.map((a) => ({
      id: a.id,
      type: "agent",
      position: { x: pos[a.id].col * COL_W, y: pos[a.id].row * ROW_H },
      data: { agent: a, rolling: rolling[a.id] ?? null, selected: a.id === selectedId },
      draggable: false,
      connectable: false,
    }));
  }, [agents, edges, rolling, selectedId]);

  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((e) => {
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
    [edges],
  );

  return (
    <div>
      <div
        className="h-80 rounded-lg border border-neutral-200 dark:border-neutral-800"
        role="figure"
        aria-label="Agent lineage graph"
      >
        <ReactFlow
          // Re-fit when an agent appears or leaves.
          key={agents.length}
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
          <Controls showInteractive={false} />
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
    </div>
  );
}
