"""T18: what-if fan-out (SPEC §7.4). Code checks that every branch changes exactly one setting of the parent's
CONFIG, ranks the branches' smoke runs by |effect| against the noise, prunes and picks the one to extend."""
import shlex

import pytest

from lab.agents import whatif as wi
from lab.agents.reproduce import StepError

PARENT = {"optimizer": "SGD", "lr": {"teacher": 0.03, "student": 0.1}, "temperature": 20, "batch": 128,
          "soft_weight": 0.9}


# ---- parent CONFIG ------------------------------------------------------------------------------------------------

def test_config_line_is_parsed_with_its_log_line():
    lines = ["start", 'CONFIG {"lr": 0.1, "temperature": 20}', "METRIC a=1 step=0"]
    assert wi.parse_config(lines) == ({"lr": 0.1, "temperature": 20}, 2)


def test_missing_or_broken_config_line_is_an_error():
    with pytest.raises(StepError, match="CONFIG"):
        wi.parse_config(["METRIC a=1 step=0"])
    with pytest.raises(StepError, match="CONFIG"):
        wi.parse_config(["CONFIG {not json"])


def test_flatten_uses_dotted_keys():
    assert wi.flatten(PARENT)["lr.student"] == 0.1 and "lr" not in wi.flatten(PARENT)


# ---- one-key check ----------------------------------------------------------------------------------------------

BRANCHES = [{"key": "temperature", "value": 5, "reason": "lower T"},
            {"key": "lr.student", "value": 0.03, "reason": "the v1 divergence"},
            {"key": "soft_weight", "value": 0.5, "reason": "more hard-label weight"}]


def test_three_one_key_branches_pass_with_their_parent_values():
    out = wi.check_branches(BRANCHES, PARENT)
    assert [(b["id"], b["key"], b["parent_value"], b["value"]) for b in out] == [
        ("b1", "temperature", 20, 5), ("b2", "lr.student", 0.1, 0.03), ("b3", "soft_weight", 0.9, 0.5)]
    assert all(b["config"] == {**wi.flatten(PARENT), b["key"]: b["value"]} for b in out)


@pytest.mark.parametrize("branches, problem", [
    (BRANCHES[:2], "3 to 4"),
    (BRANCHES + BRANCHES[:2], "3 to 4"),
    ([*BRANCHES[:2], {"key": "temperature", "value": 20}], "does not change"),
    ([*BRANCHES[:2], {"key": "momentum", "value": 0.5}], "not in the parent CONFIG"),
    ([*BRANCHES[:2], {"key": "lr", "value": 0.01}], "not in the parent CONFIG"),  # a dict: more than one setting
    ([*BRANCHES[:2], {"key": ["lr.student", "batch"], "value": [1, 2]}], "exactly one"),
    ([*BRANCHES[:2], {"key": "temperature", "value": 5}], "twice"),
])
def test_branches_that_do_not_change_exactly_one_key_are_refused(branches, problem):
    with pytest.raises(StepError, match=problem):
        wi.check_branches(branches, PARENT)


def test_branch_command_adds_one_quoted_set_argument():
    cmd = wi.branch_cmd("python train.py --epochs 1", "optimizer", "Adam W")
    assert shlex.split(cmd)[-2:] == ["--set", 'optimizer="Adam W"']


# ---- noise and ranking ---------------------------------------------------------------------------------------------

def test_noise_is_the_seed_spread_or_the_margin_with_one_seed():
    assert wi.noise([96], margin=10) == (10, "margin 10 (1 seed: no seed spread to measure)")
    n, src = wi.noise([96, 100, 104], margin=10)
    assert n == 4 and "sd over 3 seeds" in src


PARENT_FINALS = {"teacher": 300, "student_hard": 260, "student_distilled": 280}


def results(**effects):
    """branch id -> finals with the distilled student moved by `effect`; None = the smoke run failed."""
    return {b: None if e is None else {**PARENT_FINALS, "student_distilled": PARENT_FINALS["student_distilled"] + e}
            for b, e in effects.items()}


def by_id(ranking):
    return {r["id"]: r for r in ranking}


def test_top_branch_is_extended_and_inside_noise_ones_are_pruned():
    r = by_id(wi.rank(results(b1=-40, b2=4, b3=-12), PARENT_FINALS, ["student_distilled"], noise=10))
    assert r["b1"]["decision"] == "extend" and r["b1"]["effect"] == -40 and r["b1"]["score"] == 4
    assert r["b2"]["decision"] == "pruned" and "inside noise" in r["b2"]["reason"]
    assert r["b3"]["decision"] == "kept"


def test_when_nothing_is_inside_noise_the_lowest_is_still_pruned():
    r = by_id(wi.rank(results(b1=-40, b2=25, b3=-30), PARENT_FINALS, ["student_distilled"], noise=10))
    assert (r["b1"]["decision"], r["b2"]["decision"], r["b3"]["decision"]) == ("extend", "pruned", "kept")
    assert "smallest effect" in r["b2"]["reason"]


def test_failed_smoke_runs_are_pruned_with_their_error():
    r = by_id(wi.rank(results(b1=-40, b2=None, b3=-12), PARENT_FINALS, ["student_distilled"], noise=10,
                      errors={"b2": "ModuleNotFoundError: torchvision"}))
    assert r["b2"]["decision"] == "pruned" and "torchvision" in r["b2"]["reason"]


def test_extend_still_names_the_top_branch_when_all_effects_are_noise():
    r = by_id(wi.rank(results(b1=-3, b2=2, b3=1), PARENT_FINALS, ["student_distilled"], noise=10))
    assert r["b1"]["decision"] == "extend" and "inside noise" in r["b1"]["reason"]
    assert r["b2"]["decision"] == r["b3"]["decision"] == "pruned"
