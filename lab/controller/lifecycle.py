"""Lifecycle rules (SPEC §4). Code decides every one of them; the thresholds live in rules.py.

  4.1 refine  a task's acceptance check (by code) failed, or a researcher gave it 👎: the LLM writes version n+1 of the
              agent's role prompt with the lesson; code makes the new row (origin refined, parent_id the old row) and
              retires the old one "superseded by vN+1". Code-only agents (max_tokens 0, e.g. the Runner) are not
              refined: they have no prompt that could fix anything.
  4.2 retire  rolling mean reward over the agent's last MIN_SCORED scored tasks < RETIRE_BELOW. Code-only agents
              are exempt too: a crashed run counts against the agent that wrote the code (reward.charged_agent).
  4.4 merge   two active agents whose capability overlap (shared tags / all tags) is ≥ MERGE_OVERLAP, each with at
              least MIN_SCORED scored tasks: the lower-scored one becomes merged into a new version of the other
              that carries the union of both agents' capabilities and tools.
(4.3 spawn is in spawn.py.)"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from lab.controller.rules import MAX_REFINES_PER_ROLE, MERGE_OVERLAP, MIN_SCORED, RETIRE_BELOW
from lab.controller.spawn import REPAIR_POLICY

MAX_PROMPT_CHARS = 8000


@dataclass
class Retire:
    agent: dict
    mean: float
    last: list[float]
    reason: str


@dataclass
class Merge:
    winner: dict
    loser: dict
    overlap: float
    reason: str


@dataclass
class Refine:
    agent: dict
    task: dict
    kind: str      # failed_check | thumbs_down
    reason: str


def _last_rewards(rewards: list[dict]) -> dict[str, list[float]]:
    """agent_id -> its last MIN_SCORED rewards, newest first."""
    per: dict[str, list[dict]] = defaultdict(list)
    for r in rewards:
        per[r["agent_id"]].append(r)
    return {a: [float(r["reward"]) for r in sorted(rows, key=lambda r: r["ts"], reverse=True)[:MIN_SCORED]]
            for a, rows in per.items()}


def _counts(rewards: list[dict]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in rewards:
        out[r["agent_id"]] += 1
    return out


def _fmt(xs: list[float]) -> str:
    return ", ".join(f"{x:.2f}" for x in xs)


# ---- 4.2 retire ---------------------------------------------------------------------------------------------------

def retire_candidates(agents: list[dict], rewards: list[dict]) -> list[Retire]:
    last = _last_rewards(rewards)
    out = []
    for a in agents:
        xs = last.get(a["id"], [])
        if a.get("status") != "active" or len(xs) < MIN_SCORED or not (a.get("budget") or {}).get("max_tokens"):
            continue
        mean = round(sum(xs) / len(xs), 6)  # rewards are stored to 4 decimals; no float dust at the threshold
        if mean < RETIRE_BELOW:
            out.append(Retire(a, mean, xs, f"rolling mean reward {mean:.2f} over its last {len(xs)} scored tasks "
                                           f"({_fmt(xs)}) is below {RETIRE_BELOW:.2f}"))
    return out


# ---- 4.4 merge ----------------------------------------------------------------------------------------------------

def overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def merge_candidates(agents: list[dict], rewards: list[dict]) -> list[Merge]:
    last, counts = _last_rewards(rewards), _counts(rewards)
    able = [a for a in agents if a.get("status") == "active" and counts.get(a["id"], 0) >= MIN_SCORED]
    mean = {a["id"]: sum(last[a["id"]]) / len(last[a["id"]]) for a in able}
    pairs = []
    for i, a in enumerate(able):
        for b in able[i + 1:]:
            ov = overlap(a.get("capabilities") or [], b.get("capabilities") or [])
            if ov >= MERGE_OVERLAP:
                pairs.append((ov, a, b))
    out, used = [], set()
    for ov, a, b in sorted(pairs, key=lambda p: -p[0]):
        if a["id"] in used or b["id"] in used:
            continue
        winner, loser = (a, b) if (mean[a["id"]], a.get("version") or 1) >= (mean[b["id"]], b.get("version") or 1) \
            else (b, a)
        shared = set(a.get("capabilities") or []) & set(b.get("capabilities") or [])
        union = set(a.get("capabilities") or []) | set(b.get("capabilities") or [])
        reason = (f"capability overlap {ov:.2f} ({len(shared)} shared of {len(union)} tags) ≥ {MERGE_OVERLAP:.2f}; "
                  f"{winner['name']} rolling mean {mean[winner['id']]:.2f} ({counts[winner['id']]} scored tasks) "
                  f"vs {loser['name']} {mean[loser['id']]:.2f} ({counts[loser['id']]})")
        out.append(Merge(winner, loser, ov, reason))
        used |= {a["id"], b["id"]}
    return out


# ---- 4.1 refine ---------------------------------------------------------------------------------------------------

def refine_triggers(agents: list[dict], tasks: list[dict], feedback: dict[str, str],
                    already: set[tuple[str, str]]) -> list[Refine]:
    """tasks: finished tasks; feedback: task_id -> 'up'/'down'; already: (agent_id, task_id) refined before."""
    by_id = {a["id"]: a for a in agents}
    out, seen = [], set()
    for t in tasks:
        a = by_id.get(t.get("agent_id"))
        if not a or a.get("status") != "active" or a["id"] in seen or (a["id"], t["id"]) in already:
            continue
        if not (a.get("budget") or {}).get("max_tokens"):
            continue  # code-only agent: no prompt to refine
        out_ = t.get("output") or {}
        if out_.get("outcome") == "failed":
            kind = "failed_check"
            reason = f"task {t['id'][:8]} ({t.get('capability')}) failed its acceptance check (run by code)"
            if out_.get("error"):
                reason += f": {str(out_['error'])[:300]}"
        elif feedback.get(t["id"]) == "down":
            kind, reason = "thumbs_down", f"task {t['id'][:8]} ({t.get('capability')}) got 👎 from a researcher"
        else:
            continue
        out.append(Refine(a, t, kind, reason))
        seen.add(a["id"])
    return out


def role_of(name: str) -> str:
    return re.sub(r"-v\d+$", "", name)


def refine_counts(agents: list[dict], project_of: dict[str, str]) -> dict[tuple[str, str], int]:
    """(project id, role) -> refined versions created by that project's tasks."""
    out: dict[tuple[str, str], int] = defaultdict(int)
    for a in agents:
        pid = project_of.get(a.get("created_by_task") or "")
        if a.get("origin") == "refined" and pid:
            out[(pid, role_of(a["name"]))] += 1
    return dict(out)


def is_capped(project_id: str, agent_name: str, counts: dict[tuple[str, str], int]) -> bool:
    return counts.get((project_id, role_of(agent_name)), 0) >= MAX_REFINES_PER_ROLE


def next_name(name: str, version: int) -> str:
    base = re.sub(r"-v\d+$", "", name)
    return f"{base}-v{int(version) + 1}"


def refined_version(old: dict, new_prompt: str, reason: str, task_id: str) -> dict:
    prompt = (new_prompt or "").strip()
    if not prompt:
        raise ValueError("the refined role prompt is empty")
    if REPAIR_POLICY.strip() in old.get("role_prompt", "") and REPAIR_POLICY.strip() not in prompt:
        prompt += REPAIR_POLICY  # a Debugger keeps the baseline repair policy whatever the LLM wrote
    prompt = prompt[:MAX_PROMPT_CHARS]
    v = int(old.get("version") or 1)
    return {"name": next_name(old["name"], v), "role_prompt": prompt, "capabilities": list(old["capabilities"]),
            "tools": list(old["tools"]), "budget": dict(old["budget"]), "version": v + 1, "parent_id": old["id"],
            "status": "active", "origin": "refined", "origin_reason": reason, "created_by_task": task_id}


def merged_version(winner: dict, loser: dict, reason: str) -> dict:
    caps = list(dict.fromkeys([*(winner.get("capabilities") or []), *(loser.get("capabilities") or [])]))
    tools = list(dict.fromkeys([*(winner.get("tools") or []), *(loser.get("tools") or [])]))
    v = int(winner.get("version") or 1)
    return {"name": next_name(winner["name"], v), "role_prompt": winner["role_prompt"], "capabilities": caps,
            "tools": tools, "budget": dict(winner["budget"]), "version": v + 1, "parent_id": winner["id"],
            "status": "active", "origin": "refined", "origin_reason": f"merged {loser['name']} into it: {reason}",
            "created_by_task": None}
