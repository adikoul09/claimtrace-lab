"""T07: controller core logic (plan checks, routing caps, agent choice, step progression, stale tasks). Pure functions
only; no Supabase, no LLM."""
from datetime import datetime, timedelta, timezone

import pytest

from lab.controller import assign, planner, progress, routing
from lab.controller.rules import STALE_HEARTBEAT_S
from lab.schemas import CAPABILITIES

NOW = datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc)


def ago(s: float) -> str:
    return (NOW - timedelta(seconds=s)).isoformat()


# ---- routing: required caps ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("cap", CAPABILITIES)
def test_every_capability_gets_non_empty_required_caps(cap):
    assert routing.required_caps(cap, scale="smoke")
    assert routing.required_caps(cap, scale="full")


def test_caps_follow_the_contract():
    assert routing.required_caps("run", "full") == ["train"]
    assert routing.required_caps("run", "smoke") == ["smoke"]
    assert routing.required_caps("read_paper") == ["agent"]
    assert routing.required_caps("debug") == ["agent"]


def test_host_pin_is_the_executor_of_the_first_claimed_run():
    tasks = [{"capability": "write_code", "executor": "laptop-b", "started_at": "2026-10-10T09:00:00Z"},
             {"capability": "run", "executor": "laptop-a", "started_at": "2026-10-10T10:00:00Z"},
             {"capability": "run", "executor": "voroa-1", "started_at": "2026-10-10T11:00:00Z"},
             {"capability": "run", "executor": None, "started_at": None}]
    assert routing.host_pin(tasks) == "host:laptop-a"
    assert routing.host_pin([{"capability": "run", "executor": None, "started_at": None}]) is None
    assert routing.with_pin(["agent"], "host:laptop-a") == ["agent", "host:laptop-a"]
    assert routing.with_pin(["agent"], None) == ["agent"]


def test_plan_tasks_need_the_controller_cap_no_worker_has():
    assert routing.required_caps("plan") == [routing.CONTROLLER_CAP]


def test_unknown_capability_is_refused():
    with pytest.raises(ValueError):
        routing.required_caps("teleport")


# ---- routing: live executors and stale tasks ----------------------------------------------------------------------

EXECUTORS = [
    {"name": "laptop-a", "caps": ["train", "heavy", "smoke", "parse"], "busy": False, "last_heartbeat": ago(5)},
    {"name": "voroa-1", "caps": ["smoke", "parse"], "busy": False, "last_heartbeat": ago(8)},
    {"name": "laptop-b", "caps": ["smoke", "parse", "train"], "busy": False, "last_heartbeat": ago(300)},
]


def test_eligible_executors_are_live_and_have_all_caps():
    assert [e["name"] for e in routing.eligible(["train", "heavy"], EXECUTORS, NOW)] == ["laptop-a"]
    # least capable first, so light work prefers the light machine; laptop-b is dead
    assert [e["name"] for e in routing.eligible(["parse"], EXECUTORS, NOW)] == ["voroa-1", "laptop-a"]
    assert routing.eligible(["gpu"], EXECUTORS, NOW) == []


def test_stale_running_task_is_found_with_the_heartbeat_age():
    tasks = [{"id": "t1", "status": "running", "executor": "laptop-b"},
             {"id": "t2", "status": "running", "executor": "laptop-a"},
             {"id": "t3", "status": "running", "executor": "ghost"},
             {"id": "t4", "status": "running", "executor": routing.CONTROLLER_NAME}]
    stale = {s["task"]["id"]: s for s in routing.stale_tasks(tasks, EXECUTORS, NOW)}
    assert set(stale) == {"t1", "t3"}  # the controller's own tasks are not judged by worker heartbeats
    assert stale["t1"]["age_s"] == pytest.approx(300)
    assert "300 s" in stale["t1"]["reason"] and str(STALE_HEARTBEAT_S) in stale["t1"]["reason"]
    assert stale["t3"]["age_s"] is None and "no heartbeat" in stale["t3"]["reason"]


def test_heartbeat_exactly_at_the_limit_is_not_stale():
    ex = [{"name": "x", "caps": [], "last_heartbeat": ago(STALE_HEARTBEAT_S)}]
    assert routing.stale_tasks([{"id": "t", "status": "running", "executor": "x"}], ex, NOW) == []


# ---- assign -------------------------------------------------------------------------------------------------------

AGENTS = [
    {"id": "a1", "name": "designer-v1", "capabilities": ["design_experiment", "budget"], "status": "active", "version": 1},
    {"id": "a2", "name": "designer-v2", "capabilities": ["design_experiment"], "status": "active", "version": 2},
    {"id": "a3", "name": "old-designer", "capabilities": ["design_experiment"], "status": "retired", "version": 1},
    {"id": "a4", "name": "reader-v1", "capabilities": ["read_paper"], "status": "active", "version": 1},
]


def test_pick_highest_rolling_reward_among_active_agents():
    pick = assign.pick_agent(AGENTS, "design_experiment", {"a1": 0.9, "a2": 0.4, "a3": 1.0})
    assert pick.agent["id"] == "a1"
    assert "0.90" in pick.reason and "2 active" in pick.reason


def test_unscored_agents_get_the_neutral_prior_and_ties_prefer_newer_versions():
    pick = assign.pick_agent(AGENTS, "design_experiment", {})
    assert pick.agent["id"] == "a2"
    assert "no scored tasks" in pick.reason


def test_gap_when_no_active_agent_has_the_capability():
    assert assign.pick_agent(AGENTS, "debug", {}) is None


# ---- planner: code checks on the LLM's plan -----------------------------------------------------------------------

def step(cap, **kw):
    return {"capability": cap, "title": f"do {cap}", "instructions": f"please {cap}", "acceptance": "it worked",
            "budget_cpu_s": 60, **kw}


def test_plan_check_drops_unknown_capabilities_with_a_reason():
    res = planner.check_plan({"reason": "r", "steps": [step("read_paper"), step("teleport"), step("write_code")]},
                             budget_cpu_min=20, order=None)
    assert [s.capability for s in res.steps] == ["read_paper", "write_code"]
    assert len(res.dropped) == 1 and "teleport" in res.dropped[0]


def test_plan_check_defaults_run_scale_to_smoke_and_clips_budget_to_the_project_cap():
    res = planner.check_plan({"reason": "r", "steps": [step("run", budget_cpu_s=99_999),
                                                       step("run", scale="full", cmd="python train.py")]},
                             budget_cpu_min=20, order=None)
    a, b = res.steps
    assert a.scale == "smoke" and a.budget_cpu_s == 20 * 60
    assert b.scale == "full" and b.cmd == "python train.py"
    assert any("clipped" in n for n in res.notes) and any("scale" in n for n in res.notes)


def test_plan_check_rejects_an_empty_plan():
    with pytest.raises(planner.PlanError):
        planner.check_plan({"reason": "r", "steps": [step("teleport")]}, budget_cpu_min=20, order=None)


def test_plan_check_caps_the_number_of_steps():
    res = planner.check_plan({"reason": "r", "steps": [step("read_paper")] * 40}, budget_cpu_min=20, order=None)
    assert len(res.steps) == planner.MAX_STEPS and res.notes


# ---- progress: which step is ready --------------------------------------------------------------------------------

def test_first_step_is_ready_when_nothing_is_materialised():
    assert progress.next_action(3, []) == ("create", 0)


def test_next_step_waits_for_the_previous_one():
    assert progress.next_action(3, [{"input": {"step": 0}, "status": "running"}]) == ("wait", None)
    assert progress.next_action(3, [{"input": {"step": 0}, "status": "awaiting_approval"}]) == ("wait", None)
    assert progress.next_action(3, [{"input": {"step": 0}, "status": "done"}]) == ("create", 1)


def test_plan_is_done_after_the_last_step_and_blocked_on_failure_or_rejection():
    done = [{"input": {"step": i}, "status": "done"} for i in range(3)]
    assert progress.next_action(3, done) == ("done", None)
    assert progress.next_action(3, done[:1] + [{"input": {"step": 1}, "status": "failed"}]) == ("failed", 1)
    assert progress.next_action(3, [{"input": {"step": 0}, "status": "rejected"}]) == ("rejected", 0)


def test_latest_attempt_of_a_step_counts():
    tasks = [{"input": {"step": 0}, "status": "failed", "created_at": "2026-10-10T10:00:00Z"},
             {"input": {"step": 0}, "status": "done", "created_at": "2026-10-10T10:05:00Z"}]
    assert progress.next_action(2, tasks) == ("create", 1)


# ---- envbuilder step limit 4 -> 6 (HoO-A) -------------------------------------------------------------------------

def test_an_envbuilder_gets_at_least_six_steps():
    from lab.controller.rules import STEP_FLOORS
    assert STEP_FLOORS == {"setup_env": 6}
    env = {"id": "e", "name": "envbuilder-v2", "capabilities": ["setup_env"],
           "budget": {"max_tokens": 10000, "max_cpu_s": 600, "max_steps": 4}}
    assert assign.step_floor(env) == {"max_tokens": 40_000, "max_cpu_s": 600, "max_steps": 6}   # tokens floor too
    assert assign.step_floor({**env, "budget": {**env["budget"], "max_steps": 8, "max_tokens": 40_000}}) is None
    reader = {"id": "r", "name": "reader-v1", "capabilities": ["read_paper"], "budget": {"max_steps": 2}}
    assert assign.step_floor(reader) is None                                                    # no floor for it


# ---- unblock: a reset step counts only attempts after the reset, and gets a fresh try --------------------------------

def test_attempts_before_an_unblock_do_not_count():
    a = [{"id": "a1", "status": "failed", "created_at": "2026-10-11T01:00:00+00:00", "output": {}},
         {"id": "a2", "status": "failed", "created_at": "2026-10-11T01:10:00+00:00", "output": {}},
         {"id": "a3", "status": "failed", "created_at": "2026-10-11T03:10:00+00:00", "output": {}}]
    assert [t["id"] for t in progress.since_reset(a, "2026-10-11T03:00:00+00:00")] == ["a3"]
    assert progress.since_reset(a, None) == a


def test_a_step_with_no_attempt_since_its_reset_is_tried_fresh():
    assert progress.failure_action([], []) == ("retry", None)


def test_unblock_targets_the_step_the_project_blocked_on():
    steps = [{"input": {"step": 0}, "status": "done", "capability": "read_paper", "created_at": "1"},
             {"input": {"step": 3}, "status": "failed", "capability": "setup_env", "created_at": "3"},
             {"input": {"step": 2}, "status": "done", "capability": "write_code", "created_at": "2"}]
    assert progress.blocked_step(steps) == (3, "setup_env")
    assert progress.blocked_step(steps[:1]) is None          # nothing failed: nothing to unblock


# ---- envbuilder token budget 10k -> 40k (same pattern as its 6 steps) ---------------------------------------------

def test_an_envbuilder_gets_at_least_40k_tokens_and_6_steps():
    from lab.controller.rules import TOKEN_FLOORS
    assert TOKEN_FLOORS == {"setup_env": 40_000, "design_experiment": 30_000, "budget": 30_000,
                            "design_whatif": 30_000}
    env = {"id": "e", "name": "envbuilder-v2", "capabilities": ["setup_env"],
           "budget": {"max_tokens": 10000, "max_cpu_s": 600, "max_steps": 6}}
    assert assign.step_floor(env) == {"max_tokens": 40_000, "max_cpu_s": 600, "max_steps": 6}



def test_a_designer_gets_at_least_30k_tokens():
    # live 42fb4944: cpu-experiment-designer-v2 inherited 4000 tokens and stopped at 5888 on the budget step
    d = {"id": "d", "name": "cpu-experiment-designer-v2", "capabilities": ["design_experiment", "budget"],
         "budget": {"max_tokens": 4000, "max_cpu_s": 60, "max_steps": 8}}
    assert assign.step_floor(d) == {"max_tokens": 30_000, "max_cpu_s": 60, "max_steps": 8}
