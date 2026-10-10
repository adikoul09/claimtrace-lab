# ClaimTrace Lab: an evolving AI research environment (Elevate 1.0, PS3)

A researcher gives an arXiv paper. A self-organising team of AI agents reproduces its key result on CPU, runs "what if?" branches, and explains why the results differ. The team evolves through rewards, spawning, retiring and memory.

## Read first
`SPEC.md` (how it works) · `PLAN.md` (task cards; do only your assigned task)

## Stack
- `web/`: Next.js (App Router, TypeScript), Tailwind, shadcn/ui, @supabase/supabase-js, @xyflow/react, Recharts. Deployed on Vercel.
- `lab/`: Python 3.11. Uses supabase-py, google-genai (via `lab/llm.py` only), httpx, pymupdf, pydantic, pytest.
- Experiments: torch (CPU), torchvision, numpy, each in its own `uv` venv under `runs/`.
- Supabase: Postgres, Realtime and Storage. It is the only bus between the UI, the controller and the executors.

## Layout
- `web/`: UI.
- `lab/controller/`: meta-controller, rules, reward, memory.
- `lab/agents/`: generic runtime plus agent tools.
- `lab/executor/`: worker, sandbox, log parser.
- `supabase/migrations/`: SQL.
- `papers/<name>/`: reference scripts and results.
- `baseline/el01-auditor/`: our Round 0 prototype. **Read-only.** Wrap or port it into `lab/`; never edit it.

## Run
- UI: `cd web && npm install && npm run dev`
- Controller: `uv run python -m lab.controller`
- Worker: `uv run python -m lab.executor.worker`. Set `EXECUTOR_NAME` and `EXECUTOR_CAPS` first.
- Tests: `uv run pytest lab/tests -q`

## Conventions
- **Hackathon mode: demo first. Test only core logic. Small commits. Don't add dependencies or features not in PLAN.md without asking.**
- LLMs plan, read and write code. **Code computes every number, verdict, reward and lifecycle decision.**
- No simulated data. The only fallback is `LLM_MODE=replay` of real cached calls, always labelled "Replay" in the UI.
- Metric lines use exactly this format: `METRIC name=value step=N`. Every stored number keeps its log line.
- Every decision writes an `events` row with a `reason`.
- Secrets live only in env vars (see `.env.example`). Never print, commit or hard-code keys.
- LLM-written code runs only on executors, inside `runs/<id>/`, with a timeout and no secrets in its environment.
- Stay inside your session's folders and branch (PLAN.md header). Only session B1 changes `supabase/migrations/`.
- Commit messages: `T<ID>: <what>`.
