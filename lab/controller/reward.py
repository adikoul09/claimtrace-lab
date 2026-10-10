"""Reward (SPEC §5). Code computes every part; the weights and budgets live only here.

  reward    = 0.6 · outcome + 0.2 · (1 − cost_norm) + 0.2 · feedback
  outcome   ∈ {0, 0.5, 1}   failed / partial / passed
  cost_norm = min(1, (tokens / 20,000 + cpu_seconds / 600) / 2)
  feedback  ∈ {0, 0.5, 1}   👎 / none / 👍

Outcome, from the finished task (tasks.output), first match wins:
  output.outcome = passed | partial | failed   an explicit acceptance check written by the code that ran the task
  status 'failed'                              failed
  run task                                     passed with at least one METRIC line, else partial
  output.agent_status = 'stopped'              partial (the agent hit its budget before finishing)
  otherwise                                    passed
Feedback: the latest events row with type 'feedback' for the task, data.value = 'up' | 'down'.
Changing these values after 6 PM needs Laptop A's OK."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from lab.controller.rules import ROLLING_WINDOW

W_OUTCOME, W_COST, W_FEEDBACK = 0.6, 0.2, 0.2
TOKENS_NORM = 20_000
CPU_NORM_S = 600
OUTCOMES = {"failed": 0.0, "partial": 0.5, "passed": 1.0}
FEEDBACK = {"down": 0.0, "up": 1.0}
NO_FEEDBACK = 0.5


def cost_norm(tokens: float, cpu_seconds: float) -> float:
    return min(1.0, (tokens / TOKENS_NORM + cpu_seconds / CPU_NORM_S) / 2)


def reward(outcome: float, cost: float, feedback: float) -> float:
    return round(W_OUTCOME * outcome + W_COST * (1 - cost) + W_FEEDBACK * feedback, 4)


def outcome_of(task: dict) -> tuple[float, str]:
    out = task.get("output") or {}
    if out.get("outcome") in OUTCOMES:
        return OUTCOMES[out["outcome"]], f"acceptance check: {out['outcome']}"
    if task.get("status") == "failed":
        why = out.get("error_signature") or out.get("error") or "task failed"
        return 0.0, f"failed ({str(why)[:120]})"
    if task.get("capability") == "run":
        n = int(out.get("metrics") or 0)
        return (1.0, f"exit code 0, {n} metric lines") if n else (0.5, "exit code 0 but no METRIC lines")
    if out.get("agent_status") == "stopped":
        return 0.5, "stopped by its budget before finishing"
    return 1.0, "finished"


def latest_feedback(events: list[dict]) -> dict[str, str]:
    """task_id -> 'up' | 'down' from the newest valid feedback event per task."""
    out: dict[str, str] = {}
    for e in sorted(events, key=lambda e: e.get("ts") or ""):
        v = (e.get("data") or {}).get("value")
        if v in FEEDBACK and e.get("task_id"):
            out[e["task_id"]] = v
    return out


def feedback_value(value: Optional[str]) -> float:
    return FEEDBACK.get(value, NO_FEEDBACK) if value else NO_FEEDBACK


@dataclass
class Scored:
    row: dict      # a rewards row
    reason: str    # every number that produced it


def score(task: dict, tokens: int, feedback: Optional[str]) -> Scored:
    """tokens: LLM tokens of the task (the llm_calls sum when there are calls, else tasks.tokens)."""
    cpu = float(task.get("cpu_seconds") or 0)
    o, o_why = outcome_of(task)
    c = round(cost_norm(tokens, cpu), 4)
    f = feedback_value(feedback)
    r = reward(o, c, f)
    reason = (f"outcome {o:g} ({o_why}) · cost {c:.2f} ({tokens} tokens, {cpu:g} CPU s) · "
              f"feedback {feedback or 'none'} ({f:g}) → reward {r:.2f} = {W_OUTCOME}·{o:g} + {W_COST}·(1−{c:.2f}) "
              f"+ {W_FEEDBACK}·{f:g}")
    return Scored({"agent_id": task["agent_id"], "task_id": task["id"], "outcome": o, "cost_norm": c,
                   "feedback": f, "reward": r}, reason)


def rolling_means(rewards: list[dict]) -> dict[str, float]:
    """agent_id -> mean reward over its last ROLLING_WINDOW scored tasks."""
    per: dict[str, list[dict]] = defaultdict(list)
    for r in rewards:
        per[r["agent_id"]].append(r)
    out = {}
    for agent_id, rows in per.items():
        last = sorted(rows, key=lambda r: r["ts"], reverse=True)[:ROLLING_WINDOW]
        out[agent_id] = sum(float(r["reward"]) for r in last) / len(last)
    return out
