// /how: the lab in plain words, with one HTML/CSS diagram. Each step is labelled "live" (it has worked here at
// least once, counted from the database) or "next" (built or planned, not working here yet).
import type { Metadata } from "next";
import { Suspense } from "react";
import { supabase } from "@/lib/supabase";
import { howSteps, NO_EVIDENCE, type Evidence, type HowStep } from "./how";

export const metadata: Metadata = {
  title: "How it works",
  description: "How ClaimTrace Lab reproduces a paper's results: AI agents plan and write code, plain code checks every number.",
};

async function loadEvidence(): Promise<Evidence | null> {
  const db = supabase();
  const count = (q: PromiseLike<{ count: number | null; error: unknown }>) =>
    Promise.resolve(q).then((r) => (r.error ? Promise.reject(r.error) : (r.count ?? 0)));
  const head = { count: "exact", head: true } as const;
  const done = (caps: string[]) => db.from("tasks").select("id", head).in("capability", caps).eq("status", "done");
  const events = (types: string[]) => db.from("events").select("id", head).in("type", types);
  try {
    const [projects, readerDone, designerDone, implementerDone, runsDone, graded, rewards, evolved, lessons, emails] =
      await Promise.all([
        count(db.from("projects").select("id", head)),
        count(done(["read_paper", "extract_claims"])),
        count(done(["design_experiment"])),
        count(done(["write_code"])),
        count(done(["run"])),
        count(db.from("experiments").select("id", head).not("verdicts", "is", null)),
        count(events(["reward"])),
        count(events(["agent_refined", "agent_spawned", "agent_retired"])),
        count(db.from("lessons").select("id", head)),
        count(events(["email_received"])),
      ]);
    return { projects, readerDone, designerDone, implementerDone, runsDone, graded, rewards, evolved, lessons, emails };
  } catch {
    return null;
  }
}

export default function HowPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-2">
        <h1 className="text-lg font-semibold">How it works</h1>
        <p className="text-base font-medium">AI plans, reads and writes code. Code computes every number and verdict.</p>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          ClaimTrace Lab takes a research paper and tries to get the same results on an ordinary laptop. A team of AI
          agents does the reading, planning and coding; plain code does all the checking, so no number in the report
          comes from an AI&apos;s say-so.
        </p>
        <ul className="space-y-1 text-xs text-neutral-500">
          <li className="flex items-baseline gap-2">
            <Badge live /> <span>has worked here at least once (counted from the lab&apos;s own records)</span>
          </li>
          <li className="flex items-baseline gap-2">
            <Badge live={false} /> <span>built or planned, not working here yet</span>
          </li>
        </ul>
      </header>
      <Suspense fallback={<Diagram steps={howSteps(NO_EVIDENCE)} checking />}>
        <LiveDiagram />
      </Suspense>
    </article>
  );
}

async function LiveDiagram() {
  const evidence = await loadEvidence();
  return evidence ? <Diagram steps={howSteps(evidence)} /> : <Diagram steps={howSteps(NO_EVIDENCE)} checking failed />;
}

const MAIN = ["paper", "reader", "designer", "implementer", "worker", "grading", "report"];
const LOOP = ["scores", "evolve", "lessons"];
const INBOX = ["email", "inbox", "engine"];

function Diagram({ steps, checking, failed }: { steps: HowStep[]; checking?: boolean; failed?: boolean }) {
  const pick = (ids: string[]) => ids.map((id) => steps.find((s) => s.id === id)!);
  return (
    <figure className="space-y-3">
      {failed && <p className="text-xs text-red-600">Could not read the lab&apos;s records, so live / next is not shown.</p>}
      <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
        <section aria-label="Main path">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Main path</h2>
          <Flow steps={pick(MAIN)} checking={checking} />
        </section>
        <div className="space-y-6">
          <section aria-label="Side loop" className="rounded-lg border border-dashed border-neutral-300 p-3 dark:border-neutral-700">
            <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              <span aria-hidden>↻ </span>Side loop, alongside every step
            </h2>
            <p className="mb-2 text-xs text-neutral-500">How the team gets better from run to run.</p>
            <Flow steps={pick(LOOP)} checking={checking} compact />
            <p className="mt-2 text-xs text-neutral-500">
              <span aria-hidden>↩ </span>Lessons go back to the agents at the start of the next run.
            </p>
          </section>
          <section aria-label="Second input" className="rounded-lg border border-dashed border-neutral-300 p-3 dark:border-neutral-700">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Second input</h2>
            <Flow steps={pick(INBOX)} checking={checking} compact />
          </section>
        </div>
      </div>
      <figcaption className="sr-only">
        The main path runs from the paper to the report. Alongside it, the lab scores and improves its agents and
        saves lessons. A journal email is a second way in, through the project&apos;s Inbox.
      </figcaption>
    </figure>
  );
}

function Flow({ steps, checking, compact }: { steps: HowStep[]; checking?: boolean; compact?: boolean }) {
  return (
    <ol className="space-y-0">
      {steps.map((s, i) => (
        <li key={s.id}>
          {i > 0 && (
            <div aria-hidden className="flex justify-center py-0.5 text-neutral-400">
              ↓
            </div>
          )}
          <div
            className={`rounded-lg border p-2.5 ${
              s.live || checking
                ? "border-neutral-300 dark:border-neutral-700"
                : "border-dashed border-neutral-300 dark:border-neutral-700"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
              <span className="text-sm font-semibold">{s.title}</span>
              {!checking && <Badge live={s.live} />}
            </div>
            <p className={`mt-0.5 text-neutral-600 dark:text-neutral-400 ${compact ? "text-xs" : "text-sm"}`}>{s.text}</p>
            {s.proof && <p className="mt-0.5 text-xs text-neutral-500">{s.proof}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Badge({ live }: { live: boolean }) {
  return live ? (
    <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/40 dark:text-green-300">
      live
    </span>
  ) : (
    <span className="rounded border border-dashed border-neutral-400 px-1.5 py-0.5 text-xs font-medium text-neutral-600 dark:text-neutral-400">
      next
    </span>
  );
}
