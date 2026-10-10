"""The repair loop on a tiny synthetic repo, with a scripted agent standing in for the LLM (no quota, no cache).

The repo has the same kinds of defect as MatchDG: a hard-coded absolute data path, a test domain the data step never
generates, and an unconditional call into a library API that no longer exists (yaml.removed_api)."""
import subprocess
import sys
from pathlib import Path

import pytest

from el01.config import AuditConfig, Paths
from el01.llm.backend import Response
from el01.repair.agent import missing_domain, run_repair

GEN = '''import os
os.makedirs("data", exist_ok=True)
corr_list = [0.0, 0.5]
for c in corr_list:
    with open("data/d_corr_" + str(c) + ".txt", "w") as f:
        f.write(str(c))
'''
TRAIN = '''import argparse
import yaml
p = argparse.ArgumentParser()
p.add_argument("--test", default="1.0")
p.add_argument("--epochs", type=int, default=3)
p.add_argument("--dp", type=int, default=0)
a = p.parse_args()
BASE = "/home/someone/project/data/"
with open(BASE + "d_corr_0.0.txt") as f:
    f.read()
with open(BASE + "d_corr_" + a.test + ".txt") as f:
    val = float(f.read())
for epoch in range(a.epochs):
    pass
yaml.removed_api()
print("Final Test Accuracy", 50.0 + val)
'''

FIX_PATH = {"file": "train.py", "old": 'BASE = "/home/someone/project/data/"', "new": 'BASE = "data/"'}
FIX_DOMAIN = {"file": "gen_data.py", "old": "corr_list = [0.0, 0.5]", "new": "corr_list = [0.0, 0.5, 1.0]"}
FIX_API = {"file": "train.py", "old": "yaml.removed_api()", "new": "if a.dp:\n    yaml.removed_api()"}
BAD_EPOCHS = {"file": "train.py", "old": 'p.add_argument("--epochs", type=int, default=3)',
              "new": 'p.add_argument("--epochs", type=int, default=1)'}


class ScriptedLLM:
    """Answers from the failure in the prompt. `script` maps a marker in the prompt to a list of answers, used in turn."""
    mode = "replay"
    cli_version = None

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.prompts = []

    def call(self, req):
        self.prompts.append(req.prompt)
        for marker, answers in self.script.items():
            if marker in req.prompt:
                ans = answers.pop(0) if len(answers) > 1 else answers[0]
                rec = {"response": {"output": ans, "total_cost_usd": 0.0, "num_turns": 1, "models": ["scripted"]}}
                return Response(ans, req.key, "replay", "hit", rec)
        raise AssertionError("no scripted answer for prompt:\n" + req.prompt[:2000])


def _answer(edits, cls="env", why="make it run"):
    return {"edits": edits, "class": cls, "rationale": why}


@pytest.fixture
def setup(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "gen_data.py").write_text(GEN)
    (src / "train.py").write_text(TRAIN)
    (src / ".gitignore").write_text("data/\n")
    (src / "plot.py").write_text('BASE = "/home/someone/project/data/"\n')  # a script the audit never runs
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "shipped"]):
        subprocess.run(["git", "-C", str(src), *args], check=True, capture_output=True,
                       env={**__import__("os").environ, **env})
    paths = Paths.make(root=tmp_path / "proj")
    cfg = AuditConfig.model_validate({
        "id": "synth", "paper": {"title": "t", "pdf": "x.pdf"}, "repo": {"url": str(src), "commit": "HEAD"},
        "targets": [{"table": "T", "metric": {"name": "accuracy", "unit": "%", "floor": 1.0}, "seeds": 1}],
        "env": {"entry_points": ["gen_data.py", "train.py"]},
        "smoke": {"data": ["python", "gen_data.py"], "name": "train", "seeds": 1,
                  "command": ["python", "train.py", "--test", "1.0", "--epochs", "3"]}})
    paths.audit_dir("synth").mkdir(parents=True)
    return paths, cfg


SCRIPT = {"/home/someone": [_answer([FIX_PATH], "env")],
          "missing: data/d_corr_1.0.txt": [_answer([FIX_DOMAIN], "hypothesis", "generate the test domain 1.0")],
          "AttributeError": [_answer([FIX_API], "compat", "guard the removed API call by its flag")]}


def test_loop_repairs_and_hypothesis(setup):
    paths, cfg = setup
    llm = ScriptedLLM(SCRIPT)
    rec = run_repair(paths, cfg, llm, python=Path(sys.executable), echo=lambda s: None)
    assert rec["verdict"] == "runs", rec.get("verdict_reason")
    assert [r["class"] for r in rec["repairs"]] == ["env", "compat"]
    assert [r["llm_class"] for r in rec["repairs"]] == ["env", "compat"]
    assert rec["repairs"][0]["message"].startswith("REPAIR(env): make it run (train.py:8)")
    hyp = rec["hypotheses"]
    assert len(hyp) == 1 and hyp[0]["finding"] == "F1" and hyp[0]["run_by_loop"]
    assert hyp[0]["message"].startswith("HYPOTHESIS(F1): generate the test domain 1.0 (gen_data.py:3)")
    assert hyp[0]["domain"] == ["d_corr", "1.0"]
    # el01/repair holds only the repairs; el01/h-F1 sits on top of all of them
    repo = paths.repos / "src"
    log = subprocess.run(["git", "-C", str(repo), "log", "--format=%s", "el01/repair"], capture_output=True,
                         text=True).stdout.splitlines()
    assert [l.split(":")[0] for l in log] == ["REPAIR(compat)", "REPAIR(env)", "shipped"]
    log = subprocess.run(["git", "-C", str(repo), "log", "--format=%s", "el01/h-F1"], capture_output=True,
                         text=True).stdout.splitlines()
    assert [l.split(":")[0] for l in log] == ["HYPOTHESIS(F1)", "REPAIR(compat)", "REPAIR(env)", "shipped"]
    # the inertness trace: 0 calls into yaml, 0 executions of the guarded call
    (ine,) = rec["inertness"]
    assert ine["verdict"] == "inert", ine
    assert ine["without"]["ran"] is False and ine["without"]["failure"]["class"] == "missing attribute or API"
    assert ine["trace"]["libs"] == ["yaml"] and ine["trace"]["lib_calls_total"] == 0
    assert ine["trace"]["line_hits"] == {"train.py:16": 0}
    assert ine["trace"]["command"][ine["trace"]["command"].index("--epochs") + 1] == "5"
    # the failure order, and every failure cites its log line
    assert [r["failure"]["class"] if r["failure"] else None for r in rec["runs"]] == \
        ["missing path", "missing data", "missing attribute or API", None]
    assert all(r["failure"]["log_line"] for r in rec["runs"][:-1])
    # prompts carry no machine path of the worktree
    assert not any(str(paths.worktrees) in p for p in llm.prompts)


def test_policy_rejects_hypothesis_patch(setup):
    paths, cfg = setup
    script = dict(SCRIPT)
    script["/home/someone"] = [_answer([FIX_PATH, BAD_EPOCHS], "env"), _answer([FIX_PATH], "env")]
    rec = run_repair(paths, cfg, ScriptedLLM(script), python=Path(sys.executable), echo=lambda s: None)
    assert rec["verdict"] == "runs"
    first = rec["agent_calls"][0]
    assert first["policy"]["class"] == "hypothesis" and first["policy"]["llm_class"] == "env"
    assert any(r["rule"] == "number" for r in first["policy"]["rules"])
    kept = [h for h in rec["hypotheses"] if not h["run_by_loop"]]
    assert len(kept) == 1 and kept[0]["kind"] == "rejected repair"
    assert len(rec["repairs"]) == 2 and rec["counts"]["repair_attempts"] == 3


def test_not_runnable_after_max_attempts(setup):
    paths, cfg = setup
    bad = _answer([{"file": "train.py", "old": "no such line", "new": "x"}])
    rec = run_repair(paths, cfg, ScriptedLLM({"/home/someone": [bad]}), max_attempts=2,
                     python=Path(sys.executable), echo=lambda s: None)
    assert rec["verdict"] == "Not runnable"
    assert rec["counts"]["repair_attempts"] == 2 and rec["repairs"] == []
    assert all(c["outcome"].startswith("rejected") for c in rec["agent_calls"])


def test_restart_required(setup):
    paths, cfg = setup
    run_repair(paths, cfg, ScriptedLLM(SCRIPT), python=Path(sys.executable), echo=lambda s: None)
    from el01.repair.agent import RepairError
    with pytest.raises(RepairError):
        run_repair(paths, cfg, ScriptedLLM(SCRIPT), python=Path(sys.executable), echo=lambda s: None)
    rec = run_repair(paths, cfg, ScriptedLLM(SCRIPT), python=Path(sys.executable), echo=lambda s: None,
                     restart=True)
    assert rec["verdict"] == "runs" and len(rec["repairs"]) == 2


def test_missing_domain_detection(tmp_path):
    d = tmp_path / "data" / "slab"
    d.mkdir(parents=True)
    for c in ("0.0", "0.1", "0.9"):
        for case in ("train", "test"):
            (d / f"total_slabs_7_slab_noise_0.1_spur_corr_{c}_case_{case}_seed_0.pickle").write_text("")
    f = {"class": "missing data",
         "missing_path": "data/slab/total_slabs_7_slab_noise_0.1_spur_corr_1.0_case_test_seed_0.pickle"}
    cmd = ["python", "train.py", "--n_runs", "1", "--test_domains", "1.0"]
    dom = missing_domain(f, tmp_path, cmd)
    assert dom["field"] == "spur_corr" and dom["missing_value"] == "1.0"
    assert dom["generated_values"] == ["0", "0.1", "0.9"] and dom["flag"] == "--test_domains"
    assert dom["examples"] == ["total_slabs_7_slab_noise_0.1_spur_corr_0.0_case_test_seed_0.pickle",
                               "total_slabs_7_slab_noise_0.1_spur_corr_0.1_case_test_seed_0.pickle",
                               "total_slabs_7_slab_noise_0.1_spur_corr_0.9_case_test_seed_0.pickle"]
    # two fields missing at once: not a single missing domain
    f2 = dict(f, missing_path=f["missing_path"].replace("seed_0", "seed_5"))
    assert missing_domain(f2, tmp_path, cmd) is None
    # a missing folder: not a domain
    assert missing_domain(dict(f, missing_path="nowhere/x_1.0.pickle"), tmp_path, cmd) is None


def test_prompts_identical_across_runs(setup):
    """Commit shas and dates differ between runs; the prompts (and so the cache keys) must not (rule 8)."""
    paths, cfg = setup
    a, b = ScriptedLLM(SCRIPT), ScriptedLLM(SCRIPT)
    r1 = run_repair(paths, cfg, a, python=Path(sys.executable), echo=lambda s: None)
    r2 = run_repair(paths, cfg, b, python=Path(sys.executable), echo=lambda s: None, restart=True)
    assert len(a.prompts) == 3 and a.prompts == b.prompts
    assert [c["key"] for c in r1["agent_calls"]] == [c["key"] for c in r2["agent_calls"]]


def test_patch_outside_run_path_rejected(setup):
    paths, cfg = setup
    also_plot = {"file": "plot.py", "old": 'BASE = "/home/someone/project/data/"', "new": 'BASE = "data/"'}
    script = dict(SCRIPT)
    script["/home/someone"] = [_answer([FIX_PATH, also_plot], "env"), _answer([FIX_PATH], "env")]
    rec = run_repair(paths, cfg, ScriptedLLM(script), python=Path(sys.executable), echo=lambda s: None)
    assert rec["verdict"] == "runs"
    assert rec["agent_calls"][0]["outcome"] == "rejected: changes files the audited commands do not run: plot.py"
    assert rec["repairs"][0]["files"] == ["train.py"] and rec["counts"]["repair_attempts"] == 3
