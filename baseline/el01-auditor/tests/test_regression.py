"""The MatchDG regression (rule 7), the acceptance files, and rule 3: every parsed number traces to (log file, line)."""
import json
import re
import subprocess

import pytest
from typer.testing import CliRunner

from el01.cli import app
from el01.grade.spike.compare import json_diff, normalise_path, normalise_paths
from el01.grade.spike.regress import GRADE_FILES, flatten, run_regression

BEST = re.compile(r"Current Best Epoch:\s+(\d+)\s+with Test Accuracy:\s+([\d.]+)")
FINAL = re.compile(r"Final Test Accuracy \(Source Validation\) ([\d.]+) ([\d.]+)")
EVAL = re.compile(r"^(\d)\s+:\s+([\d.]+)\s+([\d.]+)")
VAL = re.compile(r"^ Accuracy:\s+val ([\d.]+)")


@pytest.fixture(scope="module")
def report(paths):
    return run_regression(paths)


def test_regression_zero_mismatches(report):
    assert (report["graded_items_checked"], report["verdict_labels_checked"], report["extraction_checks"]) == (126, 73, 6)
    assert report["mismatches"] == []
    assert report["file_mismatches"] == []
    assert report["pass"] is True


def test_acceptance_files_equal_the_spike(paths, graded_legacy):
    for key in ("table1", "table11_confirm", "f7"):
        spike = json.loads((paths.spike_metrics / GRADE_FILES[key]).read_text())
        assert json_diff(normalise_paths(spike), normalise_paths(graded_legacy[key])) == [], key


def test_file_checks_cover_the_regenerated_files(report):
    assert report["file_checks"] == 20  # 15 run dirs minus matchdg_lenet (no spike copy) + epochs + 4 grades + score
    assert report["files_not_in_spike"] == ["metrics/matchdg_lenet.json"]


def test_flatten_matches_golden_keys(paths, graded_legacy):
    gold = json.loads((paths.golden / "verdicts.json").read_text())
    assert set(flatten(graded_legacy)) == set(gold)


def _line(paths, cited, line):
    assert cited.startswith("logs/"), cited
    lines = paths.resolve_cite(cited).read_text().splitlines()
    assert 1 <= line <= len(lines), (cited, line)
    return lines[line - 1]


def test_every_parsed_number_traces_to_its_log_line(paths, parsed):
    n = 0
    for run, res in parsed["metrics"].items():
        for method, m in res.items():
            if not isinstance(m, dict): continue
            t = m.get("target")
            if t:
                for r in t["per_seed"]:
                    g = BEST.search(_line(paths, t["log"], r["line"]))
                    assert g and (int(g.group(1)), float(g.group(2))) == (r["best_epoch"], r["target_acc"]), (run, method, r)
                    n += 1
                c = t["code_reported"]
                g = FINAL.search(_line(paths, t["log"], c["line"]))
                assert g and (float(g.group(1)), float(g.group(2))) == (c["mean"], c["sd"])
            for key, s in m.items():
                if key.startswith("source_"):
                    g = EVAL.match(_line(paths, s["log"], s["line"]))
                    assert g and (round(float(g.group(2)), 2), round(float(g.group(3)), 2)) == (s["mean"], s["sd"])
                    n += 1
    for run, ms in parsed["epochs"].items():
        for method, e in ms.items():
            for r in e["per_seed"]:
                g = BEST.search(_line(paths, e["log"], r["best_line"]))
                assert g and (int(g.group(1)), float(g.group(2))) == (r["selected_epoch"], r["target_acc"])
                g = VAL.match(_line(paths, e["log"], r["source_val_line"]))
                assert g and float(g.group(1)) == r["source_val_acc"]
                n += 2
    assert n > 1000


def test_f7_values_trace_to_log_lines(paths, graded_legacy):
    for d, c in graded_legacy["f7"]["cells"].items():
        for side in ("base", "branch"):
            for v, line in zip(c[side], c[f"{side}_lines"]):
                g = BEST.search(_line(paths, c[f"{side}_log"], line))
                assert g and float(g.group(2)) == v, (d, side, line)


def test_every_cited_log_exists(paths, parsed, graded_legacy):
    cited = []

    def walk(x):
        if isinstance(x, dict): [walk(v) for v in x.values()]
        elif isinstance(x, list): [walk(v) for v in x]
        elif isinstance(x, str) and x.endswith(".log"): cited.append(x)
    walk(parsed["metrics"]); walk(parsed["epochs"]); walk(graded_legacy)
    assert cited and all(c.startswith("logs/") and paths.resolve_cite(c).is_file() for c in cited)


@pytest.mark.parametrize("raw,want", [
    ("/home/claude/spike/runs/confirm_base/train_erm.log", "logs/confirm_base/train_erm.log"),
    ("runs/matchdg_lenet_confirm/train_matchdg_0.log", "logs/matchdg_lenet_confirm/train_matchdg_0.log"),
    ("confirm_base/train_erm.log", "logs/confirm_base/train_erm.log"),
    ("logs/confirm_base/train_erm.log", "logs/confirm_base/train_erm.log"),
    ("logs/driver.log", "logs/driver.log"),
    ("utils/helper.py:173", "utils/helper.py:173"),
    (12.5, 12.5),
])
def test_normalise_path(raw, want):
    assert normalise_path(raw) == want


def test_cli_regress_and_grade_spike(paths, graded_legacy, tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["regress", "--spike", str(paths.spike)])
    assert r.exit_code == 0, r.output
    assert r.output.splitlines()[0] == "126 graded items (73 verdicts) + 6 extraction checks: 0 mismatches"
    r = runner.invoke(app, ["grade-spike", "--out", str(tmp_path)])
    assert r.exit_code == 0, r.output
    for key, name in GRADE_FILES.items():
        assert json.loads((tmp_path / name).read_text()) == graded_legacy[key]
    assert len(list((tmp_path / "metrics").glob("*.json"))) == 16  # 15 run dirs + epochs.json


def test_inputs_untouched(paths, report):
    out = subprocess.run(["git", "status", "--porcelain", "--", "inputs"], cwd=paths.root, capture_output=True, text=True, check=True)
    assert out.stdout == ""
