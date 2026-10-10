"""The controller loop (SPEC §3). Each tick:

  heartbeat   upsert executors row 'controller' (caps ['controller']) so the UI shows the controller is alive
  caps        a queued task with empty required_caps gets them from the capability map (any worker could claim it)
  stale       a running task whose executor's heartbeat is older than STALE_HEARTBEAT_S goes back to 'queued'
  score       a finished agent task gets its rewards row (SPEC §5); a new 👍/👎 feedback event rescores it
  intake      a project with status 'new' gets a queued `plan` task and status 'planning'
  plan        queued `plan` tasks are claimed and planned (LLM, checked by code); project -> 'running'
  advance     for each running project, the next ready step becomes a task: agent assigned, required_caps set;
              a crashed step gets a debug task, then a retry; a gap or a repeated failure spawns an agent

Every decision writes an events row with a reason."""
from __future__ import annotations

import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from lab.controller import assign, planner, progress, reward, routing, spawn
from lab.controller.routing import CONTROLLER_CAP, CONTROLLER_NAME
from lab.controller.rules import ROLLING_WINDOW, RUN_TIMEOUT_FLOOR_S, TICK_S
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
        self._spawn_failed: dict = {}  # (trigger task, capability, kind) -> time of the last failed spawn

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
        for step in (self.heartbeat, self.fix_empty_caps, self.requeue_stale, self.score, self.intake,
                     self.plan_queued, self.advance):
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

    # ---- score ------------------------------------------------------------------------------------------------------
    SCORE_SCAN = 200  # most recently finished tasks looked at per tick

    def score(self, now: datetime) -> None:
        tasks = self.q("tasks", "id,project_id,agent_id,capability,status,output,tokens,cpu_seconds")             .in_("status", ["done", "failed"]).not_.is_("agent_id", "null")             .order("finished_at", desc=True).limit(self.SCORE_SCAN).execute().data
        if not tasks:
            return
        ids = [t["id"] for t in tasks]
        existing = {r["task_id"]: r for r in self.db.table("rewards").select("*").in_("task_id", ids).execute().data}
        feedback = reward.latest_feedback(self.db.table("events").select("task_id,data,ts").eq("type", "feedback")
                                          .in_("task_id", ids).execute().data)
        todo = [t for t in tasks if t["id"] not in existing
                or existing[t["id"]]["feedback"] != reward.feedback_value(feedback.get(t["id"]))]
        if not todo:
            return
        tokens: dict[str, int] = defaultdict(int)
        for c in self.db.table("llm_calls").select("task_id,tokens_in,tokens_out")                 .in_("task_id", [t["id"] for t in todo]).execute().data:
            tokens[c["task_id"]] += (c["tokens_in"] or 0) + (c["tokens_out"] or 0)
        names = {a["id"]: a["name"] for a in self.db.table("agents").select("id,name").execute().data}
        for t in todo:
            s = reward.score(t, tokens.get(t["id"], t.get("tokens") or 0), feedback.get(t["id"]))
            old = existing.get(t["id"])
            if old:
                self.db.table("rewards").update({k: s.row[k] for k in ("outcome", "cost_norm", "feedback", "reward")})                     .eq("task_id", t["id"]).execute()
            else:
                self.db.table("rewards").insert(s.row).execute()
            recent = self.db.table("rewards").select("agent_id,reward,ts").eq("agent_id", t["agent_id"])                 .order("ts", desc=True).limit(ROLLING_WINDOW).execute().data
            mean = reward.rolling_means(recent).get(t["agent_id"])
            name = names.get(t["agent_id"], "agent")
            verb = f"rescored {old['reward']:.2f} → {s.row['reward']:.2f}" if old else f"scored {s.row['reward']:.2f}"
            emit(self.db, "reward_updated" if old else "reward", f"{name} {verb} on {t['capability']}",
                 f"{s.reason}; rolling mean {mean:.2f} over its last {len(recent)} scored task(s)",
                 project_id=t.get("project_id"), agent_id=t["agent_id"], task_id=t["id"],
                 data={**s.row, "rolling_mean": round(mean, 4), "rolling_n": len(recent)})

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

    # ---- advance: create the next ready step, or handle a failed one ------------------------------------------------
    def advance(self, now: datetime) -> None:
        for p in self.q("projects", key="id").eq("status", "running").execute().data:
            plans = self.db.table("tasks").select("*").eq("project_id", p["id"]).eq("capability", "plan") \
                .eq("status", "done").order("finished_at", desc=True).limit(1).execute().data
            if not plans:
                continue
            plan_task = plans[0]
            steps = (plan_task.get("output") or {}).get("steps") or []
            tasks = self.db.table("tasks").select("id,status,capability,input,created_at,output,agent_id,executor,"
                                                  "parent_task_id").eq("project_id", p["id"]).execute().data
            step_tasks = [t for t in tasks if t.get("parent_task_id") == plan_task["id"]
                          and (t.get("input") or {}).get("step") is not None]
            debugs = [t for t in tasks if t["capability"] == "debug"
                      and (t.get("input") or {}).get("plan_task_id") == plan_task["id"]]
            action, i = progress.next_action(len(steps), step_tasks)
            if action == "create":
                self.create_step(p, plan_task, steps, i, now)
            elif action == "done":
                self.db.table("projects").update({"status": "done"}).eq("id", p["id"]).execute()
                emit(self.db, "project_done", f"all {len(steps)} plan steps finished",
                     "the last step's task is done", project_id=p["id"], task_id=plan_task["id"])
            elif action == "rejected":
                self.stop_project(p, progress.latest_per_step(step_tasks)[i], "stopped", "its task was rejected")
            elif action == "failed":
                attempts = [t for t in step_tasks if t["input"]["step"] == i]
                last = progress.latest_per_step(attempts)[i]
                kind, why = progress.failure_action(attempts, debugs)
                if kind == "debug":
                    self.create_debug(p, plan_task, steps, i, last, debugs, now)
                elif kind == "retry":
                    self.create_step(p, plan_task, steps, i, now, attempts=attempts, debugs=debugs)
                elif kind == "blocked":
                    self.stop_project(p, last, "blocked", why)

    def stop_project(self, project: dict, task: dict, status: str, why: str) -> None:
        out = task.get("output") or {}
        detail = out.get("error_signature") or out.get("error")
        self.db.table("projects").update({"status": status}).eq("id", project["id"]).execute()
        emit(self.db, f"project_{status}", f"step {task['input']['step'] + 1} cannot go on; the project is {status}",
             why + (f"; last error: {detail}" if detail else ""), project_id=project["id"], task_id=task["id"])

    def create_step(self, project: dict, plan_task: dict, steps: list[dict], i: int, now: datetime,
                    attempts: list[dict] = (), debugs: list[dict] = ()) -> None:
        step = PlanStep(**steps[i])
        workdir = f"runs/{project['id']}"
        goal = step.instructions
        if attempts:
            last = progress.latest_per_step(attempts)[i]
            out = last.get("output") or {}
            goal += (f"\n\nThis is attempt {len(attempts) + 1}. The previous attempt failed: "
                     f"{out.get('error_signature') or out.get('error') or 'no error recorded'}.")
            fixed = [d for d in debugs if d["input"].get("failed_task_id") == last["id"] and d["status"] == "done"]
            if fixed:
                goal += f" A debug task worked on it: {str((fixed[-1].get('output') or {}).get('answer'))[:500]}"
        inp = {"goal": goal, "title": step.title, "step": i, "of": len(steps), "attempt": len(attempts) + 1,
               "plan_task_id": plan_task["id"], "workdir": workdir, "budget": {"max_cpu_s": step.budget_cpu_s}}
        if step.capability == "run":
            inp.update({"scale": step.scale, "cmd": step.cmd, "cwd": workdir,
                        "timeout_s": max(step.budget_cpu_s, RUN_TIMEOUT_FLOOR_S)})
        fails = Counter(t.get("agent_id") for t in attempts if t["status"] == "failed")
        context = f"Plan step {i + 1} of {len(steps)}: {step.title}\nInstructions: {step.instructions}"
        if attempts:
            context += "\nEarlier attempts failed: " + "; ".join(
                str((t.get("output") or {}).get("error_signature") or (t.get("output") or {}).get("error"))
                for t in attempts)
        self.create_task(project, step.capability, inp, now, parent_task_id=plan_task["id"],
                         caps=routing.required_caps(step.capability, step.scale), acceptance=step.acceptance,
                         requires_approval=step.requires_approval, fails=fails,
                         trigger_task=attempts[-1] if attempts else plan_task, context=context,
                         label=f"step {i + 1}/{len(steps)} {step.capability}: {step.title}"
                               + (f" (attempt {len(attempts) + 1})" if attempts else ""))

    def create_debug(self, project: dict, plan_task: dict, steps: list[dict], i: int, failed: dict,
                     debugs: list[dict], now: datetime) -> None:
        """SPEC §7.2: a crash is handed to a Debugger before the step is retried."""
        step = PlanStep(**steps[i])
        out, fin = failed.get("output") or {}, failed.get("input") or {}
        sig = out.get("error_signature")
        where = (f"at log line {out['error_log_line']} of {out.get('log_path')}" if out.get("error_log_line")
                 else f"(log {out.get('log_path') or 'not stored'})")
        cmd = fin.get("cmd")
        cmd_text = cmd if isinstance(cmd, str) else " ".join(map(str, cmd or []))
        workdir = fin.get("workdir") or f"runs/{project['id']}"
        goal = (f"Step {i + 1} ({step.title}) failed with {sig} {where}.\n"
                + (f"The command was `{cmd_text}` in the run folder.\n" if cmd_text else "")
                + "Find the cause, make the smallest fix that makes it run without changing what is measured, then "
                  "re-run the command to show the error is gone. Answer with what you changed and its label, "
                  "REPAIR(env) or REPAIR(code), or say it needs a HYPOTHESIS branch.")
        mine = [d for d in debugs if d["input"].get("failed_task_id") == failed["id"]]
        inp = {"goal": goal, "title": f"debug step {i + 1}: {sig}", "failed_task_id": failed["id"], "for_step": i,
               "plan_task_id": plan_task["id"], "workdir": workdir, "error_signature": sig,
               "error_log_line": out.get("error_log_line"), "log_path": out.get("log_path"),
               "experiment_id": out.get("experiment_id"), "cmd": cmd, "attempt": len(mine) + 1,
               "budget": {"max_cpu_s": step.budget_cpu_s}}
        context = (f"Plan step {i + 1} ({step.title}, capability {step.capability}) crashed on "
                   f"{failed.get('executor') or 'an executor'}: {sig} {where}."
                   + (f" Command: {cmd_text}." if cmd_text else ""))
        self.create_task(project, "debug", inp, now, parent_task_id=failed["id"], caps=routing.required_caps("debug"),
                         acceptance="the failing command gets past the error, and the change is labelled REPAIR(env) "
                                    "or REPAIR(code)",
                         requires_approval=False,
                         fails=Counter(d.get("agent_id") for d in mine if d["status"] == "failed"),
                         trigger_task=failed, context=context, label=f"debug step {i + 1}: {sig}")

    def create_task(self, project: dict, capability: str, inp: dict, now: datetime, *, parent_task_id: str,
                    caps: list[str], acceptance: str, requires_approval: bool, fails: Counter, trigger_task: dict,
                    context: str, label: str) -> Optional[dict]:
        """Assign the best agent (spawning one on a gap or a repeated failure), then queue the task. None: no agent
        yet (the spawn failed; it is tried again later)."""
        db, pid = self.db, project["id"]
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        rewards = db.table("rewards").select("agent_id,reward,ts").order("ts", desc=True).limit(1000).execute().data
        pick = assign.pick_agent(agents, capability, reward.rolling_means(rewards))
        trig = spawn.trigger(pick, capability, fails)
        if trig:
            agent = self.spawn_agent(project, capability, trig, context, trigger_task, agents)
            if agent is None:
                return None
            pick = assign.Pick(agent, None, f"{agent['name']}: spawned for this task ({trig.reason})")
        inp["budget"] = {**inp.get("budget", {}),
                         "max_tokens": (pick.agent.get("budget") or {}).get("max_tokens", 20_000)}
        live = routing.eligible(caps, db.table("executors").select("*").execute().data, now)
        row = db.table("tasks").insert({
            "project_id": pid, "parent_task_id": parent_task_id, "capability": capability, "required_caps": caps,
            "agent_id": pick.agent["id"], "input": inp, "acceptance": {"text": acceptance},
            "requires_approval": requires_approval,
            "status": "awaiting_approval" if requires_approval else "queued"}).execute().data[0]
        where = (f"live executors that can take it: {', '.join(e['name'] for e in live)}" if live
                 else "no live executor has these caps yet; it waits in the queue")
        emit(db, "task_assigned",
             f"{label} → {pick.agent['name']}" + (" (awaits approval)" if requires_approval else ""),
             f"{pick.reason}; needs executor caps {caps}; {where}", project_id=pid, agent_id=pick.agent["id"],
             task_id=row["id"], data={"caps": caps, "eligible": [e["name"] for e in live], "score": pick.score,
                                      "budget": inp["budget"]})
        return row

    SPAWN_RETRY_S = 60  # a failed spawn (LLM down, bad draft) is tried again after this long

    def spawn_agent(self, project: dict, capability: str, trig, context: str, trigger_task: dict,
                    agents: list[dict]) -> Optional[dict]:
        key = (trigger_task["id"], capability, trig.kind)
        if time.monotonic() - self._spawn_failed.get(key, -1e9) < self.SPAWN_RETRY_S:
            return None
        db = self.db
        cap_s = int(project.get("budget_cpu_min") or 20) * 60
        try:
            draft, resp = spawn.draft_spec(self.llm, capability, trig, context, agents, cap_s,
                                           task_id=trigger_task["id"])
            taken = {a["name"] for a in db.table("agents").select("name").execute().data}
            row, notes = spawn.check_spec(draft, capability, cap_s, taken)
        except Exception as e:
            self._spawn_failed[key] = time.monotonic()
            emit(db, "spawn_failed", f"could not spawn an agent for {capability}",
                 f"{trig.reason}; spawn failed: {type(e).__name__}: {e}"[:500], project_id=project["id"],
                 task_id=trigger_task["id"])
            return None
        origin_reason = trig.reason + (f". {draft['reason']}" if draft.get("reason") else "")
        agent = db.table("agents").insert({**row, "origin": "spawned", "origin_reason": origin_reason,
                                           "created_by_task": trigger_task["id"], "version": 1,
                                           "status": "active"}).execute().data[0]
        emit(db, "agent_spawned", f"spawned {agent['name']} for {capability}",
             origin_reason + (f" | code checks: {'; '.join(notes)}" if notes else ""), project_id=project["id"],
             agent_id=agent["id"], task_id=trigger_task["id"],
             data={"trigger": trig.kind, "tools": row["tools"], "capabilities": row["capabilities"],
                   "budget": row["budget"], "notes": notes, "model": resp.model, "mode": resp.mode,
                   "tokens": resp.tokens_in + resp.tokens_out})
        return agent
