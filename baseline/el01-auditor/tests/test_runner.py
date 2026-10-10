"""Runner and worktrees on a dummy command: 3 jobs in parallel, evidence files, one thread per job, resume."""
import json
import re
import subprocess
import sys

import pytest

from el01.ingest.repo import GitError
from el01.run.runner import Job, run_jobs
from el01.run.worktrees import ensure_worktree

DUMMY = ("import os, sys, time; print('start', time.time()); print('threads', os.environ.get('OMP_NUM_THREADS')); "
         "print('proxy', os.environ.get('HTTPS_PROXY')); time.sleep(0.6); print('end', time.time()); "
         "sys.exit(int(sys.argv[1]))")


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "train.py").write_text("print('hello')\n")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _jobs(wt, codes=(0, 0, 0)):
    return [Job(name=f"job{i}", cwd=wt, argv=["{python}", "-c", DUMMY, str(c)], seeds=1) for i, c in enumerate(codes)]


def _times(log):
    text = log.read_text()
    return float(re.search(r"^start ([\d.]+)", text, re.M).group(1)), float(re.search(r"^end ([\d.]+)", text, re.M).group(1))


def test_three_jobs_in_parallel(repo, tmp_path):
    wt, sha = ensure_worktree(repo, "HEAD", tmp_path / "worktrees" / "a" / "shipped")
    assert (wt / "train.py").exists() and sha == _git(repo, "rev-parse", "HEAD")
    run_dir = tmp_path / "runs" / "dummy"
    res = run_jobs(run_dir, _jobs(wt), max_parallel=3, python=sys.executable)

    assert sorted(res["ran"]) == ["job0", "job1", "job2"] and res["failed"] == [] and res["not_started"] == []
    assert (run_dir / "commit.txt").read_text() == sha + "\n"
    lines = (run_dir / "progress.txt").read_text().splitlines()
    assert len(lines) == 4 and lines[-1] == "ALL_DONE"
    assert all(re.fullmatch(r"job\d done in \d+s", l) for l in lines[:3])
    for i in range(3):
        log = run_dir / f"job{i}.log"
        assert "threads 1" in log.read_text() and "proxy http://127.0.0.1:9" in log.read_text()
        st = json.loads((run_dir / ".jobs" / f"job{i}.json").read_text())
        assert st["exit_code"] == 0 and st["commit"] == sha and st["seeds"] == 1 and st["argv"][0] == sys.executable
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", st["start_utc"]) and st["end_utc"] >= st["start_utc"]
    spans = [_times(run_dir / f"job{i}.log") for i in range(3)]
    assert max(s for s, _ in spans) < min(e for _, e in spans), "the 3 jobs did not overlap in time"
    session = json.loads((run_dir / "run.json").read_text())["sessions"][0]
    assert session["start_utc"] <= session["end_utc"] and sorted(session["ran"]) == ["job0", "job1", "job2"]

    # resume: nothing runs again, no file is rewritten
    mtimes = {p.name: p.stat().st_mtime_ns for p in run_dir.glob("job*.log")}
    res2 = run_jobs(run_dir, _jobs(wt), max_parallel=3, python=sys.executable)
    assert res2["ran"] == [] and sorted(res2["skipped"]) == ["job0", "job1", "job2"]
    assert {p.name: p.stat().st_mtime_ns for p in run_dir.glob("job*.log")} == mtimes
    assert (run_dir / "progress.txt").read_text().splitlines() == lines


def test_failed_job_is_recorded_and_rerun_on_resume(repo, tmp_path):
    wt, _ = ensure_worktree(repo, "HEAD", tmp_path / "wt")
    run_dir = tmp_path / "runs" / "fail"
    res = run_jobs(run_dir, _jobs(wt, (0, 3, 0)), max_parallel=2, python=sys.executable)
    assert res["failed"] == ["job1"] and res["status"]["job1"]["exit_code"] == 3
    assert "job1 failed (exit 3) in" in (run_dir / "progress.txt").read_text()
    res2 = run_jobs(run_dir, _jobs(wt, (0, 0, 0)), max_parallel=2, python=sys.executable)
    assert res2["ran"] == ["job1"] and res2["failed"] == []


def test_wall_clock_budget_stops_jobs(repo, tmp_path):
    wt, _ = ensure_worktree(repo, "HEAD", tmp_path / "wt")
    run_dir = tmp_path / "runs" / "budget"
    res = run_jobs(run_dir, _jobs(wt), max_parallel=1, wall_minutes=0.3 / 60, python=sys.executable)
    assert res["status"]["job0"]["status"] == "timeout" and res["not_started"] == ["job1", "job2"]
    assert (run_dir / "progress.txt").read_text().splitlines()[-1].startswith("STOPPED: 2 job(s) not run")


def test_worktree_must_match_its_commit(repo, tmp_path):
    first = _git(repo, "rev-parse", "HEAD")
    wt, _ = ensure_worktree(repo, first, tmp_path / "wt")
    (repo / "train.py").write_text("print('changed')\n")
    _git(repo, "commit", "-qam", "second")
    with pytest.raises(GitError, match="expected HEAD"):
        ensure_worktree(repo, "HEAD", wt)
    (wt / "train.py").write_text("tampered\n")
    with pytest.raises(GitError, match="changes to tracked files"):
        ensure_worktree(repo, first, wt)


def test_run_dir_refuses_a_different_commit(repo, tmp_path):
    wt, _ = ensure_worktree(repo, "HEAD", tmp_path / "wt")
    run_dir = tmp_path / "runs" / "x"
    run_jobs(run_dir, _jobs(wt, (0,)), python=sys.executable)
    (run_dir / "commit.txt").write_text("0" * 40 + "\n")
    with pytest.raises(RuntimeError, match="use a new run directory"):
        run_jobs(run_dir, _jobs(wt, (0,)), python=sys.executable)


def test_groups_run_one_at_a_time(repo, tmp_path):
    """Jobs of one group never overlap; another group runs beside them; logs may sit in sub-folders."""
    wt, _ = ensure_worktree(repo, "HEAD", tmp_path / "wt")
    jobs = [Job(name=f"a{i}", cwd=wt, argv=["{python}", "-c", DUMMY, "0"], group="A", log=f"arm/a{i}.log")
            for i in range(2)] + [Job(name="b0", cwd=wt, argv=["{python}", "-c", DUMMY, "0"], group="B")]
    res = run_jobs(tmp_path / "run", jobs, max_parallel=3, python=sys.executable)
    assert not res["failed"] and len(res["ran"]) == 3
    a0, a1 = _times(tmp_path / "run" / "arm" / "a0.log"), _times(tmp_path / "run" / "arm" / "a1.log")
    b0 = _times(tmp_path / "run" / "b0.log")
    assert a0[1] <= a1[0] or a1[1] <= a0[0]                      # group A: one at a time
    assert min(a0[1], a1[1]) > b0[0] and b0[1] > min(a0[0], a1[0])  # B overlaps A
    assert json.loads((tmp_path / "run" / ".jobs" / "a0.json").read_text())["group"] == "A"
