import Link from "next/link";
import { Suspense } from "react";
import { supabase } from "@/lib/supabase";
import type { Experiment } from "@/lib/types";
import { LogView } from "./log-view";

export default function LogPage({ params }: PageProps<"/logs/[exp]">) {
  return (
    <Suspense fallback={<p className="text-sm text-neutral-500">Loading…</p>}>
      <LogPageView params={params} />
    </Suspense>
  );
}

async function LogPageView({ params }: { params: PageProps<"/logs/[exp]">["params"] }) {
  const { exp } = await params;
  const { data: e } = await supabase()
    .from("experiments")
    .select("id,project_id,label,status,executor")
    .eq("id", exp)
    .maybeSingle<Pick<Experiment, "id" | "project_id" | "label" | "status" | "executor">>();

  return (
    <>
      <div className="mb-4 min-w-0">
        {e && (
          <Link href={`/p/${e.project_id}?tab=experiments`} className="text-xs text-neutral-500 hover:underline">
            ← Experiments
          </Link>
        )}
        <h1 className="break-words text-lg font-semibold">Log: {e?.label ?? "unknown experiment"}</h1>
        <p className="break-all font-mono text-xs text-neutral-500">
          {e ? `${e.status}${e.executor ? ` on ${e.executor}` : ""} · ` : ""}
          {exp}
        </p>
      </div>
      <LogView exp={exp} />
    </>
  );
}
