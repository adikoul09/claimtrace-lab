"""The controller loop (SPEC §3). Each tick:

  heartbeat   upsert executors row 'controller' (caps ['controller']) so the UI shows the controller is alive
  caps        a queued task with empty required_caps gets them from the capability map (any worker could claim it)
  stale       a running task whose executor's heartbeat is older than STALE_HEARTBEAT_S goes back to 'queued'
  score       a finished agent task gets its rewards row (SPEC §5); a new 👍/👎 feedback event rescores it
  lifecycle   retire, merge and refine agents by the rules in lifecycle.py (SPEC §4)
  whatifs     a queued design_whatif gets its agent, upstream and caps; a finished one's branches, ranking,
              approval-gated extend run and final compare are created in order (SPEC §7.4, CONTRACTS.md §5b)
  learn       after a failure-then-recovery or a finished project, the Reporter proposes lessons (SPEC §6)
  intake      a project with status 'new' gets a queued `plan` task and status 'planning'
  plan        queued `plan` tasks are claimed and planned (LLM, checked by code); project -> 'running'
  decisions   an awaiting task with a decision moves on (docs/CONTRACTS.md §6), in case the web did not move it
  advance     for each running project, the next ready step becomes a task: agent assigned, required_caps set;
              a crashed step gets a debug task, then a retry; a gap or a repeated failure spawns an agent

Every decision writes an events row with a reason."""
from __future__ import annotations

import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from lab.controller import assign, lifecycle, memory, planner, progress, reward, routing, spawn, whatif, wiring
from lab.controller.routing import CONTROLLER_CAP, CONTROLLER_NAME
from lab.controller.rules import MAX_REFINES_PER_ROLE, ROLLING_WINDOW, RUN_TIMEOUT_FLOOR_S, TICK_S
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
        self._replan_failed: dict = {}  # redirected task id -> time of the last failed replan
        self._refine_failed: dict = {}  # (agent id, task id) -> time of the last failed refinement
        self._learn_failed: dict = {}  # lesson trigger -> time of the last failed proposal
        self._whatif_finished: set = set()  # design_whatif task ids whose sequence is over

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
        for step in (self.heartbeat, self.fix_empty_caps, self.requeue_stale, self.score, self.lifecycle,
                     self.apply_decisions, self.intake, self.plan_queued, self.advance, self.prepare_whatifs,
                     self.advance_whatifs, self.learn):
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
            if t["capability"] == "design_whatif" and not (t.get("input") or {}).get("prepared"):
                continue  # prepare_whatifs sets its caps once its inputs exist
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
        tasks = self.q("tasks", "id,project_id,agent_id,capability,status,input,output,tokens,cpu_seconds") \
            .in_("status", ["done", "failed"]).not_.is_("agent_id", "null") \
            .order("finished_at", desc=True).limit(self.SCORE_SCAN).execute().data
        if not tasks:
            return
        ids = [t["id"] for t in tasks]
        existing = {r["task_id"]: r for r in self.db.table("rewards").select("*").in_("task_id", ids).execute().data}
        feedback = reward.latest_feedback(self.db.table("events").select("task_id,data,ts").eq("type", "feedback")
                                          .in_("task_id", ids).execute().data)
        todo = [t for t in tasks if t["id"] not in existing
                or existing[t["id"]]["feedback"] != reward.feedback_value(feedback.get(t["id"]))]
        for t in [t for t in todo if reward.no_answer(t)]:
            self._not_scored(t)
        todo = [t for t in todo if not reward.no_answer(t)]
        if not todo:
            return
        tokens: dict[str, int] = defaultdict(int)
        for c in self.db.table("llm_calls").select("task_id,tokens_in,tokens_out") \
                .in_("task_id", [t["id"] for t in todo]).execute().data:
            tokens[c["task_id"]] += (c["tokens_in"] or 0) + (c["tokens_out"] or 0)
        names = {a["id"]: a["name"] for a in self.db.table("agents").select("id,name").execute().data}
        up_ids = sorted({i for t in todo if t["capability"] == "run"
                         for i in ((t.get("input") or {}).get("upstream") or {}).values()})
        up = {u["id"]: u for u in self.db.table("tasks").select("id,agent_id,capability,output").in_("id", up_ids)
              .execute().data} if up_ids else {}
        for t in todo:
            charged, why = reward.charged_agent(t, up)
            s = reward.score(t, tokens.get(t["id"], t.get("tokens") or 0), feedback.get(t["id"]), charged, why)
            old = existing.get(t["id"])
            if old:
                self.db.table("rewards").update({k: s.row[k] for k in ("outcome", "cost_norm", "feedback", "reward")}) \
                    .eq("task_id", t["id"]).execute()
            else:
                self.db.table("rewards").insert(s.row).execute()
            agent_id = s.row["agent_id"]
            recent = self.db.table("rewards").select("agent_id,reward,ts").eq("agent_id", agent_id) \
                .order("ts", desc=True).limit(ROLLING_WINDOW).execute().data
            mean = reward.rolling_means(recent).get(agent_id)
            name = names.get(agent_id, "agent")
            verb = f"rescored {old['reward']:.2f} → {s.row['reward']:.2f}" if old else f"scored {s.row['reward']:.2f}"
            emit(self.db, "reward_updated" if old else "reward", f"{name} {verb} on {t['capability']}",
                 f"{s.reason}; rolling mean {mean:.2f} over its last {len(recent)} scored task(s)",
                 project_id=t.get("project_id"), agent_id=agent_id, task_id=t["id"],
                 data={**s.row, "rolling_mean": round(mean, 4), "rolling_n": len(recent)})

    def _not_scored(self, t: dict) -> None:
        """One event per task whose agent produced no answer: it is not scored and not refined."""
        if not self.once(("not_scored", t["id"])):
            return
        if self.db.table("events").select("id").eq("task_id", t["id"]).eq("type", "not_scored").limit(1) \
                .execute().data:
            return
        err = str((t.get("output") or {}).get("error") or "no error recorded")
        emit(self.db, "not_scored", f"{t['capability']} task not scored or refined: the agent produced no answer",
             f"agent_status failed ({err[:300]}); a code or LLM failure is not the agent's work, so its reward and "
             f"role prompt stay as they are", project_id=t.get("project_id"), agent_id=t.get("agent_id"),
             task_id=t["id"], data={"error": err[:1000]})

    # ---- lifecycle (SPEC §4) -----------------------------------------------------------------------------------------
    def lifecycle(self, now: datetime) -> None:
        db = self.db
        rewards = db.table("rewards").select("agent_id,task_id,reward,ts").order("ts", desc=True).limit(5000) \
            .execute().data
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        for r in lifecycle.retire_candidates(agents, rewards):
            moved = db.table("agents").update({"status": "retired"}).eq("id", r.agent["id"]).eq("status", "active") \
                .execute().data
            if moved:
                emit(db, "agent_retired", f"retired {r.agent['name']}", r.reason, agent_id=r.agent["id"],
                     data={"rule": "4.2", "mean": r.mean, "last": r.last})
                self._hand_over(r.agent, None, f"{r.agent['name']} was retired")

        agents = db.table("agents").select("*").eq("status", "active").execute().data
        for m in lifecycle.merge_candidates(agents, rewards):
            row = lifecycle.merged_version(m.winner, m.loser, m.reason)
            new = db.table("agents").insert(row).execute().data[0]
            db.table("agents").update({"status": "merged", "merged_into": new["id"]}).eq("id", m.loser["id"]).execute()
            db.table("agents").update({"status": "retired"}).eq("id", m.winner["id"]).execute()
            emit(db, "agent_merged", f"merged {m.loser['name']} into {new['name']}", m.reason, agent_id=new["id"],
                 data={"rule": "4.4", "winner": m.winner["id"], "loser": m.loser["id"], "overlap": m.overlap,
                       "capabilities": row["capabilities"]})
            emit(db, "agent_retired", f"retired {m.winner['name']}", f"superseded by v{row['version']} ({new['name']})",
                 agent_id=m.winner["id"], data={"rule": "4.4", "superseded_by": new["id"]})
            for old in (m.winner, m.loser):
                self._hand_over(old, new, f"{old['name']} was merged into {new['name']}")

        tasks = self.q("tasks", "id,project_id,agent_id,capability,status,input,output,acceptance") \
            .in_("status", ["done", "failed"]).not_.is_("agent_id", "null") \
            .order("finished_at", desc=True).limit(self.SCORE_SCAN).execute().data
        if not tasks:
            return
        feedback = reward.latest_feedback(db.table("events").select("task_id,data,ts").eq("type", "feedback")
                                          .in_("task_id", [t["id"] for t in tasks]).execute().data)
        agents = db.table("agents").select("*").execute().data
        already = {(a["parent_id"], a["created_by_task"]) for a in agents
                   if a.get("origin") == "refined" and a.get("parent_id") and a.get("created_by_task")}
        counts = self._refine_counts(agents)
        for r in lifecycle.refine_triggers(agents, tasks, feedback, already):
            key = (r.agent["id"], r.task["id"])
            pid = r.task.get("project_id")
            if lifecycle.is_capped(pid, r.agent["name"], counts):
                self._refine_capped(pid, r.agent, r.task, counts)
                continue
            if time.monotonic() - self._refine_failed.get(key, -1e9) < self.SPAWN_RETRY_S:
                continue
            self.refine(r, key)

    def _agent_names(self) -> dict[str, str]:
        return {a["id"]: a["name"] for a in self.db.table("agents").select("id,name").execute().data}

    def _refine_counts(self, agents: list[dict]) -> dict:
        refined = [a for a in agents if a.get("origin") == "refined" and a.get("created_by_task")]
        ids = sorted({a["created_by_task"] for a in refined})
        project_of = {t["id"]: t["project_id"] for t in self.db.table("tasks").select("id,project_id")
                      .in_("id", ids).execute().data} if ids else {}
        return lifecycle.refine_counts(refined, project_of)

    def _refine_capped(self, pid: str, agent: dict, task: dict, counts: dict) -> None:
        """R4: the role was refined MAX_REFINES_PER_ROLE times in this project; the task stays failed. One event per
        project and role."""
        role = lifecycle.role_of(agent["name"])
        if not self.once(("refine_capped", pid, role)):
            return
        seen = self.db.table("events").select("id").eq("project_id", pid).eq("type", "refine_capped") \
            .eq("data->>role", role).limit(1).execute().data
        if seen:
            return
        emit(self.db, "refine_capped", f"no more refines of {role} in this project",
             f"{role} was refined {counts.get((pid, role), 0)} times in this project (cap {MAX_REFINES_PER_ROLE}); "
             f"task {task['id'][:8]} stays failed and no new agent is spawned in its place",
             project_id=pid, agent_id=agent["id"], task_id=task["id"],
             data={"role": role, "refines": counts.get((pid, role), 0), "cap": MAX_REFINES_PER_ROLE})

    REFINE_SCHEMA = {"type": "object", "properties": {
        "role_prompt": {"type": "string", "description": "the full new system prompt, with the lesson built in"},
        "lesson": {"type": "string", "description": "one sentence: what the agent must do differently"},
        "reason": {"type": "string"}}, "required": ["role_prompt", "lesson"]}

    def refine(self, r, key) -> None:
        """SPEC §4.1: the LLM writes vN+1 of the role prompt; code makes the row and retires the old one."""
        from lab.llm import Request

        db, old, t = self.db, r.agent, r.task
        out = t.get("output") or {}
        detail = {k: out.get(k) for k in ("outcome", "error", "problems", "agent_status") if out.get(k)}
        prompt = (f"An agent of the research team needs a better role prompt.\n\nAgent: {old['name']} "
                  f"(capabilities {', '.join(old['capabilities'])})\nCurrent role prompt:\n{old['role_prompt']}\n\n"
                  f"Why it is being refined: {r.reason}\nThe task's goal:\n{(t.get('input') or {}).get('goal', '')}"
                  f"\nAcceptance check: {(t.get('acceptance') or {}).get('text', '')}\nWhat code recorded: "
                  f"{detail}\nAnswer excerpt: {str(out.get('answer') or '')[:1500]}\n\n"
                  "Write version n+1 of the role prompt: keep what works, add the lesson from this failure as a "
                  "concrete instruction. Return the full prompt.")
        try:
            resp = self.llm.call(Request(agent="controller", system="You improve the prompts of AI research agents.",
                                         prompt=prompt, schema=self.REFINE_SCHEMA, model="smart"),
                                 task_id=t["id"])
            o = resp.output if isinstance(resp.output, dict) else {}
            lesson = str(o.get("lesson") or "").strip()
            row = lifecycle.refined_version(old, o.get("role_prompt") or "",
                                            r.reason + (f"; lesson: {lesson}" if lesson else ""), t["id"])
            new = db.table("agents").insert(row).execute().data[0]
        except Exception as e:
            self._refine_failed[key] = time.monotonic()
            emit(db, "refine_failed", f"could not refine {old['name']}", f"{r.reason}; {type(e).__name__}: {e}"[:1000],
                 project_id=t.get("project_id"), agent_id=old["id"], task_id=t["id"])
            return
        db.table("agents").update({"status": "retired"}).eq("id", old["id"]).execute()
        emit(db, "agent_refined", f"{old['name']} → {new['name']}", row["origin_reason"],
             project_id=t.get("project_id"), agent_id=new["id"], task_id=t["id"],
             data={"rule": "4.1", "kind": r.kind, "from": old["id"], "lesson": lesson, "model": resp.model,
                   "mode": resp.mode})
        emit(db, "agent_retired", f"retired {old['name']}", f"superseded by v{row['version']} ({new['name']})",
             project_id=t.get("project_id"), agent_id=old["id"], task_id=t["id"],
             data={"rule": "4.1", "superseded_by": new["id"]})
        self._hand_over(old, new, f"{old['name']} was superseded by {new['name']}")

    def _hand_over(self, old: dict, new: Optional[dict], why: str) -> None:
        """Queued or awaiting tasks of an agent that left go to its successor, or to the best active agent."""
        db = self.db
        waiting = db.table("tasks").select("id,project_id,capability").eq("agent_id", old["id"]) \
            .in_("status", ["queued", "awaiting_approval"]).execute().data
        if not waiting:
            return
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        scores = reward.rolling_means(db.table("rewards").select("agent_id,reward,ts").order("ts", desc=True)
                                      .limit(1000).execute().data)
        for t in waiting:
            target = new if new and t["capability"] in new["capabilities"] else \
                getattr(assign.pick_agent(agents, t["capability"], scores), "agent", None)
            if target is None:
                emit(db, "gap", f"no active agent for a waiting {t['capability']} task",
                     f"{why}; no active agent has {t['capability']}; the task keeps its old agent",
                     project_id=t.get("project_id"), task_id=t["id"])
                continue
            db.table("tasks").update({"agent_id": target["id"]}).eq("id", t["id"]).execute()
            emit(db, "task_reassigned", f"{t['capability']} task → {target['name']}", why,
                 project_id=t.get("project_id"), agent_id=target["id"], task_id=t["id"])

    # ---- learn (SPEC §6) ----------------------------------------------------------------------------------------------
    def learn(self, now: datetime) -> None:
        db = self.db
        for p in self.q("projects", key="id").in_("status", ["running", "done", "blocked"]).execute().data:
            plans = db.table("tasks").select("id").eq("project_id", p["id"]).eq("capability", "plan") \
                .eq("status", "done").order("finished_at", desc=True).limit(1).execute().data
            if not plans:
                continue
            steps = db.table("tasks").select("id,status,created_at,input").eq("parent_task_id", plans[0]["id"]) \
                .execute().data
            steps = [t for t in steps if (t.get("input") or {}).get("step") is not None]
            triggers = [(f"recovery:{plans[0]['id']}:{step}",
                         f"step {step + 1} failed (task {bad[:8]}) and then succeeded (task {good[:8]})")
                        for step, bad, good in memory.recoveries(steps)]
            if p["status"] == "done":
                triggers.append((f"done:{p['id']}", "the project finished all its plan steps"))
            for key, focus in triggers:
                if time.monotonic() - self._learn_failed.get(key, -1e9) < self.SPAWN_RETRY_S:
                    continue
                seen = db.table("events").select("id").eq("project_id", p["id"]).eq("type", "lessons_proposed") \
                    .eq("data->>trigger", key).limit(1).execute().data
                if seen:
                    continue
                agents = db.table("agents").select("*").eq("status", "active").execute().data
                pick = assign.pick_agent(agents, "write_notes", {}) or assign.pick_agent(agents, "write_report", {})
                if pick is None:
                    continue
                try:
                    memory.propose(db, self.llm, p, pick.agent, key, focus)
                except Exception as e:
                    self._learn_failed[key] = time.monotonic()
                    emit(db, "lessons_failed", "could not propose lessons", f"{focus}; {type(e).__name__}: {e}"[:1000],
                         project_id=p["id"], agent_id=pick.agent["id"])

    # ---- decisions --------------------------------------------------------------------------------------------------
    def apply_decisions(self, now: datetime) -> None:
        """The web moves a decided task itself; this catches a decision written without the status change."""
        rows = self.q("tasks", "id,project_id,agent_id,capability,decision,decision_note") \
            .eq("status", "awaiting_approval").not_.is_("decision", "null").execute().data
        for t in rows:
            if t["decision"] not in wiring.DECISION_STATUS:
                continue
            status = wiring.status_after(t["decision"])
            moved = self.db.table("tasks").update({"status": status}).eq("id", t["id"]) \
                .eq("status", "awaiting_approval").execute().data
            if moved:
                emit(self.db, "decision_applied", f"{t['capability']} task {t['decision']}d → {status}",
                     f"decision '{t['decision']}' was recorded on the task" +
                     (f": {t['decision_note']}" if t.get("decision_note") else ""), project_id=t.get("project_id"),
                     agent_id=t.get("agent_id"), task_id=t["id"], data={"decision": t["decision"], "status": status})

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
        tags = memory.task_tags(project, "plan") + [c for slot in planner.REPRO_ORDER for c in slot
                                                    if not c.startswith("run")]
        lessons, skipped_lessons = memory.choose(db, tags, project, memory.PER_PLAN)
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        scores = reward.rolling_means(db.table("rewards").select("agent_id,reward,ts").order("ts", desc=True)
                                      .limit(1000).execute().data)
        abstract = None
        if not (paper and paper.get("claims")) and project.get("arxiv_id"):
            _, abstract = planner.arxiv_abstract(project["arxiv_id"])
        try:
            plan, resp = planner.make_plan(self.llm, project, paper, lessons, agents, task_id=task["id"],
                                           abstract=abstract, scores=scores)
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
        memory.apply(db, lessons, tags, "planner", project_id=pid, task_id=task["id"])
        memory.skip(db, skipped_lessons, tags, "planner", project_id=pid, task_id=task["id"])
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
            state = self._plan_state(p["id"])
            if state is None:
                continue
            plan_task, steps, step_tasks, debugs = state
            action, i = progress.next_action(len(steps), step_tasks)
            if action == "create":
                self.create_step(p, plan_task, steps, i, now, step_tasks=step_tasks, debugs=debugs)
            elif action == "done":
                self.db.table("projects").update({"status": "done"}).eq("id", p["id"]).execute()
                emit(self.db, "project_done", f"all {len(steps)} plan steps finished",
                     "the last step's task is done", project_id=p["id"], task_id=plan_task["id"])
            elif action == "rejected":
                last = progress.latest_per_step(step_tasks)[i]
                if last.get("decision") == "redirect":
                    self.redirect_step(p, plan_task, steps, i, last, step_tasks, debugs, now)
                else:
                    self.stop_project(p, last, "stopped", "a researcher rejected its task"
                                      + (f": {last['decision_note']}" if last.get("decision_note") else ""))
            elif action == "failed":
                attempts = [t for t in step_tasks if t["input"]["step"] == i]
                last = progress.latest_per_step(attempts)[i]
                kind, why = progress.failure_action(attempts, debugs)
                if kind == "debug":
                    self.create_debug(p, plan_task, steps, i, last, debugs, now, step_tasks=step_tasks)
                elif kind == "retry":
                    self.create_step(p, plan_task, steps, i, now, attempts=attempts, debugs=debugs,
                                     step_tasks=step_tasks)
                elif kind == "blocked":
                    self.stop_project(p, last, "blocked", why)

    def _plan_state(self, project_id: str):
        """(plan task, steps, step tasks, debug tasks) of the project's latest done plan, or None."""
        plans = self.db.table("tasks").select("*").eq("project_id", project_id).eq("capability", "plan") \
            .eq("status", "done").order("finished_at", desc=True).limit(1).execute().data
        if not plans:
            return None
        plan_task = plans[0]
        steps = (plan_task.get("output") or {}).get("steps") or []
        tasks = self.db.table("tasks").select("id,status,capability,input,created_at,output,agent_id,executor,"
                                              "parent_task_id,decision,decision_note") \
            .eq("project_id", project_id).execute().data
        step_tasks = [t for t in tasks if t.get("parent_task_id") == plan_task["id"]
                      and (t.get("input") or {}).get("step") is not None]
        debugs = [t for t in tasks if t["capability"] == "debug"
                  and (t.get("input") or {}).get("plan_task_id") == plan_task["id"]]
        return plan_task, steps, step_tasks, debugs

    # ---- what-ifs (SPEC §7.4) ---------------------------------------------------------------------------------------
    def prepare_whatifs(self, now: datetime) -> None:
        """A queued design_whatif (from the web) gets its agent, upstream (upstream['run'] = the reproduction's full
        run), workdir and caps; until then no worker has the caps to claim it."""
        for w in self.q("tasks").eq("status", "queued").eq("capability", "design_whatif").execute().data:
            inp = w.get("input") or {}
            if inp.get("prepared"):
                continue
            project = self.db.table("projects").select("*").eq("id", w["project_id"]).execute().data[0]
            state = self._plan_state(project["id"])
            up, problem = {}, "the project has no finished plan to branch from"
            if state:
                plan_task, steps, step_tasks, debugs = state
                up = wiring.upstream([PlanStep(**st) for st in steps], step_tasks, len(steps), debugs)
                problem = whatif.ready_problem(up, {t["id"]: t for t in step_tasks})
            if problem:
                if self.once(("whatif_waiting", w["id"])):
                    emit(self.db, "whatif_waiting", "the what-if waits for the reproduction", problem,
                         project_id=project["id"], task_id=w["id"])
                continue
            question = str(inp.get("question") or inp.get("goal") or "").strip()
            new = {**inp, "question": question, "title": f"what-if: {question[:80]}",
                   "goal": f"What if: {question}\nDesign 3-4 branches of the reproduction's full run, each changing "
                           f"exactly one setting.",
                   "upstream": up, "workdir": f"runs/{project['id']}", "budget": {"max_cpu_s": 300}, "prepared": True}
            self.create_task(project, "design_whatif", new, now, parent_task_id=w.get("parent_task_id"),
                             caps=routing.required_caps("design_whatif"),
                             acceptance="3-4 branches, each changing exactly one CONFIG key (checked by code)",
                             requires_approval=False, fails=Counter(), trigger_task=w,
                             context=f"What-if question: {question}", label=f"what-if: {question[:60]}", existing=w)

    def advance_whatifs(self, now: datetime) -> None:
        db = self.db
        for w in self.q("tasks").eq("capability", "design_whatif").eq("status", "done").execute().data:
            if w["id"] in self._whatif_finished:
                continue
            pid = w["project_id"]
            family = db.table("tasks").select("id,capability,status,created_at,input,output,decision,decision_note") \
                .eq("project_id", pid).eq("input->>whatif_of", w["id"]).execute().data
            kind, arg = whatif.next_action(w, family)
            if kind == "wait":
                continue
            if kind == "finished":
                self._whatif_finished.add(w["id"])
                seen = db.table("events").select("id").eq("task_id", w["id"]).eq("type", "whatif_finished") \
                    .limit(1).execute().data
                if not seen:
                    emit(db, "whatif_finished", f"what-if finished: {(w.get('input') or {}).get('question', '')[:80]}",
                         arg, project_id=pid, task_id=w["id"])
                continue
            project = db.table("projects").select("*").eq("id", pid).execute().data[0]
            up = (w.get("input") or {}).get("upstream") or {}
            parents = {t["id"]: t for t in db.table("tasks").select("id,status,input,created_at").eq("project_id", pid)
                       .eq("capability", "run").eq("status", "done").execute().data}
            full = parents.get(up.get("run") or "")
            if full is None:
                if self.once(("whatif_parent", w["id"])):
                    emit(db, "whatif_blocked", "the what-if lost its parent run",
                         f"upstream run {up.get('run')} is not a finished run of this project", project_id=pid,
                         task_id=w["id"])
                continue
            smokes = sorted([t for t in parents.values() if (t.get("input") or {}).get("scale") == "smoke"
                             and not (t.get("input") or {}).get("whatif_of")],
                            key=lambda t: t.get("created_at") or "")
            exps = {}
            rows = db.table("experiments").select("id,config").eq("project_id", pid) \
                .eq("config->whatif->>task_id", w["id"]).execute().data
            for e in rows:
                cfg = e.get("config") or {}
                exps[((cfg.get("whatif") or {}).get("branch_id"), cfg.get("scale"))] = e
            workdir = f"runs/{pid}"
            if kind == "branches":
                for b in arg:
                    exp = exps.get((b["id"], "smoke")) or exps.get((b["id"], None)) or \
                        db.table("experiments").insert(whatif.experiment_row(b["experiment"], pid)).execute().data[0]
                    self.create_task(project, "run", whatif.branch_input(b, exp["id"], full, smokes[-1] if smokes
                                                                         else None, w["id"]), now,
                                     parent_task_id=w["id"], caps=routing.required_caps("run", "smoke"),
                                     acceptance="exit code 0 and every final_<model> METRIC line printed",
                                     requires_approval=False, fails=Counter(), trigger_task=w,
                                     context=f"what-if branch {b['id']}", label=f"what-if {b['id']} smoke: "
                                                                                f"{b['key']}={b['value']}")
            elif kind == "rank":
                self.create_task(project, "compare", whatif.rank_input(w, workdir), now, parent_task_id=w["id"],
                                 caps=routing.required_caps("compare"),
                                 acceptance="every branch ranked by code; pruned branches carry a reason",
                                 requires_approval=False, fails=Counter(), trigger_task=w,
                                 context="rank the what-if branches", label="rank the what-if branches")
            elif kind == "extend":
                rank = max([t for t in family if whatif.role(t) == "rank"], key=lambda t: t.get("created_at") or "")
                exp = exps.get((arg["branch_id"], "full")) or \
                    db.table("experiments").insert(whatif.experiment_row(arg["experiment"], pid)).execute().data[0]
                self.create_task(project, "run", whatif.extend_input(arg, exp["id"], full, w["id"], rank["id"]), now,
                                 parent_task_id=rank["id"], caps=routing.required_caps("run", "full"),
                                 acceptance="exit code 0 and every final_<model> METRIC line printed",
                                 requires_approval=True, fails=Counter(), trigger_task=rank,
                                 context=f"extend what-if branch {arg['branch_id']}",
                                 label=f"what-if {arg['branch_id']} full run: {arg['key']}={arg['value']} "
                                       f"({arg.get('reason') or 'top-ranked branch'})")
            elif kind == "final":
                self.create_task(project, "compare", whatif.final_input(w, arg, workdir), now,
                                 parent_task_id=arg["id"], caps=routing.required_caps("compare"),
                                 acceptance="the extended branch's claims graded by code", requires_approval=False,
                                 fails=Counter(), trigger_task=arg, context="grade the extended what-if branch",
                                 label="grade the extended what-if branch")

    def stop_project(self, project: dict, task: dict, status: str, why: str) -> None:
        out = task.get("output") or {}
        detail = out.get("error_signature") or out.get("error")
        self.db.table("projects").update({"status": status}).eq("id", project["id"]).execute()
        emit(self.db, f"project_{status}", f"step {task['input']['step'] + 1} cannot go on; the project is {status}",
             why + (f"; last error: {detail}" if detail else ""), project_id=project["id"], task_id=task["id"])

    def redirect_step(self, project: dict, plan_task: dict, steps: list[dict], i: int, task: dict,
                      step_tasks: list[dict], debugs: list[dict], now: datetime) -> None:
        """SPEC §9: replan step i with the researcher's note, store it in the plan, then create the new attempt."""
        if time.monotonic() - self._replan_failed.get(task["id"], -1e9) < self.SPAWN_RETRY_S:
            return
        note = task.get("decision_note") or ""
        plan_steps = [PlanStep(**s) for s in steps]
        try:
            new, why, resp = planner.replan_step(self.llm, project, plan_steps, i, note, task_id=task["id"])
        except Exception as e:
            self._replan_failed[task["id"]] = time.monotonic()
            emit(self.db, "replan_failed", f"could not replan step {i + 1} after the redirect",
                 f"note: {note}; {type(e).__name__}: {e}"[:1000], project_id=project["id"], task_id=task["id"])
            return
        out = dict(plan_task.get("output") or {})
        out["steps"] = [*steps[:i], new.model_dump(), *steps[i + 1:]]
        out.setdefault("redirects", []).append({"step": i, "task_id": task["id"], "note": note, "reason": why,
                                                "before": steps[i]})
        self.db.table("tasks").update({"output": out}).eq("id", plan_task["id"]).execute()
        emit(self.db, "step_redirected", f"step {i + 1} replanned after a redirect: {new.title}",
             f"researcher's note: {note}; planner: {why or 'no reason given'}", project_id=project["id"],
             task_id=task["id"], data={"step": i, "before": steps[i], "after": new.model_dump(), "model": resp.model,
                                       "mode": resp.mode})
        attempts = [t for t in step_tasks if t["input"].get("step") == i]
        self.create_step(project, plan_task, out["steps"], i, now, attempts=attempts, debugs=debugs,
                         step_tasks=step_tasks, redirect_note=note)

    def create_step(self, project: dict, plan_task: dict, steps: list[dict], i: int, now: datetime,
                    attempts: list[dict] = (), debugs: list[dict] = (), step_tasks: list[dict] = (),
                    redirect_note: Optional[str] = None) -> None:
        step = PlanStep(**steps[i])
        plan_steps = [PlanStep(**s) for s in steps]
        workdir = f"runs/{project['id']}"
        goal = step.instructions
        if redirect_note:
            goal += f"\n\nA researcher redirected this step: {redirect_note}"
            attempts = [t for t in attempts if t.get("status") == "failed"]
        if attempts:
            last = progress.latest_per_step(attempts)[i]
            out = last.get("output") or {}
            goal += (f"\n\nThis is attempt {len(attempts) + 1}. The previous attempt failed: "
                     f"{out.get('error_signature') or out.get('error') or 'no error recorded'}.")
            fixed = [d for d in debugs if d["input"].get("failed_task_id") == last["id"] and d["status"] == "done"]
            if fixed:
                goal += f" A debug task worked on it: {str((fixed[-1].get('output') or {}).get('answer'))[:500]}"
        inp = {"goal": goal, "title": step.title, "step": i, "of": len(steps), "attempt": len(attempts) + 1,
               "plan_task_id": plan_task["id"], "workdir": workdir, "budget": {"max_cpu_s": step.budget_cpu_s},
               "upstream": wiring.upstream(plan_steps, list(step_tasks), i, debugs)}
        if redirect_note:
            inp["redirect_note"] = redirect_note
        if step.capability == "run":
            fields, problems = wiring.run_input(plan_steps, list(step_tasks), list(debugs), i, workdir)
            if problems:
                if self.once(("run_inputs", plan_task["id"], i, len(attempts))):
                    self.db.table("projects").update({"status": "blocked"}).eq("id", project["id"]).execute()
                    emit(self.db, "project_blocked", f"step {i + 1} ({step.title}) cannot be queued",
                         "earlier steps did not provide what the run needs: " + "; ".join(problems),
                         project_id=project["id"], task_id=plan_task["id"], data={"problems": problems})
                return
            exp = fields.pop("experiment")
            exp_row = self.db.table("experiments").insert({
                "project_id": project["id"], "label": exp["label"], "config": exp["config"], "margin": exp["margin"],
                "budget_reason": exp["budget_reason"], "status": "planned"}).execute().data[0]
            inp.update(fields)
            inp.update({"scale": step.scale, "experiment_id": exp_row["id"], "label": step.title,
                        "timeout_s": max(step.budget_cpu_s, RUN_TIMEOUT_FLOOR_S)})
        fails = spawn.fails_by_role(attempts, self._agent_names())
        context = f"Plan step {i + 1} of {len(steps)}: {step.title}\nInstructions: {step.instructions}"
        if attempts:
            context += "\nEarlier attempts failed: " + "; ".join(
                str((t.get("output") or {}).get("error_signature") or (t.get("output") or {}).get("error"))
                for t in attempts)
        self.create_task(project, step.capability, inp, now, parent_task_id=plan_task["id"], preferred=step.agent,
                         caps=routing.required_caps(step.capability, step.scale), acceptance=step.acceptance,
                         requires_approval=step.requires_approval, fails=fails,
                         trigger_task=attempts[-1] if attempts else plan_task, context=context,
                         label=f"step {i + 1}/{len(steps)} {step.capability}: {step.title}"
                               + (f" (attempt {len(attempts) + 1})" if attempts else ""))

    def create_debug(self, project: dict, plan_task: dict, steps: list[dict], i: int, failed: dict,
                     debugs: list[dict], now: datetime, step_tasks: list[dict] = ()) -> None:
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
               "budget": {"max_cpu_s": step.budget_cpu_s},
               "upstream": wiring.upstream([PlanStep(**s) for s in steps], list(step_tasks), i, debugs)}
        for k in ("files", "requirements"):  # what the failed run ran, so the Debugger can patch it
            if fin.get(k):
                inp[k] = fin[k]
        context = (f"Plan step {i + 1} ({step.title}, capability {step.capability}) crashed on "
                   f"{failed.get('executor') or 'an executor'}: {sig} {where}."
                   + (f" Command: {cmd_text}." if cmd_text else ""))
        self.create_task(project, "debug", inp, now, parent_task_id=failed["id"], caps=routing.required_caps("debug"),
                         acceptance="the failing command gets past the error, and the change is labelled REPAIR(env) "
                                    "or REPAIR(code)",
                         requires_approval=False,
                         fails=spawn.fails_by_role(mine, self._agent_names()),
                         trigger_task=failed, context=context, label=f"debug step {i + 1}: {sig}")

    def create_task(self, project: dict, capability: str, inp: dict, now: datetime, *, parent_task_id: str,
                    caps: list[str], acceptance: str, requires_approval: bool, fails: dict, trigger_task: dict,
                    context: str, label: str, preferred: Optional[str] = None,
                    existing: Optional[dict] = None) -> Optional[dict]:
        """Assign the best agent (spawning one on a gap or a repeated failure), then queue the task, or, with
        `existing`, fill in that queued row instead. None: no agent yet (the spawn failed; it is tried again later)."""
        db, pid = self.db, project["id"]
        pin = routing.host_pin(db.table("tasks").select("capability,executor,started_at").eq("project_id", pid)
                               .eq("capability", "run").execute().data)
        caps = routing.with_pin(caps, pin)
        agents = db.table("agents").select("*").eq("status", "active").execute().data
        rewards = db.table("rewards").select("agent_id,reward,ts").order("ts", desc=True).limit(1000).execute().data
        pick = assign.pick_agent(agents, capability, reward.rolling_means(rewards), preferred=preferred)
        trig = spawn.trigger(pick, capability, fails)
        if trig and trig.kind == "repeated_failure" and lifecycle.is_capped(
                pid, pick.agent["name"], self._refine_counts(db.table("agents").select("*").execute().data)):
            trig = None  # R4: a capped role is not replaced by a spawned agent either
            pick = assign.Pick(pick.agent, pick.score, pick.reason + "; its role reached the refine cap in this "
                                                                    "project, so no new agent is spawned")
        if trig:
            agent = self.spawn_agent(project, capability, trig, context, trigger_task, agents)
            if agent is None:
                return None
            pick = assign.Pick(agent, None, f"{agent['name']}: spawned for this task ({trig.reason})")
        inp["budget"] = {**inp.get("budget", {}),
                         "max_tokens": (pick.agent.get("budget") or {}).get("max_tokens", 20_000)}
        lessons, tags = [], []
        if capability != "run":  # a run has no prompt: nothing could apply a lesson there
            tags = memory.task_tags(project, capability, inp.get("error_signature"))
            lessons = memory.relevant(db, tags, memory.PER_TASK, project)
            if lessons:
                inp["goal"] = inp["goal"] + "\n\n" + memory.lessons_block(lessons)
                inp["lessons"] = [l["id"] for l in lessons]
        live = routing.eligible(caps, db.table("executors").select("*").execute().data, now)
        fields = {"required_caps": caps, "agent_id": pick.agent["id"], "input": inp, "acceptance": {"text": acceptance},
                  "requires_approval": requires_approval}
        if existing:
            moved = db.table("tasks").update(fields).eq("id", existing["id"]).eq("status", "queued").execute().data
            if not moved:
                return None
            row = moved[0]
        else:
            row = db.table("tasks").insert({
                **fields, "project_id": pid, "parent_task_id": parent_task_id, "capability": capability,
                "status": "awaiting_approval" if requires_approval else "queued"}).execute().data[0]
        memory.apply(db, lessons, tags, f"{capability} task", project_id=pid, task_id=row["id"],
                     agent_id=pick.agent["id"])
        where = (f"live executors that can take it: {', '.join(e['name'] for e in live)}" if live
                 else "no live executor has these caps yet; it waits in the queue")
        if pin:
            where += f" (pinned to {pin[5:]}, which claimed the project's first run)"
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
            everyone = db.table("agents").select("name,capabilities,budget").execute().data
            taken = {a["name"] for a in everyone}
            floor = max([(a.get("budget") or {}).get("max_tokens") or 0 for a in everyone
                         if capability in (a.get("capabilities") or [])] or [spawn.MIN_TOKENS])
            row, notes = spawn.check_spec(draft, capability, cap_s, taken, floor_tokens=floor)
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
