"use client";

// One line under the header on every page while a task waits for a researcher: "1 approval waiting · Open".
// Hidden on /approvals itself and when nothing waits. tasks is on Realtime, so the count follows within a second.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export function ApprovalStrip() {
  const onApprovals = usePathname() === "/approvals";
  const [waiting, setWaiting] = useState(0);

  useEffect(() => {
    const db = supabase();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () =>
      db
        .from("tasks")
        .select("id", { count: "exact", head: true })
        .eq("status", "awaiting_approval")
        .then(({ count, error }) => {
          if (!error) setWaiting(count ?? 0);
        });
    const channel = db
      .channel("approval-strip")
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks" }, () => {
        clearTimeout(timer);
        timer = setTimeout(load, 300);
      })
      .subscribe();
    const first = setTimeout(load, 0);
    return () => {
      clearTimeout(first);
      clearTimeout(timer);
      db.removeChannel(channel);
    };
  }, []);

  if (onApprovals || waiting === 0) return null;
  return (
    <div className="mx-auto max-w-5xl px-4">
      <Link
        key={waiting} // pops in again when the count changes
        href="/approvals"
        className="ct-pop mb-2 flex min-h-11 items-center gap-2 rounded-md border border-amber-400 bg-amber-50 px-3 text-sm text-amber-900 hover:underline dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
      >
        <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-amber-500" aria-hidden />
        <span className="min-w-0 truncate">
          {waiting} approval{waiting === 1 ? "" : "s"} waiting · <span className="font-semibold">Open</span>
        </span>
      </Link>
    </div>
  );
}
