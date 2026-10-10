"""Assign (SPEC §3.3): the active agent with the capability and the highest rolling reward gets the task."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lab.controller.rules import NEUTRAL_REWARD, STEP_FLOORS, TOKEN_FLOORS


@dataclass
class Pick:
    agent: dict
    score: Optional[float]   # None: no scored task yet
    reason: str


def step_floor(agent: dict) -> Optional[dict]:
    """The agent's budget with max_steps and max_tokens raised to its capabilities' floors (STEP_FLOORS,
    TOKEN_FLOORS), or None if already enough."""
    caps = agent.get("capabilities") or []
    budget = dict(agent.get("budget") or {})
    new = dict(budget)
    for key, floors in (("max_steps", STEP_FLOORS), ("max_tokens", TOKEN_FLOORS)):
        floor = max([floors[c] for c in caps if c in floors] or [0])
        if floor and int(budget.get(key) or 0) < floor:
            new[key] = floor
    return new if new != budget else None


def pick_agent(agents: list[dict], capability: str, scores: dict[str, float],
               preferred: Optional[str] = None) -> Optional[Pick]:
    """The planner's choice when it is an active agent with the capability, else the highest rolling reward.
    None means a gap: no active agent has this capability."""
    cands = [a for a in agents if a.get("status") == "active" and capability in (a.get("capabilities") or [])]
    if not cands:
        return None
    if preferred:
        mine = [a for a in cands if a["name"] == preferred]
        if mine:
            s = scores.get(mine[0]["id"])
            return Pick(mine[0], s, f"{preferred}: chosen by the planner; "
                                    + (f"rolling reward {s:.2f}" if s is not None else "no scored tasks yet"))
        note = f"the planner chose {preferred}, which is not an active agent with {capability}; "
        best = pick_agent(agents, capability, scores)
        return Pick(best.agent, best.score, note + best.reason)
    best = max(cands, key=lambda a: (scores.get(a["id"], NEUTRAL_REWARD), a.get("version") or 1, a["name"]))
    score = scores.get(best["id"])
    why = (f"rolling reward {score:.2f}" if score is not None
           else f"no scored tasks yet (prior {NEUTRAL_REWARD:.2f})")
    n = len(cands)
    return Pick(best, score, f"{best['name']}: {why}; highest of {n} active agent{'s' if n > 1 else ''} "
                             f"with {capability}")
