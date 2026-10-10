"""A spending cap for one phase's live calls: before a call that misses the cache, the recorded cost of this phase's
earlier live calls (usage lines carrying the phase's tag) plus an estimate for the call must stay under the cap."""
from __future__ import annotations

import json
from pathlib import Path

from el01.llm.backend import LLMError

ESTIMATE_USD = {"code_extractor": 0.5, "branch_writer": 0.4}
DEFAULT_ESTIMATE = 0.5


def spent(usage_log: Path, tag: str) -> float:
    if not Path(usage_log).exists():
        return 0.0
    total = 0.0
    for line in Path(usage_log).read_text().splitlines():
        r = json.loads(line)
        if r.get("tag") == tag and r.get("cache") == "miss":
            total += r.get("total_cost_usd") or 0.0
    return total


class Cap:
    def __init__(self, usage_log: Path, cap_usd: float, tag: str):
        self.usage_log, self.cap_usd, self.tag = Path(usage_log), cap_usd, tag

    def __call__(self, req) -> None:
        s = spent(self.usage_log, self.tag)
        est = ESTIMATE_USD.get(req.agent, DEFAULT_ESTIMATE)
        if s + est > self.cap_usd:
            raise LLMError(f"live spend cap: {self.tag} has spent ${s:.2f} of ${self.cap_usd:.2f}; the next "
                           f"{req.agent} call (about ${est:.2f}) would pass it. Ask Builder before raising the cap")
