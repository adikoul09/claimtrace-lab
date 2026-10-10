"""Rule 5: the grader refuses a run set with no pre-registration, an uncommitted one, changed rule files, a foreign
code tree, an unplanned log, or a job that started before it."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from el01.grade import prereg

ROOT = Path(__file__).resolve().parent.parent


def _git(cwd, *a):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@x.invalid", *a],
                   check=True, capture_output=True, text=True)


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "root"
    for f in prereg.HASHED:
        (r / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, r / f)
    _git(r, "init", "-q")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "init")
    return r


PLAN = {"kind": "exploratory", "table": "Table 1", "baseline": "base", "seeds": [0, 1], "seeds_graded": [0, 1],
        "arms": {"base": {"ref": "b", "commit": "a" * 40, "tree": "t" * 40, "methods": ["erm"]},
                 "h": {"ref": "h", "commit": "c" * 40, "tree": "u" * 40, "methods": ["erm"]}},
        "family": [["h", "erm"]]}


def _write(root):
    audit, run = root / "audits" / "x", root / "runs" / "set"
    prereg.write(root, audit, "set", PLAN, {"accuracy": 1.0}, "rule", run, "x")
    return audit, run


def _commit(root):
    _git(root, "add", "audits")
    _git(root, "commit", "-q", "-m", "prereg")


def test_missing_prereg_refused(root):
    with pytest.raises(prereg.PreregError, match="no pre-registration"):
        prereg.check(root, root / "audits" / "x", "set", root / "runs" / "set")


def test_uncommitted_then_ok(root):
    audit, run = _write(root)
    with pytest.raises(prereg.PreregError, match="not committed"):
        prereg.check(root, audit, "set", run)
    _commit(root)
    rec = prereg.check(root, audit, "set", run)
    assert set(rec["hashes"]) == set(prereg.HASHED)
    txt = (run / prereg.PREREG_TXT).read_text()
    assert "completed runs at this time:\n(none)" in txt and "el01/grade/legacy/verdicts_v2.py" in txt


def test_changed_rule_file_refused(root):
    audit, run = _write(root)
    _commit(root)
    with (root / "el01/grade/rules.py").open("a") as f:
        f.write("\n# edit\n")
    with pytest.raises(prereg.PreregError, match="rules.py changed"):
        prereg.check(root, audit, "set", run)


def test_foreign_tree_and_unplanned_log_refused(root):
    audit, run = _write(root)
    _commit(root)
    (run / "h").mkdir()
    (run / "h" / "tree.txt").write_text("z" * 40 + "\n")
    (run / "h" / "train_perf.log").write_text("")
    with pytest.raises(prereg.PreregError) as e:
        prereg.check(root, audit, "set", run)
    assert "not the planned" in str(e.value) and "train_perf.log is not in the plan" in str(e.value)


def test_write_refuses_after_runs_started(root):
    run = root / "runs" / "set" / "base"
    run.mkdir(parents=True)
    (run / "train_erm.log").write_text("Run 0\n")
    with pytest.raises(prereg.PreregError, match="already exist"):
        _write(root)


def test_job_before_prereg_refused(root):
    audit, run = _write(root)
    _commit(root)
    (run / ".jobs").mkdir()
    (run / ".jobs" / "j.json").write_text(json.dumps({"name": "j", "start_utc": "2000-01-01T00:00:00Z"}))
    with pytest.raises(prereg.PreregError, match="before the pre-registration"):
        prereg.check(root, audit, "set", run)
