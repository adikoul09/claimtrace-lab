"""The branch writer on a local clone of robustdg, with scripted agents standing in for the LLM (no quota, no cache).

The writer's answer for F2 first changes two settings (selection rule and momentum); the scripted extractor reports
both, each citing a patched line, so code rejects it; the second answer changes only the selection rule and passes.
The scripted extractor also reports an unrelated wording difference in a key the patch never touches: extractor
disagreement, listed but not counted."""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from el01.branch import selfcheck as sc
from el01.branch import writer as W
from el01.config import AuditConfig, Paths
from el01.llm.backend import Response

ROOT = Path(__file__).resolve().parent.parent
REAL = Paths.make()
FILES = ["audit.yaml", "extraction_score.json", "settings.json", "settings_diff.json", "claims.json", "links.json"]
SELECT_OLD = ("            if self.val_acc[-1] > self.max_val_acc:\n"
              "                self.max_val_acc=self.val_acc[-1]")
SELECT_NEW = ("            curr_val_loss= self.get_val_loss()\n"
              "            if curr_val_loss < self.min_val_loss:\n"
              "                self.min_val_loss= curr_val_loss")
INIT = {"file": "algorithms/erm_match.py", "old": "        self.max_val_acc= 0.0",
        "new": "        self.max_val_acc= 0.0\n        self.min_val_loss= float('inf')"}
LOSS_FN = {"file": "algorithms/algo.py", "old": "    def get_dp_noise(self):",
           "new": "    def get_val_loss(self):\n        val_loss= 0.0\n        val_size= 0\n"
                  "        for batch_idx, (x_e, y_e ,d_e, idx_e, obj_e) in enumerate(self.val_dataset):\n"
                  "            with torch.no_grad():\n                x_e= x_e.to(self.cuda)\n"
                  "                y_e= torch.argmax(y_e, dim=1).to(self.cuda)\n                out= self.phi(x_e)\n"
                  "                val_loss+= F.cross_entropy(out, y_e.long(), reduction='sum').item()\n"
                  "                val_size+= y_e.shape[0]\n        return val_loss/val_size\n\n"
                  "    def get_dp_noise(self):"}
H1 = [INIT, LOSS_FN, {"file": "algorithms/erm_match.py", "old": SELECT_OLD, "new": SELECT_NEW}]
MOMENTUM = {"file": "algorithms/algo.py", "old": "momentum= 0.9,  nesterov=True", "new": "momentum= 0.0,  nesterov=True"}


def _line_of(snap: Path, file: str, text: str) -> int:
    for n, l in enumerate((snap / file).read_text().splitlines(), 1):
        if text in l:
            return n
    raise AssertionError(f"{text!r} not in {file}")


class Scripted:
    mode, cli_version = "replay", None

    def __init__(self, base_tree, base_answer):
        self.base_tree, self.base_answer = base_tree, base_answer
        self.writer_answers = [{"readings": [{"label": "cross-entropy", "paper_value": "lowest validation loss",
                                              "edits": H1 + [MOMENTUM], "rationale": "r"}]},
                               {"readings": [{"label": "cross-entropy", "paper_value": "lowest validation loss",
                                              "edits": H1, "rationale": "r"}]}]
        self.prompts = []

    def call(self, req):
        self.prompts.append(req.prompt)
        if req.agent == "branch_writer":
            ans = self.writer_answers.pop(0)
        elif req.inputs["repo_tree"] == self.base_tree:
            ans = self.base_answer
        else:
            snap = req.repo_copy
            ans = copy.deepcopy(self.base_answer)
            s = ans["settings"]
            n = _line_of(snap, "algorithms/erm_match.py", "if curr_val_loss < self.min_val_loss:")
            s["train.model_selection"] = {"value": "min_val_loss", "evidence": [
                {"file": "algorithms/erm_match.py", "lines": str(n), "code": "if curr_val_loss < self.min_val_loss:"}]}
            if "momentum= 0.0" in (snap / "algorithms/algo.py").read_text():
                m = _line_of(snap, "algorithms/algo.py", "momentum= 0.0")
                s["optim.momentum"] = {"value": {"ERM": 0.0}, "evidence": [
                    {"file": "algorithms/algo.py", "lines": str(m), "code": "momentum= 0.0"}]}
            s["eval.metric"]["value"] = "accuracy, worded differently"
        rec = {"response": {"output": ans, "total_cost_usd": 0.0, "num_turns": 1, "models": ["scripted"]}}
        return Response(ans, req.key, "replay", "hit", rec)


@pytest.fixture()
def setup(tmp_path):
    root = tmp_path / "root"
    real_repo = REAL.repos / "robustdg"
    if not (real_repo / ".git").exists():
        pytest.skip("workspace/repos/robustdg is missing (Phase 0)")
    repo = root / "workspace" / "repos" / "robustdg"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(real_repo), str(repo)], check=True)
    base = subprocess.run(["git", "-C", str(real_repo), "rev-parse", "el01/h-F1"], capture_output=True, text=True,
                          check=True).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "branch", "el01/h-F1", base], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", base], check=True)
    audit = root / "audits" / "matchdg"
    audit.mkdir(parents=True)
    for f in FILES:
        shutil.copy(REAL.audit_dir("matchdg") / f, audit / f)
    paths = Paths.make(root=root)
    cfg = AuditConfig.for_audit(paths, "matchdg")
    tree = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{base}^{{tree}}"], capture_output=True, text=True,
                          check=True).stdout.strip()
    answer = json.loads((REAL.audit_dir("matchdg") / "settings/table-1/code_run1.answer.json").read_text())
    return paths, cfg, repo, Scripted(tree, answer)


def test_findings_come_from_the_checker(setup):
    paths, cfg, _, _ = setup
    fs = {f.id: f for f in W.load_findings(paths, cfg, skip=("F1",))}
    assert sorted(fs, key=lambda x: int(x[1:])) == ["F2", "F3", "F4", "F5", "F6", "F7", "F8"]
    assert fs["F2"].keys == ["train.model_selection"] and fs["F2"].table == "Table 1"
    assert fs["F3"].keys == ["optim.momentum", "optim.nesterov"] and fs["F3"].also_in == ["Suppl. Table 11"]
    assert fs["F7"].table == "Suppl. Table 11"
    assert ("loss.terms", None) in fs["F4"].wanted
    assert fs["F6"].wanted == {("train.model_selection_data", "hyperparameter_tuning")}


def test_two_setting_patch_rejected_then_one_setting_passes(setup):
    paths, cfg, repo, llm = setup
    rec = W.run_branches(paths, cfg, llm, only=["F2"], echo=lambda s: None)
    f = rec["findings"][0]
    r = f["readings"][0]
    assert [a["pass"] for a in r["attempts"]] == [False, True]
    first, second = r["attempts"]
    assert "optim.momentum" in first["reason"]
    assert [a["key"] for a in second["attributed"]] == ["train.model_selection"]
    assert "eval.metric" in second["disagreement"]          # noise: listed, not counted
    assert r["status"] == "written" and r["branch"] == "el01/h-F2"
    msg = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s", "el01/h-F2"], capture_output=True,
                         text=True).stdout.strip()
    assert msg.startswith("HYPOTHESIS(F2): train.model_selection: lowest validation loss instead of best_val_accuracy")
    # the retry prompt carried code's reason; the writer prompts name no F-number
    writer_prompts = [p for p in llm.prompts if "branch-writing step" in p]
    assert len(writer_prompts) == 2 and "optim.momentum" in writer_prompts[1]
    assert not any(re.search(r"\bF\d\b", p) for p in writer_prompts)
    assert rec["counts"]["written"] == 1


def test_comment_in_added_line_rejected():
    diff = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,2 @@\n a = 1\n+b = 2  # paper says so\n")
    assert W.added_comments(diff, lambda p: "a = 1\nb = 2  # paper says so\n") == ["x.py:2"]
    diff2 = diff.replace("  # paper says so", "").replace("+b = 2", "+b = '#not a comment'")
    assert W.added_comments(diff2, lambda p: "a = 1\nb = '#not a comment'\n") == []


def test_selfcheck_needs_an_attributed_change():
    base = {k: {"value": None, "checks": []} for k in sc.S.KEYS}
    v = sc.judge("", base, copy.deepcopy(base), {("train.model_selection", None)})
    assert not v["pass"] and "no difference" in v["reason"]
