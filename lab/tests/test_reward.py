"""T08: reward formula (SPEC §5), the outcome and feedback that feed it, and the rolling mean per agent."""
import pytest

from lab.controller import reward
from lab.controller.rules import ROLLING_WINDOW


# ---- formula ------------------------------------------------------------------------------------------------------

def test_weights_are_the_spec_values():
    assert (reward.W_OUTCOME, reward.W_COST, reward.W_FEEDBACK) == (0.6, 0.2, 0.2)
    assert (reward.TOKENS_NORM, reward.CPU_NORM_S) == (20_000, 600)


@pytest.mark.parametrize("tokens,cpu,expected", [
    (0, 0, 0.0),
    (20_000, 0, 0.5),
    (0, 600, 0.5),
    (10_000, 300, 0.5),
    (20_000, 600, 1.0),
    (90_000, 5_000, 1.0),  # capped at 1
])
def test_cost_norm(tokens, cpu, expected):
    assert reward.cost_norm(tokens, cpu) == pytest.approx(expected)


@pytest.mark.parametrize("outcome,cost,feedback,expected", [
    (1, 0, 0.5, 0.9),     # passed, free, no feedback
    (1, 0, 1, 1.0),       # best case
    (0, 1, 0, 0.0),       # worst case
    (0.5, 0.5, 0.5, 0.5),
    (1, 0.25, 0, 0.75),
])
def test_reward_formula(outcome, cost, feedback, expected):
    assert reward.reward(outcome, cost, feedback) == pytest.approx(expected)


# ---- outcome (computed by code from the finished task) ------------------------------------------------------------

def task(status="done", capability="write_code", **output):
    return {"id": "t", "status": status, "capability": capability, "output": output}


def test_an_explicit_code_check_result_wins():
    assert reward.outcome_of(task(outcome="partial"))[0] == 0.5
    assert reward.outcome_of(task(status="done", outcome="failed"))[0] == 0


def test_failed_task_scores_zero():
    value, why = reward.outcome_of(task(status="failed", error_signature="ModuleNotFoundError:torchvision"))
    assert value == 0 and "ModuleNotFoundError" in why


def test_run_without_metric_lines_is_partial_and_with_them_passed():
    assert reward.outcome_of(task(capability="run", exit_code=0, metrics=0))[0] == 0.5
    value, why = reward.outcome_of(task(capability="run", exit_code=0, metrics=12))
    assert value == 1 and "12 metric" in why


def test_agent_stopped_by_its_budget_is_partial():
    assert reward.outcome_of(task(status="done", status_detail="x", agent_status="stopped"))[0] == 0.5
    assert reward.outcome_of(task(status="done", agent_status="finished"))[0] == 1


# ---- feedback -----------------------------------------------------------------------------------------------------

def test_feedback_latest_event_wins_and_none_is_neutral():
    evs = [{"task_id": "t", "data": {"value": "up"}, "ts": "2026-10-10T10:00:00Z"},
           {"task_id": "t", "data": {"value": "down"}, "ts": "2026-10-10T10:01:00Z"},
           {"task_id": "u", "data": {"value": "up"}, "ts": "2026-10-10T10:02:00Z"},
           {"task_id": "v", "data": {"value": "meh"}, "ts": "2026-10-10T10:02:00Z"}]
    fb = reward.latest_feedback(evs)
    assert reward.feedback_value(fb.get("t")) == 0
    assert reward.feedback_value(fb.get("u")) == 1
    assert reward.feedback_value(fb.get("v")) == 0.5  # unknown values are ignored
    assert reward.feedback_value(None) == 0.5


# ---- score a task -------------------------------------------------------------------------------------------------

def test_score_builds_the_rewards_row_and_a_reason_with_every_number():
    t = {"id": "t1", "agent_id": "a1", "status": "done", "capability": "run", "cpu_seconds": 300, "tokens": 0,
         "output": {"exit_code": 0, "metrics": 4}}
    s = reward.score(t, tokens=10_000, feedback=None)
    assert s.row == {"agent_id": "a1", "task_id": "t1", "outcome": 1, "cost_norm": 0.5, "feedback": 0.5,
                     "reward": pytest.approx(0.6 + 0.1 + 0.1)}
    for part in ("outcome 1", "cost 0.50", "10000 tokens", "300 CPU s", "feedback none", "reward 0.80"):
        assert part in s.reason


# ---- rolling mean per agent ---------------------------------------------------------------------------------------

def test_rolling_mean_uses_the_last_window_rewards_per_agent():
    rows = [{"agent_id": "a", "reward": r, "ts": f"2026-10-10T10:0{i}:00Z"} for i, r in enumerate([0.0, 1.0, 0.5, 0.9])]
    rows.append({"agent_id": "b", "reward": 0.2, "ts": "2026-10-10T10:00:00Z"})
    means = reward.rolling_means(rows)
    assert ROLLING_WINDOW == 3
    assert means["a"] == pytest.approx((1.0 + 0.5 + 0.9) / 3)
    assert means["b"] == pytest.approx(0.2)


# ---- who a crashed run counts against -----------------------------------------------------------------------------

def run_task(status="failed", sig="ModuleNotFoundError:torchvision", upstream=None):
    return {"id": "r1", "agent_id": "runner", "status": status, "capability": "run",
            "output": {"error_signature": sig} if sig else {"exit_code": 0, "metrics": 3},
            "input": {"upstream": upstream or {}}}


BY_ID = {"w": {"id": "w", "agent_id": "implementer", "capability": "write_code", "output": {"files": {}}},
         "d": {"id": "d", "agent_id": "debugger", "capability": "debug", "output": {"files": {"train.py": "v2"}}},
         "e": {"id": "e", "agent_id": "debugger", "capability": "debug", "output": {"requirements": "x"}}}


def test_a_crashed_run_counts_against_the_agent_that_wrote_the_code():
    agent_id, why = reward.charged_agent(run_task(upstream={"write_code": "w"}), BY_ID)
    assert agent_id == "implementer" and "wrote the code" in why


def test_a_debugger_that_changed_the_files_is_charged_over_the_implementer():
    assert reward.charged_agent(run_task(upstream={"write_code": "w", "debug": "d"}), BY_ID)[0] == "debugger"
    # a debug task that only changed the requirements did not write the code that crashed
    assert reward.charged_agent(run_task(upstream={"write_code": "w", "debug": "e"}), BY_ID)[0] == "implementer"


def test_successful_runs_and_runs_without_known_code_stay_with_their_agent():
    assert reward.charged_agent(run_task(status="done", sig=None, upstream={"write_code": "w"}), BY_ID) ==         ("runner", None)
    assert reward.charged_agent(run_task(upstream={}), BY_ID) == ("runner", None)
