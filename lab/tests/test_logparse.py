import json
from pathlib import Path

import pytest

from lab.executor.logparse import error_signature, last_traceback, parse_log, parse_metric

ROOT = Path(__file__).resolve().parents[2]


def test_exact_format():
    m = parse_metric("METRIC teacher_test_errors=67 step=3", 12)
    assert (m.name, m.value, m.step, m.log_line) == ("teacher_test_errors", 67.0, 3, 12)
    assert m.as_row("exp-1") == {"experiment_id": "exp-1", "name": "teacher_test_errors",
                                 "value": 67.0, "step": 3, "log_line": 12}


@pytest.mark.parametrize("line,value", [
    ("METRIC loss=0.12345 step=1", 0.12345),
    ("METRIC loss=-2 step=1", -2.0),
    ("METRIC loss=1e-05 step=1", 1e-05),
    ("METRIC loss=0.5 step=1\r", 0.5),   # Windows line ending
    ("METRIC loss=0.5 step=1   ", 0.5),
])
def test_values(line, value):
    assert parse_metric(line, 1).value == value


@pytest.mark.parametrize("line", [
    "epoch 3 METRIC loss=0.5 step=3",   # not at line start
    "METRIC loss=0.5",                  # no step
    "METRIC loss= step=1",
    "METRIC loss=abc step=1",
    "METRIC loss=nan step=1",           # not storable as a real number
    "METRIC loss=inf step=1",
    "METRIC loss=0.5 step=1.5",
    "METRIC loss=0.5 step=1 extra",
    "metric loss=0.5 step=1",
    "",
])
def test_rejects_non_metric_lines(line):
    assert parse_metric(line, 1) is None


def test_parse_log_line_numbers_are_one_based():
    lines = ["B0 distillation reference", "", "METRIC a=1 step=0", "noise", "METRIC b=2.5 step=7"]
    assert [(m.name, m.value, m.step, m.log_line) for m in parse_log(lines)] == [
        ("a", 1.0, 0, 3), ("b", 2.5, 7, 5)]


def test_every_b0_metric_line_parses():
    """Real lines printed by papers/distillation/reference.py (B0), as kept in its results.json."""
    lines = json.loads((ROOT / "papers/distillation/results.json").read_text())["metric_log"]
    parsed = [parse_metric(l, i) for i, l in enumerate(lines, 1)]
    assert lines and all(parsed)
    final = {m.name: m.value for m in parsed}
    assert "final_teacher_test_errors" in final and "total_wall_s" in final


TB = """\
step 1
Traceback (most recent call last):
  File "train.py", line 3, in <module>
    import torchvision
ModuleNotFoundError: No module named 'torchvision'
"""

CHAINED = """\
Traceback (most recent call last):
  File "a.py", line 1, in <module>
KeyError: 'x'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "a.py", line 4, in <module>
    open("data/train.csv")
FileNotFoundError: [Errno 2] No such file or directory: 'data/train.csv'
"""


def test_last_traceback():
    tb = last_traceback(TB.splitlines())
    assert (tb.exc_type, tb.message, tb.log_line) == ("ModuleNotFoundError", "No module named 'torchvision'", 5)


def test_chained_uses_the_last_traceback():
    tb = last_traceback(CHAINED.splitlines())
    assert tb.exc_type == "FileNotFoundError" and tb.log_line == 10


@pytest.mark.parametrize("log,sig", [
    (TB, "ModuleNotFoundError:torchvision"),
    (CHAINED, "FileNotFoundError:train.csv"),
    ("Traceback (most recent call last):\n  File \"x.py\", line 1\nRuntimeError: shape mismatch 3 vs 4\n",
     "RuntimeError"),
    ("all good\nMETRIC a=1 step=0\n", None),
])
def test_error_signature(log, sig):
    assert error_signature(log.splitlines()) == sig
