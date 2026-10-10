"""T11: verdicts by code (SPEC §7.5) and the explanation's number check. The golden reference is B0's full run v2
(papers/distillation/results_full_v2.json): its numbers stand in for a reproduction's final metrics."""
import json
from pathlib import Path

import pytest

from lab.agents import analyst as an

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "papers" / "distillation" / "results_full_v2.json").read_text(encoding="utf-8"))

CLAIMS = [
    {"id": "c7", "model": "Large neural net", "metric": "test errors", "value": 67, "unit": "errors",
     "direction": "lower_is_better", "whose": "oracle", "valid": True, "page": 4, "quote": "67 test errors"},
    {"id": "c8", "model": "Small net", "metric": "test errors", "value": 146, "unit": "errors",
     "direction": "lower_is_better", "whose": "baseline", "valid": True, "page": 4, "quote": "146 errors"},
    {"id": "c9", "model": "Distilled small net", "metric": "test errors", "value": 74, "unit": "errors",
     "direction": "lower_is_better", "whose": "method", "valid": True, "page": 4, "quote": "74 test errors"},
]
CLAIM_MAP = {"teacher": "c7", "student_hard": "c8", "student_distilled": "c9"}


def finals_from_golden():
    return {name: {"value": m["test_errors"], "log_line": 100 + i}
            for i, (name, m) in enumerate(GOLDEN["models"].items())}


def by_id(grades):
    return {g["claim_id"]: g for g in grades["claims"]}


# ---- absolute claims ---------------------------------------------------------------------------------------------

def test_golden_run_grades_as_expected():
    g = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1)
    v = by_id(g)
    assert (v["c8"]["ours"], v["c8"]["delta"], v["c8"]["verdict"]) == (143, -3, "Reproduced")       # 143 vs 146
    assert (v["c7"]["ours"], v["c7"]["verdict"]) == (80, "Partially reproduced")                    # +13, order holds
    assert (v["c9"]["ours"], v["c9"]["verdict"]) == (96, "Partially reproduced")                    # +22, order holds
    assert all(x["label"].endswith("(1 seed)") for x in g["claims"])
    assert v["c9"]["log_line"] == 102 and v["c9"]["metric_name"] == "final_student_distilled"


def test_claim_far_off_with_its_relation_broken_is_not_reproduced():
    finals = {"teacher": {"value": 80, "log_line": 1}, "student_hard": {"value": 143, "log_line": 2},
              "student_distilled": {"value": 9020, "log_line": 3}}  # v1: the diverged student
    v = by_id(an.grade(CLAIMS, CLAIM_MAP, finals, margin=10, seeds=1))
    assert v["c9"]["verdict"] == "Not reproduced"
    assert "c9 better than c8" in v["c9"]["broken_relations"]


def test_missing_final_metric_or_failed_run_is_not_runnable():
    finals = finals_from_golden()
    del finals["student_distilled"]
    assert by_id(an.grade(CLAIMS, CLAIM_MAP, finals, margin=10, seeds=1))["c9"]["verdict"] == "Not runnable"
    g = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1, ran=False)
    assert {x["verdict"] for x in g["claims"]} == {"Not runnable"}


def test_three_seeds_drop_the_seed_note_and_exact_margin_counts_as_reproduced():
    finals = {"teacher": {"value": 77, "log_line": 1}, "student_hard": {"value": 136, "log_line": 2},
              "student_distilled": {"value": 84, "log_line": 3}}
    v = by_id(an.grade(CLAIMS, CLAIM_MAP, finals, margin=10, seeds=3))
    assert v["c7"]["verdict"] == "Reproduced" and v["c7"]["delta"] == 10
    assert "seed" not in v["c7"]["label"]


def test_margin_is_required_before_grading():
    with pytest.raises(ValueError, match="margin"):
        an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=None, seeds=1)


# ---- relative claim (method vs baseline gap) -----------------------------------------------------------------------

def test_relative_claim_on_the_golden_run_holds_in_direction_but_gap_is_smaller():
    rel = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1)["relative"]
    assert len(rel) == 1
    r = rel[0]
    assert (r["method"], r["baseline"]) == ("c9", "c8")
    assert (r["paper_gap"], r["ours_gap"]) == (72, 47)       # 146-74, 143-96
    assert r["verdict"] == "Partially reproduced" and r["size_note"] == "gap smaller than reported"


def test_relative_claim_with_reversed_direction_is_not_reproduced():
    finals = {**finals_from_golden(), "student_distilled": {"value": 150, "log_line": 9}}
    r = an.grade(CLAIMS, CLAIM_MAP, finals, margin=10, seeds=1)["relative"][0]
    assert r["verdict"] == "Not reproduced"


# ---- golden reference column ------------------------------------------------------------------------------------

def test_reference_values_attach_by_the_paper_value():
    ref = an.reference_values(GOLDEN)
    assert ref == {67: 80, 146: 143, 74: 96}
    v = by_id(an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1, reference=ref))
    assert v["c9"]["reference"] == 96


# ---- number check on the explanation ------------------------------------------------------------------------------

def test_explanation_using_only_table_numbers_passes():
    g = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1)
    text = ("The small net reproduced: 143 errors against the paper's 146, inside the margin of 10. The distilled "
            "net made 96 errors (paper 74, +22), so the gap to the small net is 47 instead of 72, from 1 seed. "
            "Claim c9 still beats c8 on 10,000 test images.")
    assert an.number_check(text, g, allowed_extra=[10000]) == []


def test_explanation_with_an_invented_number_is_rejected():
    g = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1)
    text = "The distilled net made 96 errors, about 30% worse than the paper, after 45 epochs."
    assert an.number_check(text, g) == ["30%", "45"]


def test_number_check_handles_signs_decimals_and_rounding():
    tables = {"claims": [{"ours": 96.4, "paper": 74, "delta": -2.25}], "relative": []}
    assert an.number_check("96.4 vs 74, a change of 2.25 (or -2.25, about 2.3)", tables) == ["2.3"]
    assert an.number_check("ours 96 errors", tables) == ["96"]  # 96.4 is not 96: no silent rounding


# ---- explanation flow (fake agent; the number check decides) -----------------------------------------------------

class _Rows:
    def __init__(self, rows):
        self.data = rows

    def __getattr__(self, _):  # select/eq/contains/order: the fake ignores filters
        return lambda *a, **k: self

    def execute(self):
        return self


class _DB:
    def table(self, _):
        return _Rows([{"id": "a1", "name": "analyst-v1", "capabilities": ["explain_diff"]}])


def _fake_agent(answers, seen):
    from lab.agents.runtime import RunResult

    def run_agent(agent, goal, workdir, **kw):
        seen.append(goal)
        return RunResult("finished", answers.pop(0), "done", 1, 10, 0.1)
    return run_agent


def test_explanation_with_unknown_numbers_is_retried_then_accepted(monkeypatch):
    from lab.agents import runtime
    seen = []
    monkeypatch.setattr(runtime, "run_agent", _fake_agent(["About 30% worse.", "96 errors against 74."], seen))
    g = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1)
    out = an.explain(_DB(), g, "exp", None)
    assert out["accepted"] and out["text"] == "96 errors against 74."
    assert "30%" in seen[1]  # the retry names the rejected number


def test_explanation_failing_twice_is_rejected_and_not_shown(monkeypatch):
    from lab.agents import runtime
    monkeypatch.setattr(runtime, "run_agent", _fake_agent(["After 45 epochs.", "After 45 epochs, still."], []))
    g = an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1)
    out = an.explain(_DB(), g, "exp", None)
    assert out["accepted"] is False and out["text"] is None
    assert "45" in out["problems"][0]


# ---- experiments.verdicts list (docs/CONTRACTS.md §5) -------------------------------------------------------------

def test_verdict_items_follow_the_contract_list():
    items = an.verdict_items(an.grade(CLAIMS, CLAIM_MAP, finals_from_golden(), margin=10, seeds=1))
    by = {i["claim_id"]: i for i in items}
    assert set(by) == {"c7", "c8", "c9", "c9_vs_c8"}
    assert by["c8"] == {"claim_id": "c8", "verdict": "reproduced", "ours": 143, "paper": 146, "margin": 10,
                        "note": by["c8"]["note"], "log_line": 101}
    assert by["c9"]["verdict"] == "partially reproduced" and by["c9"]["note"].startswith("(1 seed)")
    assert (by["c9_vs_c8"]["ours"], by["c9_vs_c8"]["paper"]) == (47, 72)
    assert "gap smaller than reported" in by["c9_vs_c8"]["note"]


def test_not_runnable_item_has_null_ours_and_no_log_line():
    finals = finals_from_golden()
    del finals["student_distilled"]
    by = {i["claim_id"]: i for i in an.verdict_items(an.grade(CLAIMS, CLAIM_MAP, finals, margin=10, seeds=3))}
    assert (by["c9"]["verdict"], by["c9"]["ours"], by["c9"]["log_line"]) == ("not runnable", None, None)
    assert not by["c9"]["note"].startswith("(")  # 3 seeds: no seed note
