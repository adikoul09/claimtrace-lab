"""Integration item 2/3: the reproduction plan order (code-checked), the wiring of a step's inputs from earlier
outputs (docs/CONTRACTS.md §3), the planner's agent choice, and decisions on awaiting tasks."""
import pytest

from lab.controller import assign, planner, wiring
from lab.schemas import PlanStep


def st(cap, scale=None, **kw):
    return {"capability": cap, "title": cap, "instructions": f"do {cap}", "acceptance": "ok", "budget_cpu_s": 60,
            **({"scale": scale} if scale else {}), **kw}


GOOD = [st("read_paper"), st("design_experiment"), st("write_code"), st("setup_env"), st("run", "smoke"),
        st("budget"), st("run", "full"), st("compare"), st("write_report")]


# ---- order --------------------------------------------------------------------------------------------------------

def test_the_reproduction_order_passes():
    res = planner.check_plan({"reason": "r", "steps": GOOD}, budget_cpu_min=20)
    assert [s.capability for s in res.steps] == [s["capability"] for s in GOOD]


def test_alternatives_in_a_slot_are_allowed():
    steps = [st("extract_claims")] + GOOD[1:7] + [st("explain_diff"), st("write_report")]
    planner.check_plan({"reason": "r", "steps": steps}, budget_cpu_min=20)


@pytest.mark.parametrize("steps", [
    GOOD[:2] + [GOOD[3], GOOD[2]] + GOOD[4:],                         # setup_env before write_code
    GOOD[:4] + [GOOD[6], GOOD[5], GOOD[4]] + GOOD[7:],                # full run before smoke
    GOOD[:-1],                                                        # no report
    GOOD + [st("write_notes")],                                       # an extra step
    GOOD[:4] + [st("run")] + GOOD[5:],                                # smoke without a scale is not accepted here
], ids=["env-before-code", "full-before-smoke", "missing-step", "extra-step", "unscaled-run"])
def test_any_other_order_is_rejected(steps):
    with pytest.raises(planner.PlanError, match="order"):
        planner.check_plan({"reason": "r", "steps": steps}, budget_cpu_min=20)


def test_the_planner_gets_a_second_chance_with_the_rejection_reason():
    calls = []

    class FakeLLM:
        def call(self, req, task_id=None):
            calls.append(req.prompt)
            out = {"reason": "r", "steps": GOOD[::-1]} if len(calls) == 1 else {"reason": "fixed", "steps": GOOD}
            return type("R", (), {"output": out, "tokens_in": 1, "tokens_out": 1, "model": "m", "mode": "replay"})()

    plan, _ = planner.make_plan(FakeLLM(), {"budget_cpu_min": 20}, None, [], [])
    assert plan.reason == "fixed" and len(calls) == 2 and "order" in calls[1]


# ---- the planner's agent choice -----------------------------------------------------------------------------------

AGENTS = [{"id": "a1", "name": "designer-v1", "capabilities": ["design_experiment"], "status": "active", "version": 1},
          {"id": "a2", "name": "designer-v2", "capabilities": ["design_experiment"], "status": "active", "version": 2},
          {"id": "a3", "name": "reader-v1", "capabilities": ["read_paper"], "status": "active", "version": 1}]


def test_the_planners_agent_is_used_when_it_is_active_and_able():
    pick = assign.pick_agent(AGENTS, "design_experiment", {"a2": 0.9}, preferred="designer-v1")
    assert pick.agent["id"] == "a1" and "planner" in pick.reason


def test_an_unfit_planner_choice_falls_back_to_rolling_reward_with_a_note():
    pick = assign.pick_agent(AGENTS, "design_experiment", {"a2": 0.9}, preferred="reader-v1")
    assert pick.agent["id"] == "a2" and "reader-v1" in pick.reason


# ---- wiring -------------------------------------------------------------------------------------------------------

def task(cap, step, status="done", ts="2026-10-10T10:00:00Z", **output):
    return {"id": f"{cap}-{step}-{ts}", "capability": cap, "status": status, "created_at": ts,
            "input": {"step": step}, "output": output}


def test_upstream_is_the_latest_done_task_of_each_earlier_step():
    steps = [PlanStep(**s) for s in GOOD]
    tasks = [task("read_paper", 0), task("design_experiment", 1, status="failed"),
             task("design_experiment", 1, ts="2026-10-10T11:00:00Z"), task("write_code", 2)]
    up = wiring.upstream(steps, tasks, 3)
    assert up == {"read_paper": "read_paper-0-2026-10-10T10:00:00Z",
                  "design_experiment": "design_experiment-1-2026-10-10T11:00:00Z",
                  "write_code": "write_code-2-2026-10-10T10:00:00Z"}


def test_run_inputs_come_from_code_env_budget_and_later_debug_fixes():
    steps = [PlanStep(**s) for s in GOOD]
    tasks = [task("design_experiment", 1, margin=10, margin_reason="floor", config={"claim_map": {"teacher": "c1"}}),
             task("write_code", 2, files={"train.py": "v1"}), task("setup_env", 3, requirements="torch==2.4.0"),
             task("run", 4), task("budget", 5, epochs=5, subset=0, seeds=[0, 1], reason="5 epochs fit")]
    debugs = [{"id": "d", "capability": "debug", "status": "done", "created_at": "2026-10-10T12:00:00Z",
               "input": {}, "output": {"files": {"train.py": "v2"}, "repair_label": "REPAIR(code)"}}]
    smoke, problems = wiring.run_input(steps, tasks, debugs, 4, "runs/p")
    assert not problems
    assert smoke["cmd"] == "python train.py --data-dir ../../data --epochs 1 --subset 5000 --seed 0"
    assert smoke["files"] == {"train.py": "v2"} and smoke["requirements"] == "torch==2.4.0"
    full, problems = wiring.run_input(steps, tasks, debugs, 6, "runs/p")
    assert not problems
    assert full["cmd"] == "python train.py --data-dir ../../data --epochs 5 --subset 0 --seed 0"
    assert full["experiment"]["margin"] == 10 and full["experiment"]["budget_reason"] == "5 epochs fit"
    # the Analyst and the Report read experiments.config.claim_map, so the design's config is copied as is
    assert full["experiment"]["config"]["claim_map"] == {"teacher": "c1"}
    assert full["experiment"]["config"]["budget"] == {"epochs": 5, "subset": 0, "seeds": [0, 1]}


def test_upstream_run_at_compare_is_the_full_run_and_debug_is_included():
    steps = [PlanStep(**s) for s in GOOD]
    tasks = [task("run", 4, experiment_id="smoke-exp"), task("budget", 5),
             task("run", 6, ts="2026-10-10T11:00:00Z", experiment_id="full-exp")]
    debugs = [{"id": "d1", "capability": "debug", "status": "done", "created_at": "2026-10-10T10:30:00Z",
               "input": {}, "output": {}}]
    up = wiring.upstream(steps, tasks, 7, debugs)
    assert up["run"] == "run-6-2026-10-10T11:00:00Z" and up["debug"] == "d1"
    assert wiring.upstream(steps, tasks, 5, [])["run"] == "run-4-2026-10-10T10:00:00Z"


def test_missing_upstream_outputs_are_reported_not_invented():
    steps = [PlanStep(**s) for s in GOOD]
    _, problems = wiring.run_input(steps, [task("write_code", 2)], [], 6, "runs/p")
    assert any("train.py" in p for p in problems)
    assert any("requirements" in p for p in problems)
    assert any("epochs" in p for p in problems)


# ---- decisions ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("decision,status", [("approve", "queued"), ("reject", "rejected"), ("redirect", "rejected")])
def test_decision_moves_an_awaiting_task(decision, status):
    assert wiring.status_after(decision) == status


# ---- redirect: replan one step with the researcher's note ---------------------------------------------------------

class OneShot:
    def __init__(self, out):
        self.out, self.prompts = out, []

    def call(self, req, task_id=None):
        self.prompts.append(req.prompt)
        return type("R", (), {"output": self.out, "tokens_in": 1, "tokens_out": 1, "model": "m", "mode": "replay"})()


def test_replan_step_puts_the_note_in_the_prompt_and_keeps_the_slot():
    steps = [PlanStep(**s) for s in GOOD]
    llm = OneShot({"reason": "use 3 seeds as asked", "step": st("budget", budget_cpu_s=99_999, agent="designer-v1")})
    new, reason, _ = planner.replan_step(llm, {"budget_cpu_min": 20}, steps, 5, "use 3 seeds")
    assert "use 3 seeds" in llm.prompts[0]
    assert new.capability == "budget" and new.agent == "designer-v1" and new.budget_cpu_s == 1200
    assert reason == "use 3 seeds as asked"


def test_replan_step_cannot_change_the_capability_or_scale():
    steps = [PlanStep(**s) for s in GOOD]
    with pytest.raises(planner.PlanError):
        planner.replan_step(OneShot({"reason": "r", "step": st("write_code")}), {"budget_cpu_min": 20}, steps, 5, "n")
    with pytest.raises(planner.PlanError):
        planner.replan_step(OneShot({"reason": "r", "step": st("run", "smoke")}), {"budget_cpu_min": 20}, steps, 6, "n")
