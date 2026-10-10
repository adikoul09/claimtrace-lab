// Pure logic behind the write routes (SPEC §9, §12): the DEMO_PASSCODE cookie, approval decisions and 👍/👎.
// The routes only load the task, call these, and write what they return.

export const DEMO_COOKIE = "ct_demo";
const NOTE_MAX = 1000;

// --- passcode cookie -------------------------------------------------------------------------------

/** HMAC of a fixed label keyed by the passcode: the cookie proves the passcode without holding it. */
export async function demoToken(passcode: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(passcode), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode("claimtrace-demo-v1"));
  return Buffer.from(sig).toString("hex");
}

/** Constant-time check of the cookie. No passcode configured → always false (writes stay closed). */
export async function checkDemoToken(token: string | undefined, passcode: string | undefined): Promise<boolean> {
  if (!token || !passcode) return false;
  const want = await demoToken(passcode);
  if (token.length !== want.length) return false;
  let diff = 0;
  for (let i = 0; i < want.length; i++) diff |= token.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

// --- decisions and feedback ------------------------------------------------------------------------

type TaskRow = {
  id: string;
  project_id: string | null;
  agent_id: string | null;
  capability: string;
  status: string;
};

export type EventInsert = {
  project_id: string | null;
  agent_id: string | null;
  task_id: string;
  type: string;
  message: string;
  reason: string;
  data: Record<string, unknown>;
};

type Refusal = { ok: false; status: 400 | 409; error: string };

const refuse = (status: 400 | 409, error: string): Refusal => ({ ok: false, status, error });

function cleanNote(note: unknown): string | null | Refusal {
  if (note === undefined || note === null) return null;
  if (typeof note !== "string") return refuse(400, "note must be text");
  const t = note.trim();
  if (t.length > NOTE_MAX) return refuse(400, `note is longer than ${NOTE_MAX} characters`);
  return t || null;
}

const DECISIONS = {
  approve: { status: "queued", verb: "approved" },
  reject: { status: "rejected", verb: "rejected" },
  // The controller replans with the note (SPEC §9); this task itself stops here.
  redirect: { status: "rejected", verb: "redirected" },
} as const;
type Decision = keyof typeof DECISIONS;

export function planDecision(
  task: TaskRow,
  body: { decision?: unknown; note?: unknown },
):
  | {
      ok: true;
      update: { status: string; decision: Decision; decision_note: string | null };
      event: EventInsert;
    }
  | Refusal {
  const d = body.decision;
  if (typeof d !== "string" || !(d in DECISIONS)) return refuse(400, "decision must be approve, reject or redirect");
  const decision = d as Decision;
  const note = cleanNote(body.note);
  if (typeof note === "object" && note !== null) return note;
  if (decision === "redirect" && !note) return refuse(400, "a redirect needs a note saying what to do instead");
  if (task.status !== "awaiting_approval") return refuse(409, `task is ${task.status}, not awaiting approval`);

  const { status, verb } = DECISIONS[decision];
  return {
    ok: true,
    update: { status, decision, decision_note: note },
    event: {
      project_id: task.project_id,
      agent_id: task.agent_id,
      task_id: task.id,
      type: "decision",
      message: `${task.capability} task ${verb}`,
      reason: `${verb} by a researcher on /approvals` + (note ? `: ${note}` : ""),
      data: { decision, note, status },
    },
  };
}

const FEEDBACK = { up: "👍", down: "👎" } as const;

export function planFeedback(task: TaskRow, body: { value?: unknown }): { ok: true; event: EventInsert } | Refusal {
  const v = body.value;
  if (v !== "up" && v !== "down") return refuse(400, "value must be up or down");
  if (task.status !== "done" && task.status !== "failed")
    return refuse(409, `task is ${task.status}; feedback is for finished tasks`);
  return {
    ok: true,
    event: {
      project_id: task.project_id,
      agent_id: task.agent_id,
      task_id: task.id,
      type: "feedback",
      message: `${FEEDBACK[v]} on ${task.capability} task`,
      reason: `researcher feedback (${v}); the controller rescores the task's reward with it`,
      data: { value: v },
    },
  };
}

// --- new research and what-if (SPEC §12: POST /api/projects, POST /api/projects/[id]/whatif) ---------

const BUDGET_MIN = 1;
const BUDGET_MAX = 240;
const DEFAULT_BUDGET_CPU_MIN = 20; // SPEC §7.3 project cap
const QUESTION_MAX = 500;

/** "1503.02531", "arXiv:1503.02531v2", arxiv.org/abs|pdf URLs, or old-style "hep-th/9901001" → the id; else null. */
export function parseArxivId(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  let s = raw.trim();
  const url = s.match(/^https?:\/\/(?:www\.)?arxiv\.org\/(?:abs|pdf)\/(.+?)(?:\.pdf)?\/?$/i);
  if (url) s = url[1];
  else if (/^[a-z]+:\/\//i.test(s)) return null;
  s = s.replace(/^arxiv:/i, "");
  return /^(\d{4}\.\d{4,5}|[a-z-]+(\.[A-Z]{2})?\/\d{7})(v\d+)?$/.test(s) ? s : null;
}

export function planProject(body: { arxiv_id?: unknown; repo_url?: unknown; budget_cpu_min?: unknown }):
  | {
      ok: true;
      row: { title: string; arxiv_id: string; repo_url: string | null; budget_cpu_min: number; status: "new" };
    }
  | Refusal {
  const arxiv = parseArxivId(body.arxiv_id);
  if (!arxiv) return refuse(400, "arxiv_id must be an arXiv id like 1503.02531 or an arxiv.org link");

  let repo: string | null = null;
  if (body.repo_url !== undefined && body.repo_url !== null && body.repo_url !== "") {
    if (typeof body.repo_url !== "string" || body.repo_url.length > 300) return refuse(400, "repo_url is not a URL");
    const r = body.repo_url.trim();
    let u: URL;
    try {
      u = new URL(r);
    } catch {
      return refuse(400, "repo_url is not a URL");
    }
    if (u.protocol !== "https:") return refuse(400, "repo_url must be an https link"); // fetch_repo is https only
    repo = r;
  }

  const b = body.budget_cpu_min ?? DEFAULT_BUDGET_CPU_MIN;
  if (typeof b !== "number" || !Number.isInteger(b) || b < BUDGET_MIN || b > BUDGET_MAX)
    return refuse(400, `budget_cpu_min must be a whole number from ${BUDGET_MIN} to ${BUDGET_MAX}`);

  // status 'new': the controller's intake queues the plan task (lab/controller/loop.py).
  return { ok: true, row: { title: `arXiv ${arxiv}`, arxiv_id: arxiv, repo_url: repo, budget_cpu_min: b, status: "new" } };
}

export function planWhatIf(
  projectId: string,
  body: { question?: unknown },
):
  | {
      ok: true;
      task: {
        project_id: string;
        capability: "design_whatif";
        required_caps: string[];
        status: "queued";
        input: { question: string };
      };
    }
  | Refusal {
  const q = typeof body.question === "string" ? body.question.trim() : "";
  if (!q) return refuse(400, "ask a question");
  if (q.length > QUESTION_MAX) return refuse(400, `the question is longer than ${QUESTION_MAX} characters`);
  return {
    ok: true,
    task: {
      project_id: projectId,
      capability: "design_whatif",
      // docs/CONTRACTS.md §5b: no worker has 'controller', so nobody claims the task until the controller has
      // filled its agent, upstream and goal and switched it to ['agent'].
      required_caps: ["controller"],
      status: "queued",
      input: { question: q },
    },
  };
}
