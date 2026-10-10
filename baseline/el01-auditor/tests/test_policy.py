"""Repair policy: code classifies every REPAIR and HYPOTHESIS commit of the spike's bundle as the spike did."""
import subprocess

import pytest

from el01.repair.policy import classify_patch, guarded_statements, lex, parse_unified_diff


@pytest.fixture(scope="module")
def commits(paths):
    repo = paths.workspace / "repos" / "robustdg"
    if not (repo / ".git").exists():
        pytest.skip("workspace/repos/robustdg is missing (Phase 0)")
    shas = subprocess.run(["git", "-C", str(repo), "rev-list", "--no-merges", "--remotes=audit/*", "^3eee173"],
                          capture_output=True, text=True, check=True).stdout.split()
    out = {}
    for sha in shas:
        subj = subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%s", sha], capture_output=True,
                              text=True).stdout.strip()
        diff = subprocess.run(["git", "-C", str(repo), "show", "--format=", sha], capture_output=True,
                              text=True).stdout
        out[sha] = (subj, diff)
    return out


# The failure each spike repair answered (Phase 2's classifier on the spike's logs / this laptop's runs).
FAILURES = {"REPAIR(env): hard-coded": ("missing path", "FileNotFoundError"),
            "REPAIR(env): fall back to CPU": ("no GPU", "AssertionError"),
            "REPAIR(compat)": ("missing attribute or API", "AttributeError")}


def test_bundle_repairs_are_repairs(commits):
    repairs = [(s, d) for s, d in commits.values() if s.startswith("REPAIR")]
    assert len(repairs) == 3
    for subj, diff in repairs:
        fc, exc = next(v for k, v in FAILURES.items() if subj.startswith(k))
        r = classify_patch(diff, fc, exc)
        assert r["class"] == subj[len("REPAIR("):subj.index(")")], (subj, r)
        assert r["rules"] == []


def test_bundle_hypotheses_are_hypotheses(commits):
    hyps = [(s, d) for s, d in commits.values() if s.startswith("HYPOTHESIS")]
    assert len(hyps) == 8  # h0, h1, h1b, h2 (twice: own branch and h-combined), h4, h6, F7
    for subj, diff in hyps:
        # whatever failure it would answer, and whatever the agent says, the policy calls it a hypothesis
        r = classify_patch(diff, "missing attribute or API", "AttributeError", llm_class="compat")
        assert r["class"] == "hypothesis", subj
        assert r["rules"], subj


def test_llm_class_is_advisory():
    diff = ("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-base = '/home/u/data/'\n+base = 'data/'\n")
    assert classify_patch(diff, "missing path", "FileNotFoundError", llm_class="compat")["class"] == "env"
    assert classify_patch(diff, "missing path", "FileNotFoundError", llm_class="hypothesis")["class"] == "hypothesis"


@pytest.mark.parametrize("old,new,rule", [
    ("opt = SGD(params, lr=args.lr)", "opt = Adam(params, lr=args.lr)", "training"),
    ("x = f(a)", "x = f(a, 3)", "number"),
    ("domains = args.domains", "domains = args.domains[:2]", "number"),
    ("idx = train_split(d)", "idx = val_split(d)", "data"),
])
def test_rules(old, new, rule):
    diff = f"--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-{old}\n+{new}\n"
    r = classify_patch(diff, "missing attribute or API", "AttributeError", "compat")
    assert r["class"] == "hypothesis" and rule in [x["rule"] for x in r["rules"]]


def test_context_and_comments_do_not_count():
    diff = ("--- a/algo.py\n+++ b/algo.py\n@@ -1,3 +1,4 @@\n def get_test_accuracy(self, epoch):\n"
            "-    lib.hook()  # loss 0.9\n+    if self.args.flag:\n+        lib.hook()  # loss 0.9\n     return acc\n")
    r = classify_patch(diff, "missing attribute or API", "AttributeError", "compat")
    assert r["class"] == "compat", r
    assert guarded_statements(diff) == [{"file": "algo.py", "line": 3, "text": "lib.hook()  # loss 0.9"}]


def test_parser_header_lines_inside_hunks():
    diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n--- not a header\n+x = 1\n"
            " y = 2\n")
    (f,) = parse_unified_diff(diff)
    assert f.path == "a.py" and f.removed == [(1, "-- not a header")] and f.added == [(1, "x = 1")]


def test_lex():
    assert lex('cuda= torch.device("cuda:" + str(args.cuda_device))  # 0.9') == [
        ("name", "cuda"), ("name", "torch"), ("name", "device"), ("str", '"cuda:"'), ("name", "str"),
        ("name", "args"), ("name", "cuda_device")]
    assert [v for k, v in lex("a = b[0.10] + 1e-3 - x2") if k == "num"] == ["0.10", "1e-3"]
