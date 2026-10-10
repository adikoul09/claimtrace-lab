"""Fixed thresholds for the controller (SPEC §3, §4). Changing them after 6 PM needs Laptop A's OK."""

TICK_S = 3                   # controller loop period
STALE_HEARTBEAT_S = 60       # a running task whose executor's heartbeat is older than this goes back to the queue
ROLLING_WINDOW = 3           # rewards per agent in the rolling mean (SPEC §4.2)
NEUTRAL_REWARD = 0.5         # prior for an agent with no scored task yet, when choosing who gets a task
RUN_TIMEOUT_FLOOR_S = 300    # a run step's timeout is at least this (a first run downloads data)
