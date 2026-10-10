"""T09: spawn on a gap or a repeated failure (SPEC §4.3), and what the controller does after a step fails."""
import pytest

from lab.controller import progress, spawn
from lab.controller.assign import Pick
from lab.controller.rules import MAX_DEBUG_ATTEMPTS, MAX_STEP_ATTEMPTS

# ---- when to spawn ------------------------------------------------------------------------------------------------


def test_gap_triggers_a_spawn():
    t = spawn.trigger(None, "debug", {})
    assert t.kind == "gap" and "debug" in t.reason


def test_same_agent_failing_twice_triggers_a_spawn():
    pick = Pick({"id": "a1", "name": "implementer-v1"}, None, "best")
    assert spawn.trigger(pick, "write_code", {"a1": 1}) is None
    t = spawn.trigger(pick, "write_code", {"a1": 2})
    assert t.kind == "repeated_failure" and "implementer-v1" in t.reason and "2" in t.reason


def test_no_spawn_when_an_agent_is_available():
    assert spawn.trigger(Pick({"id": "a", "name": "x"}, 0.9, "r"), "debug", {"b": 5}) is None


# ---- code checks on the LLM's draft -------------------------------------------------------------------------------

def draft(**kw):
    d = {"name": "Debugger", "role_prompt": "You fix crashes.", "tools": ["read_file", "write_file", "rm_rf"],
         "capabilities": ["debug", "teleport"], "budget": {"max_tokens": 10**7, "max_cpu_s": 10**6, "max_steps": 99},
         "reason": "a run failed"}
    d.update(kw)
    return d


def test_check_keeps_only_fixed_tools_and_registry_capabilities():
    row, notes = spawn.check_spec(draft(), "debug", budget_cap_s=1200, taken={"reader-v1"})
    assert set(row["tools"]) <= set(spawn.FIXED_TOOLS)
    assert "rm_rf" not in row["tools"] and any("rm_rf" in n for n in notes)
    assert row["capabilities"] == ["debug"] and any("teleport" in n for n in notes)


def test_a_debugger_gets_the_baseline_repair_tools_and_policy():
    row, _ = spawn.check_spec(draft(tools=[]), "debug", budget_cap_s=1200, taken=set())
    assert set(spawn.REPAIR_TOOLS) <= set(row["tools"])
    assert "REPAIR(env)" in row["role_prompt"] and "HYPOTHESIS" in row["role_prompt"]
    assert row["role_prompt"].startswith("You fix crashes.")


def test_the_needed_capability_is_always_granted():
    row, _ = spawn.check_spec(draft(capabilities=[]), "write_code", budget_cap_s=1200, taken=set())
    assert row["capabilities"] == ["write_code"]
    assert "REPAIR(env)" not in row["role_prompt"]


def test_budget_is_clipped_to_the_project_cap_and_spawn_limits():
    row, notes = spawn.check_spec(draft(), "debug", budget_cap_s=1200, taken=set())
    b = row["budget"]
    assert b["max_cpu_s"] == 1200 and b["max_tokens"] == spawn.MAX_TOKENS and b["max_steps"] == spawn.MAX_STEPS
    assert any("clipped" in n for n in notes)


def test_missing_budget_gets_defaults():
    row, _ = spawn.check_spec(draft(budget=None), "debug", budget_cap_s=1200, taken=set())
    assert row["budget"] == {**spawn.DEFAULT_BUDGET, "max_cpu_s": min(spawn.DEFAULT_BUDGET["max_cpu_s"], 1200)}


def test_name_is_slugged_versioned_and_unique():
    row, _ = spawn.check_spec(draft(name="Crash Debugger!"), "debug", budget_cap_s=1200, taken=set())
    assert row["name"] == "crash-debugger-v1"
    row, _ = spawn.check_spec(draft(name="debugger-v1"), "debug", budget_cap_s=1200, taken={"debugger-v1"})
    assert row["name"] == "debugger-2-v1"


def test_empty_role_prompt_is_refused():
    with pytest.raises(spawn.SpawnError):
        spawn.check_spec(draft(role_prompt="  "), "debug", budget_cap_s=1200, taken=set())


# ---- after a step fails -------------------------------------------------------------------------------------------

def att(tid, status="failed", sig=None, ts="2026-10-10T10:00:00Z"):
    return {"id": tid, "status": status, "created_at": ts, "output": {"error_signature": sig} if sig else {}}


def dbg(failed_id, status, ts="2026-10-10T10:01:00Z"):
    return {"id": f"d-{failed_id}-{ts}", "status": status, "created_at": ts, "input": {"failed_task_id": failed_id}}


def test_a_crash_gets_a_debug_task_first():
    assert progress.failure_action([att("r1", sig="ModuleNotFoundError:torchvision")], []) == ("debug", None)


def test_wait_for_the_debug_task_then_retry_the_step():
    a = [att("r1", sig="E")]
    assert progress.failure_action(a, [dbg("r1", "running")]) == ("wait", None)
    assert progress.failure_action(a, [dbg("r1", "done")]) == ("retry", None)


def test_a_failure_without_a_crash_signature_is_retried():
    assert progress.failure_action([att("w1")], []) == ("retry", None)


def test_failed_debug_is_tried_again_up_to_the_limit():
    a = [att("r1", sig="E")]
    ds = [dbg("r1", "failed", ts=f"2026-10-10T10:0{i}:00Z") for i in range(1, MAX_DEBUG_ATTEMPTS + 1)]
    assert progress.failure_action(a, ds[:1]) == ("debug", None)
    kind, why = progress.failure_action(a, ds)
    assert kind == "blocked" and str(MAX_DEBUG_ATTEMPTS) in why


def test_a_step_is_given_up_after_the_attempt_limit():
    a = [att(f"r{i}", sig="E", ts=f"2026-10-10T10:0{i}:00Z") for i in range(MAX_STEP_ATTEMPTS)]
    kind, why = progress.failure_action(a, [])
    assert kind == "blocked" and str(MAX_STEP_ATTEMPTS) in why


def test_only_debug_tasks_for_the_latest_failure_count():
    a = [att("r1", sig="E", ts="2026-10-10T10:00:00Z"), att("r2", sig="E", ts="2026-10-10T10:05:00Z")]
    assert progress.failure_action(a, [dbg("r1", "done")]) == ("debug", None)
