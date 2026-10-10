"use client";

// One metric's curve over steps. Single series, so the title names it and there is no legend.
// Non-finite values (NaN) are gaps in the line; the tooltip shows the stored text and its log line.
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Point, Series } from "./experiments";

const AXIS = { fill: "#737373", fontSize: 10 }; // neutral-500: legible on light and dark surfaces

function PointTip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  const p = active ? payload?.[0]?.payload : undefined;
  if (!p) return null;
  return (
    <div className="rounded border border-neutral-200 bg-white px-2 py-1 text-xs shadow-sm dark:border-neutral-700 dark:bg-neutral-900">
      <div className="tabular-nums">
        step {p.step}: <span className="font-semibold">{p.text}</span>
      </div>
      <div className="text-neutral-500">log line {p.log_line}</div>
    </div>
  );
}

export function MetricChart({ series, experimentId }: { series: Series; experimentId: string }) {
  const last = series.points[series.points.length - 1];
  return (
    <figure className="min-w-0 rounded-lg border border-neutral-200 p-2 dark:border-neutral-800">
      <figcaption className="mb-1 flex flex-wrap items-baseline justify-between gap-x-2 text-xs">
        <span className="break-all font-mono font-semibold">{series.name}</span>
        <a
          href={`/logs/${experimentId}#L${last.log_line}`}
          className="tabular-nums text-neutral-500 hover:underline"
          title={`Latest value, log line ${last.log_line}`}
        >
          step {last.step}: {last.text}
        </a>
      </figcaption>
      <div className="h-40 text-sky-600 dark:text-sky-400">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series.points} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#737373" strokeOpacity={0.2} vertical={false} />
            <XAxis dataKey="step" type="number" domain={["dataMin", "dataMax"]} tick={AXIS} tickLine={false} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} domain={["auto", "auto"]} />
            <Tooltip content={<PointTip />} cursor={{ stroke: "#737373", strokeDasharray: "3 3" }} />
            <Line
              dataKey="value"
              stroke="currentColor"
              strokeWidth={2}
              dot={series.points.length <= 30 ? { r: 2 } : false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
