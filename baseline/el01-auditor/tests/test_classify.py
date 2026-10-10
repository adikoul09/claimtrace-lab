"""Failure classification of the run as shipped: the spike's real log, plus synthetic tracebacks for each class."""
import json

import pytest

from el01.config import Paths
from el01.run.classify import classify, last_traceback, path_literal

PATHS = Paths.make()
ROBUSTDG = PATHS.repos / "robustdg"
SPIKE_ROOT = "/home/claude/spike/robustdg"  # how the spike's logs spell the repo root


@pytest.mark.skipif(not (ROBUSTDG / "utils" / "slab_data.py").exists(), reason="robustdg clone missing")
def test_spike_shipped_log_is_missing_path_at_slab_data_75(paths):
    log = paths.logs / "01_train_erm_shipped.log"
    lines = log.read_text().splitlines()
    r = classify(log, [SPIKE_ROOT], ROBUSTDG)
    assert r["class"] == "missing path" and r["exception"] == "FileNotFoundError"
    assert r["location"] == "utils/slab_data.py:75" and r["origin"]["literal"].startswith("/home/t-dimaha/")
    assert (r["raised_at"]["file"], r["raised_at"]["line"]) == ("utils/slab_data.py", 78)
    # every location keeps its log line (rule 3)
    assert lines[r["log_line"] - 1].startswith("FileNotFoundError: [Errno 2] No such file or directory: '/home/t-dimaha/")
    assert 'utils/slab_data.py", line 78' in lines[r["raised_at"]["log_line"] - 1]
    assert [f["repo_file"] for f in r["frames"]] == ["train.py", "utils/helper.py", "data/slab_loader.py",
                                                     "data/slab_loader.py", "utils/slab_data.py"]


def _log(tmp_path, body, name="x.log"):
    p = tmp_path / name
    p.write_text("Run 0\nsome output\n" + body)
    return p


def _tb(frames, last):
    out = "Traceback (most recent call last):\n"
    for f, line in frames:
        out += f'  File "{f}", line {line}, in <module>\n    code()\n'
    return out + last + "\n"


@pytest.mark.parametrize("last,cls", [
    ("RuntimeError: Found no NVIDIA driver on your system. Please check that you have an NVIDIA GPU", "no GPU"),
    ("AssertionError: Torch not compiled with CUDA enabled", "no GPU"),
    ("AttributeError: module 'opacus' has no attribute 'autograd_grad_sample'", "missing attribute or API"),
    ("ImportError: cannot import name 'PrivacyEngine' from 'opacus' (/env/opacus/__init__.py)", "missing attribute or API"),
    ("FileNotFoundError: [Errno 2] No such file or directory: 'data/datasets/slab/x_case_test_seed_0.pickle'", "missing data"),
    ("ModuleNotFoundError: No module named 'more_itertools'", "other"),
    ("ValueError: too many values to unpack", "other"),
])
def test_classes(tmp_path, last, cls):
    wt = tmp_path / "wt"
    (wt / "utils").mkdir(parents=True)
    log = _log(tmp_path, _tb([(f"{wt}/train.py", 216), (f"{wt}/utils/x.py", 12)], last))
    r = classify(log, [str(wt)], wt, inside=[wt])
    assert r["class"] == cls
    assert r["raised_at"] == {"file": "utils/x.py", "line": 12, "func": "<module>", "log_line": 6}


def test_absolute_path_inside_the_worktree_is_missing_data_and_literal_is_found(tmp_path):
    wt = tmp_path / "wt"
    (wt / "utils").mkdir(parents=True)
    (wt / "utils" / "load.py").write_text("import os\n\nBASE = '/data/sets/'\nOTHER = 'a/b/'\n\n"
                                          "def load(n):\n    return open(BASE + 'slab/' + n)\n")
    out = _tb([(f"{wt}/utils/load.py", 7)],
              f"FileNotFoundError: [Errno 2] No such file or directory: '{wt}/data/x.pickle'")
    assert classify(_log(tmp_path, out), [str(wt)], wt, inside=[wt])["class"] == "missing data"
    out = _tb([(f"{wt}/utils/load.py", 7)], "FileNotFoundError: [Errno 2] No such file or directory: '/data/sets/slab/x.pickle'")
    (wt / "data").mkdir()
    (wt / "data" / "x.pickle").write_text("")
    r = classify(_log(tmp_path, out, "y.log"), [str(wt)], wt, inside=[wt])
    assert r["class"] == "missing path" and r["location"] == "utils/load.py:3"
    assert r["origin"] == {"file": "utils/load.py", "line": 3, "literal": "/data/sets/"}
    assert r["same_name_in_worktree"] == ["data/x.pickle"]


def test_chained_exceptions_use_the_last_traceback():
    lines = (_tb([("/r/a.py", 1)], "KeyError: 'x'") + "\nDuring handling of the above exception, another exception occurred:\n\n"
             + _tb([("/r/b.py", 2), ("<frozen importlib._bootstrap>", 1007)], "AttributeError: no attr")).splitlines()
    tb = last_traceback(lines, ["/r"])
    assert tb.exc_type == "AttributeError" and [f.repo_file for f in tb.frames] == ["b.py", None]
    assert last_traceback(["all good", "done"]) is None


def test_path_literal_prefers_the_prefix(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("A = '/x/'\nB = '/x/y/z/'\nC = 'z/q.pkl'\n")
    assert path_literal(src, "/x/y/z/q.pkl") == {"line": 2, "literal": "/x/y/z/"}


def test_committed_run_as_shipped_summary():
    """Phase 2 acceptance, as recorded by `el01 run-shipped matchdg`."""
    p = PATHS.audit_dir("matchdg") / "run_as_shipped.json"
    if not p.exists():
        pytest.skip("run `el01 run-shipped matchdg` first")
    s = json.loads(p.read_text())
    assert s["commit"].startswith("3eee173") and s["outcome"] == "failed"
    assert s["failure"]["class"] == "missing path" and s["failure"]["location"] == "utils/slab_data.py:75"
    assert s["run"]["log"] == "runs/shipped/train_erm.log" and s["env"]["torch"] == "1.11.0"
