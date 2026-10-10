"use client";

// Header live-data check (SPEC §10): when did the newest event and metric land?
// Global on purpose: it proves the whole bus is alive, on every page.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { formatAgo, latestTs } from "@/lib/live";
import { ExecutorDots } from "@/components/live/executor-dots";
import { InboxToast } from "@/components/inbox/inbox-toast";
import { InboxCard } from "@/components/live/inbox-card";
import { projectIdFromPath } from "@/components/live/inbox";
import { ReplayBadge } from "@/components/live/replay-badge";
import { TokenMeter } from "@/components/live/token-meter";

async function newestTs(table: "events" | "metrics"): Promise<string | null> {
  const { data } = await supabase()
    .from(table)
    .select("ts")
    .order("ts", { ascending: false })
    .limit(1);
  return data?.[0]?.ts ?? null;
}

function Stamp({ label, ts, now }: { label: string; ts: string | null; now: number | null }) {
  return (
    <span className="whitespace-nowrap">
      <span className="text-neutral-500">{label}: </span>
      {ts ? (
        <time dateTime={ts} title={new Date(ts).toISOString()} className="tabular-nums">
          {new Date(ts).toLocaleTimeString()}
          {now !== null && ` (${formatAgo(ts, now)})`}
        </time>
      ) : (
        <span>never</span>
      )}
    </span>
  );
}

// On a project page (any tab), the newest journal email for that project, and a toast when a new one arrives. The pathname is request data, so the
// caller wraps this in <Suspense> (cacheComponents).
function ProjectInbox() {
  const projectId = projectIdFromPath(usePathname());
  if (!projectId) return null;
  return (
    <div className="mx-auto max-w-5xl px-4">
      <InboxCard key={projectId} projectId={projectId} />
      <InboxToast key={`toast-${projectId}`} projectId={projectId} />
    </div>
  );
}

export function LiveHeader() {
  const [eventTs, setEventTs] = useState<string | null>(null);
  const [metricTs, setMetricTs] = useState<string | null>(null);
  // Clock starts after mount: reading the time during prerender is not allowed.
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    const db = supabase();
    const tickNow = () => setNow(Date.now());
    const first = setTimeout(tickNow, 0);
    newestTs("events").then((ts) => setEventTs((cur) => latestTs(cur, ts)));
    newestTs("metrics").then((ts) => setMetricTs((cur) => latestTs(cur, ts)));
    const channel = db
      .channel("header-latest")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "events" }, (p) =>
        setEventTs((cur) => latestTs(cur, (p.new as { ts: string }).ts)),
      )
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "metrics" }, (p) =>
        setMetricTs((cur) => latestTs(cur, (p.new as { ts: string }).ts)),
      )
      .subscribe();
    const tick = setInterval(tickNow, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(tick);
      db.removeChannel(channel);
    };
  }, []);

  return (
    <header className="border-b border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-xs">
        <span className="mr-auto flex items-center gap-2">
          <Link href="/" className="text-sm font-semibold">
            ClaimTrace Lab
          </Link>
          <ReplayBadge />
        </span>
        <Link href="/approvals" className="text-neutral-600 hover:underline dark:text-neutral-400">
          Approvals
        </Link>
        <ExecutorDots now={now} />
        <TokenMeter />
        <Stamp label="latest event" ts={eventTs} now={now} />
        <Stamp label="latest metric" ts={metricTs} now={now} />
      </div>
      <Suspense fallback={null}>
        <ProjectInbox />
      </Suspense>
    </header>
  );
}
