"""Integration item 1: the worker runs any non-`run` task through the assigned agent; reproduction stages are
capability handlers that read earlier steps through input.upstream (docs/CONTRACTS.md §3-§4). No LLM (a scripted agent stands in) and no
Supabase (an in-memory table store stands in)."""
import json
import uuid

import pytest

from lab.agents import stages
from lab.agents.runtime import RunResult


class Store:
    """Just enough of the supabase client: select/eq/contains/in_/order/limit/single, insert, update().eq()."""

    def __init__(self, **tables):
        self.rows = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return Q(self, name)


class Q:
    def __init__(self, store, name):
        self.store, self.name, self.filters, self.op, self.payload = store, name, [], "select", None
        self._single, self._order, self._limit = False, None, None

    def select(self, *_):
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def in_(self, k, vs):
        self.filters.append(lambda r: r.get(k) in vs)
        return self

    def contains(self, k, vs):
        self.filters.append(lambda r: set(vs) <= set(r.get(k) or []))
        return self

    def order(self, k, desc=False):
        self._order = (k, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, patch):
        self.op, self.payload = "update", patch
        return self

    def execute(self):
        rows = self.store.rows.setdefault(self.name, [])
        if self.op == "insert":
            new = [{"id": str(uuid.uuid4()), **r} for r in (self.payload if isinstance(self.payload, list)
                                                             else [self.payload])]
            rows.extend(new)
            return type("R", (), {"data": new})()
        hit = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in hit:
                r.update(self.payload)
            return type("R", (), {"data": hit})()
        if self._order:
            hit.sort(key=lambda r: r.get(self._order[0]) or "", reverse=self._order[1])
        if self._limit:
            hit = hit[:self._limit]
        return type("R", (), {"data": (hit[0] if hit else None) if self._single else hit})()
CLAIMS = [
    {"id": "c7", "model": "Large net", "metric": "test errors", "value": 67, "unit": "errors",
     "direction": "lower_is_better", "whose": "oracle", "valid": True, "page": 4, "quote": "67 test errors"},
    {"id": "c8", "model": "Small net", "metric": "test errors", "value": 146, "unit": "errors",
     "direction": "lower_is_better", "whose": "baseline", "valid": True, "page": 4, "quote": "146 errors"},
]
PID = "p1"
AGENTS = [{"id": f"a-{c}", "name": f"{c}-v1", "capabilities": [c], "tools": ["read_file", "write_file"],
           "budget": {"max_steps": 5, "max_tokens": 1000, "max_cpu_s": 60}, "status": "active", "version": 1,
           "role_prompt": "x"}
          for c in ("design_experiment", "write_code", "setup_env", "budget", "write_report", "debug", "compare")]


def store():
    return Store(projects=[{"id": PID, "title": "Distillation", "budget_cpu_min": 20, "arxiv_id": "1503.02531"}],
                 papers=[{"project_id": PID, "claims": CLAIMS, "settings": []}], agents=AGENTS,
                 experiments=[], tasks=[], events=[], metrics=[])


def task(cap, workdir, **inp):
    return {"id": f"t-{cap}", "project_id": PID, "capability": cap, "agent_id": f"a-{cap}",
            "input": {"goal": f"do {cap}", "title": cap, "workdir": workdir, **inp}}


def with_upstream(db, **outputs):
    """Add a done task per capability with the given output; returns input.upstream."""
    up = {}
    for cap, out in outputs.items():
        row = {"id": f"up-{cap}", "project_id": PID, "capability": cap, "status": "done", "executor": "laptop-b",
               "input": out.pop("_input", {}), "output": out}
        db.rows["tasks"].append(row)
        up[cap] = row["id"]
    return up


@pytest.fixture
def scripted(monkeypatch):
    """scripted(answer, files={...}, status='finished'): the next agent writes files and answers."""
    def set_(answer="", files=None, status="finished", before=None):
        def fake(agent, goal, workdir, **kw):
            if before:
                before(workdir)
            for name, text in (files or {}).items():
                (workdir / name).write_text(text, encoding="utf-8")
            fake.goals.append(goal)
            return RunResult(status, answer if status == "finished" else None, "scripted", 2, 300, 1.5)
        fake.goals = []
        monkeypatch.setattr(stages, "run_agent", fake)
        return fake
    return set_


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(stages, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stages, "ROOT", tmp_path)
    (tmp_path / "runs" / PID).mkdir(parents=True)
    return tmp_path


DESIGN = {"experiment": "MNIST", "reason": "fits", "models": [{"name": "teacher", "claim_id": "c7"},
                                                             {"name": "student_hard", "claim_id": "c8"}]}
GOOD = ('import argparse, json\nap = argparse.ArgumentParser()\nap.add_argument("--data-dir")\n'
        'ap.add_argument("--epochs")\nap.add_argument("--subset")\nprint("CONFIG " + json.dumps({}))\n'
        'print("METRIC train_examples_full=1 step=0")\nfor n in ["teacher", "student_hard"]:\n'
        '    print(f"METRIC {n}_epoch_s=1 step=1"); print(f"METRIC final_{n}=1 step=0")\n')


def test_design_stage_outputs_design_config_and_margin(runs, scripted):
    scripted(json.dumps(DESIGN))
    db = store()
    out = stages.handle(db, task("design_experiment", f"runs/{PID}"), executor="laptop-b")
    assert out["outcome"] == "passed" and out["agent_status"] == "finished"
    assert out["config"]["claim_map"] == {"teacher": "c7", "student_hard": "c8"}
    assert (out["margin"], out["config"]["seeds"]) == (10, [0]) and out["margin_reason"]
    assert out["tokens"] == 300 and db.rows["experiments"] == []  # the controller creates the run experiments
    assert any(e["type"] == "margin_declared" for e in db.rows["events"])


def test_design_stage_with_a_bad_answer_fails_with_the_error(runs, scripted):
    scripted(json.dumps({**DESIGN, "models": [{"name": "teacher", "claim_id": "c99"}]}))
    out = stages.handle(store(), task("design_experiment", f"runs/{PID}"), executor="laptop-b")
    assert out["outcome"] == "failed" and "c99" in out["error"]


def test_write_code_stage_outputs_the_file_and_passes_the_plan_notes(runs, scripted):
    db = store()
    up = with_upstream(db, design_experiment={"design": DESIGN})
    agent = scripted("done", files={"train.py": GOOD})
    out = stages.handle(db, task("write_code", f"runs/{PID}", upstream=up, redirect_note="use SGD"),
                        executor="laptop-b")
    assert out["outcome"] == "passed" and out["files"] == {"train.py": GOOD}
    assert "do write_code" in agent.goals[0] and "use SGD" in agent.goals[0] and "--subset" in agent.goals[0]


def test_write_code_stage_without_a_design_fails_clearly(runs, scripted):
    scripted("done", files={"train.py": GOOD})
    out = stages.handle(store(), task("write_code", f"runs/{PID}"), executor="laptop-b")
    assert out["outcome"] == "failed" and "design_experiment" in out["error"]


def test_bad_script_fails_the_write_code_stage(runs, scripted):
    db = store()
    up = with_upstream(db, design_experiment={"design": DESIGN})
    scripted("done", files={"train.py": "print('hi')\n"})
    out = stages.handle(db, task("write_code", f"runs/{PID}", upstream=up), executor="laptop-b")
    assert out["outcome"] == "failed" and "--epochs" in out["error"] and "files" not in out


def test_setup_env_gets_train_py_from_upstream_and_outputs_requirements(runs, scripted):
    db = store()
    up = with_upstream(db, write_code={"files": {"train.py": GOOD}})
    seen = {}
    scripted("env ready", files={"requirements.txt": "numpy==1.26.4\n", "env.json": "{}"},
             before=lambda wd: seen.update(train=(wd / "train.py").read_text(encoding="utf-8")))
    out = stages.handle(db, task("setup_env", f"runs/{PID}", upstream=up), executor="laptop-b")
    assert seen["train"] == GOOD
    assert out["outcome"] == "passed" and out["requirements"] == "numpy==1.26.4\n"


def test_budget_stage_reads_the_upstream_smoke_run_and_code_clips(runs, scripted):
    db = store()
    smoke = db.table("experiments").insert({"project_id": PID, "label": "smoke", "config": {}}).execute().data[0]
    for n, v in [("train_examples", 5000), ("train_examples_full", 60000), ("teacher_epoch_s", 1.0),
                 ("student_hard_epoch_s", 0.5)]:
        db.rows["metrics"].append({"experiment_id": smoke["id"], "name": n, "value": v, "step": 1, "log_line": 1})
    up = with_upstream(db, design_experiment={"design": DESIGN},
                       run={"experiment_id": smoke["id"], "wall_s": 21.5, "_input": {"scale": "smoke"}})
    scripted(json.dumps({"epochs": 500, "reason": "long"}))
    out = stages.handle(db, task("budget", f"runs/{PID}", upstream=up), executor="laptop-b")
    assert out["outcome"] == "passed" and out["budget"]["clipped"] is True
    assert (out["epochs"], out["subset"], out["seeds"]) == ((1200 - 20) // 18, 0, [0])
    assert out["reason"].startswith(f"{out['epochs']} epochs") and "laptop-b" in out["reason"]


def test_debug_stage_labels_the_repair_and_returns_the_changed_file(runs, scripted):
    db = store()
    up = with_upstream(db, write_code={"files": {"train.py": GOOD}})
    fixed = GOOD + "# fixed\n"
    scripted("Added the missing import. REPAIR(code)", files={"train.py": fixed})
    out = stages.handle(db, task("debug", f"runs/{PID}", upstream=up), executor="laptop-b")
    assert (out["outcome"], out["repair_label"], out["files"]) == ("passed", "REPAIR(code)", {"train.py": fixed})
    assert "requirements" not in out


def test_debug_stage_without_a_label_fails(runs, scripted):
    scripted("I changed some things.")
    out = stages.handle(store(), task("debug", f"runs/{PID}"), executor="laptop-b")
    assert out["outcome"] == "failed" and "REPAIR" in out["error"]


def test_compare_stage_grades_the_upstream_full_run_by_code(runs, scripted):
    db = store()
    exp = db.table("experiments").insert({"project_id": PID, "label": "full", "margin": 10, "status": "done",
                                          "config": {"claim_map": {"teacher": "c7", "student_hard": "c8"},
                                                     "seeds": [0]}}).execute().data[0]
    db.rows["metrics"] += [{"experiment_id": exp["id"], "name": "final_teacher", "value": 80, "step": 0,
                            "log_line": 40},
                           {"experiment_id": exp["id"], "name": "final_student_hard", "value": 143, "step": 0,
                            "log_line": 41}]
    up = with_upstream(db, run={"experiment_id": exp["id"], "_input": {"scale": "full"}})
    agent = scripted("unused")
    out = stages.handle(db, task("compare", f"runs/{PID}", upstream=up), executor="laptop-b")
    assert out["outcome"] == "passed" and out["experiment_id"] == exp["id"] and agent.goals == []
    v = {x["claim_id"]: x for x in db.rows["experiments"][0]["verdicts"]}
    assert v["c8"]["verdict"] == "reproduced" and v["c7"]["verdict"] == "partially reproduced"
    assert v["c8"]["log_line"] == 41


def test_generic_capability_runs_the_agent_and_maps_its_status_to_an_outcome(runs, scripted):
    scripted("# Report")
    out = stages.handle(store(), task("write_report", f"runs/{PID}"), executor="laptop-b")
    assert (out["outcome"], out["markdown"]) == ("passed", "# Report")
    scripted(status="stopped")
    out = stages.handle(store(), task("write_report", f"runs/{PID}"), executor="laptop-b")
    assert (out["outcome"], out["agent_status"]) == ("partial", "stopped")


def test_task_without_an_assigned_agent_fails_without_calling_anything(runs, scripted):
    agent = scripted("x")
    t = {**task("write_report", f"runs/{PID}"), "agent_id": None}
    out = stages.handle(store(), t, executor="laptop-b")
    assert out["outcome"] == "failed" and agent.goals == []


def test_workdir_outside_runs_is_refused(runs, scripted):
    scripted("x")
    out = stages.handle(store(), task("write_report", "../elsewhere"), executor="laptop-b")
    assert out["outcome"] == "failed" and "runs" in out["error"]


# ---- the worker's dispatch ------------------------------------------------------------------------------------------

def _worker(db):
    from lab.executor.worker import Worker
    w = object.__new__(Worker)
    w.name, w.caps, w.db, w.busy = "laptop-b", ["agent", "host:laptop-b"], db, False
    return w


@pytest.mark.parametrize("outcome, status", [("passed", "done"), ("partial", "done"), ("failed", "failed")])
def test_worker_writes_the_handlers_output_outcome_and_tokens(monkeypatch, outcome, status):
    db = store()
    t = {**task("write_report", f"runs/{PID}"), "status": "running"}
    db.rows["tasks"].append(t)
    monkeypatch.setattr(stages, "handle", lambda db, task, executor: {"outcome": outcome, "tokens": 120,
                                                                      "cpu_s": 2.5, "error": None})
    _worker(db).run_agent_task(t)
    row = db.rows["tasks"][0]
    assert (row["status"], row["output"]["outcome"], row["tokens"], row["cpu_seconds"]) == (status, outcome, 120, 2.5)
    assert {e["type"] for e in db.rows["events"]} >= {"task_started", "task_finished" if status == "done"
                                                      else "task_failed"}


def test_worker_turns_a_handler_crash_into_a_failed_task(monkeypatch):
    db = store()
    t = {**task("write_report", f"runs/{PID}"), "status": "running"}
    db.rows["tasks"].append(t)
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(stages, "handle", boom)
    _worker(db).run_agent_task(t)
    assert db.rows["tasks"][0]["status"] == "failed" and "db down" in db.rows["tasks"][0]["output"]["error"]
