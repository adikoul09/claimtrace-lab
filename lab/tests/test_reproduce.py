"""T10: the code checks around autonomous reproduction (SPEC §7.2-7.3). No LLM and no Supabase: the agents' answers
and the smoke run's metrics are given as data."""
import pytest

from lab.agents import reproduce as rp

CLAIMS = [
    {"id": "c7", "model": "Large neural net (1200 units/layer)", "metric": "test errors", "value": 67,
     "unit": "errors", "direction": "lower_is_better", "whose": "oracle", "valid": True, "page": 4,
     "quote": "This net achieved 67 test errors whereas ..."},
    {"id": "c8", "model": "Small net (800 units/layer)", "metric": "test errors", "value": 146, "unit": "errors",
     "direction": "lower_is_better", "whose": "baseline", "valid": True, "page": 4, "quote": "... achieved 146 errors."},
    {"id": "c9", "model": "Distilled small net", "metric": "test errors", "value": 74, "unit": "errors",
     "direction": "lower_is_better", "whose": "method", "valid": True, "page": 4, "quote": "... it achieved 74 test errors."},
    {"id": "c1", "model": "Distilled Single model", "metric": "WER", "value": 10.7, "unit": "%", "valid": False,
     "direction": "lower_is_better", "whose": "method", "page": 5, "quote": "Distilled Single model 60.8% 10.7%"},
]

DESIGN = {"experiment": "MNIST distillation", "reason": "the MNIST result fits on CPU",
          "models": [{"name": "teacher", "claim_id": "c7", "description": "2x1200 ReLU, dropout"},
                     {"name": "student_hard", "claim_id": "c8", "description": "2x800 ReLU, hard labels"},
                     {"name": "student_distilled", "claim_id": "c9", "description": "2x800, soft targets T=20"}]}


# ---- answers from agents -----------------------------------------------------------------------------------------

def test_parse_answer_accepts_fenced_json():
    assert rp.parse_answer('```json\n{"epochs": 5}\n```') == {"epochs": 5}
    assert rp.parse_answer('Here: {"epochs": 5, "reason": "x"}') == {"epochs": 5, "reason": "x"}


def test_parse_answer_rejects_non_json():
    with pytest.raises(rp.StepError, match="JSON"):
        rp.parse_answer("five epochs please")


# ---- design check ------------------------------------------------------------------------------------------------

def test_valid_design_passes_and_keeps_the_claim_map():
    d = rp.check_design(DESIGN, CLAIMS)
    assert d["claim_map"] == {"teacher": "c7", "student_hard": "c8", "student_distilled": "c9"}


@pytest.mark.parametrize("models, problem", [
    ([], "at least one model"),
    ([{"name": "Teacher Net", "claim_id": "c7"}], "snake_case"),
    ([{"name": "teacher", "claim_id": "c99"}], "no claim c99"),
    ([{"name": "teacher", "claim_id": "c1"}], "not valid"),
    ([{"name": "a", "claim_id": "c7"}, {"name": "a", "claim_id": "c8"}], "twice"),
])
def test_bad_designs_are_refused(models, problem):
    with pytest.raises(rp.StepError, match=problem):
        rp.check_design({**DESIGN, "models": models}, CLAIMS)


# ---- train.py contract -------------------------------------------------------------------------------------------

GOOD_SCRIPT = '''
import argparse, json, time
ap = argparse.ArgumentParser()
ap.add_argument("--data-dir"); ap.add_argument("--epochs", type=int); ap.add_argument("--subset", type=int)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
print("CONFIG " + json.dumps({"lr": 0.1}))
print("METRIC train_examples=60000 step=0"); print("METRIC train_examples_full=60000 step=0")
for name in ["teacher", "student_hard", "student_distilled"]:
    print(f"METRIC {name}_epoch_s=1.0 step=1")
    print(f"METRIC final_{name}=100 step=0")
'''


def test_script_meeting_the_contract_passes():
    assert rp.check_train_script(GOOD_SCRIPT, ["teacher", "student_hard", "student_distilled"]) == []


@pytest.mark.parametrize("script, problem", [
    ("def broken(:\n", "does not compile"),
    (GOOD_SCRIPT.replace("--subset", "--n"), "--subset"),
    (GOOD_SCRIPT.replace("METRIC", "RESULT"), "METRIC"),
    (GOOD_SCRIPT.replace("CONFIG", "CFG"), "CONFIG"),
    (GOOD_SCRIPT + "\nopen('../../papers/distillation/reference.py')\n", "golden"),
    (GOOD_SCRIPT + "\nimport json; json.load(open('results_full.json'))\n", "golden"),
])
def test_contract_problems_are_reported(script, problem):
    problems = rp.check_train_script(script, ["teacher"])
    assert any(problem in p for p in problems), problems


def test_implementer_goal_never_points_at_the_golden_reference():
    goal = rp.implementer_goal(rp.check_design(DESIGN, CLAIMS), CLAIMS, settings=[])
    assert "reference.py" not in goal and "results_full" not in goal and "papers/" not in goal
    assert "--subset" in goal and "METRIC final_teacher=" in goal and "74" in goal


# ---- smoke timing and budget (code decides) ---------------------------------------------------------------------

SMOKE_METRICS = [
    {"name": "train_examples", "value": 5000, "step": 0},
    {"name": "train_examples_full", "value": 60000, "step": 0},
    {"name": "teacher_epoch_s", "value": 1.0, "step": 1},
    {"name": "student_hard_epoch_s", "value": 0.25, "step": 1},
    {"name": "student_distilled_epoch_s", "value": 0.25, "step": 1},
    {"name": "teacher_test_errors", "value": 900, "step": 1},
]


def test_smoke_timing_scales_epoch_time_to_the_full_data():
    t = rp.smoke_timing(SMOKE_METRICS, wall_s=21.5, models=["teacher", "student_hard", "student_distilled"])
    assert t["scale"] == 12
    assert t["epoch_s_full"] == {"teacher": 12.0, "student_hard": 3.0, "student_distilled": 3.0}
    assert t["per_epoch_s"] == 18.0
    assert t["overhead_s"] == 20.0  # 21.5 s wall minus 1.5 s of epochs


def test_smoke_timing_needs_every_models_epoch_time():
    with pytest.raises(rp.StepError, match="student_distilled_epoch_s"):
        rp.smoke_timing(SMOKE_METRICS[:4], wall_s=10, models=["teacher", "student_hard", "student_distilled"])


TIMING = {"scale": 12, "epoch_s_full": {"teacher": 12.0, "student_hard": 3.0, "student_distilled": 3.0},
          "per_epoch_s": 18.0, "overhead_s": 20.0, "train_examples_full": 60000}


def test_budget_within_the_cap_is_kept_with_its_numbers_in_the_reason():
    b = rp.plan_budget({"epochs": 30, "reason": "converges by 30"}, TIMING, cap_s=1200, executor="laptop-b")
    assert (b["epochs"], b["subset"], b["clipped"]) == (30, 0, False)
    assert b["est_s"] == 20 + 30 * 18
    assert "30 epochs" in b["reason"] and "laptop-b" in b["reason"] and "18.0 s/epoch" in b["reason"]
    assert "converges by 30" in b["reason"]


def test_budget_over_the_cap_is_clipped_by_code():
    b = rp.plan_budget({"epochs": 100, "reason": "paper trains long"}, TIMING, cap_s=1200, executor="laptop-b")
    assert b["epochs"] == 65 and b["clipped"] is True  # (1200 - 20) // 18
    assert b["est_s"] <= 1200
    assert "proposed 100" in b["reason"]


def test_budget_too_small_for_one_full_epoch_uses_a_subset():
    b = rp.plan_budget({"epochs": 3, "reason": "x"}, TIMING, cap_s=29, executor="laptop-b")
    assert b["epochs"] == 1 and b["subset"] == 30000  # (29 - 20) / 18 = half the data
    assert b["est_s"] <= 29


def test_budget_rejects_a_bad_proposal_and_an_impossible_cap():
    with pytest.raises(rp.StepError, match="epochs"):
        rp.plan_budget({"epochs": 0}, TIMING, cap_s=1200, executor="x")
    with pytest.raises(rp.StepError, match="overhead"):
        rp.plan_budget({"epochs": 1}, TIMING, cap_s=15, executor="x")


def test_margin_is_declared_from_the_claim_unit():
    assert rp.declare_margin([c for c in CLAIMS if c["id"] in ("c7", "c8", "c9")]) == (10, rp.MARGIN_REASON["errors"])
    assert rp.declare_margin([CLAIMS[3]])[0] is None
