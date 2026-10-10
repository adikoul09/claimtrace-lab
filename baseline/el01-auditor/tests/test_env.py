"""Environment builder: Python choice, wheel tags, wheel-gap bumps, requirements, the import scan. No network."""
import json
from datetime import date

import pytest

from el01.config import Paths
from el01.env.builder import (Host, PyPI, Req, _plan_entries, compare_freeze, max_python_from_filenames, months_before,
                              parse_lock, parse_requirements, python_by_date, wheel_ok)
from el01.env.imports import dist_for_module, module_for_dist, scan

MAC_ARM = Host("Darwin", "arm64", (27, 0))


def test_python_by_commit_date():
    assert python_by_date(date(2022, 3, 20))[0] == "3.9"   # robustdg @ 3eee173 (spec section 4)
    assert python_by_date(date(2022, 4, 3))[0] == "3.9"
    assert python_by_date(date(2022, 4, 4))[0] == "3.10"   # 3.10.0: 2021-10-04
    assert months_before(date(2022, 8, 31), 6) == date(2022, 2, 28)
    assert months_before(date(2022, 3, 20), 6) == date(2021, 9, 20)


def test_max_python_from_wheel_names():
    torch181 = ["torch-1.8.1-cp36-cp36m-manylinux1_x86_64.whl", "torch-1.8.1-cp39-cp39-manylinux1_x86_64.whl",
                "torch-1.8.1-cp38-none-macosx_10_9_x86_64.whl"]
    assert max_python_from_filenames(torch181) == "3.9"
    assert max_python_from_filenames(["tensorflow_gpu-1.15.2-cp37-cp37m-manylinux2010_x86_64.whl"]) == "3.7"
    assert max_python_from_filenames(torch181 + ["x-1.0-py3-none-any.whl"]) is None
    assert max_python_from_filenames(["x-1.0.tar.gz"]) is None


@pytest.mark.parametrize("filename,py,host,ok", [
    ("torch-1.11.0-cp39-none-macosx_11_0_arm64.whl", "3.9.25", MAC_ARM, True),
    ("torch-1.11.0-cp39-none-macosx_11_0_arm64.whl", "3.10", MAC_ARM, False),
    ("h5py-3.6.0-cp39-cp39-macosx_10_9_x86_64.whl", "3.9", MAC_ARM, False),
    ("numpy-1.22.3-cp39-cp39-macosx_10_9_universal2.whl", "3.9", MAC_ARM, True),
    ("scipy-1.8.0-cp39-cp39-macosx_12_0_arm64.whl", "3.9", Host("Darwin", "arm64", (11, 0)), False),
    ("cryptography-36.0.0-cp36-abi3-macosx_10_10_universal2.whl", "3.9", MAC_ARM, True),
    ("opacus-1.1.0-py3-none-any.whl", "3.9", MAC_ARM, True),
    ("six-1.16.0-py2.py3-none-any.whl", "3.9", Host("Windows", "AMD64"), True),
    ("numpy-1.22.3-cp39-cp39-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", "3.9", Host("Linux", "x86_64"), True),
    ("numpy-1.22.3-cp39-cp39-manylinux_2_17_aarch64.manylinux2014_aarch64.whl", "3.9", Host("Linux", "x86_64"), False),
    ("numpy-1.22.3-cp39-cp39-win_amd64.whl", "3.9", Host("Windows", "AMD64"), True),
])
def test_wheel_tags(filename, py, host, ok):
    assert wheel_ok(filename, py, host) is ok


def _file(name, t, kind="bdist_wheel"):
    return {"filename": name, "packagetype": kind, "upload_time_iso_8601": t, "yanked": False}


def test_wheel_gap_bump_picks_the_earliest_release_with_a_wheel(tmp_path):
    rel = {"3.6.0": [_file("h5py-3.6.0-cp39-cp39-macosx_10_9_x86_64.whl", "2021-11-16T10:00:00.000000Z"),
                     _file("h5py-3.6.0.tar.gz", "2021-11-16T10:00:00.000000Z", "sdist")],
           "3.7.0rc1": [_file("h5py-3.7.0rc1-cp39-cp39-macosx_11_0_arm64.whl", "2022-05-01T00:00:00.000000Z")],
           "3.7.0": [_file("h5py-3.7.0-cp39-cp39-macosx_11_0_arm64.whl", "2022-05-24T09:00:00.000000Z"),
                     _file("h5py-3.7.0-cp39-cp39-macosx_10_9_x86_64.whl", "2022-05-24T09:30:00.000000Z")],
           "3.8.0": [_file("h5py-3.8.0-cp39-cp39-macosx_11_0_arm64.whl", "2023-01-23T00:00:00.000000Z")]}
    (tmp_path / "h5py.json").write_text(json.dumps({"releases": rel}))
    (tmp_path / "h5py-3.6.0.json").write_text(json.dumps({"urls": rel["3.6.0"]}))
    pypi = PyPI(tmp_path)
    assert not pypi.has_wheel("h5py", "3.6.0", "3.9", MAC_ARM)
    assert pypi.next_wheel_release("h5py", "3.6.0", "3.9", MAC_ARM) == ("3.7.0", "2022-05-24", "2022-05-24T09:30:01Z")
    assert pypi.next_wheel_release("h5py", "3.6.0", "3.9", Host("Linux", "x86_64")) is None


def test_requirements_and_lock_parsing():
    text = "numpy\n# comment\ntorch==1.8.1  # pinned\n-r other.txt\ngit+https://x/y.git\nscikit_learn[alldeps]>=0.24 ; python_version>'3'\ntensorflow-gpu==1.15.2"
    reqs, unsupported = parse_requirements(text)
    assert [r.name for r in reqs] == ["numpy", "torch", "scikit-learn", "tensorflow-gpu"]
    assert [r.pinned for r in reqs] == [None, "1.8.1", None, "1.15.2"]
    assert [r.lineno for r in reqs] == [1, 3, 6, 7] and unsupported == ["line 4: -r other.txt", "line 5: git+https://x/y.git"]
    assert parse_lock("torch==1.11.0\n    # via torchvision\nScikit_Learn==1.0.2\n") == {"torch": "1.11.0", "scikit-learn": "1.0.2"}
    d = compare_freeze({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "9", "d": "4"})
    assert d == {"changed": [{"package": "b", "ours": "2", "theirs": "9"}], "only_ours": [{"package": "c", "version": "3"}],
                 "only_theirs": [{"package": "d", "version": "4"}], "same": 1}


def test_module_distribution_names():
    assert dist_for_module("sklearn") == "scikit-learn" and dist_for_module("more_itertools") == "more-itertools"
    assert module_for_dist("tensorflow-gpu") == "tensorflow" and module_for_dist("More_Itertools") == "more_itertools"
    assert module_for_dist("pillow") == "PIL" and dist_for_module("absl") == "absl-py"


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture()
def fake_repo(tmp_path):
    _write(tmp_path, "main.py", "import os, numpy\nimport pkg.mod\nfrom ns import tool\nclass A:\n    import attr\n"
           "def f():\n    import torch\n    from lazymod import g\nif os.name:\n    import pandas\n"
           "try:\n    import pycuda.driver\nexcept:\n    pass\ntry:\n    import cupy\nexcept ImportError:\n    import numpy\n")
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/mod.py", "import scipy\nfrom . import helper\n")
    _write(tmp_path, "pkg/helper.py", "import yaml\n")
    _write(tmp_path, "ns/tool.py", "import sklearn.manifold\n")       # namespace package: no __init__.py
    _write(tmp_path, "lazymod.py", "import opacus\nimport pandas\nimport scipy\n")
    _write(tmp_path, "unused.py", "import tensorflow\n")
    return tmp_path


def test_import_tiers(fake_repo):
    sc = scan(fake_repo, ["main.py"])
    tiers = {m: sc.tier(m) for m in sc.third_party}
    assert tiers == {"numpy": "eager", "scipy": "eager", "yaml": "eager", "sklearn": "eager", "attr": "eager",
                     "torch": "lazy", "pandas": "lazy", "opacus": "lazy", "pycuda": "guarded", "cupy": "guarded"}
    assert sc.local_files == {"lazymod.py": "lazy", "main.py": "eager", "ns/tool.py": "eager", "pkg/__init__.py": "eager",
                              "pkg/helper.py": "eager", "pkg/mod.py": "eager"}
    assert [str(s) for s in sc.third_party["opacus"]] == ["lazymod.py:1 (lazy)"]


def test_plan_entries(fake_repo):
    sc = scan(fake_repo, ["main.py"])
    reqs, _ = parse_requirements("numpy==1.22.3\nscikit-learn\nadvertorch\ntorch\n")
    entries, log = _plan_entries(sc, reqs, ["more-itertools==8.12.0"])
    by = {e.dist: e for e in entries}
    assert by["numpy"].line == "numpy==1.22.3" and by["numpy"].tier == "eager" and by["torch"].tier == "lazy"
    assert by["pyyaml"].source.startswith("added: `yaml` imported at pkg/helper.py:1")
    assert by["more-itertools"].source == "audit.yaml env.extra" and "pycuda" not in by and "cupy" not in by
    assert log["not_imported"] == [{"line": "advertorch", "lineno": 3}]
    assert [g["module"] for g in log["guarded"]] == ["cupy", "pycuda"]
    assert sorted(a["dist"] for a in log["added"]) == ["attrs", "more-itertools", "opacus", "pandas", "pyyaml", "scipy"]


ROBUSTDG = Paths.make().repos / "robustdg"


@pytest.mark.skipif(not (ROBUSTDG / "train.py").exists(), reason="robustdg clone missing (Phase 0, step 5)")
def test_robustdg_scan():
    sc = scan(ROBUSTDG, ["data_gen_syn.py", "train.py", "test.py"])
    assert {"torch", "torchvision", "numpy", "sklearn", "scipy", "pandas", "matplotlib", "seaborn"} <= set(sc.modules("eager"))
    assert {"opacus", "more_itertools", "tensorflow", "mia", "h5py"} <= set(sc.modules("lazy"))
    assert "pycuda" in sc.modules("guarded")


ENV = Paths.make().envs / "matchdg"


@pytest.mark.skipif(not (ENV / "env.json").exists(), reason="run `el01 env build matchdg` first")
def test_built_matchdg_env():
    """Phase 2 acceptance: Python 3.9.x, torch 1.11.0, numpy 1.22.3 in the built env."""
    rep = json.loads((ENV / "env.json").read_text())
    freeze = parse_lock((ENV / "freeze.txt").read_text())
    assert rep["status"] == "built" and rep["python"]["installed"].startswith("3.9.")
    assert (freeze["torch"], freeze["numpy"]) == ("1.11.0", "1.22.3")
    assert rep["import_check"]["torch"] == "imported" and rep["import_check"]["opacus"] == "found"
