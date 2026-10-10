# PLAN: ClaimTrace Lab (task cards)

Work on one task at a time, in order. Each session does only the tasks marked with its owner code.

**Sessions**

| Code | Who | Folders | Branch |
|---|---|---|---|
| B | Laptop B, before 1:30 PM | — | `main`, or a feature branch it merges itself |
| A | Laptop A, before 1:30 PM | — | same as B |
| A1 | Laptop A, from 1:30 PM | `web/` team, live and approvals | `feat/web-team-live` |
| A2 | Laptop A, from 1:30 PM | `web/` experiments, report, notes and logs | `feat/web-exp-report` |
| B1 | Laptop B, from 1:30 PM | `lab/controller`, `lab/db.py`, `lab/schemas.py`, `lab/llm.py`, `supabase/` | `feat/controller` |
| B2 | Laptop B, from 1:30 PM | `lab/agents`, `lab/executor`, `papers/` | `feat/agents-exec` |

**Default paste line** (when a card doesn't give its own):
`/agent-skills:build Implement TASK <ID> from PLAN.md. Touch only <files>. Stop when the acceptance criteria pass, commit, and report.`

---

## Phase 0: paper lock and running skeleton (deadline 12:00)

```
TASK T00 — Import the Round 0 baseline (manual, Laptop A, no Claude needed)
Owner: A (Laptop A)   Est: 15   Depends on: repo created
Goal: The Round 0 code is in the new repo as read-only baseline/el01-auditor/, with no names and no heavy workspace files.
Files/area: baseline/   Branch: main
Steps (Mac Terminal, inside your claimtrace-lab clone):
  mkdir -p baseline
  rsync -a --exclude workspace --exclude .git --exclude .venv --exclude __pycache__ \
        --exclude MASTER_PROMPT.md --exclude CLAUDE.md --exclude '*.bundle' \
        ~/el01-auditor/ baseline/el01-auditor/
  (names check done, see team notes)
  du -sh baseline/   # should be well under 100 MB; drop anything bigger than 50 MB
  git add baseline && git commit -m "T00: import Round 0 baseline (read-only)" && git push
Acceptance criteria:
  - baseline/el01-auditor/ is pushed; the grep shows no names (remove or edit any file that has them)
  - no nested CLAUDE.md or MASTER_PROMPT.md inside baseline/ (they would confuse the coding sessions)
Verify: Laptop B pulls and can see baseline/el01-auditor/el01/
```

```
TASK B0 — Distillation reference run (paper-lock smoke test)
Owner: B   Est: 30   Depends on: none
Goal: Know whether the paper's key result appears on CPU at reduced scale, and how long it takes.
Files/area: papers/distillation/reference.py, papers/distillation/results.json   Branch: main
Acceptance criteria:
  - `python papers/distillation/reference.py --quick` finishes in ≤15 min on CPU
  - prints test errors (/10,000) for teacher, student-hard, student-distilled (T=20), each next to the paper's value, plus wall-clock per model
  - prints each metric as `METRIC name=value step=N` and writes results.json
Verify: run it with --quick; open results.json
```

```
TASK T01 — Database schema
Owner: B   Est: 30   Depends on: none
Goal: All tables from SPEC §11 exist, with read-only RLS for anon, Realtime on, and the claim_task() RPC.
Files/area: supabase/migrations/001_init.sql   Branch: main
Acceptance criteria:
  - the SQL runs cleanly in the Supabase SQL editor (Laptop A pastes it)
  - claim_task(executor_name text, caps text[]) returns at most one queued task whose required_caps ⊆ caps, using FOR UPDATE SKIP LOCKED, and sets status='running'
  - Realtime publication includes events, metrics, tasks, agents and experiments
  - the seed roster from SPEC §2.4 is inserted (7 agents, origin='seed')
Verify: Laptop A runs the SQL, then `select * from agents;` shows 7 rows
```

```
TASK T02 — Worker skeleton with live metrics
Owner: B   Est: 45   Depends on: T01, B0
Goal: A worker process claims a task, runs a script and streams METRIC lines into Supabase as they happen.
Files/area: lab/db.py, lab/executor/worker.py, lab/executor/logparse.py, lab/tests/test_logparse.py, pyproject.toml   Branch: main
Reuse: baseline/el01-auditor runner and parsers (read them first, wrap or port them; don't edit baseline/). Use a Windows-safe process start.
Acceptance criteria:
  - `uv run python -m lab.executor.worker` sends a heartbeat to executors every 10 s
  - a task with capability='run' and input {cmd, cwd} is claimed, run with a timeout and a stripped environment, and every stdout line is saved to Storage `logs/<experiment_id>.log`
  - every METRIC line becomes a metrics row with its log_line; an events row is written when the task starts and when it ends
  - pytest covers logparse
Verify: insert a test task that runs reference.py --quick; watch the metrics rows arrive in Supabase
```

```
TASK T03 — Web skeleton, deployed
Owner: A   Est: 45   Depends on: T01
Goal: The deployed Vercel URL shows a project page whose Live tab streams events over Realtime.
Files/area: web/ (new Next.js app), web/lib/supabase.ts, web/lib/types.ts, web/app/p/[id]/page.tsx   Branch: main
Acceptance criteria:
  - `npm run build` passes; deployed on Vercel from main (root directory web/)
  - /p/[id]?tab=live lists events newest-first and updates without a refresh when a row is inserted
  - the header shows "latest event" and "latest metric" timestamps
  - the layout works at 375 px wide
Verify: insert an events row in Supabase; it appears on the deployed page within 2 s
```

**12:00 CHECKPOINT:** a worker run of `reference.py` streams live metric lines to the deployed URL.

---

## Phase 1: before the 1:30 PM reset

```
TASK T04 — LLM wrapper and generic agent runtime
Owner: B   Est: 60   Depends on: T02
Goal: Any agent row can run: its role_prompt plus the fixed tools (SPEC §2.2) in a loop, within its budget.
Reuse: port the baseline el01 LLM backend (replay cache, usage logging) into lab/llm.py, replacing `claude -p` with LLM_API_KEY providers.
Files/area: lab/llm.py, lab/agents/runtime.py, lab/agents/tools.py, lab/tests/test_runtime.py   Branch: main
Acceptance criteria:
  - lab/llm.py: LLM_PROVIDER switch (gemini first); logs every call to llm_calls (tokens, model, mode); LLM_MODE=replay returns cached real responses by cache_key
  - the runtime stops at max_steps, max_tokens or max_cpu_s and emits events with reasons
  - tools are limited to the fixed set; file tools cannot leave runs/<id>/
Verify: a test agent with the read_file tool summarises a file; events and llm_calls rows appear
```

```
TASK T05 — Paper intake and Reader
Owner: B   Est: 45   Depends on: T04
Goal: Given arXiv 1503.02531, the Reader stores the claims and settings (SPEC §7.1).
Reuse: baseline claim-card schema and settings schema v2 (extraction prompts and schema files).
Files/area: lab/agents/paper.py (fetch_paper), lab/tests/test_claims.py   Branch: main
Acceptance criteria:
  - the PDF is fetched from arXiv and its text stored; papers.claims includes the teacher, small-net and distilled test errors, each with a quote and page
  - papers.settings covers architecture, hidden units, temperature, regularisation and epochs where stated
  - a code check confirms each claim's value appears in its quote
Verify: inspect the papers row; compare it with results.json from B0
```

```
TASK T06 — Team view (static) and header
Owner: A   Est: 45   Depends on: T03
Goal: The Team tab shows agent cards from the agents table (capabilities, version, status, reward placeholder).
Files/area: web/app/p/[id] (team tab), web/components/team/*   Branch: main
Acceptance criteria:
  - lists all agents with status badges (active, retired, merged) and origin (seed, spawned, refined)
  - updates live when an agents row changes
Verify: change an agent's status in Supabase; the card updates without a refresh
```

---

## Phase 2: 1:30 PM to 6:00 PM (four sessions)

| ID | Owner | Est | Depends | Goal | Acceptance (summary) |
|---|---|---|---|---|---|
| T07 | B1 | 75 | T04 | **Controller v1**: intake → plan (LLM, steps by capability) → tasks → assign the best agent → route to an executor by caps | A new project creates a plan event with a reason, plus queued tasks with capabilities; tasks reach the right executor |
| T08 | B1 | 45 | T07 | **Reward** (SPEC §5) per finished task, plus the rolling mean per agent | pytest for the formula; rewards rows appear; constants live in one file |
| T09 | B1 | 45 | T07 | **Spawn** on a gap or repeated failure (SPEC §4.3); the spawned Debugger gets the baseline repair-agent tools | When no `debug` agent exists and a run fails, a Debugger row is created with origin_reason, then assigned |
| T10 | B2 | 75 (baseline env builder) | T05 | **Autonomous reproduction**: Implementer writes train.py from claims and settings → EnvBuilder (uv) → smoke → budgeted full run (SPEC §7.2–7.3) | A Distillation run completes on laptop-a with no hand steps; METRIC lines stream; the budget reason is stored |
| T11 | B2 | 45 (baseline grader) | T10 | **Analyst**: verdicts by code (SPEC §7.5), reusing the baseline grader, plus an explanation limited to table numbers | experiments.verdicts filled; the number check rejects explanation text with unknown numbers |
| T12 | A1 | 75 | T06 | **Team lineage graph** (React Flow) plus the scoreboard | Edges for parent, merged_into and spawned_by; clicking a card shows its reward breakdown |
| T13 | A1 | 20 | T03 | **Executor status dots** in the header | Dots go grey when the heartbeat is over 30 s old |
| T14 | A2 | 75 | T03 | **Experiments tree plus metric curves** | Tree from experiments.parent_id; live Recharts curve per experiment; budget reason shown |
| T15 | A2 | 60 | T14 | **Report tab**: claims vs ours, verdicts, links to log lines; /logs/[exp] viewer | Every number links to `#L<n>`, and the viewer highlights that line |

**6:00 PM CHECKPOINT:** arXiv ID → plan → code → run → graded report on the deployed URL, with no hand steps.

---

## Phase 3: 6:00 PM to 11:59 PM

| ID | Owner | Est | Depends | Goal | Acceptance (summary) |
|---|---|---|---|---|---|
| T16 | B1 | 60 | T08 | **Lifecycle**: refine, retire, merge (SPEC §4) | pytest for each rule; events carry the numbers that triggered them |
| T17 | B1 | 60 | T16 | **Memory**: write lessons (with evidence), retrieve by tags, `lesson_applied` events (SPEC §6); import the MatchDG F1–F9 lessons from baseline (labelled) | Run 2 shows at least 1 lesson applied; retries, time and tokens are compared |
| T18 | B2 | 90 | T11 | **What-if fan-out**: 3–4 one-change branches, smoke, rank, prune or extend behind approval (SPEC §7.4) | The one-key check passes; a pruned branch has its reason; the extend task waits in awaiting_approval |
| T19 | B2 | 60 | T18 | **Why it differs**: settings-diff table plus branch effects in the report data | Rows labelled scale/omission/difference/same; tested rows show the effect |
| T20 | A1 | 60 | T12 | **/approvals (mobile)** plus 👍/👎 on tasks; `DEMO_PASSCODE` login | Approve on a phone → the task runs; feedback changes the reward |
| T21 | A1 | 30 | T20 | **New-research form** plus what-if input | Creates a project or what-if via the API routes |
| T22 | A2 | 60 | T15 | **Report "why" section**, memory effect, Markdown export, Notes tab | The exported .md matches the screen |
| T23 | A2 | 45 | T22 | **Mobile pass** on all views | Member3's phone checklist passes |

**11:59 PM CHECKPOINT:** the full demo flow (Blueprint §3) on the deployed URL. Live-data check: the latest-record timestamps are under 60 s old during a run.

---

## Phase 4: 12:00 AM to 4:00 AM (freeze at 4:00)

| ID | Owner | Est | Goal |
|---|---|---|---|
| T24 | B1 | 45 | Controller deployed on Voroa, plus the `voroa-1` executor (smoke caps) |
| T25 | B2 | 45 | Run 2 end to end for the memory proof; capture the numbers |
| T26 | A1 | 45 | Replay mode in the UI (labelled), built from real runs, for the demo fallback |
| T27 | B1 | 20 | n8n webhook call on awaiting_approval (uses Member3's URL) |
| T28 | B2 | 90 | STRETCH: a second approach or paper (Grinsztajn or TabPFN), only if all checkpoints passed |
| T29 | A2 | 60 | Polish: empty states, loading, error toasts |
| T30 | B2 + A2 | 45 | **MatchDG (Round 0) precomputed project**: load the baseline golden files and report into the tables as a labelled, precomputed project (R10 comparison) |

**After 4:00 AM:** bug fixes only. 5:30 AM: `/agent-skills:review`, ShipReady scan, `/agent-skills:ship` once.
