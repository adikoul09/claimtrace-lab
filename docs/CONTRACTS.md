# Contracts between the controller, the executors and the UI

Supabase is the only bus. This file says who writes which field, in what shape. If code and this file disagree, fix
one of them in the same commit. Owner: B1 (controller); changes need a heads-up to B2 (agents, executor) and A1/A2 (web).

## 1. Routing: `tasks.required_caps` and executor caps

`claim_task(executor_name, caps)` hands a worker the oldest queued task whose `required_caps ⊆ caps`. The controller
always sets `required_caps`; an empty list would let any worker take the task.

| Task | `required_caps` | Who runs it |
|---|---|---|
| `plan` | `['controller']` | the controller itself (no worker has this cap) |
| agent steps: `read_paper`, `extract_claims`, `extract_settings`, `design_experiment`, `budget`, `write_code`, `setup_env`, `debug`, `compare`, `explain_diff`, `design_whatif`, `write_report`, `write_notes` | `['agent']` | a worker running the agent runtime on the task's agent |
| `run`, `input.scale = 'smoke'` | `['smoke']` | a worker running `input.cmd` |
| `run`, `input.scale = 'full'` | `['train']` | a worker running `input.cmd` (heavy machine) |

**Host pinning.** Every worker also advertises `host:<EXECUTOR_NAME>` in its caps (e.g. `agent,smoke,train,host:laptop-a`).
Once a project's first `run` task has been claimed, the controller adds `host:<that executor>` to the `required_caps`
of every later task of the project, so the run folder, the venv and the data stay on one machine.

**Liveness.** Workers upsert `executors` (`name`, `caps`, `busy`, `last_heartbeat`) every 10 s. A `running` task whose
executor's heartbeat is older than 60 s goes back to `queued` (executor cleared) with a `task_requeued` event and reason.
The controller heartbeats as executor `controller` (caps `['controller']`).

## 2. Plan order (reproduction goal)

The controller's plan for a reproduction is these capabilities in this order (code rejects any other order and gives
the planner one more try with the reason; the LLM picks titles, instructions, acceptance checks, budgets, reasons and
the agent per step; code uses that agent if it is active and has the capability, else the highest rolling reward):

`read_paper` (or `extract_claims`) → `design_experiment` → `write_code` → `setup_env` → `run` (smoke) → `budget` →
`run` (full) → `compare` (or `explain_diff`) → `write_report`

A step's task exists only once the step before it is `done` (there is no "waiting" status).

## 3. `tasks.input` (written by the controller)

Every step:

| Field | Meaning |
|---|---|
| `goal` | what the agent must do (self-contained; may end with the previous attempt's error or a redirect note) |
| `title` | short label for the UI |
| `step`, `of`, `attempt` | 0-based step index, number of steps, 1-based attempt |
| `plan_task_id` | the `plan` task (also `tasks.parent_task_id`) |
| `workdir` | `runs/<project_id>` (relative to the repo root, on the executor) |
| `budget` | `{max_cpu_s, max_tokens}`: CPU from the plan (clipped to the project cap), tokens from the agent's row |
| `upstream` | `{capability: task_id}`: the latest `done` task of each earlier step (a later step of the same capability wins, so at `compare` `upstream['run']` is the full run), plus the latest `done` `debug` task; read their `output` for what you need |
| `redirect_note` | present when a researcher redirected this step (§6) |

`run` steps also carry what the worker needs, filled by the controller from upstream outputs:

| Field | Source |
|---|---|
| `scale` | `smoke` or `full` |
| `cmd` | smoke: `python train.py --data-dir ../../data --epochs 1 --subset 5000 --seed 0`; full: `--epochs`, `--subset`, `--seed` from the `budget` output |
| `cwd` | `runs/<project_id>` |
| `files` | `{"train.py": ...}` from the latest `write_code` output, or a later `debug` output that changed it |
| `requirements` | from the latest `setup_env` output, or a later `debug` output that changed it |
| `experiment_id` | an `experiments` row the controller creates for the run: `config` = the `design_experiment` output's `config` (with `claim_map`) plus `scale`, `cmd` and, for full runs, `budget`; `margin` from that output; `budget_reason` from the `budget` output |
| `timeout_s`, `network` | at least 300 s; `network: true` for the dataset download |

`debug` tasks: `failed_task_id`, `for_step`, `error_signature`, `error_log_line`, `log_path`, `experiment_id`, `cmd`,
`files` and `requirements` (what the failed run ran), plus the common fields. `tasks.parent_task_id` is the failed task.

If an earlier step's output lacks what a run needs (`files['train.py']`, `requirements`, the budget's `epochs`/`subset`),
the controller does not invent it: the project goes to `blocked` with a `project_blocked` event naming what is missing.

## 4. `tasks.output` (written by whoever ran the task)

All agent tasks:

| Field | Meaning |
|---|---|
| `agent_status` | `finished` / `stopped` / `failed` (the runtime's RunResult.status) |
| `outcome` | `passed` / `partial` / `failed`: the acceptance check, **run by code** (wins over everything else in the reward) |
| `answer` | the agent's final answer (text) |
| `error` | why it failed, if it did |

Per capability (extra fields the next steps read):

| Capability | Output fields |
|---|---|
| `read_paper`, `extract_*` | (writes `papers.claims`, `papers.settings`) `claims_valid`, `settings_valid` counts |
| `design_experiment` | `design` (models and `claim_map` {model name → claim id}), `config`, `margin`, `margin_reason` |
| `write_code` | `files: {"train.py": "<code>"}` |
| `setup_env` | `requirements: "<pinned requirements.txt>"` |
| `budget` | `epochs`, `subset`, `seeds` (list), `reason` (e.g. "3 seeds × 5 epochs ≈ 9 min, from smoke 1.8 min/epoch") |
| `run` (worker) | `experiment_id`, `log_path`, `log_lines`, `exit_code`, `wall_s`, `cpu_s`, `metrics` (count), `error_signature`, `error_log_line` |
| `debug` | `repair_label`: `REPAIR(env)` / `REPAIR(code)` / `HYPOTHESIS`; `files` and/or `requirements` when it changed them |
| `compare`, `explain_diff` | `experiment_id` (its `verdicts` are written) |
| `write_report`, `write_notes` | `markdown` |

Tokens come from `llm_calls` rows with the task's id; `tasks.cpu_seconds` is set by the worker.

## 5. `experiments.verdicts`

A list, one item per claim (written by the Analyst; the UI computes nothing):

```json
[{"claim_id": "c3", "verdict": "partially reproduced", "ours": 96, "paper": 74, "margin": 10,
  "note": "distilled < hard-label still holds", "log_line": 812}]
```

- `verdict` ∈ `reproduced` · `partially reproduced` · `not reproduced` · `not runnable` (lower case). With fewer than
  3 seeds, `note` starts with `(1 seed)` (or the seed count).
- `ours`, `paper`, `margin`: numbers (`ours` is `null` when not runnable); `log_line`: the line of the METRIC that gave
  `ours` in the experiment's log.
- Relative claims ("method beats baseline") are items too: `claim_id` = `<method id>_vs_<baseline id>`, and `ours` /
  `paper` are the gaps.
- Grading detail (rules, relations, the explanation and its number check) goes in the `graded` event's `data`.

`metrics.value` may be `NULL` (migration 003): a `METRIC` line whose value is NaN or inf is stored as a row with
`value = NULL` and its `log_line`, plus a `divergence_detected` event.

## 5b. What-if fan-out (SPEC §7.4; logic B2, sequencing B1)

The `train.py` contract (code-checked at `write_code`) includes `--set KEY=VALUE` (repeatable, JSON value, overrides
one CONFIG key) and a printed `CONFIG {json}` line. A branch is the same `train.py` plus one `--set`.

1. The web queues a `design_whatif` task with `input.question` and `required_caps ['controller']` (no worker has
   that cap, so nobody claims it early). Once the reproduction has a finished full run, the controller assigns the
   agent and fills `upstream` (`upstream['run']` = that full run), `workdir`, `goal` and `prepared: true`, then sets
   `required_caps ['agent']` (+ host pin). Until then it emits `whatif_waiting` once.
2. `design_whatif` output:
   ```
   {question, noise, noise_source, parent_experiment_id, parent_smoke_experiment_id, parent_full_cmd,
    parent_config_log_line,
    branches: [{id: "b1", key, value, parent_value, reason, scale: "smoke", cwd: "runs/<pid>/whatif/<task8>-b1", cmd,
                experiment: {label, parent_id, changed_key, margin,
                             config: {claim_map, seeds, design, margin_reason, scale, settings,
                                      whatif: {task_id, branch_id, key, value, parent_value, question}}}}]}
   ```
   3–4 branches; code rejects a branch that changes more or fewer than one key.
Every task the controller creates for a what-if carries `input.whatif_of` = the `design_whatif` task id.

3. The controller creates, per branch, the `experiments` row from `branch.experiment` **exactly as given** (the
   ranking finds branches through `config.whatif.task_id` and `branch_id`) and a smoke `run` task (`['smoke']` +
   host pin; `files`/`requirements` from the reproduction's latest done run task's input; the branch's
   `experiment_id`, `cmd`, `cwd`).
4. When every branch's smoke is `done` or `failed`, the controller creates one `compare` task with
   `input.whatif_task_id`. Output:
   ```
   {whatif_task_id, experiment_id,
    ranking: [{id, key, value, decision: "extend" | "kept" | "pruned", reason, effect, score, model, experiment_id}],
    extend: {branch_id, key, value, reason, smoke_experiment_id, cwd, scale: "full", cmd,
             experiment: {...same shape as a branch's, config.scale "full"}} | null}
   ```
   Pruned branch experiments get `status = 'pruned'` and `pruned_reason`; each decision is also in `config.whatif`.
5. If `extend` is not null, the controller creates its experiments row from `extend.experiment` and the full `run`
   from `extend.cmd` / `extend.cwd` with `requires_approval = true` (`awaiting_approval`). After approval and the
   run, it queues a `compare` with `input.extend_experiment_id` (no `whatif_task_id`), which grades that experiment
   like a normal compare.
6. The sequence ends with one `whatif_finished` event (task = the `design_whatif` task) and its reason: graded, no
   branch extended, the ranking failed, the extend run was rejected (a redirect counts as a rejection here) or
   failed. Branch smoke runs are not debugged or retried: a failed smoke is pruned by the ranking ("smoke failed").

`design_experiment` output's `design` may carry `setting_ids` / `settings_used` (the paper settings that belong to the
experiment; `s1`.. follow the order of `papers.settings`).

### `experiments.config.why` (T19)

Written at `compare` / `explain_diff` on a reproduction experiment:

```
{settings_diff: [{key, setting_id, applies_to, paper, quote, page, paper_numbers, our_key, ours, our_numbers,
                  label: "same" | "difference" | "paper omission" | "scale reduction (budget)", why, also: [keys],
                  branch_effects: [{branch_id, value, model, smoke_effect, score, decision, full_effect,
                                    experiment_id}]}],
 config_log_line, labels: {label: count}}
```

## 6. Decisions and feedback (written by the web, acted on by the controller)

`POST /api/tasks/<id>/decision` moves a task out of `awaiting_approval` and writes a `decision` event
(`data: {decision, note, status}`):

| Decision | The web sets | Then the controller |
|---|---|---|
| `approve` | `status = 'queued'`, `decision = 'approve'` | nothing: a worker claims it |
| `reject` | `status = 'rejected'`, `decision = 'reject'` | stops the project (`stopped`) with an event and reason |
| `redirect` | `status = 'rejected'`, `decision = 'redirect'`, `decision_note` (required) | replans that step with the note in the planner prompt, creates the new attempt (with `redirect_note`) and emits `step_redirected` |

Feedback: `POST /api/tasks/<id>/feedback` writes an events row `{type: 'feedback', task_id, data: {value: 'up' | 'down'}}`
on a `done` or `failed` task. The controller rescores the task's reward from the newest one.

## 6b. Inbox "Send to engine" (T33)

The web writes one event when a researcher sends an `email_received` event's points to the engine:
`{type: 'engine_requested', project_id, task_id: null, data: {email_event_id}}`. The controller acts on each once:

- `plan_redirect`: `data {engine_request_id, email_event_id, from, subject, points: [str], plan_task_id}`; `reason` is
  the numbered points as sent to the planner (at most 10, each cut at 300 characters). A new `plan` task
  (`input.redirect_note`, `input.source`) is queued and the project goes to `planning`; the plan follows, then its
  tasks, as for any plan.
- or `engine_request_refused`: `data {engine_request_id, email_event_id}`, `reason` = why (email not found, another
  project's email, no points).

## 6c. Lesson events (MEM-1, for the Lessons panel)

- `lesson_applied`: `data {lesson_id, kind, tags (the matched tags), where ("planner" | "<capability> task"), rank
  (1 = most relevant), overlap (number of matched tags), times_applied (after this use), paper}`.
- `lesson_skipped` (at plan time only): `data {lesson_id, reason, detail, kind, tags, where, paper}` with `reason` one
  of `no_evidence` · `other_paper` (a `setting_mattered` lesson from another paper) · `duplicate` (same kind and tag
  set as a lesson used more often) · `over_limit` (more than 5 matched).
- `paper` is the lesson's arXiv id, `round0:matchdg` for the imported Round 0 lessons, or null.

## 7. Statuses

- `tasks.status`: `queued` → `running` → `done` / `failed`; `awaiting_approval` → `queued` / `rejected`.
- `projects.status`: `new` → `planning` → `running` → `done` / `blocked` / `stopped` / `plan_failed`. The controller
  never touches `test` or `reference` projects.
- `agents.status`: `active` / `retired` / `merged` (`merged_into` set); `origin`: `seed` / `spawned` / `refined`.

## 8. LLM calls

Only through `lab/llm.py`. Every answered call writes `llm_calls` (`agent_id`, `task_id`, `model`, `tokens_in`,
`tokens_out`, `total_tokens`, `request_id`, `mode`, `cache_key`). Provider errors are events with the full text, keys
scrubbed: `llm_error`, `llm_quota_exhausted` (403, no retry), `llm_filtered` (content filter, no retry), `llm_daily_cap`
(more than 700,000 live tokens since 05:30 IST).
