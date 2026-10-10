"""Ablation planning pieces: which statements a reach trace watches, and the methods and commands of a table."""
import json

from el01.branch import ablate as A
from el01.branch.compare import level, signature
from el01.config import Paths

SRC = '''import os
class A:
    def f(self, x):
        y = (x +
             1)
        if y > 2:
            return y
        return 0

    def g(self):
        pass
'''


def test_statement_lines_skip_headers_and_imports():
    # 1 import, 3 def header, 5 continuation of the statement on 4, 6 if header, 10 def header, 11 body
    assert A.statement_lines(SRC, {1, 3, 5, 6, 10, 11}) == [4, 6, 11]


def test_table_methods_from_links():
    links = json.loads((Paths.make().audit_dir("matchdg") / "links.json").read_text())
    mt = A.table_methods(links, "Table 1")
    assert list(mt) == ["erm", "dann", "mmd", "coral", "randmatch", "cdann", "c-mmd", "c-coral", "perfmatch"]
    assert mt["erm"]["group"] == mt["perfmatch"]["group"] != mt["dann"]["group"]
    assert mt["mmd"]["group"] == mt["coral"]["group"]          # the shared result directory (DECISIONS.md)
    assert A._opt(mt["erm"]["train"], "--n_runs", "20").count("--n_runs") == 1
    assert A.data_steps(links, "Table 1") == [["python", "data_gen_syn.py"]]


def test_diff_levels():
    d = lambda rem, add: ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -5,1 +5,1 @@\n-" + rem + "\n+" + add + "\n")
    a = signature(d("x = 1", "x = 2  # paper"))
    assert level(a, signature(d("x = 1", "x =  2"))) == "identical"
    assert level(a, signature(d("x = 1", "x = 3"))) == "same lines"
    two = signature(d("x = 1", "x = 3") + "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,1 @@\n-y\n+z\n")
    assert level(a, two) == "covers"
    assert level(two, a) == "different"
