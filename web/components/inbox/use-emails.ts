"use client";

// The project's email_received events (newest first), kept current over Realtime.
import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Event } from "@/lib/types";
import { mergeEmails } from "./inbox";

export function useProjectEmails(projectId: string, channel: string, onNew?: (e: Event) => void) {
  const [emails, setEmails] = useState<Event[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onNewRef = useRef(onNew);
  useEffect(() => {
    onNewRef.current = onNew;
  });

  useEffect(() => {
    const db = supabase();
    // Subscribe before the fetch so an email landing in between is not missed; mergeEmails dedupes.
    const ch = db
      .channel(`${channel}-${projectId}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "events", filter: `project_id=eq.${projectId}` },
        (p) => {
          const e = p.new as Event;
          if (e.type !== "email_received") return;
          setEmails((cur) => mergeEmails(cur, [e]));
          onNewRef.current?.(e);
        },
      )
      .subscribe();

    db.from("events")
      .select("*")
      .eq("project_id", projectId)
      .eq("type", "email_received")
      .order("ts", { ascending: false })
      .limit(100)
      .then(({ data, error }) => {
        setLoaded(true);
        if (error) setError(error.message);
        else setEmails((cur) => mergeEmails(cur, (data ?? []) as Event[]));
      });

    return () => {
      db.removeChannel(ch);
    };
  }, [projectId, channel]);

  return { emails, loaded, error };
}
