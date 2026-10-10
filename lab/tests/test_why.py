"""T19: why results differ (SPEC §7.5): the settings diff (paper vs ours, labelled by code) and the branch effects
for the rows a what-if branch tested."""
from lab.agents import why

SETTINGS = [
    {"key": "hidden_units", "applies_to": "teacher", "value": "1200 rectified linear hidden units", "page": 3,
     "quote": "two hidden layers of 1200 rectified linear hidden units", "valid": True},
    {"key": "temperature", "applies_to": "student_distilled", "value": "20", "page": 4,
     "quote": "at a temperature of 20", "valid": True},
    {"key": "regularisation", "applies_to": "teacher", "value": "dropout and weight-constraints", "page": 3,
     "quote": "regularized using dropout and weight-constraints", "valid": True},
    {"key": "lr", "applies_to": "all", "value": None, "quote": None, "page": None, "valid": True},
    {"key": "epochs", "applies_to": "all", "value": None, "quote": None, "page": None, "valid": True},
    {"key": "batch", "applies_to": "all", "value": None, "quote": None, "page": None, "valid": True},
    {"key": "hidden_units", "applies_to": "speech", "value": "2560 rectified linear units", "page": 4,
     "quote": "8 hidden layers each containing 2560 rectified linear units", "valid": True},
    {"key": "data_subset", "applies_to": "speech", "value": "3% of the data", "page": 7,
     "quote": "with only 3% of the data", "valid": True},
]
OURS = {"hidden": {"teacher": 1200, "student": 800}, "lr": {"teacher": 0.03, "student": 0.1}, "temperature": 5,
        "dropout": {"input": 0.2, "hidden": 0.5}, "max_norm": 3.5, "batch_size": 128, "optimizer": "SGD"}
BUDGET = {"epochs": 12, "subset": 0, "seeds": [0]}


def rows_by(rows):
    return {(r["key"], r.get("our_key")): r for r in rows}


def test_each_paper_setting_gets_a_code_label():
    rows = rows_by(why.settings_diff(SETTINGS[:6], OURS, BUDGET))
    assert rows[("hidden_units", "hidden.teacher")]["label"] == "same"          # 1200 in both
    assert rows[("temperature", "temperature")]["label"] == "difference"        # paper 20, ours 5
    assert rows[("regularisation", "dropout.input")]["label"] == "same"         # dropout is used
    assert rows[("lr", "lr.student")]["label"] == "paper omission"
    assert rows[("epochs", "epochs")]["label"] == "paper omission" and rows[("epochs", "epochs")]["ours"] == 12
    assert rows[("batch", "batch_size")]["ours"] == 128


def test_rows_keep_quote_page_and_numbers_for_the_explanation():
    r = rows_by(why.settings_diff(SETTINGS[:2], OURS, BUDGET))[("temperature", "temperature")]
    assert (r["paper"], r["quote"], r["page"]) == ("20", "at a temperature of 20", 4)
    assert (r["paper_numbers"], r["our_numbers"]) == ([20], [5])


def test_a_stated_scale_setting_cut_by_the_budget_is_a_scale_reduction():
    stated = [{"key": "epochs", "applies_to": "all", "value": "3000 epochs", "page": 3, "quote": "for 3000 epochs",
               "valid": True}]
    r = why.settings_diff(stated, OURS, BUDGET)[0]
    assert (r["label"], r["ours"]) == ("scale reduction (budget)", 12)


def test_only_the_designs_settings_are_compared_when_it_names_them():
    rows = why.settings_diff(SETTINGS, OURS, BUDGET, used={"s1", "s2", "s3"})
    assert {r["key"] for r in rows} == {"hidden_units", "temperature", "regularisation", "lr", "epochs", "batch"}
    assert not any("2560" in str(r["paper"]) for r in rows)  # the speech model's setting is left out


def test_setting_without_a_matching_config_key_says_so():
    r = why.settings_diff([{"key": "augmentation", "applies_to": "teacher", "value": "jittered by up to two pixels",
                            "page": 3, "quote": "jittered by up to two pixels", "valid": True}], OURS, BUDGET)[0]
    assert (r["our_key"], r["label"]) == (None, "difference") and "no CONFIG key" in r["why"]


def test_branch_effects_attach_to_the_rows_they_tested():
    rows = why.settings_diff(SETTINGS[:2], OURS, BUDGET)
    branches = [{"id": "b1", "key": "temperature", "value": 20, "decision": "extend", "effect": -40, "score": 4,
                 "model": "student_distilled", "experiment_id": "e1", "full_effect": -18}]
    out = why.attach_effects(rows, branches)
    t = rows_by(out)[("temperature", "temperature")]
    assert t["branch_effects"] == [{"branch_id": "b1", "value": 20, "model": "student_distilled", "smoke_effect": -40,
                                    "score": 4, "decision": "extend", "full_effect": -18, "experiment_id": "e1"}]
    assert rows_by(out)[("hidden_units", "hidden.teacher")]["branch_effects"] == []
