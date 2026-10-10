"""Parser specs: line-numbered values, per-run blocks, counts; equal to parse_runs on the spike logs."""
from pathlib import Path

from el01.grade.parse import parse_train
from el01.link.parser_spec import SpecError, apply, validate

TRAIN = {"name": "target", "step": "train",
         "line_regex": r"Current Best Epoch:\s+(\d+)\s+with Test Accuracy:\s+([\d.]+)", "value_group": 2,
         "sd_group": None, "run_start_regex": r"^Run (\d+)", "key_group": None, "key_value": None,
         "per_epoch": True, "count": None}
EVAL = {"name": "source_1", "step": "eval", "line_regex": r"^(\d)\s+:\s+([\d.]+)\s+([\d.]+)", "value_group": 2,
        "sd_group": 3, "run_start_regex": None, "key_group": 1, "key_value": "0", "per_epoch": False, "count": 1}
LOG = """setup line
Current Best Epoch: 0 with Test Accuracy: 11.0
Run 0
Current Best Epoch: 0 with Test Accuracy: 50.0
Current Best Epoch: 1 with Test Accuracy: 55.5
Run 1
Current Best Epoch: 0 with Test Accuracy: 60.0
Current Best Epoch: 0 with Test Accuracy: 60.0
0  :  99.97999 0.0189
1  :  96.39 0.199
"""


def test_per_run_last_match_with_lines(tmp_path):
    f = tmp_path / "train.log"
    f.write_text(LOG)
    blocks = apply(TRAIN, f)["blocks"]
    assert [(b["run"], b["value"], b["line"], b["matches"]) for b in blocks] == [("0", 55.5, 5, 2), ("1", 60.0, 8, 2)]
    assert validate(TRAIN, f, n_runs=2, epochs=2)["ok"]
    v = validate(TRAIN, f, n_runs=1, epochs=1)
    assert not v["ok"] and "2 run blocks" in v["problems"][0]
    e = apply(EVAL, f)["blocks"]
    assert [(b["value"], b["sd"], b["line"]) for b in e] == [(99.97999, 0.0189, 9)]
    assert validate(EVAL, f, n_runs=None, epochs=None)["ok"]


def test_bad_specs(tmp_path):
    f = tmp_path / "x.log"
    f.write_text(LOG)
    assert not validate({**TRAIN, "value_group": 3}, f, 2, 2)["ok"]
    assert not validate({**TRAIN, "line_regex": "("}, f, 2, 2)["ok"]
    assert "no value" in validate({**TRAIN, "line_regex": r"(nothing) (here)"}, f, 2, None)["problems"][0]
    try:
        apply({**EVAL, "key_value": None}, f)
    except SpecError:
        pass
    else:
        raise AssertionError("key_group without key_value must be rejected")


def test_equals_parse_train_on_the_spike_logs(paths):
    n = 0
    for f in sorted(paths.logs.glob("*/train_*.log")):
        try:
            ref = parse_train(f, paths.cite)
        except Exception:
            continue  # e.g. MatchDG's contrastive phase: no test-accuracy line
        got = [(int(b["run"]), b["value"], b["line"]) for b in apply(TRAIN, f, paths.cite)["blocks"]
               if b["value"] is not None]
        assert got == [(r["seed_run"], r["target_acc"], r["line"]) for r in ref["per_seed"]], f
        n += 1
    assert n >= 90
