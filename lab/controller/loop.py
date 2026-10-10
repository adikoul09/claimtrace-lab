"""The controller loop (SPEC §3). Each tick:

  heartbeat   upsert executors row 'controller' (caps ['controller']) so the UI shows the controller is alive
  caps        a queued task with empty required_caps gets them from the capability map (any worker could claim it)
  stale       a running task whose executor's heartbeat is older than STALE_HEARTBEAT_S goes back to 'queued'
  intake      a project with status 'new' gets a queued `plan` task and status 'planning'
  plan        queued `plan` tasks are claimed and planned (LLM, checked by code); project -> 'running'
  advance     for each running project, the next ready step becomes a task: agent assigned, required_caps set

Every decision writes an events row with a reason."""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from typing import Optional

from lab.controller import assign, planner, progress, routing
from lab.controller.routing import CONTROLLER_CAP, CONTROLLER_NAME
from lab.controller.rules import RUN_TIMEOUT_FLOOR_S, TICK_S
from lab.db import client, emit
from lab.schemas import PlanStep


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Controller:
    def __init__(self, db=None, llm=None, project_id: Optional[str] = None):
        self.db = db if db is not None else client()
        self._llm = llm
        self.project_id = project_id  # set: act only on this project (tests, demos); None: all projects
        self._noted: set = set()  # (kind, key) of conditions already reported, so a waiting state is logged once

    @property
    def llm(self):
        if self._llm is None:
            from lab.llm import LLM
            self._llm = LLM(db=self.db)
        return self._llm

    def q(self, table: str, cols: str = "*", key: str = "project_id"):
        """A select on `table`, limited to this controller's project when it has one."""
        query = self.db.table(table).select(cols)
        return query.eq(key, self.project_id) if self.project_id else query

    def once(self, key) -> bool:
        if key in self._noted:
            return False
        self._noted.add(key)
        return True

    # ---- loop -----------------------------------------------------------------------------------------------------
    def startup(self) -> None:
        """A task 'running' on the controller belongs to a previous controller process that stopped mid-way."""
        rows = self.q("tasks", "id,project_id,capability").eq("status", "running") \
            .eq("executor", CONTROLLER_NAME).execute().data
        for t in rows:
            self._requeue(t, "controller restarted while this task was running", {"executor": CONTROLLER_NAME})

    def tick(self, now: Optional[datetime] = None) -> None:
        now = now or utc_now()
        for step in (self.heartbeat, self.fix_empty_caps, self.requeue_stale, self.intake, self.plan_queued,
                     self.advance):
            try:
                step(now)
            except Exception as e:  # one failing step must not stop the loop
                print(f"[controller] {step.__name__} failed: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()

    def serve(self, interval: float = TICK_S) -> None:
        self.startup()
        print(f"[controller] online; tick every {interval} s", flush=True)
        while True:
            self.tick()
            time.sleep(interval)

    # ---- heartbeat, caps, stale -------------------------------------------------------------------------------------
    def heartbeat(self, now: datetime) -> None:
        self.db.table("executors").upsert({"name": CONTROLLER_NAME, "caps": [CONTROLLER_CAP], "busy": False,
                                           "last_heartbeat": now.isoformat()}).execute()

    def fix_empty_caps(self, now: datetime) -> None:
        rows = self.q("tasks", "id,project_id,agent_id,capability,input").eq("status", "queued") \
            .eq("required_caps", "{}").execute().data
        for t in rows:
            try:
                caps = routing.required_caps(t["capability"], (t.get("input") or {}).get("scale"))
            except ValueError:
                if self.once(("unroutable", t["id"])):
                    print(f"[controller] task {t['id']} has unknown capability {t['capability']!r}", flush=True)
                continue
            self.db.table("tasks").update({"required_caps": caps}).eq("id", t["id"]).eq("status", "queued").execute()
            emit(self.db, "task_routed", f"{t['capability']} task now needs executor caps {caps}",
                 "required_caps were empty, so any worker could have claimed it; set from the capability map",
                 project_id=t.get("project_id"), agent_id=t.get("agent_id"), task_id=t["id"], data={"caps": caps})

    def requeue_stale(self, now: datetime) -> None:
        running = self.q("tasks", "id,project_id,agent_id,capability,status,executor") \
            .eq("status", "running").execute().data
        if not running:
            return
        executors = self.db.table("executors").select("*").execute().data
        for s in routing.stale_tasks(running, executors, now):
            self._requeue(s["task"], s["reason"], {"executor": s["task"]["executor"], "heartbeat_age_s": s["age_s"]})

    def _requeue(self, t: dict, reason: str, data: dict) -> None:
        moved = self.db.table("tasks").update({"status": "queued", "executor": None, "started_at": None}) \
            .eq("id", t["id"]).eq("status", "running").execute().data
        if moved:
            emit(self.db, "task_requeued", f"{t['capability']} task back in the queue", reason,
                 project_id=t.get("project_id"), agent_id=t.get("agent_id"), task_id=t["id"], data=data)

    # ---- intake and plan --------------------------------------------------------------------------------------------
    def intake(self, now: datetime) -> None:
        for p in self.q("projects", key="id").eq("status", "new").execute().data:
            has_plan = self.db.table("tasks").select("id").eq("project_id", p["id"]).eq("capability", "plan") \
                .in_("status", ["queued", "running"]).execute().data
            if not has_plan:
                self.db.table("tasks").insert({
                    "project_id": p["id"], "capability": "plan", "required_caps": routing.required_caps("plan"),
                    "input": {"goal": "reproduce the key result on CPU"}}).execute()
            self.db.table("projects").update({"status": "planning"}).eq("id", p["id"]).execute()
            emit(self.db, "project_intake", f"new project: {p['title']}",
                 f"arXiv {p.get('arxiv_id') or '?'}, budget {p.get('budget_cpu_min')} CPU-min; queued for planning",
                 project_id=p["id"])

    def plan_queued(self, now: datetime) -> None:
        for t in self.q("tasks", "id").eq("status", "queued").eq("capability", "plan").execute().data:
            claimed = self.db.table("tasks").update({"status": "running", "executor": CONTROLLER_NAME,
                                                     "started_at": now.isoformat()}) \
                .eq("id", t["id"]).eq("status", "queued").execute().data
            if claimed:
                self.plan(claimed[0])

    def plan(self, task: dict) -> None:
        db, pid = self.db, task["project_id"]
        project = db.table("projects").select("*").eq("id", pid).execute().data[0]
        papers = db.table("papers").select("*").eq("project_id", pid).execute().data
        paper = papers[0] if papers else None
        tags = project.get("tags") or []
        lessons = db.table("lessons").select("id,kind,text,tags").overlaps("tags", tags).limit(10).execute().data \
            if tags else []
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        abstract = None
        if not (paper and paper.get("claims")) and project.get("arxiv_id"):
            _, abstract = planner.arxiv_abstract(project["arxiv_id"])
        try:
            plan, resp = planner.make_plan(self.llm, project, paper, lessons, agents, task_id=task["id"],
                                           abstract=abstract)
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"[:500]
            db.table("tasks").update({"status": "failed", "output": {"error": reason},
                                      "finished_at": utc_now().isoformat()}).eq("id", task["id"]).execute()
            db.table("projects").update({"status": "plan_failed"}).eq("id", pid).execute()
            emit(db, "plan_failed", "planning failed", reason, project_id=pid, task_id=task["id"])
            return
        steps = [s.model_dump() for s in plan.steps]
        db.table("tasks").update({
            "status": "done", "finished_at": utc_now().isoformat(), "tokens": resp.tokens_in + resp.tokens_out,
            "output": {"reason": plan.reason, "steps": steps, "dropped": plan.dropped, "notes": plan.notes,
                       "lessons": [l["id"] for l in lessons], "model": resp.model, "mode": resp.mode}}) \
            .eq("id", task["id"]).execute()
        db.table("projects").update({"status": "running"}).eq("id", pid).execute()
        reason = plan.reason or "the planner gave no reason"
        if plan.dropped:
            reason += f" | code dropped {len(plan.dropped)} step(s): " + "; ".join(plan.dropped)
        emit(db, "plan", f"plan: {len(steps)} steps: " + " → ".join(s["capability"] for s in steps), reason,
             project_id=pid, task_id=task["id"],
             data={"steps": [{"capability": s["capability"], "title": s["title"], "scale": s["scale"],
                              "budget_cpu_s": s["budget_cpu_s"]} for s in steps],
                   "lessons_used": [l["id"] for l in lessons], "notes": plan.notes, "dropped": plan.dropped,
                   "model": resp.model, "mode": resp.mode, "tokens": resp.tokens_in + resp.tokens_out})

    # ---- advance: create the next ready step ------------------------------------------------------------------------
    def advance(self, now: datetime) -> None:
        for p in self.q("projects", key="id").eq("status", "running").execute().data:
            plans = self.db.table("tasks").select("*").eq("project_id", p["id"]).eq("capability", "plan") \
                .eq("status", "done").order("finished_at", desc=True).limit(1).execute().data
            if not plans:
                continue
            plan_task = plans[0]
            steps = (plan_task.get("output") or {}).get("steps") or []
            step_tasks = self.db.table("tasks").select("id,status,input,created_at,output") \
                .eq("parent_task_id", plan_task["id"]).execute().data
            step_tasks = [t for t in step_tasks if (t.get("input") or {}).get("step") is not None]
            action, i = progress.next_action(len(steps), step_tasks)
            if action == "create":
                self.create_step(p, plan_task, steps, i, now)
            elif action == "done":
                self.db.table("projects").update({"status": "done"}).eq("id", p["id"]).execute()
                emit(self.db, "project_done", f"all {len(steps)} plan steps finished",
                     "the last step's task is done", project_id=p["id"], task_id=plan_task["id"])
            elif action in ("failed", "rejected"):
                self.on_step_stopped(p, plan_task, progress.latest_per_step(step_tasks)[i], action)

    def on_step_stopped(self, project: dict, plan_task: dict, task: dict, action: str) -> None:
        """No repair path yet (T09 adds the Debugger): the project stops here, with the reason."""
        status = "blocked" if action == "failed" else "stopped"
        self.db.table("projects").update({"status": status}).eq("id", project["id"]).execute()
        why = (task.get("output") or {}).get("error") or (task.get("output") or {}).get("error_signature")
        emit(self.db, f"project_{status}", f"step {task['input']['step'] + 1} was {action}; the project is {status}",
             f"task {task['id'][:8]} {action}" + (f": {why}" if why else ""), project_id=project["id"],
             task_id=task["id"])

    def create_step(self, project: dict, plan_task: dict, steps: list[dict], i: int, now: datetime) -> None:
        db, pid = self.db, project["id"]
        step = PlanStep(**steps[i])
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        rewards = db.table("rewards").select("agent_id,reward,ts").order("ts", desc=True).limit(1000).execute().data
        pick = assign.pick_agent(agents, step.capability, assign.rolling_means(rewards))
        if pick is None:
            self.on_gap(project, plan_task, step, i)
            return
        caps = routing.required_caps(step.capability, step.scale)
        live = routing.eligible(caps, db.table("executors").select("*").execute().data, now)
        workdir = f"runs/{pid}"
        inp = {"goal": step.instructions, "title": step.title, "step": i, "of": len(steps),
               "plan_task_id": plan_task["id"], "workdir": workdir,
               "budget": {"max_cpu_s": step.budget_cpu_s,
                          "max_tokens": (pick.agent.get("budget") or {}).get("max_tokens", 20_000)}}
        if step.capability == "run":
            inp.update({"scale": step.scale, "cmd": step.cmd, "cwd": workdir, "timeout_s": max(step.budget_cpu_s, RUN_TIMEOUT_FLOOR_S)})
        row = db.table("tasks").insert({
            "project_id": pid, "parent_task_id": plan_task["id"], "capability": step.capability,
            "required_caps": caps, "agent_id": pick.agent["id"], "input": inp,
            "acceptance": {"text": step.acceptance}, "requires_approval": step.requires_approval,
            "status": "awaiting_approval" if step.requires_approval else "queued"}).execute().data[0]
        where = (f"live executors that can take it: {', '.join(e['name'] for e in live)}" if live
                 else "no live executor has these caps yet; it waits in the queue")
        emit(db, "task_assigned",
             f"step {i + 1}/{len(steps)} {step.capability} → {pick.agent['name']}: {step.title}"
             + (" (awaits approval)" if step.requires_approval else ""),
             f"{pick.reason}; needs executor caps {caps}; {where}", project_id=pid, agent_id=pick.agent["id"],
             task_id=row["id"], data={"caps": caps, "eligible": [e["name"] for e in live], "score": pick.score,
                                      "budget_cpu_s": step.budget_cpu_s})

    def on_gap(self, project: dict, plan_task: dict, step: PlanStep, i: int) -> None:
        """No active agent has the capability. T09 spawns one; until then the step waits, reported once."""
        if self.once(("gap", plan_task["id"], i)):
            emit(self.db, "gap", f"gap: no active agent has {step.capability}",
                 f"step {i + 1} ({step.title}) needs {step.capability}; it waits until an agent with it exists",
                 project_id=project["id"], task_id=plan_task["id"], data={"capability": step.capability})
