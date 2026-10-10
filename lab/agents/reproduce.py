"""Autonomous reproduction (SPEC §7.2-7.3): design -> code -> environment -> smoke -> budget -> full run.

Agents do the open-ended parts; code checks every answer and makes every decision:
  design       Designer picks the experiment and one model per target claim     code: claim ids exist and are valid
  write_code   Implementer writes train.py from the claims and settings only     code: compiles, CLI and METRIC contract,
                                                                                 never touches the golden reference
  setup_env    EnvBuilder writes pinned requirements and calls make_env          code: pinned check, venv per hash
  smoke        run task (caps: smoke): 1 epoch on 5,000 examples                 code: per-model epoch time from METRIC
  budget       Designer proposes epochs                                          code: clips to the project cap
  full         run task (caps: train), METRIC lines stream to Supabase           the budget reason is on the experiment
A failed smoke goes back to the Implementer (or the EnvBuilder for a missing module) as REPAIR(code)/REPAIR(env),
at most MAX_REPAIRS times. Run tasks carry train.py and the requirements, so any executor with the caps can claim them.

The Implementer works only in runs/<project>/repro/ (file tools cannot leave it) and is never shown
papers/<name>/reference.py or its results: those are the golden check for grading, not an input.

  python -m lab.agents.reproduce --project-id <id> [--executor-name laptop-b] [--cap-min 20] [--no-wait]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lab.agents.runtime import run_agent
from lab.agents.tools import RUNS
from lab.db import client, emit, setting
from lab.llm import LLM

SMOKE_EPOCHS, SMOKE_SUBSET = 1, 5000
MAX_REPAIRS = 2
DEFAULT_CAP_MIN = 20
DATA_DIR = "../../../data"  # from runs/<project>/repro/ to the shared data/ folder on every executor
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
GOLDEN = ("reference.py", "results_full", "papers/")
MARGIN_FLOOR = {"errors": 10}
MARGIN_REASON = {"errors": "SPEC §7.5 floor for MNIST test errors: 10 of 10,000 (the paper states no spread); "
                           "declared before the run"}


class StepError(Exception):
    pass


class AgentError(StepError):
    """The agent itself failed (LLM error, budget stop), as opposed to its output failing the code check."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- checks (pure; tested) ---------------------------------------------------------------------------------------

def parse_answer(text: str) -> dict:
    """An agent's final answer as a JSON object; tolerates a ```json fence or a sentence around it."""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    for candidate in (s, s[s.find("{"): s.rfind("}") + 1] if "{" in s else ""):
        try:
            out = json.loads(candidate)
            if isinstance(out, dict):
                return out
        except (json.JSONDecodeError, ValueError):
            pass
    raise StepError(f"the answer is not a JSON object: {text[:200]!r}")


def check_design(design: dict, claims: list[dict]) -> dict:
    by_id = {c["id"]: c for c in claims}
    models = design.get("models") or []
    if not models:
        raise StepError("the design needs at least one model")
    seen, problems = set(), []
    for m in models:
        name, cid = m.get("name", ""), m.get("claim_id", "")
        if not NAME_RE.match(name or ""):
            problems.append(f"model name {name!r} must be snake_case")
        if name in seen:
            problems.append(f"model name {name!r} is used twice")
        seen.add(name)
        if cid not in by_id:
            problems.append(f"there is no claim {cid} (model {name})")
        elif not by_id[cid].get("valid"):
            problems.append(f"claim {cid} is not valid (its quote or value failed the code check)")
    if problems:
        raise StepError("; ".join(problems))
    return {**design, "claim_map": {m["name"]: m["claim_id"] for m in models}}


def check_train_script(code: str, names: list[str]) -> list[str]:
    problems = []
    try:
        compile(code, "train.py", "exec")
    except SyntaxError as e:
        return [f"train.py does not compile: {e.msg} at line {e.lineno}"]
    for flag in ("--data-dir", "--epochs", "--subset"):
        if flag not in code:
            problems.append(f"missing CLI flag {flag}")
    if "METRIC " not in code:
        problems.append("prints no METRIC lines (format: METRIC name=value step=N)")
    if "CONFIG" not in code:
        problems.append("prints no CONFIG line with the chosen hyperparameters")
    for token in ("final_", "_epoch_s", "train_examples_full"):
        if token not in code:
            problems.append(f"never prints the {token} metric(s) the contract requires")
    for name in names:
        if name not in code:
            problems.append(f"never mentions model {name!r}")
    hits = [g for g in GOLDEN if g in code]
    if hits:
        problems.append(f"touches the golden reference ({', '.join(hits)}); write it from the paper only")
    return problems


def _values(metrics: list[dict], name: str) -> list[float]:
    return [float(m["value"]) for m in metrics if m["name"] == name]


def smoke_timing(metrics: list[dict], wall_s: float, models: list[str]) -> dict:
    needed = ["train_examples", "train_examples_full", *(f"{m}_epoch_s" for m in models)]
    missing = [n for n in needed if not _values(metrics, n)]
    if missing:
        raise StepError(f"the smoke run printed no {', '.join(missing)}")
    used, full = _values(metrics, "train_examples")[0], _values(metrics, "train_examples_full")[0]
    if used <= 0 or full <= 0:
        raise StepError(f"bad example counts: train_examples={used}, train_examples_full={full}")
    scale = full / used
    raw = {m: _values(metrics, f"{m}_epoch_s") for m in models}
    epoch_s_full = {m: round(sum(v) / len(v) * scale, 1) for m, v in raw.items()}
    return {"scale": round(scale, 3), "epoch_s_full": epoch_s_full,
            "per_epoch_s": round(sum(epoch_s_full.values()), 1),
            "overhead_s": round(max(0.0, wall_s - sum(sum(v) for v in raw.values())), 1),
            "train_examples": int(used), "train_examples_full": int(full), "smoke_wall_s": wall_s}


def plan_budget(proposal: dict, timing: dict, cap_s: float, executor: str) -> dict:
    epochs = proposal.get("epochs")
    if not isinstance(epochs, int) or isinstance(epochs, bool) or epochs < 1:
        raise StepError(f"epochs must be a positive integer, got {epochs!r}")
    per, over, full = timing["per_epoch_s"], timing["overhead_s"], timing["train_examples_full"]
    left = cap_s - over
    if left <= 0 or per <= 0:
        raise StepError(f"the smoke start-up overhead ({over:.0f} s) alone exceeds the cap ({cap_s:.0f} s)")
    max_epochs = int(left // per)
    if max_epochs >= 1:
        final, subset = min(epochs, max_epochs), 0
        est = over + final * per
    else:
        final, subset = 1, int(full * left / per)
        est = over + per * subset / full
    clipped = final != epochs or subset != 0
    k = len(timing["epoch_s_full"])
    per_model = ", ".join(f"{m} {s:.1f} s" for m, s in timing["epoch_s_full"].items())
    data = f"{subset} of {full} examples" if subset else "full data"
    clock = " (wall-clock: CPU time of a venv run is not measurable on Windows)" if os.name == "nt" else ""
    reason = (f"{final} epochs × {k} models on {data} ≈ {est / 60:.1f} min, timed on {executor}: smoke "
              f"{per:.1f} s/epoch at full data ({per_model}) + {over:.0f} s start-up; cap {cap_s / 60:.0f} min"
              f"{clock}.")
    if clipped:
        reason += f" Designer proposed {epochs} epochs; code clipped it to fit the cap."
    if proposal.get("reason"):
        reason += f" Designer: {proposal['reason']}"
    return {"epochs": final, "subset": subset, "est_s": round(est, 1), "clipped": clipped, "proposed": epochs,
            "max_epochs": max_epochs, "cap_s": cap_s, "reason": reason}


def declare_margin(target_claims: list[dict]) -> tuple[float | None, str]:
    units = {c.get("unit") for c in target_claims}
    if len(units) == 1 and (u := units.pop()) in MARGIN_FLOOR:
        return MARGIN_FLOOR[u], MARGIN_REASON[u]
    return None, f"no margin floor for units {sorted(map(str, units))}; the paper states no spread"


# ---- goals (what each agent is told) -----------------------------------------------------------------------------

def _claim_line(c: dict) -> str:
    return (f"{c['id']} | {c.get('model')} | {c.get('metric')} = {c.get('value')} {c.get('unit')} "
            f"({c.get('direction')}, {c.get('whose')}) | \"{c.get('quote')}\" (p. {c.get('page')})")


def _setting_line(s: dict) -> str:
    if s.get("value") is None:
        return f"- {s['key']} ({s.get('applies_to') or 'all'}): not stated by the paper"
    return f"- {s['key']} ({s.get('applies_to') or 'all'}): {s['value']} — \"{s.get('quote')}\" (p. {s.get('page')})"


def designer_goal(claims: list[dict], settings: list[dict], cap_min: float) -> str:
    valid = [c for c in claims if c.get("valid")]
    return (f"Choose what to reproduce from this paper on a CPU, with at most {cap_min:g} CPU-minutes for the full run.\n"
            "Pick ONE experiment whose key result can be reproduced at small scale on CPU (a dataset available "
            "through torchvision, small models). List the models to train; each model reproduces exactly one claim "
            "below (use its id). Order the models so that a model another one needs (e.g. a teacher) comes first.\n\n"
            "Claims (id | model | metric | direction, whose | quote):\n" + "\n".join(map(_claim_line, valid)) +
            "\n\nSettings stated by the paper:\n" + "\n".join(map(_setting_line, settings)) +
            '\n\nFinish with answer = a JSON object: {"experiment": "<one line>", "reason": "<why this experiment '
            'and why it fits on CPU>", "models": [{"name": "<snake_case>", "claim_id": "<id>", "description": '
            '"<architecture and training, from the settings>"}]}')


def implementer_goal(design: dict, claims: list[dict], settings: list[dict], feedback: str | None = None) -> str:
    by_id = {c["id"]: c for c in claims}
    models, names = design["models"], [m["name"] for m in design["models"]]
    model_lines = "\n".join(
        f"- {m['name']}: {m.get('description', '')}\n  reproduces claim {m['claim_id']}: "
        f"{_claim_line(by_id[m['claim_id']])}" for m in models)
    finals = "\n".join(
        f"  METRIC final_{m['name']}=<{by_id[m['claim_id']].get('metric')} in {by_id[m['claim_id']].get('unit')}, "
        f"on the full test set> step=0" for m in models)
    goal = (
        f"Write train.py (one file, Python 3, PyTorch on CPU) that reproduces this experiment from the paper: "
        f"{design.get('experiment')}\n\nModels, trained in this order:\n{model_lines}\n\n"
        "Paper settings (verbatim quotes; 'not stated' means you choose a sensible value and say so in CONFIG):\n"
        + "\n".join(map(_setting_line, settings)) +
        "\n\nContract (code checks it; the run fails otherwise):\n"
        "- CLI: python train.py --data-dir DIR --epochs N --subset M --seed S\n"
        "  --epochs: epochs for EVERY model; --subset: train on the first M training examples (0 = all); load the "
        "dataset with torchvision.datasets(..., download=True) into --data-dir.\n"
        "- CPU only. Read no files other than the dataset; write nothing outside the current folder.\n"
        "- First print one line: CONFIG <json of every hyperparameter you chose: optimizer, lr, batch size, momentum, "
        "loss weights, temperature, dropout, weight constraints, augmentation, ...>\n"
        "- Then print METRIC train_examples=<examples used> step=0 and METRIC train_examples_full=<training set "
        "size> step=0\n"
        f"- After every epoch of every model ({', '.join(names)}) print METRIC <name>_train_loss=<v> step=<epoch>, "
        "METRIC <name>_test_errors=<v> step=<epoch> (or the claim's metric) and METRIC <name>_epoch_s=<seconds for "
        "that epoch, evaluation included> step=<epoch>\n"
        "- At the end print, for each model, its final value in the claim's unit:\n" + finals + "\n"
        "- Metric lines use exactly: METRIC name=value step=N (numbers only, print(..., flush=True)).\n"
        "- If a loss becomes NaN or inf, print a line saying so and stop training that model.\n"
        "Write the file with write_file (path train.py), then finish with a one-line summary of your choices.")
    if feedback:
        goal += f"\n\nYour previous train.py failed. Fix it (keep everything that worked):\n{feedback}"
    return goal


def envbuilder_goal(feedback: str | None = None) -> str:
    goal = ("train.py in your run dir needs a Python environment. Read train.py, then call make_env with the "
            "requirements.txt content: one line per third-party package that train.py imports, pinned as "
            f"name==version.\nExecutor: Python {platform.python_version()} on {platform.platform()} "
            f"({platform.machine()}). Choose versions that publish wheels for this platform and Python; if a pin is "
            "wrong, pip's error lists the versions that exist. For PyTorch CPU wheels you may add the line "
            "--extra-index-url https://download.pytorch.org/whl/cpu\nFinish when make_env reports 'env ready'.")
    if feedback:
        goal += f"\n\nThe last run failed because of the environment:\n{feedback}"
    return goal


def budget_goal(design: dict, timing: dict, cap_s: float, executor: str, settings: list[dict]) -> str:
    per_model = "\n".join(f"- {m}: {s:.1f} s/epoch" for m, s in timing["epoch_s_full"].items())
    said = [_setting_line(s) for s in settings if s["key"] == "epochs"] or ["- epochs: not stated"]
    max_epochs = int((cap_s - timing["overhead_s"]) // timing["per_epoch_s"]) if timing["per_epoch_s"] else 0
    return (f"Choose the number of epochs (the same for every model) for the full reproduction run of: "
            f"{design.get('experiment')}\n\nSmoke run on {executor}: 1 epoch on {timing['train_examples']} of "
            f"{timing['train_examples_full']} training examples; code scaled the times to the full data:\n"
            f"{per_model}\nStart-up overhead: {timing['overhead_s']:.0f} s. Project cap: {cap_s / 60:.0f} minutes, "
            f"i.e. at most about {max_epochs} epochs on the full data.\nThe paper says:\n" + "\n".join(said) +
            '\n\nFinish with answer = a JSON object: {"epochs": <int>, "reason": "<one sentence>"}. '
            "Code checks it against the cap.")


# ---- orchestration (Supabase + agents; verified end to end) ------------------------------------------------------

class Pipeline:
    def __init__(self, db, project_id: str, executor: str, cap_min: float | None = None, llm: LLM | None = None,
                 wait: bool = True):
        self.db, self.pid, self.executor, self.wait = db, project_id, executor, wait
        self.llm = llm or LLM(db=db)
        self.project = db.table("projects").select("*").eq("id", project_id).single().execute().data
        rows = db.table("papers").select("*").eq("project_id", project_id).execute().data
        if not rows or not rows[0].get("claims"):
            raise StepError("the project has no papers row with claims; run the Reader first (T05)")
        self.paper = rows[0]
        self.claims, self.settings = self.paper["claims"], self.paper.get("settings") or []
        self.cap_s = 60 * float(cap_min or self.project.get("budget_cpu_min") or DEFAULT_CAP_MIN)
        self.rel = f"runs/{project_id}/repro"
        self.workdir = RUNS / project_id / "repro"
        self.workdir.mkdir(parents=True, exist_ok=True)

    # -- small helpers --
    def event(self, type_: str, message: str, reason: str, **kw) -> None:
        emit(self.db, type_, message, reason, project_id=self.pid, **kw)
        print(f"[repro] {message} ({reason[:160]})", flush=True)

    def agent_for(self, capability: str) -> dict:
        rows = self.db.table("agents").select("*").eq("status", "active").contains("capabilities", [capability]) \
            .order("version", desc=True).execute().data
        if not rows:
            raise StepError(f"no active agent has capability {capability!r} (a gap for the controller to fill)")
        return rows[0]

    def agent_step(self, capability: str, title: str, goal: str, check, model: str = "fast"):
        """Run one agent as a tasks row; `check(result)` is the code acceptance check: it returns the step's output
        or raises StepError. Returns (output, task_id)."""
        agent = self.agent_for(capability)
        task = self.db.table("tasks").insert({
            "project_id": self.pid, "capability": capability, "agent_id": agent["id"], "executor": self.executor,
            "status": "running", "started_at": utc_now(),
            "input": {"title": title, "goal": goal, "workdir": self.rel},
            "acceptance": {"text": check.__doc__ or "code check"}}).execute().data[0]
        res = run_agent(agent, goal, self.workdir, db=self.db, llm=self.llm, task_id=task["id"],
                        project_id=self.pid, model=model)
        ok, problems, output = False, [], {}
        if res.status != "finished":
            problems = [f"agent {res.status}: {res.reason}"]
        else:
            try:
                output, ok = check(res), True
            except StepError as e:
                problems = [str(e)]
        self.db.table("tasks").update({
            "status": "done" if ok else "failed", "tokens": res.tokens, "cpu_seconds": res.cpu_s,
            "finished_at": utc_now(), "output": {"answer": (res.answer or "")[:2000], **(output or {})},
            "acceptance": {"text": check.__doc__ or "code check", "passed": ok, "problems": problems},
        }).eq("id", task["id"]).execute()
        self.event("task_finished" if ok else "task_failed", f"{agent['name']}: {title} "
                   f"{'passed' if ok else 'failed'} its code check",
                   "; ".join(problems) if problems else f"{res.steps} steps, {res.tokens} tokens",
                   agent_id=agent["id"], task_id=task["id"])
        if not ok:
            raise (StepError if res.status == "finished" else AgentError)(f"{title}: {'; '.join(problems)}")
        return output, task["id"]

    def queue_run(self, title: str, scale: str, caps: list[str], args: str, code: str, requirements: str,
                  experiment_id: str, timeout_s: int) -> dict:
        task = self.db.table("tasks").insert({
            "project_id": self.pid, "capability": "run", "required_caps": caps, "status": "queued",
            "input": {"title": title, "scale": scale, "cmd": f"python train.py {args}", "cwd": self.rel,
                      "files": {"train.py": code}, "requirements": requirements, "experiment_id": experiment_id,
                      "network": True, "network_reason": "dataset download if this executor lacks it",
                      "timeout_s": timeout_s, "label": title},
            "acceptance": {"text": "exit code 0 and every final_<model> METRIC line printed"}}).execute().data[0]
        self.event("task_queued", f"{title} queued for an executor with caps {caps}",
                   f"python train.py {args}; timeout {timeout_s} s", task_id=task["id"],
                   data={"experiment_id": experiment_id})
        return task

    def wait_task(self, task_id: str, timeout_s: float) -> dict:
        t0, last = time.monotonic(), None
        while time.monotonic() - t0 < timeout_s:
            row = self.db.table("tasks").select("*").eq("id", task_id).single().execute().data
            if row["status"] != last:
                print(f"[repro] task {task_id[:8]}: {row['status']} {row.get('executor') or ''}", flush=True)
                last = row["status"]
            if row["status"] in ("done", "failed", "rejected"):
                return row
            time.sleep(3)
        raise StepError(f"task {task_id} did not finish within {timeout_s:.0f} s")

    def log_tail(self, experiment_id: str, n: int = 40) -> str:
        try:
            data = self.db.storage.from_("logs").download(f"{experiment_id}.log")
            return "\n".join(data.decode("utf-8", "replace").splitlines()[-n:])
        except Exception as e:
            return f"(log not available: {type(e).__name__})"

    def metrics_of(self, experiment_id: str) -> list[dict]:
        return self.db.table("metrics").select("name,value,step,log_line").eq("experiment_id", experiment_id) \
            .execute().data

    # -- steps --
    def design(self) -> dict:
        def designed(res):
            """the answer is a JSON design whose models each map to one valid claim"""
            d = check_design(parse_answer(res.answer), self.claims)
            (self.workdir / "design.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
            return {"design": d}
        out, _ = self.agent_step("design_experiment", "Choose the experiment and target claims",
                                 designer_goal(self.claims, self.settings, self.cap_s / 60), designed)
        return out["design"]

    def implement(self, design: dict, feedback: str | None = None) -> str:
        names = [m["name"] for m in design["models"]]
        for attempt in range(1, 3):
            path = self.workdir / "train.py"
            def written(res):
                """train.py exists, compiles, meets the CLI/METRIC contract and never touches the golden reference"""
                if not path.is_file():
                    raise StepError("the agent wrote no train.py")
                problems = check_train_script(path.read_text(encoding="utf-8"), names)
                if problems:
                    raise StepError("; ".join(problems))
                return {"lines": len(path.read_text(encoding="utf-8").splitlines())}
            title = "Write train.py" if not feedback else "REPAIR(code): fix train.py"
            try:
                self.agent_step("write_code", title, implementer_goal(design, self.claims, self.settings, feedback),
                                written, model="smart")
                return path.read_text(encoding="utf-8")
            except StepError as e:
                if attempt == 2 or isinstance(e, AgentError):  # a quota or budget stop is not a code problem
                    raise
                feedback = f"the code check found: {e}"
        raise AssertionError("unreachable")

    def setup_env(self, feedback: str | None = None) -> str:
        def built(res):
            """make_env succeeded: env.json and pinned requirements.txt exist in the run dir"""
            env, req = self.workdir / "env.json", self.workdir / "requirements.txt"
            if not env.is_file() or not req.is_file():
                raise StepError("make_env never reported 'env ready'")
            return {"env": json.loads(env.read_text(encoding="utf-8"))}
        for f in ("env.json", "requirements.txt"):
            (self.workdir / f).unlink(missing_ok=True)
        self.agent_step("setup_env", "Build the environment" if not feedback else "REPAIR(env): fix requirements",
                        envbuilder_goal(feedback), built)
        return (self.workdir / "requirements.txt").read_text(encoding="utf-8")

    def run(self) -> dict:
        self.event("repro_started", "Autonomous reproduction started",
                   f"SPEC §7.2 ladder: design, code, env, smoke, budget, full run; cap {self.cap_s / 60:.0f} min")
        design = self.design()
        targets = [c for c in self.claims if c["id"] in design["claim_map"].values()]
        margin, margin_reason = declare_margin(targets)
        exp = self.db.table("experiments").insert({
            "project_id": self.pid, "label": f"Reproduction: {design.get('experiment')}", "status": "planned",
            "margin": margin, "config": {"design": design, "claim_map": design["claim_map"],
                                         "margin_reason": margin_reason, "seeds": [0]}}).execute().data[0]
        self.event("margin_declared", f"margin {margin} declared before the run", margin_reason,
                   data={"experiment_id": exp["id"]})

        code = self.implement(design)
        requirements = self.setup_env()
        names = list(design["claim_map"])
        smoke_args = f"--data-dir {DATA_DIR} --epochs {SMOKE_EPOCHS} --subset {SMOKE_SUBSET} --seed 0"
        for repair in range(MAX_REPAIRS + 1):
            smoke_exp = self.db.table("experiments").insert({
                "project_id": self.pid, "parent_id": exp["id"], "status": "planned",
                "label": f"smoke: {SMOKE_EPOCHS} epoch, {SMOKE_SUBSET} examples" + (f" (repair {repair})" if repair
                                                                                    else ""),
                "config": {"epochs": SMOKE_EPOCHS, "subset": SMOKE_SUBSET, "scale": "smoke"}}).execute().data[0]
            task = self.queue_run("Smoke run", "smoke", ["smoke"], smoke_args, code, requirements, smoke_exp["id"], 900)
            row = self.wait_task(task["id"], 900 + 1800)
            out = row.get("output") or {}
            finals = [m for m in self.metrics_of(smoke_exp["id"]) if m["name"].startswith("final_")]
            missing = [n for n in names if f"final_{n}" not in {m["name"] for m in finals}]
            if row["status"] == "done" and not missing:
                break
            sig = out.get("error_signature") or (f"no final metric for {missing}" if row["status"] == "done" else
                                                 out.get("error") or "failed")
            if repair == MAX_REPAIRS:
                raise StepError(f"smoke run still failing after {MAX_REPAIRS} repairs: {sig}")
            feedback = f"smoke run: {sig} (log line {out.get('error_log_line')})\nlog tail:\n" + \
                       self.log_tail(smoke_exp["id"])
            if str(sig).startswith("ModuleNotFoundError") or "environment build failed" in str(out.get("error", "")):
                self.event("repair", "REPAIR(env) after a failed smoke run", str(sig))
                requirements = self.setup_env(feedback)
            else:
                self.event("repair", "REPAIR(code) after a failed smoke run", str(sig))
                code = self.implement(design, feedback)

        timing = smoke_timing(self.metrics_of(smoke_exp["id"]), float(out.get("wall_s") or 0), names)
        timing["executor"] = row.get("executor")

        def budgeted(res):
            """the proposal is a positive epoch count; code clips it to the project cap"""
            return {"budget": plan_budget(parse_answer(res.answer), timing, self.cap_s, row.get("executor"))}
        b, _ = self.agent_step("budget", "Choose the full-run scale",
                               budget_goal(design, timing, self.cap_s, row.get("executor"), self.settings), budgeted)
        b = b["budget"]
        args = f"--data-dir {DATA_DIR} --epochs {b['epochs']} --subset {b['subset']} --seed 0"
        self.db.table("experiments").update({
            "budget_reason": b["reason"],
            "config": {**exp["config"], "epochs": b["epochs"], "subset": b["subset"], "est_s": b["est_s"],
                       "smoke_timing": timing, "budget": b, "cmd": f"python train.py {args}",
                       "requirements": requirements}}).eq("id", exp["id"]).execute()
        self.event("budget_chosen", f"full run: {b['epochs']} epochs" + (f", {b['subset']} examples" if b["subset"]
                                                                          else ""), b["reason"],
                   data={"experiment_id": exp["id"], **b})

        timeout = int(max(600, 2 * b["est_s"] + 300))
        full = self.queue_run("Full run", "full", ["train"], args, code, requirements, exp["id"], timeout)
        result = {"experiment_id": exp["id"], "task_id": full["id"], "budget": b}
        if self.wait:
            row = self.wait_task(full["id"], timeout + 3600)
            result["status"] = row["status"]
            result["finals"] = {m["name"]: m["value"] for m in self.metrics_of(exp["id"])
                                if m["name"].startswith("final_")}
            self.event("repro_finished" if row["status"] == "done" else "repro_failed",
                       f"reproduction run {row['status']}: {result['finals']}",
                       f"full run task {full['id'][:8]} on {row.get('executor')}", data=result)
        return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Autonomous reproduction of a project's paper (SPEC §7.2-7.3)")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--executor-name", default=setting("EXECUTOR_NAME") or "driver",
                    help="recorded as the executor of the agent steps")
    ap.add_argument("--cap-min", type=float, help="override projects.budget_cpu_min")
    ap.add_argument("--no-wait", action="store_true", help="queue the full run and exit")
    a = ap.parse_args(argv)
    db = client()
    try:
        res = Pipeline(db, a.project_id, a.executor_name, a.cap_min, wait=not a.no_wait).run()
    except StepError as e:
        emit(db, "repro_failed", "Autonomous reproduction stopped", str(e)[:1000], project_id=a.project_id)
        sys.exit(f"stopped: {e}")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
