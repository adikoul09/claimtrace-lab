"""Executor worker (SPEC §8): heartbeat, claim a task, run it, stream METRIC lines into Supabase as they are printed.

  EXECUTOR_NAME=laptop-b EXECUTOR_CAPS=smoke,parse,train  uv run python -m lab.executor.worker [--once]

A `run` task's input: {cmd, cwd?, experiment_id?, label?, timeout_s?, network?, python?, files?, requirements?}
  cmd            list of args, or one string split like a POSIX shell (use forward slashes); `python` -> the worker's
                 interpreter unless input.python names another (or input.requirements gives the env)
  cwd            a folder under runs/, relative to the repo root (default runs/<task_id>/); created if missing
  experiment_id  where the metrics go; without it a new experiments row is made for the task's project
  files          {relative path: text}: the code to run, written into cwd first, so any executor can claim the task
  requirements   pinned requirements text: the worker builds (or reuses) that venv here and runs `python` from it
Every stdout/stderr line goes to Storage `logs/<experiment_id>.log` (and runs/logs/ locally); every METRIC line becomes
a metrics row with its 1-based log line; events are written when the task starts and when it ends.

Ported from baseline/el01-auditor/el01/run/runner.py: stripped environment, closed-proxy guard unless the step needs the
network, hard timeout, unbuffered output. Changed for Round 1: the environment is an allowlist (no keys reach the child),
the whole process tree is killed on timeout, output is streamed line by line, and there is no fork shim (Windows starts
processes with spawn semantics; nothing is inherited but the allowlisted environment)."""
from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from lab.db import ROOT, client, emit, setting
from lab.executor.logparse import error_signature, last_traceback, parse_divergence, parse_metric

RUNS = ROOT / "runs"
HEARTBEAT_S = 10
POLL_S = 2
UPLOAD_EVERY_S = 5
DEFAULT_TIMEOUT_S = 1200
LOG_BUCKET = "logs"

DEAD_PROXY = "http://127.0.0.1:9"  # discard port: ordinary downloads fail (best effort, not a network sandbox)
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
KEEP_VARS = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME",
             "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS",
             "PROCESSOR_ARCHITECTURE", "OS", "LANG", "LC_ALL", "TZ", "USER", "USERNAME", "LOGNAME")
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSCODE", "CREDENTIAL")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def child_env(python: str, network: bool = False) -> dict:
    """Allowlisted environment: nothing from .env and nothing that looks like a secret."""
    env = {k: v for k in KEEP_VARS
           if (v := os.environ.get(k)) is not None and not any(h in k.upper() for h in SECRET_HINTS)}
    env["PATH"] = str(Path(python).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"  # the log keeps everything printed before a crash or a kill
    env["PYTHONIOENCODING"] = "utf-8"
    if not network:
        env.update({k: DEAD_PROXY for k in PROXY_VARS})
    return env


def resolve_argv(cmd, python: str) -> list[str]:
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(a) for a in cmd]
    if argv and argv[0] in ("python", "python3", "{python}"):
        argv[0] = python
    return argv


def resolve_cwd(cwd: str | None, task_id: str) -> Path:
    p = (RUNS / task_id) if not cwd else Path(cwd) if Path(cwd).is_absolute() else ROOT / cwd
    p, runs = p.resolve(), RUNS.resolve()
    if p == runs or not p.is_relative_to(runs):
        raise ValueError(f"cwd must be a folder inside runs/, got {cwd!r}")
    p.mkdir(parents=True, exist_ok=True)
    return p


def start(argv: list[str], cwd: Path, env: dict) -> subprocess.Popen:
    """Windows-safe start: no shell, own process group (so a timeout can kill the whole tree), no stdin."""
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)


def kill_tree(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        p.kill()
    except OSError:
        pass


def cpu_seconds(rusage_before) -> float | None:
    """CPU time (user + system) of the finished process tree on POSIX; None on Windows, where a venv's python.exe is
    a launcher whose own process times miss the real interpreter (measured: 0.1 s for a 449 s run)."""
    if rusage_before is None:
        return None
    import resource
    r, b = resource.getrusage(resource.RUSAGE_CHILDREN), rusage_before
    return round((r.ru_utime + r.ru_stime) - (b.ru_utime + b.ru_stime), 1)


class LogSink:
    """Every line, numbered from 1, kept locally and re-uploaded to Storage at most every UPLOAD_EVERY_S."""

    def __init__(self, db, experiment_id: str):
        self.db, self.object = db, f"{experiment_id}.log"
        self.lines: list[str] = []
        (RUNS / "logs").mkdir(parents=True, exist_ok=True)
        self.local = open(RUNS / "logs" / self.object, "w", encoding="utf-8")
        self.dirty, self.last_upload, self.error = False, 0.0, None

    def add(self, line: str) -> int:
        self.lines.append(line)
        self.local.write(line + "\n")
        self.local.flush()
        self.dirty = True
        return len(self.lines)

    def flush(self, force: bool = False) -> None:
        if not self.dirty or (not force and time.monotonic() - self.last_upload < UPLOAD_EVERY_S):
            return
        data = ("\n".join(self.lines) + "\n").encode("utf-8")
        try:
            self.db.storage.from_(LOG_BUCKET).upload(
                self.object, data, {"content-type": "text/plain; charset=utf-8", "upsert": "true"})
            self.dirty, self.error = False, None
        except Exception as e:  # retried on the next flush; the local copy is complete
            self.error = f"{type(e).__name__}: {e}"
            print(f"[worker] log upload failed (will retry): {self.error}", flush=True)
        self.last_upload = time.monotonic()

    def close(self) -> None:
        self.flush(force=True)
        self.local.close()


def advertised_caps(name: str, caps: list[str]) -> list[str]:
    """EXECUTOR_CAPS plus 'agent' (this worker runs agent tasks) and 'host:<name>' (tasks pinned to this machine,
    e.g. a full run that must use the run folder a smoke run left here)."""
    out = list(dict.fromkeys(caps))
    for extra in ("agent", f"host:{name}"):
        if extra not in out:
            out.append(extra)
    return out


def write_files(files: dict, cwd: Path) -> list[str]:
    """Write a task's code into its run dir. Every path must stay inside cwd. Returns the paths written, sorted."""
    root = Path(cwd).resolve()
    targets = {}
    for rel, text in files.items():
        if not isinstance(text, str):
            raise ValueError(f"files[{rel!r}] must be text")
        target = (root / rel).resolve() if rel and not Path(rel).is_absolute() and ":" not in rel else None
        if target is None or target == root or not target.is_relative_to(root):
            raise ValueError(f"file path {rel!r} is outside the run dir")
        targets[target.relative_to(root).as_posix()] = (target, text)
    for target, text in targets.values():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return sorted(targets)


def ensure_bucket(db) -> None:
    try:
        db.storage.get_bucket(LOG_BUCKET)
    except Exception:
        db.storage.create_bucket(LOG_BUCKET, options={"public": False})


def experiment_for(db, task: dict) -> str:
    inp = task.get("input") or {}
    if inp.get("experiment_id"):
        return inp["experiment_id"]
    if not task.get("project_id"):
        raise ValueError("task has neither input.experiment_id nor project_id; metrics need an experiment")
    row = db.table("experiments").insert({
        "project_id": task["project_id"], "label": inp.get("label") or f"run {task['id'][:8]}",
        "config": {"cmd": inp.get("cmd")}}).execute().data[0]
    return row["id"]


class Worker:
    def __init__(self, name: str, caps: list[str]):
        self.name, self.caps = name, caps
        self.db = client()
        self.busy = False
        self.stop = threading.Event()

    # -- heartbeat ------------------------------------------------------------------------------------------------
    def beat(self, db=None) -> None:
        (db or self.db).table("executors").upsert({
            "name": self.name, "caps": self.caps, "busy": self.busy, "last_heartbeat": utc_now()}).execute()

    def _heartbeat_loop(self) -> None:
        db = client()  # one client per thread
        while not self.stop.is_set():
            try:
                self.beat(db)
            except Exception as e:
                print(f"[worker] heartbeat failed: {type(e).__name__}: {e}", flush=True)
            self.stop.wait(HEARTBEAT_S)

    # -- tasks ----------------------------------------------------------------------------------------------------
    def claim(self) -> dict | None:
        rows = self.db.rpc("claim_task", {"executor_name": self.name, "caps": self.caps}).execute().data
        return rows[0] if rows else None

    def finish(self, task: dict, ok: bool, output: dict, message: str, reason: str, cpu: float = 0.0) -> None:
        db, tid = self.db, task["id"]
        db.table("tasks").update({"status": "done" if ok else "failed", "output": output, "cpu_seconds": cpu,
                                  "finished_at": utc_now()}).eq("id", tid).execute()
        if output.get("experiment_id"):
            db.table("experiments").update({"status": "done" if ok else "failed"}) \
                .eq("id", output["experiment_id"]).execute()
        emit(db, "task_finished" if ok else "task_failed", message, reason, project_id=task.get("project_id"),
             agent_id=task.get("agent_id"), task_id=tid, data=output)
        print(f"[worker] {message} ({reason})", flush=True)

    def run_task(self, task: dict) -> None:
        db, tid, inp = self.db, task["id"], task.get("input") or {}
        try:
            if task["capability"] != "run":
                raise ValueError(f"this worker only runs capability 'run', not {task['capability']!r}")
            if not inp.get("cmd"):
                raise ValueError("input.cmd is missing")
            python = inp.get("python") or sys.executable
            cwd = resolve_cwd(inp.get("cwd"), tid)
            written = write_files(inp["files"], cwd) if inp.get("files") else []
            timeout_s = float(inp.get("timeout_s") or DEFAULT_TIMEOUT_S)
            exp_id = experiment_for(db, task)
        except Exception as e:
            self.finish(task, False, {"error": str(e)}, f"{self.name} could not start task {tid[:8]}",
                        f"bad task: {e}")
            return
        env_info = None
        if inp.get("requirements") is not None:
            from lab.agents.tools import make_env
            try:
                env = make_env(inp["requirements"], RUNS / "envs")
            except Exception as e:
                self.finish(task, False, {"experiment_id": exp_id, "error": str(e)[-2000:]},
                            f"environment build failed on {self.name}", f"make_env: {str(e).splitlines()[0]}")
                return
            python, env_info = env.python, env.as_dict()
            emit(db, "env_ready", f"{self.name}: env {env.key} " + ("reused" if env.cached else
                                                                     f"built in {env.seconds:.0f} s"),
                 f"run needs pinned requirements; {env.tool} venv keyed by their hash",
                 project_id=task.get("project_id"), agent_id=task.get("agent_id"), task_id=tid, data=env_info)
        argv = resolve_argv(inp["cmd"], python)

        log_path = f"{LOG_BUCKET}/{exp_id}.log"
        db.table("experiments").update({"status": "running", "executor": self.name, "log_path": log_path}) \
            .eq("id", exp_id).execute()
        cmd_text = inp["cmd"] if isinstance(inp["cmd"], str) else " ".join(map(str, inp["cmd"]))
        emit(db, "task_started", f"{self.name} started: {cmd_text}",
             f"claimed by {self.name}: required caps {task.get('required_caps') or []} within {self.caps}",
             project_id=task.get("project_id"), agent_id=task.get("agent_id"), task_id=tid,
             data={"experiment_id": exp_id, "cwd": cwd.relative_to(ROOT).as_posix(), "timeout_s": timeout_s,
                   "network": bool(inp.get("network")), "files": written, "env": env_info})

        sink = LogSink(db, exp_id)
        rusage = None
        if os.name != "nt":
            import resource
            rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        t0 = time.monotonic()
        try:
            p = start(argv, cwd, child_env(python, network=bool(inp.get("network"))))
        except OSError as e:
            sink.add(f"worker: could not start {argv[0]!r}: {e}")
            sink.close()
            self.finish(task, False, {"experiment_id": exp_id, "log_path": log_path, "error": str(e)},
                        f"run could not start on {self.name}", f"could not start {argv[0]!r}: {e}")
            return

        timed_out = threading.Event()

        def on_timeout():
            timed_out.set()
            kill_tree(p)

        timer = threading.Timer(timeout_s, on_timeout)
        timer.daemon = True
        timer.start()
        n_metrics, unsent, n_diverged = 0, [], 0
        diverged: set[str] = set()
        try:
            for raw in p.stdout:
                line = raw.rstrip("\r\n")
                n = sink.add(line)
                print(f"  | {line}", flush=True)
                m = parse_metric(line, n)
                d = None if m else parse_divergence(line, n)
                if d:
                    n_diverged += 1
                    if d.name not in diverged:  # the first per metric; a NaN run repeats it every epoch
                        diverged.add(d.name)
                        self.divergence(task, exp_id, d)
                if m:
                    try:
                        db.table("metrics").insert(m.as_row(exp_id)).execute()
                        n_metrics += 1
                    except Exception as e:
                        print(f"[worker] metric insert failed (will retry): {type(e).__name__}", flush=True)
                        unsent.append(m.as_row(exp_id))
                sink.flush()
            code = p.wait()
        except KeyboardInterrupt:
            kill_tree(p)
            p.wait()
            sink.close()
            self.finish(task, False, {"experiment_id": exp_id, "log_path": log_path, "log_lines": len(sink.lines)},
                        f"run stopped on {self.name}", "worker interrupted (Ctrl-C); process tree killed")
            raise
        finally:
            timer.cancel()

        wall = round(time.monotonic() - t0, 1)
        cpu = cpu_seconds(rusage)
        if unsent:
            try:
                db.table("metrics").insert(unsent).execute()
                n_metrics, unsent = n_metrics + len(unsent), []
            except Exception as e:
                print(f"[worker] {len(unsent)} metric rows could not be stored: {type(e).__name__}", flush=True)
        sink.close()

        ok = code == 0 and not timed_out.is_set()
        tb = None if ok else last_traceback(sink.lines)
        sig = None if ok else error_signature(sink.lines)
        output = {"experiment_id": exp_id, "log_path": log_path, "log_lines": len(sink.lines), "exit_code": code,
                  "wall_s": wall, "cpu_s": cpu, "cpu_seconds_source": "rusage" if cpu is not None else "wall_clock",
                  "metrics": n_metrics, "metrics_unsent": len(unsent), "divergences": n_diverged,
                  "error_signature": sig, "error_log_line": tb.log_line if tb else None,
                  "log_upload_error": sink.error}
        if timed_out.is_set():
            reason = f"timeout: process tree killed after {timeout_s:.0f} s"
        elif ok:
            reason = "exit code 0"
        else:
            reason = f"exit code {code}" + (f"; {sig} at log line {tb.log_line}" if sig and tb else "")
        self.finish(task, ok, output,
                    f"run {'finished' if ok else 'failed'} on {self.name} in {wall:.0f} s: "
                    f"{n_metrics} metrics, {len(sink.lines)} log lines", reason,
                    cpu=cpu if cpu is not None else wall)

    def divergence(self, task: dict, exp_id: str, d) -> None:
        """A NaN/inf METRIC line. metrics.value is NOT NULL until B1's migration, so no row yet: the event carries
        the name, raw value, step and log line, and the controller's debug/spawn path reacts to it."""
        try:
            emit(self.db, "divergence_detected", f"{d.name}={d.raw} at step {d.step}",
                 f"non-finite METRIC value at log line {d.log_line}: the run diverged",
                 project_id=task.get("project_id"), agent_id=task.get("agent_id"), task_id=task["id"],
                 data={"experiment_id": exp_id, "name": d.name, "raw": d.raw, "step": d.step,
                       "log_line": d.log_line})
        except Exception as e:  # never stop the run over an event
            print(f"[worker] divergence event failed: {type(e).__name__}: {e}", flush=True)

    # -- main loop ------------------------------------------------------------------------------------------------
    def serve(self, once: bool = False) -> None:
        ensure_bucket(self.db)
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        print(f"[worker] {self.name} online, caps {self.caps}; heartbeat every {HEARTBEAT_S} s", flush=True)
        try:
            while True:
                try:
                    task = self.claim()
                except Exception as e:
                    print(f"[worker] claim failed: {type(e).__name__}: {e}", flush=True)
                    time.sleep(5)
                    continue
                if task is None:
                    time.sleep(POLL_S)
                    continue
                print(f"[worker] claimed task {task['id']} ({task['capability']})", flush=True)
                self.busy = True
                self.beat()
                try:
                    self.run_task(task)
                finally:
                    self.busy = False
                    self.beat()
                if once:
                    return
        except KeyboardInterrupt:
            print("[worker] stopping", flush=True)
        finally:
            self.stop.set()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="ClaimTrace Lab executor worker")
    ap.add_argument("--once", action="store_true", help="exit after one task")
    a = ap.parse_args(argv)
    name = setting("EXECUTOR_NAME")
    caps = [c.strip() for c in (setting("EXECUTOR_CAPS") or "").split(",") if c.strip()]
    if not name or not caps:
        sys.exit("set EXECUTOR_NAME and EXECUTOR_CAPS (env or .env)")
    Worker(name, advertised_caps(name, caps)).serve(once=a.once)


if __name__ == "__main__":
    main()
