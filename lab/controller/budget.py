"""Token guard (HoO-A). Once the day's live LLM tokens (llm_calls since 05:30 IST, the same number as lab/llm.py's
700k cap) reach BUDGET_HOLD_TOKENS, the controller makes no LLM call and queues no LLM task; queued LLM tasks get
HOLD_CAP, a cap no worker has, so only CPU work (runs, code-only compares) continues. The hold lifts when the meter
drops below the threshold (the next quota day) and the cap is removed again."""
from __future__ import annotations

CPU_CAPABILITIES = ("run", "compare")  # compare grades by code (no LLM); explain_diff calls the Analyst LLM
HOLD_CAP = "hold:budget"


def needs_llm(capability: str) -> bool:
    return capability not in CPU_CAPABILITIES


def on_hold(used: int, limit: int) -> bool:
    return used >= limit


def held(caps: list[str]) -> list[str]:
    return list(caps) if HOLD_CAP in caps else [*caps, HOLD_CAP]


def released(caps: list[str]) -> list[str]:
    return [c for c in caps if c != HOLD_CAP]
