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


def test_subset_zero_is_the_full_training_set_not_a_budget_cut():
    """Live 42fb4944: --subset 0 (all data) was labelled 'scale reduction (budget)' against 'all 60,000 cases'."""
    stated = [{"key": "data_subset", "applies_to": "teacher", "value": "all 60,000 training cases", "page": 3,
               "quote": "trained on all 60,000 training cases", "valid": True},
              {"key": "data_subset", "applies_to": "speech", "value": "3% of the data", "page": 7,
               "quote": "with only 3% of the data", "valid": True}]
    rows = why.settings_diff(stated, {"data_subset": 0}, BUDGET)
    assert [r["label"] for r in rows] == ["same", "difference"]
    assert all("full training set" in r["why"] for r in rows)


# ---- why ours differs, per claim (shown under the verdict) ---------------------------------------------------------

PAPER = [  # the shape the Reader stores: several experiments of one paper, each setting scoped by applies_to
    {"key": "hidden_units", "applies_to": "MNIST large teacher", "value": "1200 rectified linear units per layer",
     "page": 3, "quote": "two hidden layers of 1200 rectified linear hidden units", "valid": True},
    {"key": "regularisation", "applies_to": "MNIST large teacher", "value": "dropout and weight-constraints",
     "page": 3, "quote": "strongly regularized using dropout and weight-constraints", "valid": True},
    {"key": "augmentation", "applies_to": "MNIST large teacher", "value": "jittered by up to two pixels", "page": 3,
     "quote": "the input images were jittered by up to two pixels", "valid": True},
    {"key": "data_subset", "applies_to": "MNIST large teacher", "value": "all 60,000 training cases", "page": 3,
     "quote": "trained on all 60,000 training cases", "valid": True},
    {"key": "hidden_units", "applies_to": "MNIST small student", "value": "800 rectified linear units per layer",
     "page": 4, "quote": "two hidden layers of 800 rectified linear hidden units", "valid": True},
    {"key": "regularisation", "applies_to": "MNIST small student", "value": "none", "page": 4,
     "quote": "and no regularization", "valid": True},
    {"key": "hidden_units", "applies_to": "MNIST distilled student", "value": "800 rectified linear units per layer",
     "page": 4, "quote": "two hidden layers of 800 rectified linear hidden units", "valid": True},
    {"key": "temperature", "applies_to": "MNIST distilled student", "value": "20", "page": 4,
     "quote": "at a temperature of 20", "valid": True},
    {"key": "hidden_units", "applies_to": "speech baseline", "value": "2560 rectified linear units per layer",
     "page": 4, "quote": "each containing 2560 rectified linear units", "valid": True},
    {"key": "lr", "applies_to": "all", "value": None, "quote": None, "page": None, "valid": True},
]
SECTION = "3 Preliminary experiments on MNIST"
CLAIMS = [{"id": "c1", "model": "large neural net", "table_or_section": SECTION, "unit": "errors"},
          {"id": "c2", "model": "smaller net without regularization", "table_or_section": SECTION, "unit": "errors"},
          {"id": "c3", "model": "distilled smaller net", "table_or_section": SECTION, "unit": "errors"}]
CONFIG = {"hidden_units": {"teacher": 256, "student": 128}, "epochs": {"teacher": 7, "student": 7},
          "lr": {"teacher": 0.001, "student": 0.001}, "temperature": 20.0, "dropout": 0.0, "weight_decay": 0.0,
          "augmentation": "none", "data_subset": 0, "seeds": [0]}
RUN_BUDGET = {"epochs": 7, "subset": 0, "seeds": [0]}


def test_each_claim_is_compared_with_the_settings_of_its_own_model():
    """Code matches a claim's model and section to the settings' applies_to; other experiments' settings stay out."""
    sel = {c["id"]: [PAPER[int(s[1:]) - 1]["applies_to"] for s in why.claim_settings(c, PAPER)] for c in CLAIMS}
    assert set(sel["c1"]) == {"MNIST large teacher"}
    assert set(sel["c2"]) == {"MNIST small student"}
    assert set(sel["c3"]) == {"MNIST distilled student"}


def test_why_ours_differs_lists_the_setup_differences_from_stored_data_only():
    g = {"claims": [{"claim_id": "c1", "model": "teacher_mlp_compact", "paper": 67, "ours": 216, "delta": 149},
                    {"claim_id": "c3", "model": "distilled_student_mlp", "paper": 74, "ours": 255, "delta": 181},
                    {"claim_id": "c9", "model": "x", "paper": 1, "ours": None, "delta": None}],
         "why": {"our_config": CONFIG, "budget": RUN_BUDGET}}
    why.attach_why_differs(g, CLAIMS + [{"id": "c9", "model": "x"}], PAPER)
    c1, c3, c9 = (r["why_differs"] for r in g["claims"])
    keys = {(r["key"], r["our_key"]) for r in c1["reasons"]}
    assert {("hidden_units", "hidden_units.teacher"), ("regularisation", "dropout"),
            ("augmentation", "augmentation")} <= keys                         # 1200 vs 256, dropout off, no jitter
    assert ("data_subset", "data_subset") in {(r["key"], r["our_key"]) for r in c1["same"]}
    assert "Ours 216 vs paper 67 (+149 errors)" in c1["summary"]
    assert "1200 rectified linear units per layer" in c1["summary"] and "hidden_units.teacher = 256" in c1["summary"]
    assert "7 epochs" in c1["summary"] and "1 seed" in c1["summary"] and "does not state" in c1["summary"]
    assert "2560" not in c1["summary"] + c3["summary"]                         # the speech model's setting stays out
    assert ("hidden_units", "hidden_units.student") in {(r["key"], r["our_key"]) for r in c3["reasons"]}
    assert "temperature" in {r["key"] for r in c3["same"]}                     # 20 in both
    assert c9 is None                                                          # not runnable: nothing to explain


def test_experiment_diff_adds_each_claims_model_settings_and_the_compute_budget():
    """config.why.settings_diff (read by the site): the design named only some settings; the paper's other stated
    settings for each graded claim's model (teacher dropout, input jitter) are compared too, scoped to our model's
    CONFIG keys, each row naming the claims it explains, plus one compute-budget row from the stored facts."""
    claims = [{**CLAIMS[0], "runnable": {"facts": {"hardware": "GPUs", "compute": "a few days"}}}, CLAIMS[2]]
    rows = why.experiment_diff(PAPER, claims, {"teacher_mlp_compact": "c1", "distilled_student_mlp": "c3"}, CONFIG,
                               RUN_BUDGET, used={"s1", "s8"}, budget_reason="7 epochs x 2 models; cap 10 min")
    by = {(r["key"], r["setting_id"]): r for r in rows}
    jitter = by[("augmentation", "s3")]
    assert (jitter["label"], jitter["our_key"], jitter["claim_ids"]) == ("difference", "augmentation", ["c1"])
    assert by[("regularisation", "s2")]["label"] == "difference"                 # dropout and weight-constraints: off
    assert by[("hidden_units", "s7")]["our_key"] == "hidden_units.student"       # distilled student: 800 vs 128
    assert by[("temperature", "s8")]["label"] == "same" and by[("temperature", "s8")]["claim_ids"] == ["c3"]
    assert by[("hidden_units", "s1")]["applies_to"] == "MNIST large teacher"     # the paper's words are kept
    assert not any(r["setting_id"] in ("s5", "s6", "s9") for r in rows)          # small net, speech: not graded here
    compute = by[("compute_budget", None)]
    assert compute["paper"] == "GPUs; a few days" and compute["ours"] == "7 epochs x 2 models; cap 10 min"
    assert compute["label"] == "scale reduction (budget)" and compute["claim_ids"] == ["c1"]


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
