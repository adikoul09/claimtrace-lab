# ClaimTrace Lab

**Checks whether a paper's claims hold up by re-running them, with an AI agent team that improves itself.**

Live demo: **https://claimtrace-lab.vercel.app**
Built in 24 hours at Elevate 1.0 (DJSCE), Round 1, Problem Statement 3, by Team Axiom 3.

> AI plans, reads and writes code. **Plain code computes every number, verdict and reward.** No number in a report comes from an AI's say-so.

---

## What it does

1. **Paper in.** Give it an arXiv ID.
2. **Reader agent** lists every claim the paper makes, with the exact quote and page.
3. **Triage (code)** marks each claim as runnable on a laptop or not, with a reason (e.g. *no public data*, *dataset too big*).
4. **Designer agent** plans a small, budgeted version of the experiment and declares the match margin **before** the run.
5. **Implementer + Env builder agents** write the code and build the environment.
6. **Laptop worker** runs a smoke test, then the full run, after human approval. Every printed number is saved with its log line.
7. **Analyst (code)** grades each claim as Reproduced, Partially reproduced or Not reproduced against the pre-declared margin.
8. **Report** puts each claim next to our number, and each number links to the log line that printed it.

### The self-improving team
- Agents are **database rows** (role, prompt, tools, budget), not hard-coded classes.
- A **meta-controller** scores every agent after each task (rolling reward), then **refines** agents that keep failing, **spawns** a new specialist when a role fails repeatedly (with the reason recorded), and **retires** superseded versions.
- **Lessons**: what worked or failed is saved as a lesson. Lessons are kept only with evidence, ranked by relevance, and capped at 5 per plan. Paper-specific lessons are skipped on other papers, and the reason is shown.

### Other features
- **"What if?"**: ask in plain English (e.g. *"What if the temperature changes?"*). The Designer proposes 3–4 one-change branches; each gets a smoke run, weak ones are pruned, and the strongest waits for your approval.
- **Approvals queue** (`/approvals`): full runs need a human yes, and phones work too.
- **Why it differs**: a settings diff of paper vs ours, with each setting labelled *difference*, *paper omission* or *scale (budget)*.
- **Journal inbox**: reviewer emails (via n8n) land in a per-project Inbox tab with an unread badge and a banner.
- **Live tab**: realtime event stream, with a "Key moments" filter for spawns, refinements, lessons and approvals.

---

## Results (live run, arXiv 1503.02531, *Distilling the Knowledge in a Neural Network*)

- **73 claims extracted:** 18 runnable on a laptop, 55 not (36 no public data, 19 dataset too big).
- **Run end to end by the agents**, including phone approval of the full run.
- **Verdicts (code-graded, CPU scale, compact MLP):** teacher and distilled nets *partially reproduced*; the hard-target baseline *not reproduced*. The paper's ordering (teacher better than student) held in every seed.
- **Honest headline:** across 3 seeds and a temperature sweep, the paper's main claim (distilled beats hard-target) is **not established at CPU scale**. The difference is within seed noise.
- A labelled **reference run** with a larger network is closer to the paper (80 / 143 / 96 test errors vs the paper's 67 / 146 / 74).

---

## Architecture

```
            ┌──────────────────────── Next.js on Vercel (web/) ───────────────────────┐
 Browser ──▶│ Projects · Report · Experiments · Team · Inbox · Live · Notes · /how    │
            │ Server routes (all writes, passcode-protected)                          │
            └───────────────┬─────────────────────────────────────────────────────────┘
                            │  read: anon key, SELECT only (RLS on)
                            ▼
                ┌─────────────────────────────┐
                │ Supabase                    │◀── n8n (journal email → /api/inbox)
                │ Postgres · Realtime ·       │
                │ Storage · tasks queue       │
                └──────────────┬──────────────┘
                               │ claim_task()
              ┌────────────────┴─────────────────┐
              ▼                                  ▼
   lab/controller (meta-controller)      lab/executor (laptop worker)
   plans, assigns, scores, refines,      smoke + full runs, logs every
   spawns, retires; token guard          number with its log line
              │
              ▼
   lab/agents  (Reader, Designer, Implementer, Env builder, Runner, Analyst, Reporter)
   ── LLM via an OpenAI-compatible gateway
```

**Stack:** Next.js · Tailwind · React Flow · Recharts · Supabase (Postgres, Realtime, Storage) · Python 3.12 · n8n · Vercel

---

## Repository layout

```
web/            Next.js app (UI + server routes)
  app/          pages: home, /p/[id] (project tabs), /approvals, /how, /logs
  components/   report, team, inbox, live, experiments
lab/            Python engine
  controller/   meta-controller: planning, rewards, refine/spawn/retire, lessons, token guard
  agents/       agent roles and tools
  executor/     laptop worker that claims and runs tasks
```

---

## Running it locally

> You need your own Supabase project and an OpenAI-compatible LLM endpoint. **Never commit `.env` files.**

### 1. Web app
```bash
cd web
cp .env.example .env.local      # fill in your Supabase URL/keys and demo passcode
npm install
npm run dev                     # http://localhost:3000
```

### 2. Engine (Python 3.12)
```bash
cd <repo root>
python -m venv .venv
# Windows: .\.venv\Scripts\activate   ·   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt  # or your project's dependency file
cp .env.example .env             # Supabase service key + LLM_API_KEY (never commit)

python -m lab.controller                         # meta-controller
EXECUTOR_CAPS=smoke,train python -m lab.executor.worker   # laptop worker
```
Windows PowerShell: `$env:EXECUTOR_CAPS='smoke,train'` then `python -m lab.executor.worker`.

Resume a blocked project at its failed step:
```bash
python -m lab.controller --unblock <project-id>
```

---

## Security

- The browser uses the **anon key with SELECT only** on public tables; **Row Level Security is on** for every table.
- **All writes go through server routes** that require a demo passcode.
- Security headers (CSP, X-Frame-Options, etc.) are set in `web/next.config.ts`.
- Secrets live only in environment variables, never in the repo.

---

## Honest limitations

- Only **one paper** has been run end to end so far. Any-paper triage works, but no second paper has been demonstrated.
- **3 claims graded** live (out of 18 runnable). Seeds are shown as separate rows; there is no averaging yet.
- The Reporter agent wrote no narrative text on the live run. Verdicts and "why" lines are code-made and unaffected.
- Extra seed and temperature runs were launched by an operator (labelled "operator follow-up" on the site), not by the agents.
- "Send to engine" for journal emails is planned, not built.
- Agent **merging** is designed but has not happened in a real run.

## Roadmap
- Average seeds per claim and show the spread
- A second and third paper end to end
- Link each verdict to the settings that explain it
- "Send to engine" for reviewer emails
- Lesson expiry (drop lessons that never help)

---

## Team
Team Axiom 3, Elevate 1.0 (DJSCE), October 2026.
