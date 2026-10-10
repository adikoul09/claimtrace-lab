"""Fixed thresholds for the controller (SPEC §3, §4). Changing them after 6 PM needs Laptop A's OK."""

TICK_S = 3                   # controller loop period
STALE_HEARTBEAT_S = 60       # a running task whose executor's heartbeat is older than this goes back to the queue
ROLLING_WINDOW = 3           # rewards per agent in the rolling mean (SPEC §4.2)
NEUTRAL_REWARD = 0.5         # prior for an agent with no scored task yet, when choosing who gets a task
RUN_TIMEOUT_FLOOR_S = 300    # a run step's timeout is at least this (a first run downloads data)
MAX_STEP_ATTEMPTS = 3        # tries of one plan step before the project is blocked
MAX_DEBUG_ATTEMPTS = 2       # debug tasks for one failure before the project is blocked
SPAWN_ON_FAILURES = 2        # the same agent failing the same task this often spawns a new agent (SPEC §4.3b)
RETIRE_BELOW = 0.35          # rolling mean reward below this over the last MIN_SCORED tasks retires an agent (§4.2)
MERGE_OVERLAP = 0.8          # capability overlap (shared / all tags) at which two agents merge (§4.4)
MIN_SCORED = 3               # scored tasks an agent needs before retire or merge can apply to it
