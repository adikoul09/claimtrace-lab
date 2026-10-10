"""Token guard (HoO-A): env-configurable attempt and refine limits, and a budget hold above the daily threshold."""
import importlib

from lab.controller import budget, rules


def test_defaults_are_two_attempts_one_refine_and_a_600k_hold(monkeypatch):
    for k in ("LAB_MAX_ATTEMPTS", "LAB_REFINE_CAP", "LAB_BUDGET_HOLD_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("lab.db._dotenv", lambda: {})
    r = importlib.reload(rules)
    assert (r.MAX_STEP_ATTEMPTS, r.MAX_DEBUG_ATTEMPTS, r.MAX_REFINES_PER_ROLE, r.BUDGET_HOLD_TOKENS) == (2, 2, 1, 600_000)


def test_the_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LAB_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LAB_REFINE_CAP", "2")
    monkeypatch.setenv("LAB_BUDGET_HOLD_TOKENS", "500000")
    r = importlib.reload(rules)
    assert (r.MAX_STEP_ATTEMPTS, r.MAX_REFINES_PER_ROLE, r.BUDGET_HOLD_TOKENS) == (3, 2, 500_000)
    monkeypatch.setenv("LAB_MAX_ATTEMPTS", "not a number")
    assert importlib.reload(rules).MAX_STEP_ATTEMPTS == 2          # a bad value falls back to the default
    monkeypatch.delenv("LAB_MAX_ATTEMPTS")
    monkeypatch.delenv("LAB_REFINE_CAP")
    monkeypatch.delenv("LAB_BUDGET_HOLD_TOKENS")
    importlib.reload(rules)


def test_only_runs_and_code_compares_continue_on_hold():
    assert not budget.needs_llm("run") and not budget.needs_llm("compare")
    for cap in ("plan", "read_paper", "design_experiment", "write_code", "debug", "explain_diff", "design_whatif",
                "write_report"):
        assert budget.needs_llm(cap)


def test_hold_threshold_and_the_hold_cap():
    assert budget.on_hold(600_000, 600_000) and not budget.on_hold(599_999, 600_000)
    caps = budget.held(["agent", "host:laptop-b"])
    assert caps == ["agent", "host:laptop-b", budget.HOLD_CAP] and budget.held(caps) == caps   # idempotent
    assert budget.released(caps) == ["agent", "host:laptop-b"]
