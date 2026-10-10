"""Thresholds for the controller (SPEC §3, §4). Changing them after 6 PM needs Laptop A's OK.

The token guard values (HoO-A, night of 10-11 Oct) can be set in the environment or .env without a code change:
  LAB_MAX_ATTEMPTS        tries of one plan step, and debug tasks for one failure        (default 2: one retry)
  LAB_REFINE_CAP          refines of one agent role per project                          (default 1)
  LAB_BUDGET_HOLD_TOKENS  live LLM tokens today at which the controller holds LLM work   (default 600,000)
  LAB_SPAWN_AFTER         failures of the same role on the same task before a spawn (§4.3b) (default 2; with
                          LAB_MAX_ATTEMPTS 2 a spawn can only happen if this is 1)
"""
from lab.db import setting


def _int(name: str, default: int) -> int:
    try:
        return int(str(setting(name, default)).strip())
    except (TypeError, ValueError):
        return default


TICK_S = 3                   # controller loop period
STALE_HEARTBEAT_S = 60       # a running task whose executor's heartbeat is older than this goes back to the queue
ROLLING_WINDOW = 3           # rewards per agent in the rolling mean (SPEC §4.2)
NEUTRAL_REWARD = 0.5         # prior for an agent with no scored task yet, when choosing who gets a task
RUN_TIMEOUT_FLOOR_S = 300    # a run step's timeout is at least this (a first run downloads data)
MAX_STEP_ATTEMPTS = _int("LAB_MAX_ATTEMPTS", 2)      # tries of one plan step before the project is blocked
MAX_DEBUG_ATTEMPTS = MAX_STEP_ATTEMPTS               # debug tasks for one failure before the project is blocked
SPAWN_ON_FAILURES = _int("LAB_SPAWN_AFTER", 2)       # same role failing the same task this often spawns (§4.3b)
RETIRE_BELOW = 0.35          # rolling mean reward below this over the last MIN_SCORED tasks retires an agent (§4.2)
MERGE_OVERLAP = 0.8          # capability overlap (shared / all tags) at which two agents merge (§4.4)
MIN_SCORED = 3               # scored tasks an agent needs before retire or merge can apply to it
MAX_REFINES_PER_ROLE = _int("LAB_REFINE_CAP", 1)     # refines of one role per project; then the task stays failed
BUDGET_HOLD_TOKENS = _int("LAB_BUDGET_HOLD_TOKENS", 600_000)  # live tokens today at which LLM work is held
