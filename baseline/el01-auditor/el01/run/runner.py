"""Run jobs in parallel up to the budget; every run directory keeps the evidence of what ran.

A job is (worktree, command, seeds, log file). A run directory gets:
  commit.txt        the commit each worktree was at (one sha, as in the spike, or `<sha> <worktree>` lines)
  <job>.log         the job's stdout and stderr
  .jobs/<job>.json  argv, cwd, commit, seeds, start and end UTC, seconds, exit code
  progress.txt      one line per job (`<job> done in Ns`, as the spike's run scripts wrote), then ALL_DONE
  run.json          one entry per session: start and end UTC, jobs run and skipped
Resumable: a job whose status says exit 0 is skipped; failed, timed-out or interrupted jobs run again.
Jobs that share a `group` never run at the same time (e.g. robustdg jobs with the same method_name and train domains
in one worktree share a result directory, and train.py:202-203 creates it with an exists-then-makedirs race); the
pending jobs are started round-robin over groups so a waiting group does not hold every worker.

Isolation (rule 11): audited code runs with the audited env's interpreter, one thread per job, and with proxy variables
pointing at a closed local port so that ordinary Python downloads fail (best effort, not a network sandbox). A job
marked `network` (a data step that downloads a dataset, e.g. MNIST) runs without that guard.
Platform (macOS only): worker processes start with "fork", as on Linux, through the sitecustomize shim in
el01/run/shims/fork/ on PYTHONPATH; recorded in each job's status as `mp_start_method`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout  # not the builtin TimeoutError on 3.10
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

THREAD_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
               "NUMEXPR_NUM_THREADS")
DEAD_PROXY = "http://127.0.0.1:9"  # discard port: connections are refused
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
DROP_VARS = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "NO_PROXY", "no_proxy")
PYTHON_TOKENS = ("python", "python3", "{python}")
FORK_SHIM = Path(__file__).resolve().parent / "shims" / "fork"  # macOS: Linux's "fork" start method (sitecustomize)


@dataclass(frozen=True)
class Job:
    name: str
    cwd: Path                     # the worktree
    argv: Sequence[str]           # argv[0] `python` (or any `{python}` token) becomes the env's interpreter
    seeds: Optional[int] = None   # recorded; the command carries the seeds itself (e.g. --n_runs)
    log: Optional[str] = None     # default <name>.log
    network: bool = False         # data steps only (rule 11): no closed-proxy guard for this job
    group: Optional[str] = None   # jobs of one group run one at a time

    @property
    def log_name(self) -> str:
        return self.log or f"{self.name}.log"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve_argv(argv: Sequence[str], python: Optional[Path]) -> list[str]:
    if python is None:
        return list(argv)
    out = [str(python) if (i == 0 and a in PYTHON_TOKENS) else a for i, a in enumerate(argv)]
    return [str(python) if a == "{python}" else a for a in out]


def job_env(python: Optional[Path] = None, base: Optional[dict] = None, network: bool = False) -> dict:
    env = {k: v for k, v in (os.environ if base is None else base).items() if k not in DROP_VARS}
    env.update({k: "1" for k in THREAD_VARS})
    if not network:  # a data step that downloads keeps the user's own proxy settings, if any
        env.update({k: DEAD_PROXY for k in PROXY_VARS})
    env["PYTHONUNBUFFERED"] = "1"  # the log keeps everything printed before a crash or a kill
    if sys.platform == "darwin":
        env["PYTHONPATH"] = str(FORK_SHIM)
    if python is not None:
        bindir = Path(python).parent
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(bindir.parent)
    return env


def _head(cwd: Path) -> str:
    p = subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else "not-a-git-worktree"


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    tmp.replace(path)


def job_status(run_dir: Path, name: str) -> Optional[dict]:
    p = Path(run_dir) / ".jobs" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _round_robin(jobs: list[Job]) -> list[Job]:
    """Jobs in an order that alternates between groups (jobs without a group are their own group)."""
    queues: dict = {}
    for i, j in enumerate(jobs):
        queues.setdefault(j.group if j.group is not None else ("", i), []).append(j)
    out, qs = [], list(queues.values())
    while qs:
        out += [q.pop(0) for q in qs]
        qs = [q for q in qs if q]
    return out


def run_jobs(run_dir: Path, jobs: Sequence[Job], max_parallel: int = 1, wall_minutes: Optional[float] = None,
             python: Optional[Path] = None, echo: Callable[[str], None] = lambda s: None) -> dict:
    """Run `jobs` (resuming), at most `max_parallel` at a time, within `wall_minutes` for this session.
    Returns {"ran": [...], "skipped": [...], "not_started": [...], "failed": [...], "status": {name: status}}."""
    run_dir = Path(run_dir)
    names = [j.name for j in jobs]
    if len(set(names)) != len(names):
        raise ValueError(f"job names must be unique: {names}")
    (run_dir / ".jobs").mkdir(parents=True, exist_ok=True)

    # commit.txt: written once; a resume from another commit would mix code states in one run directory
    heads = {}
    for j in jobs:
        heads.setdefault(Path(j.cwd).resolve(), _head(Path(j.cwd)))
    commit_text = (next(iter(heads.values())) + "\n" if len(set(heads.values())) == 1 and len(heads) == 1
                   else "".join(f"{sha} {cwd.name}\n" for cwd, sha in sorted(heads.items())))
    commit_file = run_dir / "commit.txt"
    if commit_file.exists() and commit_file.read_text() != commit_text:
        raise RuntimeError(f"{commit_file} records {commit_file.read_text().split()} but the worktrees are at "
                           f"{commit_text.split()}: use a new run directory")
    commit_file.write_text(commit_text)

    done = [j for j in jobs if (job_status(run_dir, j.name) or {}).get("exit_code") == 0]
    pending = _round_robin([j for j in jobs if j not in done])
    group_locks = {j.group: threading.Lock() for j in pending if j.group is not None}
    for j in done:
        echo(f"{j.name}: finished earlier, skipped")
    session = {"start_utc": utc_now(), "max_parallel": max_parallel, "wall_minutes": wall_minutes,
               "skipped": [j.name for j in done], "ran": [], "not_started": []}
    deadline = time.monotonic() + wall_minutes * 60 if wall_minutes else None
    lock = threading.Lock()
    procs: set[subprocess.Popen] = set()
    stopping = threading.Event()
    env = job_env(python)
    net_env = job_env(python, network=True)

    def progress(line: str) -> None:
        with lock:
            with (run_dir / "progress.txt").open("a") as f:
                f.write(line + "\n")
        echo(line)

    def run_one(j: Job) -> Optional[dict]:
        remaining = None if deadline is None else deadline - time.monotonic()
        if stopping.is_set() or (remaining is not None and remaining <= 0):
            with lock:
                session["not_started"].append(j.name)
            return None
        if j.group is not None:
            with group_locks[j.group]:
                return _run(j)
        return _run(j)

    def _run(j: Job) -> Optional[dict]:
        if stopping.is_set():
            return None
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            with lock:
                session["not_started"].append(j.name)
            return None
        argv = resolve_argv(j.argv, python)
        st = {"name": j.name, "argv": argv, "cwd": str(Path(j.cwd).resolve()), "commit": heads[Path(j.cwd).resolve()],
              "seeds": j.seeds, "log": j.log_name, "network": j.network, "group": j.group, "start_utc": utc_now(),
              "mp_start_method": "fork" if "PYTHONPATH" in env and env["PYTHONPATH"] == str(FORK_SHIM) else None}
        t0 = time.monotonic()
        (run_dir / j.log_name).parent.mkdir(parents=True, exist_ok=True)
        with (run_dir / j.log_name).open("w") as log:
            try:
                p = subprocess.Popen(argv, cwd=j.cwd, stdout=log, stderr=subprocess.STDOUT,
                                     env=net_env if j.network else env)
            except OSError as e:  # the command itself is missing: recorded like any failure
                log.write(f"el01 runner: could not start {argv[0]!r}: {e}\n")
                p = None
                code, status = None, "failed"
            if p is not None:
                with lock:
                    procs.add(p)
                try:
                    code = p.wait(timeout=remaining)
                    status = "done" if code == 0 else "failed"
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                    code, status = None, "timeout"
                finally:
                    with lock:
                        procs.discard(p)
        secs = round(time.monotonic() - t0)
        st.update(end_utc=utc_now(), seconds=secs, exit_code=code, status=status)
        if stopping.is_set() and status != "done":
            return None  # interrupted: no status, so the job runs again on resume
        _write_json(run_dir / ".jobs" / f"{j.name}.json", st)
        progress({"done": f"{j.name} done in {secs}s", "failed": f"{j.name} failed (exit {code}) in {secs}s",
                  "timeout": f"{j.name} timed out after {secs}s (wall-clock budget)"}[status])
        with lock:
            session["ran"].append(j.name)
        return st

    if pending:
        pool = ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(pending))))
        try:
            futures = [pool.submit(run_one, j) for j in pending]
            for f in futures:
                while True:  # short waits keep the main thread responsive to Ctrl-C
                    try:
                        f.result(timeout=0.2)
                        break
                    except FutureTimeout:
                        continue
        except KeyboardInterrupt:
            stopping.set()
            with lock:
                for p in procs:
                    p.kill()
            raise
        finally:
            pool.shutdown(wait=True)

    statuses = {j.name: job_status(run_dir, j.name) for j in jobs}
    if pending:
        if all(statuses.values()):
            progress("ALL_DONE")
        else:
            missing = [n for n, s in statuses.items() if s is None]
            progress(f"STOPPED: {len(missing)} job(s) not run (wall-clock budget): {' '.join(missing)}")
    session["end_utc"] = utc_now()
    runlog = run_dir / "run.json"
    sessions = json.loads(runlog.read_text())["sessions"] if runlog.exists() else []
    _write_json(runlog, {"jobs": names, "sessions": sessions + [session]})
    return {"ran": session["ran"], "skipped": session["skipped"], "not_started": session["not_started"],
            "failed": [n for n, s in statuses.items() if s and s["exit_code"] != 0], "status": statuses}
