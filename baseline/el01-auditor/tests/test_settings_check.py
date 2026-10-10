"""The Phase 5 checker is not vacuous: in-memory mutations of the recorded settings make it fail where they should."""
import copy
import json

import pytest

from el01.config import Paths
from el01.diff import spike
from el01.extract import settings as S


@pytest.fixture(scope="module")
def data():
    paths = Paths.make()
    try:
        settings, diffs = S.load_settings(paths, "matchdg")
    except FileNotFoundError:
        pytest.skip("no settings.json yet")
    return settings, diffs, json.loads((paths.golden / "findings.json").read_text())


def rediff(settings, diffs, target):
    t = next(x for x in settings["tables"] if x["target"] == target)
    d = next(x for x in diffs["tables"] if x["target"] == target)
    d.update(S.diff_pairings(t["runs"]))


def code_runs(settings, target):
    t = next(x for x in settings["tables"] if x["target"] == target)
    return [v for k, v in t["runs"].items() if k.startswith("code_")]


def test_committed_result_passes(data):
    out = spike.check(*data)
    assert out["pass"], (out["table1"]["summary"], out["table11"] and out["table11"]["code_runs"])


def test_no_augmented_selection_fails_f7(data):
    settings, diffs, golden = copy.deepcopy(data)
    for r in code_runs(settings, spike.TABLE11):
        v = r["settings"]["train.model_selection_data"]
        v["value"] = [e for e in v["value"] or [] if e.get("version") != "augmented"]
    rediff(settings, diffs, spike.TABLE11)
    out = spike.check(settings, diffs, golden)
    assert not out["table11"]["pass"] and out["table11"]["summary"]["F7"]["found_in"].startswith("0/")


def test_paper_value_in_code_hides_f2(data):
    settings, diffs, golden = copy.deepcopy(data)
    paper = next(x for x in settings["tables"] if x["target"] == spike.TABLE1)["runs"]["paper_run1"]
    for r in code_runs(settings, spike.TABLE1):
        r["settings"]["train.model_selection"]["value"] = paper["settings"]["train.model_selection"]["value"]
    rediff(settings, diffs, spike.TABLE1)
    out = spike.check(settings, diffs, golden)
    assert not out["table1"]["pass"] and not out["table1"]["summary"]["F2"]["all_pairings"]


def test_unverified_citation_fails_f7(data):
    settings, diffs, golden = copy.deepcopy(data)
    for r in code_runs(settings, spike.TABLE11):
        for k in ("data.augmentation", "train.model_selection_data"):
            for c in r["settings"][k]["checks"]:
                if c["file"] == "data/mnist_loader_match_eval.py":
                    c["ok"] = False
    out = spike.check(settings, diffs, golden)
    assert not out["table11"]["pass"]
    assert all(not v["citations_verified"]["data/mnist_loader_match_eval.py:38"]
               for v in out["table11"]["code_runs"].values())


def test_new_findings_are_one_group_per_setting_across_runs():
    f = lambda m, code, ev="verified": {"key": "optim.lr_schedule", "kind": "paper omission", "method": m,
                                        "paper": None, "code": code, "evidence": {"paper": "null", "code": ev}}
    pairings = {"paper_run1 x code_run1": [f("ERM", "step"), f("RandMatch", "step")],
                "paper_run1 x code_run2": [f("erm_match", "step(25)")],
                "paper_run2 x code_run1": [f("ERM", "step")]}
    groups = spike.new_findings(spike.TABLE11, pairings)
    assert len(groups) == 1 and len(groups[0]["pairings"]) == 3
    assert groups[0]["methods"] == ["ERM", "RandMatch", "erm_match"] and len(groups[0]["variants"]) == 3
    assert next(v for v in groups[0]["variants"] if v["method"] == "ERM")["pairings"] == \
        ["paper_run1 x code_run1", "paper_run2 x code_run1"]
    pr = spike.precision(spike.TABLE11, {**pairings, "x": [{"key": "optim.momentum", "kind": "paper omission",
                                                            "method": "all", "code": 0.9}]})
    assert (pr["known"], pr["new_unverified"], pr["precision_lower_bound"]) == (1, 1, "1/2")


def test_f8_is_known_only_in_the_f1_to_f8_count():
    se = {"key": "eval.aggregation", "kind": "difference", "method": "Source columns (test.py)",
          "paper": "mean_sd_over_seeds", "code": "mean_se_over_seeds (np.std/sqrt(n))",
          "evidence": {"paper": "verified", "code": "verified"}}
    assert spike.is_f8(se)
    assert not spike.is_f8({**se, "code": "mean_sd_over_seeds (np.std)"})
    assert not spike.is_f8({**se, "paper": "mean and standard error"})
    pairings = {"paper_run1 x code_run1": [se, {"key": "optim.momentum", "kind": "paper omission", "method": "all",
                                                 "code": 0.9}]}
    assert spike.precision(spike.TABLE1, pairings, spike.KNOWN_F7)["precision_lower_bound"] == "1/2"
    assert spike.precision(spike.TABLE1, pairings, spike.KNOWN)["precision_lower_bound"] == "2/2"
    assert spike.new_findings(spike.TABLE1, pairings) == []


def test_target_validation_print_is_a_false_alarm_counted_as_false():
    fa = {"key": "train.model_selection_data", "kind": "difference", "use": "checkpoint", "method": None,
          "paper": {"split": "val", "domains": "source", "version": "plain"},
          "code": {"split": "test", "domains": "target", "version": "plain"}, "evidence": {}}
    pairings = {"p1 x c1": [fa, {"key": "optim.momentum", "kind": "paper omission", "method": "all", "code": 0.9}]}
    pr = spike.precision(spike.TABLE1, pairings)
    assert (pr["known"], pr["false_alarms"], pr["new_unverified"], pr["precision_lower_bound"]) == (1, 1, 0, "1/2")
    assert spike.new_findings(spike.TABLE1, pairings)[0]["status"] == "false alarm: target-validation print"
    assert spike.false_alarm({**fa, "code": {"split": "val", "domains": "source", "version": "augmented"}}) is None
