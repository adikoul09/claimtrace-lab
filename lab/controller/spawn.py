"""Spawn (SPEC §4.3): a new agent row, drafted by the LLM, checked by code.

Triggers (code): (a) a gap, no active agent has the capability a task needs; (b) the agent that would get the task
already failed this same task SPAWN_ON_FAILURES times. "The same agent" is its role (the name without -vN): a refined
version is the same agent with a better prompt, so implementer-v1 failing and then implementer-v2 failing is twice.
Every failed attempt counts, including one where the agent produced no answer. The LLM drafts {name, role_prompt, tools, capabilities, budget,
reason} from the gap and the failure context. Code then keeps only tools from the fixed set, grants the needed
capability, clips the budget, makes the name unique, and gives a Debugger the baseline repair-agent tools and policy
(baseline/el01-auditor/el01/llm/prompts/repair.md, el01/repair/policy.py)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from lab.agents.tools import FIXED_TOOLS, TOOL_DOCS
from lab.controller.rules import SPAWN_ON_FAILURES
from lab.schemas import CAPABILITIES

MAX_TOKENS = 60_000
MIN_TOKENS = 20_000  # below this a new agent cannot even read a paper excerpt (live 808f07a4: 4000 ran out at once)
MAX_STEPS = 15
DEFAULT_BUDGET = {"max_tokens": 40_000, "max_cpu_s": 600, "max_steps": 10}
LLM_AGENT = "controller"

# The baseline repair agent read the code, edited it and re-ran the smoke command; here that is these fixed tools.
REPAIR_TOOLS = ("read_file", "list_dir", "write_file", "make_env", "run", "query_memory", "emit")
REPAIR_POLICY = """

Repair policy (from the Round 0 audit; code checks every patch):
- You may change the code only to make it RUN, never WHAT IS MEASURED.
- REPAIR(env): environment fixes, e.g. a missing package, an absolute path, GPU-only device selection on a CPU machine.
- REPAIR(code): compatibility fixes, e.g. a library API that no longer exists, on a path the experiment does not use.
- HYPOTHESIS, never a repair: any change to data, splits, model, loss, optimizer, metric, model selection or any
  number used in training. Do not make it; report it as a hypothesis instead.
- Write the smallest fix at the root cause, label it REPAIR(env) or REPAIR(code) in your answer, then re-run the
  failing command to show it now gets past the error. A compatibility repair must leave the measured numbers
  unchanged (inertness check)."""

SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "short role name, e.g. debugger"},
        "role_prompt": {"type": "string", "description": "the system prompt: who the agent is and how it works"},
        "tools": {"type": "array", "items": {"type": "string", "enum": list(FIXED_TOOLS)}},
        "capabilities": {"type": "array", "items": {"type": "string", "enum": list(CAPABILITIES)}},
        "budget": {"type": "object", "properties": {"max_tokens": {"type": "integer"},
                                                    "max_cpu_s": {"type": "integer"},
                                                    "max_steps": {"type": "integer"}}},
        "reason": {"type": "string", "description": "one sentence: why this agent, for this gap"},
    },
    "required": ["name", "role_prompt", "tools", "capabilities", "reason"],
}


class SpawnError(ValueError):
    pass


@dataclass
class Trigger:
    kind: str     # gap | repeated_failure
    reason: str


def role_of(name: str) -> str:
    """An agent's role: its name without the version suffix (reader-v13 -> reader)."""
    return re.sub(r"-v\d+$", "", name or "")


def fails_by_role(attempts: list[dict], names: dict[str, str]) -> dict[str, int]:
    """role -> failed attempts of this same task (names: agent_id -> agent name, retired agents included)."""
    out: dict[str, int] = {}
    for t in attempts:
        if t.get("status") == "failed" and t.get("agent_id") in names:
            r = role_of(names[t["agent_id"]])
            out[r] = out.get(r, 0) + 1
    return out


def trigger(pick, capability: str, fails: dict[str, int]) -> Optional[Trigger]:
    """pick: assign.pick_agent's result (None = gap); fails: role -> failed attempts of this same task."""
    if pick is None:
        return Trigger("gap", f"gap: no active agent has the capability {capability}")
    role = role_of(pick.agent["name"])
    n = fails.get(role, 0)
    if n >= SPAWN_ON_FAILURES:
        return Trigger("repeated_failure", f"{role} failed this task {n} times, the last as {pick.agent['name']} "
                                           f"(spawn after {SPAWN_ON_FAILURES})")
    return None


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    s = re.sub(r"-v\d+$", "", s)
    return s or "agent"


def unique_name(base: str, taken: set[str]) -> str:
    name, n = f"{base}-v1", 2
    while name in taken:
        name, n = f"{base}-{n}-v1", n + 1
    return name


def check_spec(draft: dict, capability: str, budget_cap_s: int, taken: set[str],
               floor_tokens: int = MIN_TOKENS) -> tuple[dict, list[str]]:
    """The agents row fields code allows from the draft, plus notes on every change code made."""
    notes = []
    prompt = (draft.get("role_prompt") or "").strip()
    if not prompt:
        raise SpawnError("the draft has no role prompt")
    tools = [t for t in dict.fromkeys(draft.get("tools") or []) if t in FIXED_TOOLS]
    bad = [t for t in draft.get("tools") or [] if t not in FIXED_TOOLS]
    if bad:
        notes.append(f"tools not in the fixed set dropped: {bad}")
    caps = [c for c in dict.fromkeys(draft.get("capabilities") or []) if c in CAPABILITIES]
    bad = [c for c in draft.get("capabilities") or [] if c not in CAPABILITIES]
    if bad:
        notes.append(f"capabilities not in the registry dropped: {bad}")
    if capability not in caps:
        caps.insert(0, capability)
    if capability == "debug":
        added = [t for t in REPAIR_TOOLS if t not in tools]
        tools += added
        if added:
            notes.append(f"baseline repair-agent tools added: {added}")
        prompt += REPAIR_POLICY
    budget = {**DEFAULT_BUDGET, **{k: v for k, v in (draft.get("budget") or {}).items()
                                   if k in DEFAULT_BUDGET and isinstance(v, int) and v > 0}}
    limits = {"max_tokens": MAX_TOKENS, "max_cpu_s": int(budget_cap_s), "max_steps": MAX_STEPS}
    for k, cap in limits.items():
        floor = min(max(floor_tokens, MIN_TOKENS), MAX_TOKENS)
        if k == "max_tokens" and budget[k] < floor:
            notes.append(f"budget max_tokens raised from {budget[k]} to {floor} (floor: an existing agent's budget for "
                         f"{capability}, at least {MIN_TOKENS})")
            budget[k] = floor
        if budget[k] > cap:
            if (draft.get("budget") or {}).get(k) is not None:
                notes.append(f"budget {k} clipped from {budget[k]} to {cap}")
            budget[k] = cap
    return {"name": unique_name(slug(draft.get("name")), taken), "role_prompt": prompt, "tools": tools,
            "capabilities": caps, "budget": budget}, notes


def build_prompt(capability: str, trig: Trigger, context: str, agents: list[dict], budget_cap_s: int) -> str:
    team = "\n".join(f"- {a['name']}: {', '.join(a.get('capabilities') or [])}" for a in agents) or "- (none)"
    tools = "\n".join(f"- {TOOL_DOCS[t]}" for t in FIXED_TOOLS)
    return f"""The research team needs a new agent.

Why: {trig.reason}.
Capability it must have: {capability}

What happened:
{context}

Current active team:
{team}

Tools that exist (choose only from these):
{tools}

Draft the agent: a short role name, a role prompt (its system prompt: what it does, how it works step by step, what it
must never do), the tools it needs, its capabilities, and a budget (max_tokens, max_cpu_s up to {budget_cap_s},
max_steps). Its task goal will carry its inputs (claims, settings, earlier outputs). The role prompt must not assume
any file exists in the run folder: do not assume file names; if it needs files, it should list_dir first."""


def draft_spec(llm, capability: str, trig: Trigger, context: str, agents: list[dict], budget_cap_s: int, *,
               task_id=None) -> tuple[dict, object]:
    from lab.llm import Request

    resp = llm.call(Request(agent=LLM_AGENT, system="You design agents for an AI research team.",
                            prompt=build_prompt(capability, trig, context, agents, budget_cap_s), schema=SPEC_SCHEMA,
                            model="smart"), task_id=task_id)
    return (resp.output if isinstance(resp.output, dict) else {}), resp
