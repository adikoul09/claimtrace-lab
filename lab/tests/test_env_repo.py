"""T10: make_env (pinned requirements, cached venv per requirements hash) and fetch_repo (https only, pinned commit).
The venv and clone tests are real: they create a venv with no packages and clone a local repository."""
import shutil
import subprocess
from pathlib import Path

import pytest

from lab.agents import tools
from lab.agents.tools import ToolError, check_requirements, env_key


# ---- requirements check (code, before anything is installed) ------------------------------------------------------

def test_pinned_requirements_pass_with_index_options():
    text = "# deps\ntorch==2.4.1\n\n--extra-index-url https://download.pytorch.org/whl/cpu\nnumpy==1.26.4  # pin\n"
    pkgs, opts = check_requirements(text)
    assert pkgs == ["numpy==1.26.4", "torch==2.4.1"]
    assert opts == ["--extra-index-url https://download.pytorch.org/whl/cpu"]


@pytest.mark.parametrize("line", ["torch", "torch>=2.0", "numpy~=1.26", "torch==2.*"])
def test_unpinned_requirements_are_refused(line):
    with pytest.raises(ToolError, match="pinned"):
        check_requirements(f"numpy==1.26.4\n{line}\n")


@pytest.mark.parametrize("line", ["-e .", "-r other.txt", "./local_pkg", "git+https://github.com/x/y",
                                  "--trusted-host example.com", "--index-url http://insecure.example.com/simple"])
def test_editable_local_vcs_and_unsafe_options_are_refused(line):
    with pytest.raises(ToolError):
        check_requirements(f"numpy==1.26.4\n{line}\n")


def test_env_key_ignores_comments_blank_lines_and_order():
    a = env_key("torch==2.4.1\nnumpy==1.26.4\n")
    assert a == env_key("# c\nnumpy==1.26.4\n\ntorch==2.4.1  # x\n")
    assert a != env_key("torch==2.4.0\nnumpy==1.26.4\n")


# ---- make_env (real venv, no packages) -----------------------------------------------------------------------------

def test_make_env_builds_once_then_reuses_the_cached_env(tmp_path):
    first = tools.make_env("# stdlib only\n", tmp_path / "envs")
    assert first.cached is False and Path(first.python).is_file()
    out = subprocess.run([first.python, "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True)
    assert Path(out.stdout.strip()).resolve() == (tmp_path / "envs" / first.key / "venv").resolve()
    second = tools.make_env("\n# stdlib only, again\n", tmp_path / "envs")
    assert second.cached is True and second.python == first.python


def test_make_env_tool_writes_requirements_and_env_json(tmp_path):
    runs = tmp_path / "runs"
    box = tools.ToolBox(runs / "r1", allowed=["make_env"], runs_root=runs)
    obs = box.call("make_env", {"requirements": ""})
    assert "env ready" in obs
    assert (runs / "r1" / "requirements.txt").read_text() == ""
    assert '"python"' in (runs / "r1" / "env.json").read_text()


def test_make_env_tool_reports_unpinned_requirements_to_the_agent(tmp_path):
    runs = tmp_path / "runs"
    box = tools.ToolBox(runs / "r1", allowed=["make_env"], runs_root=runs)
    with pytest.raises(ToolError, match="pinned"):
        box.call("make_env", {"requirements": "torch\n"})


# ---- fetch_repo ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["file:///C:/Users", "C:/Users/someone/repo", "../other", "http://github.com/a/b",
                                 "ssh://git@github.com/a/b", "https://github.com/a/b --upload-pack=x"])
def test_fetch_repo_accepts_only_plain_https_urls(tmp_path, url):
    runs = tmp_path / "runs"
    box = tools.ToolBox(runs / "r1", allowed=["fetch_repo"], runs_root=runs)
    with pytest.raises(ToolError, match="https"):
        box.call("fetch_repo", {"url": url})


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_clone_checks_out_the_pinned_commit_and_records_it(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(src), *a], check=True, capture_output=True, text=True).stdout
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "one")
    first = git("rev-parse", "HEAD").strip()
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "two")

    info = tools.clone(str(src), tmp_path / "runs" / "r1" / "repo", commit=first)
    assert info["commit"] == first
    head = subprocess.run(["git", "-C", str(tmp_path / "runs" / "r1" / "repo"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == first
