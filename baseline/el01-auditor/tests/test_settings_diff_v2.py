"""The schema-v2 diff rules (el01/diff/settings_diff.diff_v2) on small synthetic sides, and on the spike's v1 outputs."""
from el01.diff import settings_diff as xd


def side(**kv):
    return {k.replace("__", "."): {"value": v} for k, v in kv.items()}


AUG = {"ops": ["random_resized_crop", "random_horizontal_x"], "relative_to_domain_transform": "after",
       "applies_to": [{"split": "val", "domains": "source", "use": "model_selection", "methods": ["M2"],
                       "phase": "first"}], "note": None}
SEL_AUG = {"use": "checkpoint", "split": "val", "domains": "source", "version": "augmented", "metric": "match score",
           "methods": ["M2"], "phase": "first", "note": None}
SEL_PLAIN = {"use": "checkpoint", "split": "val", "domains": "source", "version": "plain", "metric": "acc",
             "methods": None, "phase": None, "note": None}


def keys(fs):
    return [(f["key"], f["kind"]) for f in fs]


def test_augmentation_paper_silent_is_an_omission_that_reaches_the_selection():
    p = side(data__augmentation=None)
    c = side(data__augmentation=[AUG], train__model_selection_data=[SEL_PLAIN, SEL_AUG])
    fs = xd.diff_v2(p, c)
    aug = [f for f in fs if f["key"] == "data.augmentation"]
    assert keys(aug) == [("data.augmentation", "paper omission")]
    assert aug[0]["reaches"]["selection_reads_augmented"] == [
        {"use": "checkpoint", "split": "val", "domains": "source", "version": "augmented", "methods": ["M2"],
         "phase": "first"}]
    # the augmented selection step is itself non-default, so it is listed too; the plain one is not
    sel = [f for f in fs if f["key"] == "train.model_selection_data"]
    assert keys(sel) == [("train.model_selection_data", "paper omission")] and sel[0]["method"] == ["M2"]


def test_explicit_none_is_a_difference_and_no_code_augmentation_is_nothing():
    c = side(data__augmentation=[AUG])
    assert keys(xd.diff_v2(side(data__augmentation=[]), c)) == [("data.augmentation", "difference")]
    assert xd.diff_v2(side(data__augmentation=None), side(data__augmentation=[])) == []
    assert xd.diff_v2(side(data__augmentation=None), side(data__augmentation=None)) == []
    same = dict(AUG)
    assert xd.diff_v2(side(data__augmentation=[same]), c) == []


def test_selection_data_difference_by_use_and_method():
    paper = [{"use": "hyperparameter_tuning", "split": "val", "domains": "source", "version": "plain",
              "metric": None, "methods": None, "phase": None, "note": None}]
    code = [{"use": "hyperparameter_tuning", "split": "test", "domains": "target", "version": "plain",
             "metric": "acc", "methods": ["M1"], "phase": None, "note": None}, SEL_PLAIN]
    fs = xd.diff_v2(side(train__model_selection_data=paper), side(train__model_selection_data=code))
    assert keys(fs) == [("train.model_selection_data", "difference")]
    assert fs[0]["use"] == "hyperparameter_tuning" and fs[0]["fields"] == ["split", "domains"]


def test_enum_keys_and_simple_entries():
    fs = xd.diff_v2(side(eval__aggregation="mean_sd_over_seeds", optim__name="SGD"),
                    side(eval__aggregation={"source": "mean_se_over_seeds: np.std/sqrt(n)",
                                            "target": "mean_sd_over_seeds"}, optim__name="sgd"))
    assert [(f["key"], f["method"]) for f in fs] == [("eval.aggregation", "source")]
    rs = {"height": 32, "width": 32, "methods": None, "note": None}
    assert keys(xd.diff_v2(side(), side(data__preprocessing__resize=[rs]))) == [
        ("data.preprocessing.resize", "paper omission")]
    assert keys(xd.diff_v2(side(data__preprocessing__resize=[dict(rs, height=28, width=28)]),
                           side(data__preprocessing__resize=[rs]))) == [("data.preprocessing.resize", "difference")] * 2
    norm = {"kind": "none", "mean": None, "std": None, "methods": None, "note": None}
    assert xd.diff_v2(side(), side(data__preprocessing__normalization=[norm])) == []
    rot = {"kind": "rotation", "domains": [0, 15, 30], "params": None, "direction": "counterclockwise",
           "methods": None, "note": None}
    assert keys(xd.diff_v2(side(data__domain_transform=[dict(rot, direction="clockwise")]),
                           side(data__domain_transform=[rot]))) == [("data.domain_transform", "difference")]
    assert xd.diff_v2(side(data__domain_transform=[dict(rot, direction="unknown")]),
                      side(data__domain_transform=[rot])) == []


def test_spike_v1_outputs_still_recover_f1_to_f5(paths):
    """The per-method rule 3 and the enumerated model-selection compare replace v1's; on the spike's four blind
    outputs they still recover the five findings v1 recovered."""
    P, C = xd.load_outputs(paths.extraction_outputs)
    for p in P.values():
        for c in C.values():
            fs = xd.diff_v2(xd.settings(p), xd.settings(c))
            assert all(fn(fs) for fn in xd.GROUND_TRUTH.values())


def test_numbers_per_method_and_phase():
    paper = {"ERM": 100, "MatchDG": {"Phase 1": 50, "Phase 2": 100}}
    code = {"ERM": 100, "MatchDG": {"phase1": 50, "phase2": 100}}
    assert xd.diff_v2(side(train__epochs=paper), side(train__epochs=code)) == []
    fs = xd.diff_v2(side(train__epochs=100), side(train__epochs=code))      # paper gives one value for all
    assert [(f["key"], f["method"]) for f in fs] == [("train.epochs", "MatchDG")]
    # names: exact (letters and digits), the spike's alias (rand -> RandMatch), else the one name containing it
    lr = {"ERM": 0.1, "RandMatch": 0.1, "DANN": 0.1, "CDANN": 0.1}
    fs = xd.diff_v2(side(optim__lr=lr), side(optim__lr={"erm": 0.1, "rand": 0.01, "dann": 0.01, "c-dann": 0.1}))
    assert sorted(f["method"] for f in fs) == ["dann", "rand"]
    # a code value for every method is paired with each paper method
    assert [f["method"] for f in xd.diff_v2(side(optim__lr=lr), side(optim__lr=0.1))] == []


def test_model_selection_per_method_skips_other():
    paper = "best_val_accuracy"
    code = {"ERM": "best_val_accuracy", "MatchDG": "other: phase 1 keeps the best match score"}
    assert xd.diff_v2(side(train__model_selection=paper), side(train__model_selection=code)) == []
    code = {"ERM": "best_val_accuracy", "MatchDG": {"phase 1": "other: match score", "phase 2": "min_val_loss"}}
    fs = xd.diff_v2(side(train__model_selection=paper), side(train__model_selection=code))
    assert [(f["key"], f["method"]) for f in fs] == [("train.model_selection", "MatchDG")]
    fs = xd.diff_v2(side(train__model_selection="min_val_loss: early stopping"),
                    side(train__model_selection="best_val_accuracy"))
    assert [(f["key"], f["kind"]) for f in fs] == [("train.model_selection", "difference")]


def test_domain_transform_kind_is_compared_as_an_enum():
    t = {"kind": "feature_noise", "domains": [0, 0.1, 1.0], "params": "linear coordinate replaced by noise",
         "direction": "not_applicable", "methods": None, "note": None}
    assert xd.diff_v2(side(data__domain_transform=[dict(t, params="noise on the linear feature")]),
                      side(data__domain_transform=[t])) == []
    fs = xd.diff_v2(side(data__domain_transform=[dict(t, kind="correlation_strength")]),
                    side(data__domain_transform=[t]))
    assert [(f["key"], f["field"]) for f in fs] == [("data.domain_transform", "kind")]
    # free text outside the vocabulary names nothing a fixed rule can compare
    assert xd.diff_v2(side(data__domain_transform=[dict(t, kind="label-dependent noise on linear feature")]),
                      side(data__domain_transform=[t])) == []
    from el01.extract.settings import SCHEMA_V2
    assert xd.DOMAIN_KINDS == tuple(next(k for k in SCHEMA_V2["keys"] if k["key"] == "data.domain_transform")
                                    ["entry"]["properties"]["kind"]["enum"])
