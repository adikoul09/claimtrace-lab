"use client";

// Inbox card (T31): the newest journal email n8n forwarded for this project (POST /api/inbox), over Realtime.
// Hidden until there is one. Email text is shown as plain text only.
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Event } from "@/lib/types";
import { inboxEmail, type InboxEmail } from "./inbox";

export function InboxCard({ projectId }: { projectId: string }) {
  const [latest, setLatest] = useState<{ ts: string; email: InboxEmail } | null>(null);

  useEffect(() => {
    const db = supabase();
    const keep = (e: Event) => {
      const email = inboxEmail(e);
      if (email) setLatest((cur) => (cur && Date.parse(cur.ts) >= Date.parse(e.ts) ? cur : { ts: e.ts, email }));
    };

    // Subscribe before the fetch so an email landing in between is not missed; keep() keeps the newest.
    const channel = db
      .channel(`inbox-${projectId}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events", filter: `project_id=eq.${projectId}` },
        (p) => keep(p.new as Event),
      )
      .subscribe();

    db.from("events")
      .select("*")
      .eq("project_id", projectId)
      .eq("type", "email_received")
      .order("ts", { ascending: false })
      .limit(1)
      .then(({ data }) => {
        if (data?.[0]) keep(data[0] as Event);
      });

    return () => {
      db.removeChannel(channel);
    };
  }, [projectId]);

  if (!latest) return null;
  const { from, subject, receivedAt, points } = latest.email;

  return (
    <section
      aria-labelledby="inbox-heading"
      className="mb-2 rounded-md border border-sky-300 bg-sky-50 p-3 text-sm dark:border-sky-800 dark:bg-sky-950/40"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-neutral-600 dark:text-neutral-400">
        <h2 id="inbox-heading" className="font-semibold text-sky-800 dark:text-sky-300">
          Journal email
        </h2>
        <span className="min-w-0 break-all">from {from}</span>
        <time dateTime={receivedAt} title={new Date(receivedAt).toISOString()} className="tabular-nums">
          {new Date(receivedAt).toLocaleString()}
        </time>
      </div>
      <p className="mt-1 break-words font-medium">{subject}</p>
      {points.length > 0 ? (
        <ol className="mt-2 list-decimal space-y-0.5 pl-5">
          {points.map((p, i) => (
            <li key={i} className="break-words">
              {p}
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-1 text-xs text-neutral-500">No bullet or numbered points found in the email.</p>
      )}
      <button
        type="button"
        disabled
        title="Coming next: turn these points into what-if questions for the team"
        className="mt-3 w-full rounded border border-neutral-300 px-3 py-1.5 text-xs text-neutral-500 sm:w-auto dark:border-neutral-700"
      >
        Send to engine (next)
      </button>
    </section>
  );
}
