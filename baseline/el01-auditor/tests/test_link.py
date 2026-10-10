"""Linker checks: coverage, argv, the scripts' own parsers, dry runs with the epoch ladder, parser specs on the logs."""
import os
import subprocess
import sys
from pathlib import Path

from el01.config import AuditConfig, Paths
from el01.link import linker
from el01.link.spike import handwritten_table1, handwritten_table11

PHASE1 = '''import argparse
p = argparse.ArgumentParser()
p.add_argument('--epochs', type=int, default=50)
p.add_argument('--n_runs', type=int, default=3)
a = p.parse_args()
for e in range(a.epochs):
    print('Done Training for epoch: ', e)
    if (e + 1) % 5 == 0:                      # like MatchDG's contrastive phase: a checkpoint every 5th epoch only
        open('ckpt.txt', 'w').write(str(e))
'''
PHASE2 = '''import argparse, os, sys
p = argparse.ArgumentParser()
p.add_argument('--epochs', type=int, default=100)
p.add_argument('--n_runs', type=int, default=3)
p.add_argument('--method', type=str, default='erm')
a = p.parse_args()
if not os.path.exists('ckpt.txt'):
    sys.exit('no checkpoint from phase 1')
for r in range(a.n_runs):
    print('Run', r)
    for e in range(a.epochs):
        print('Current Best Epoch: ', e, ' with Test Accuracy: ', 50.0 + r)
'''
TARGET = {"name": "target", "step": "phase2", "line_regex": r"Current Best Epoch:\s+(\d+)\s+with Test Accuracy:\s+([\d.]+)",
          "value_group": 2, "sd_group": None, "run_start_regex": r"^Run (\d+)", "key_group": None, "key_value": None,
          "per_epoch": True, "count": None, "evidence": "phase2.py:10"}


def table():
    def card(row, col, valid=True):
        return {"claim_id": f"T|{row}|{col}", "valid": valid, "source": {"row": row, "column": col}}
    return {"target": "T", "table": "T", "cards": [card("A", "x"), card("A", "Avg"), card("B", "x", valid=False)]}


def ctx(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "phase1.py").write_text(PHASE1)
    (wt / "phase2.py").write_text(PHASE2)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-qm", "toy"]):
        subprocess.run(["git", "-C", str(wt), *cmd], check=True, env=env, capture_output=True)
    cfg = AuditConfig.model_validate({"id": "toy", "paper": {"title": "toy"}, "repo": {"url": "x", "commit": "x"},
                                      "targets": [], "budget": {"max_parallel_jobs": 2}})
    audit = tmp_path / "audit"
    audit.mkdir()
    return linker.Ctx(paths=Paths.make(), cfg=cfg, repo=wt, base="x", snap=wt, head="x", branch=None, head_why="",
                      wt=wt, py=Path(sys.executable), audit_dir=audit, ev=audit / "link", runs=audit / "runs" / "link",
                      llm=None, echo=lambda s: None)


def answer(steps=None, **over):
    steps = steps or [{"name": "phase1", "argv": ["python", "phase1.py", "--epochs", "50"]},
                      {"name": "phase2", "argv": ["python", "phase2.py", "--epochs", "100", "--method", "erm"]}]
    a = {"data_steps": [], "parsers": [TARGET],
         "cells": [{"claim_ids": ["T|A|x"], "status": "linked", "steps": steps, "parser": "target", "derived_from": [],
                    "derived_op": None, "evidence": "", "reason": ""},
                   {"claim_ids": ["T|A|Avg"], "status": "derived", "steps": [], "parser": None,
                    "derived_from": ["T|A|x"], "derived_op": "mean", "evidence": "", "reason": "average"}],
         "notes": ""}
    a.update(over)
    return a


def run(c, a):
    rec = linker.check_answer(c, table(), a)
    rec.update(target="T", slug="t")
    linker.evaluate(c, [rec], dry_run=True)
    return rec


def test_coverage_and_structure(tmp_path):
    c = ctx(tmp_path)
    rec = linker.check_answer(c, table(), answer())
    assert rec["problems"] == []
    assert [x["status"] for x in rec["cells"]] == ["linked", "derived", "not_linked"]   # B's card failed verification
    bad = answer(cells=[{"claim_ids": ["T|A|x", "T|A|Avg"], "status": "linked", "parser": "nope", "evidence": "",
                         "steps": [{"name": "s", "argv": ["python", "missing.py", ">", "out.log"]}],
                         "derived_from": [], "derived_op": None, "reason": ""}])
    rec = linker.check_answer(c, table(), bad)
    cell = rec["cells"][0]
    assert any("exactly one cell" in p for p in cell["problems"]) and any("no parser" in p for p in cell["problems"])
    assert any("no script" in p for p in cell["steps"][0]["problems"])
    assert any("shell syntax" in p for p in cell["steps"][0]["problems"])
    rec = linker.check_answer(c, table(), answer(cells=[]))
    assert "2 verified cells not in any entry" in rec["problems"][0]


def test_dry_run_ladder_and_parser(tmp_path):
    c = ctx(tmp_path)
    rec = run(c, answer())
    cell = rec["cells"][0]
    assert cell["problems"] == [], cell["problems"]
    atts = cell["dry_run"]["attempts"]
    # phase 1 at 1 epoch saves no checkpoint, so phase 2 fails; the ladder re-runs phase 1 at 5 epochs
    assert [a["earlier_steps_epochs"] for a in atts] == [1, 5] and [a["ok"] for a in atts] == [False, True]
    assert atts[1]["jobs"][0]["argv"] == ["python", "phase1.py", "--epochs", "5", "--n_runs", "1"]
    assert atts[1]["jobs"][1]["argv"] == ["python", "phase2.py", "--epochs", "1", "--method", "erm", "--n_runs", "1"]
    pc = cell["parser_check"]
    assert pc["ok"] and (pc["n_runs"], pc["epochs"]) == (1, 1)
    assert pc["values"] == [{"run": "0", "value": 50.0, "sd": None, "log": atts[1]["jobs"][1]["log"], "line": 2}]
    assert cell["steps"][1]["namespace"] == {"epochs": 100, "method": "erm", "n_runs": 3}   # the command as linked


def test_unknown_option_is_not_run(tmp_path):
    c = ctx(tmp_path)
    steps = [{"name": "phase1", "argv": ["python", "phase1.py", "--epochs", "50"]},
             {"name": "phase2", "argv": ["python", "phase2.py", "--bogus", "1"]}]
    rec = run(c, answer(steps=steps))
    cell = rec["cells"][0]
    assert any("--bogus" in p for p in cell["problems"]) and "dry_run" not in cell


def test_handwritten_commands(paths):
    h1, h11 = handwritten_table1(paths.spike), handwritten_table11(paths.spike)
    assert len(h1) == 9 and all(len(s) == 2 for s in h1.values())
    perf = h1["perf"]
    assert perf[0]["argv"][:2] == ["python", "train.py"] and perf[1]["argv"][:2] == ["python", "test.py"]
    assert perf[0]["argv"][perf[0]["argv"].index("--test_domains") + 1] == "1.0"   # from run_table1_rest.sh:12
    assert (perf[0]["log"], perf[1]["log"]) == ("train_perf.log", "eval_perf.log")
    assert len(h11) == 24
    m = h11[("matchdg", "30")]
    assert [s["log"] for s in m] == ["train_matchdg_ctr_30.log", "train_matchdg_30.log"]
    a = m[1]["argv"]
    assert a[a.index("--train_domains") + 1: a.index("--test_domains")] == ["0", "15", "45", "60", "75"]


def test_feedback_names_the_failure_and_cells_without_machine_paths(tmp_path):
    c = ctx(tmp_path)
    a = answer(steps=[{"name": "phase2", "argv": ["python", "phase2.py", "--epochs", "100"]}])   # no phase 1
    (c.wt / "ckpt.txt").write_text("stale, from an earlier dry run")   # the clean start must remove it
    rec = run(c, a)
    assert not linker.table_ok(rec)
    text = linker.feedback(c, rec, a)
    assert "dry run of step 'phase2' (python phase2.py --epochs 1 --n_runs 1) failed (exit 1)" in text
    assert "no checkpoint from phase 1" in text and "cells: T|A|x" in text
    assert "derived from cells that are not validly linked: ['T|A|x']" in text
    assert str(tmp_path) not in text and '"claim_ids"' in text    # the previous answer is quoted back
