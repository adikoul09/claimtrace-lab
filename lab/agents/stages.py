"""Capability handlers: how an executor runs a non-`run` task (docs/CONTRACTS.md §3-§4).

The controller makes one task per plan step and assigns an agent (tasks.agent_id); the worker claims it and calls
handle(), which runs that agent through lab/agents/runtime.py in input.workdir (runs/<project_id>). Inputs from earlier
steps come from input.upstream {capability: task_id} (their tasks.output); the stages' own checks are code:

  read_paper, extract_*  the Reader (skipped when papers.claims exists)    claims_valid, settings_valid
  design_experiment   Designer picks the experiment and target claims      check_design -> design, config, margin
  write_code          Implementer writes train.py from claims + settings   check_written -> files {"train.py"}
  setup_env           EnvBuilder writes pinned requirements, make_env       check_built -> requirements
  budget              Designer proposes epochs from the smoke run           plan_budget -> epochs, subset, seeds, reason
  debug               Debugger repairs a crash                              repair_label parsed by code; changed
                                                                            files / requirements
  compare             verdicts by code (no LLM)                             experiment_id (verdicts written)
  explain_diff        verdicts + the Analyst's number-checked explanation   experiment_id
  anything else       the agent's own loop on input.goal                    answer (markdown for write_report/notes)

Every output has agent_status, outcome (passed | partial | failed, decided by code; B1's reward reads it), answer,
error, tokens and cpu_s. Files from upstream outputs are written into the workdir before an agent runs, so steps
that ran on another machine before host pinning still see train.py and requirements.txt.

The one-shot fallback `python -m lab.agents.reproduce` runs the same checks in one process."""
from __future__ import annotations

import json
import re
from pathlib import Path

from lab.agents.reproduce import (StepError, budget_goal, check_built, check_design, check_designed, check_written,
                                  declare_margin, designer_goal, envbuilder_goal, implementer_goal, parse_answer,
                                  plan_budget, smoke_timing)
from lab.agents.runtime import run_agent
from lab.agents.tools import RUNS
from lab.db import ROOT, emit
from lab.llm import LLM

PAPER_CAPS = ("read_paper", "extract_claims", "extract_settings")
FILE_CAPS = ("write_code", "debug")  # upstream outputs that may carry files, in the order they apply
NOTES_MAX = 2_000
DEFAULT_CAP_MIN = 20
REPAIR_RE = re.compile(r"REPAIR\((env|code)\)|HYPOTHESIS")


class Ctx:
    def __init__(self, db, task: dict, executor: str, llm=None):
        self.db, self.task, self.executor, self.llm = db, task, executor, llm
        self.inp = task.get("input") or {}
        self.pid = task.get("project_id")
        rel = self.inp.get("workdir") or f"runs/{self.pid}"
        wd = (ROOT / rel).resolve()
        if wd == RUNS.resolve() or not wd.is_relative_to(RUNS.resolve()):
            raise StepError(f"input.workdir must be a folder inside runs/, got {rel!r}")
        wd.mkdir(parents=True, exist_ok=True)
        self.workdir = wd
        self._agent = self._project = self._paper = None
        self._up: dict[str, dict] = {}

    @property
    def agent(self) -> dict:
        if self._agent is None:
            aid = self.task.get("agent_id")
            rows = self.db.table("agents").select("*").eq("id", aid).execute().data if aid else []
            if not rows:
                raise StepError("the task has no assigned agent (tasks.agent_id); the controller assigns one")
            self._agent = rows[0]
        return self._agent

    @property
    def project(self) -> dict:
        if self._project is None:
            rows = self.db.table("projects").select("*").eq("id", self.pid).execute().data
            self._project = rows[0] if rows else {}
        return self._project

    @property
    def paper(self) -> dict:
        if self._paper is None:
            rows = self.db.table("papers").select("*").eq("project_id", self.pid).execute().data
            self._paper = rows[0] if rows else {}
        return self._paper

    @property
    def claims(self) -> list[dict]:
        if not self.paper.get("claims"):
            raise StepError("the project has no claims yet (the read_paper step must run first)")
        return self.paper["claims"]

    @property
    def settings(self) -> list[dict]:
        return self.paper.get("settings") or []

    @property
    def cap_s(self) -> float:
        return 60 * float(self.project.get("budget_cpu_min") or DEFAULT_CAP_MIN)

    def upstream(self, capability: str, required: bool = True) -> dict:
        """The upstream task row of an earlier step (its output, executor, ...), from input.upstream."""
        if capability not in self._up:
            tid = (self.inp.get("upstream") or {}).get(capability)
            rows = self.db.table("tasks").select("*").eq("id", tid).execute().data if tid else []
            self._up[capability] = rows[0] if rows else {}
        row = self._up[capability]
        if required and not row:
            raise StepError(f"input.upstream has no finished {capability} task; that step must run first")
        return row

    def out_of(self, capability: str, required: bool = True) -> dict:
        return self.upstream(capability, required).get("output") or {}

    def materialize(self) -> list[str]:
        """Write train.py (latest write_code/debug output) and requirements.txt (setup_env/debug) into the workdir."""
        files, req = {}, None
        for src in (*(self.out_of(c, required=False) for c in ("write_code", "setup_env", "debug")), self.inp):
            files.update(src.get("files") or {})  # a debug task's input carries the failed run's own files: last
            req = src.get("requirements") if src.get("requirements") is not None else req
        if req is not None:
            files["requirements.txt"] = req
        if files:
            from lab.executor.worker import write_files
            return write_files(files, self.workdir)
        return []

    def notes(self) -> str:
        """The plan step's instructions, the controller's note on earlier attempts, a researcher's redirect."""
        g = (self.inp.get("goal") or "").strip()
        out = f"\n\nNotes from the plan step:\n{g[:NOTES_MAX]}" if g else ""
        if self.inp.get("redirect_note"):
            out += f"\n\nA researcher redirected this step: {self.inp['redirect_note'][:NOTES_MAX]}"
        return out


def checked(ctx: Ctx, goal: str, check, model: str = "fast") -> dict:
    """Run the task's agent on `goal`; `check(answer)` is the code acceptance check (returns output fields, or raises
    StepError). Returns tasks.output."""
    res = run_agent(ctx.agent, goal, ctx.workdir, db=ctx.db, llm=ctx.llm, task_id=ctx.task["id"],
                    project_id=ctx.pid, model=model)
    out = {"agent_status": res.status, "tokens": res.tokens, "cpu_s": res.cpu_s, "steps": res.steps,
           "answer": (res.answer or "")[:2000], "acceptance": check.__doc__ or "code check"}
    if res.status != "finished":
        return {**out, "outcome": "failed", "error": f"agent {res.status}: {res.reason}"[:500]}
    try:
        return {**out, **(check(res.answer) or {}), "outcome": "passed", "error": None}
    except StepError as e:
        return {**out, "outcome": "failed", "error": str(e)[:1000]}


def _design(ctx: Ctx) -> dict:
    d = ctx.out_of("design_experiment").get("design")
    if not d:
        raise StepError("the design_experiment output has no design")
    return check_design(d, ctx.claims)


# ---- handlers ---------------------------------------------------------------------------------------------------

def h_paper(ctx: Ctx) -> dict:
    if ctx.paper.get("claims"):
        c, s = ctx.paper["claims"], ctx.settings
        return {"outcome": "passed", "agent_status": "skipped", "tokens": 0, "cpu_s": 0.0, "error": None,
                "claims_valid": sum(bool(x.get("valid")) for x in c),
                "settings_valid": sum(bool(x.get("valid")) for x in s),
                "answer": f"the papers row already has {len(c)} claims and {len(s)} settings; nothing to do"}
    from lab.agents.paper import read_paper
    arxiv = ctx.project.get("arxiv_id")
    if not arxiv:
        raise StepError("the project has no arxiv_id")
    res = read_paper(ctx.pid, arxiv, db=ctx.db, llm=ctx.llm or LLM(db=ctx.db), agent=ctx.agent, workdir=ctx.workdir,
                     task_id=ctx.task["id"], model="fast")  # fast at the 4000 cap: smart ran out reasoning
    cv = sum(bool(c.get("valid")) for c in res.get("claims", []))
    sv = sum(bool(s.get("valid")) for s in res.get("settings", []))
    return {"outcome": "passed" if cv else "failed", "agent_status": "finished", "tokens": res.get("tokens", 0),
            "cpu_s": 0.0, "claims_valid": cv, "settings_valid": sv,
            "error": None if cv else "no claim passed the code checks (quote on the page, value in the quote)"}


def h_design(ctx: Ctx) -> dict:
    def designed(answer):
        """the answer is a JSON design whose models each map to one valid claim; code declares the margin"""
        d = check_designed(answer, ctx.claims, ctx.workdir, ctx.settings)
        margin, why = declare_margin([c for c in ctx.claims if c["id"] in d["claim_map"].values()])
        emit(ctx.db, "margin_declared", f"margin {margin} declared before the run", why, project_id=ctx.pid,
             task_id=ctx.task["id"], agent_id=ctx.agent.get("id"))
        return {"design": d, "margin": margin, "margin_reason": why,
                "config": {"claim_map": d["claim_map"], "design": d, "seeds": [0], "margin_reason": why}}
    return checked(ctx, designer_goal(ctx.claims, ctx.settings, ctx.cap_s / 60) + ctx.notes(), designed)


def h_write_code(ctx: Ctx) -> dict:
    design = _design(ctx)
    names = [m["name"] for m in design["models"]]
    (ctx.workdir / "train.py").unlink(missing_ok=True)  # the check must see this attempt's file, not an old one
    def written(_):
        """train.py exists, compiles, meets the CLI/METRIC contract and never touches the golden reference"""
        info = check_written(ctx.workdir, names)
        return {**info, "files": {"train.py": (ctx.workdir / "train.py").read_text(encoding="utf-8")}}
    return checked(ctx, implementer_goal(design, ctx.claims, ctx.settings) + ctx.notes(), written, model="fast")


def h_setup_env(ctx: Ctx) -> dict:
    ctx.materialize()
    if not (ctx.workdir / "train.py").is_file():
        raise StepError("no train.py: the write_code step must run first")
    for f in ("env.json", "requirements.txt"):
        (ctx.workdir / f).unlink(missing_ok=True)
    def built(_):
        """make_env succeeded: env.json and pinned requirements.txt exist in the run dir"""
        info = check_built(ctx.workdir)
        return {**info, "requirements": (ctx.workdir / "requirements.txt").read_text(encoding="utf-8")}
    return checked(ctx, envbuilder_goal() + ctx.notes(), built)


def h_budget(ctx: Ctx) -> dict:
    design = _design(ctx)
    smoke = ctx.upstream("run")
    sout = smoke.get("output") or {}
    exp_id = sout.get("experiment_id") or (smoke.get("input") or {}).get("experiment_id")
    if (smoke.get("input") or {}).get("scale") not in (None, "smoke"):
        raise StepError("upstream run is not a smoke run; the budget needs the smoke run's epoch times")
    metrics = ctx.db.table("metrics").select("name,value,step,log_line").eq("experiment_id", exp_id).execute().data
    timing = smoke_timing(metrics, float(sout.get("wall_s") or 0), list(design["claim_map"]))
    timing["executor"] = smoke.get("executor")
    def budgeted(answer):
        """the proposal is a positive epoch count; code clips it to the project cap"""
        b = plan_budget(parse_answer(answer), timing, ctx.cap_s, smoke.get("executor"))
        emit(ctx.db, "budget_chosen", f"full run: {b['epochs']} epochs" + (f", {b['subset']} examples"
                                                                            if b["subset"] else ""),
             b["reason"], project_id=ctx.pid, task_id=ctx.task["id"], agent_id=ctx.agent.get("id"), data=b)
        return {"epochs": b["epochs"], "subset": b["subset"], "seeds": [0], "reason": b["reason"], "budget": b,
                "timing": timing}
    return checked(ctx, budget_goal(design, timing, ctx.cap_s, smoke.get("executor"), ctx.settings) + ctx.notes(),
                   budgeted)


def repair_label(answer: str) -> str | None:
    """REPAIR(env) / REPAIR(code) / HYPOTHESIS, as the Debugger states it (the last one named wins)."""
    hits = [m.group(0) for m in REPAIR_RE.finditer(answer or "")]
    return hits[-1] if hits else None


def h_debug(ctx: Ctx) -> dict:
    ctx.materialize()
    before = {f: (ctx.workdir / f).read_text(encoding="utf-8") if (ctx.workdir / f).is_file() else None
              for f in ("train.py", "requirements.txt")}
    def repaired(answer):
        """the Debugger names its change REPAIR(env), REPAIR(code) or HYPOTHESIS"""
        label = repair_label(answer)
        if not label:
            raise StepError("the answer does not label the change REPAIR(env), REPAIR(code) or HYPOTHESIS")
        out = {"repair_label": label}
        after = {f: (ctx.workdir / f).read_text(encoding="utf-8") if (ctx.workdir / f).is_file() else None
                 for f in before}
        if after["train.py"] is not None and after["train.py"] != before["train.py"]:
            out["files"] = {"train.py": after["train.py"]}
        if after["requirements.txt"] is not None and after["requirements.txt"] != before["requirements.txt"]:
            out["requirements"] = after["requirements.txt"]
        return out
    return checked(ctx, (ctx.inp.get("goal") or "Repair the failed step.") +
                   (f"\n\nA researcher redirected this step: {ctx.inp['redirect_note']}"
                    if ctx.inp.get("redirect_note") else ""), repaired)


def h_grade(ctx: Ctx) -> dict:
    from lab.agents import analyst

    if ctx.inp.get("whatif_task_id") and not ctx.inp.get("extend_experiment_id"):
        return h_whatif_rank(ctx)
    exp_id = ctx.inp.get("extend_experiment_id") or ctx.inp.get("experiment_id") or         ctx.out_of("run").get("experiment_id")
    if not exp_id:
        raise StepError("no experiment to grade: input.experiment_id and the upstream run's output are empty")
    explain = ctx.task["capability"] == "explain_diff"
    g = analyst.run(ctx.db, exp_id, with_explanation=explain, agent=ctx.agent if explain else None,
                    task_id=ctx.task["id"], llm=ctx.llm, log_reader=lambda e: log_lines(ctx, e))
    if ctx.inp.get("extend_experiment_id"):
        ext = next((e for e in _experiments(ctx) if e["id"] == exp_id), {})
        if ext.get("parent_id"):
            refresh_why(ctx, ext["parent_id"])  # the parent's table gains the branch's full-budget effect
    runnable = [r for r in g["claims"] if r["verdict"] != "Not runnable"]
    outcome = "passed" if runnable else "failed"
    if explain and not g["explanation"]["accepted"]:
        outcome = "partial" if runnable else "failed"
    tries = g["explanation"].get("tries") or []
    return {"outcome": outcome, "experiment_id": exp_id, "agent_status": "finished" if explain else "skipped",
            "answer": g["explanation"].get("text") or "",
            "verdicts": {r["claim_id"]: r["label"] for r in g["claims"]},
            "error": None if outcome == "passed" else "; ".join(g["explanation"]["problems"]) or
            "no claim was runnable", "tokens": sum(t.get("tokens") or 0 for t in tries), "cpu_s": 0.0}


def h_generic(ctx: Ctx) -> dict:
    ctx.materialize()
    goal = (ctx.inp.get("goal") or ctx.inp.get("title") or ctx.task["capability"]) + \
        (f"\n\nA researcher redirected this step: {ctx.inp['redirect_note']}" if ctx.inp.get("redirect_note") else "")
    res = run_agent(ctx.agent, goal, ctx.workdir, db=ctx.db, llm=ctx.llm, task_id=ctx.task["id"],
                    project_id=ctx.pid)
    outcome = {"finished": "passed", "stopped": "partial"}.get(res.status, "failed")
    out = {"outcome": outcome, "agent_status": res.status, "tokens": res.tokens, "cpu_s": res.cpu_s,
           "steps": res.steps, "answer": (res.answer or "")[:8000],
           "error": None if outcome == "passed" else res.reason[:500]}
    if ctx.task["capability"] in ("write_report", "write_notes"):
        out["markdown"] = res.answer or ""
    return out




def handle(db, task: dict, executor: str, llm=None) -> dict:
    """tasks.output for one claimed non-`run` task. Never raises: a stage problem is outcome failed with its error."""
    handler = HANDLERS.get(task["capability"], h_generic)
    try:
        ctx = Ctx(db, task, executor, llm)
        _ = ctx.agent  # a task without an agent fails before anything runs
        out = handler(ctx)
    except StepError as e:
        out = {"outcome": "failed", "agent_status": "failed", "tokens": 0, "cpu_s": 0.0, "error": str(e)[:1000]}
    out["handler"] = handler.__name__
    return out


# ---- what-if (T18; SPEC §7.4; CONTRACTS.md: the controller creates the branch runs from these outputs) ----------------

def log_lines(ctx: Ctx, experiment_id: str) -> list[str]:
    """An experiment's log: the local copy the worker kept (same machine), else Storage."""
    local = RUNS / "logs" / f"{experiment_id}.log"
    if local.is_file():
        return local.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        return ctx.db.storage.from_("logs").download(f"{experiment_id}.log").decode("utf-8", "replace").splitlines()
    except Exception as e:
        raise StepError(f"the log of experiment {experiment_id} is not available: {type(e).__name__}") from None


def _experiments(ctx: Ctx) -> list[dict]:
    return ctx.db.table("experiments").select("*").eq("project_id", ctx.pid).execute().data


def _finals(ctx: Ctx, experiment_id: str, models) -> dict:
    rows = ctx.db.table("metrics").select("name,value,log_line").eq("experiment_id", experiment_id).execute().data
    want = {f"final_{m}": m for m in models}
    return {want[r["name"]]: r["value"] for r in rows if r["name"] in want and r["value"] is not None}


def parent_smoke_task(ctx: Ctx) -> dict:
    """The reproduction's latest finished smoke run (not a what-if branch's)."""
    branch_exps = {e["id"] for e in _experiments(ctx) if (e.get("config") or {}).get("whatif")}
    rows = ctx.db.table("tasks").select("*").eq("project_id", ctx.pid).eq("capability", "run") \
        .eq("status", "done").order("created_at", desc=True).execute().data
    for t in rows:
        inp = t.get("input") or {}
        if inp.get("scale") == "smoke" and inp.get("experiment_id") not in branch_exps:
            return t
    raise StepError("no finished smoke run of the reproduction: branches start from its command")


def method_models(claim_map: dict, claims: list[dict]) -> list[str]:
    whose = {c["id"]: c.get("whose") for c in claims}
    return [m for m, cid in claim_map.items() if whose.get(cid) == "method"] or list(claim_map)


def h_design_whatif(ctx: Ctx) -> dict:
    from lab.agents import whatif as wi

    question = ctx.inp.get("question") or ctx.inp.get("goal")
    if not question:
        raise StepError("the what-if task has no question")
    full_run = ctx.upstream("run")
    parent_id = (full_run.get("output") or {}).get("experiment_id") or (full_run.get("input") or {}).get(
        "experiment_id")
    parent = next((e for e in _experiments(ctx) if e["id"] == parent_id), None)
    if not parent:
        raise StepError("the upstream run has no experiment to branch from")
    pcfg = parent.get("config") or {}
    cfg, cfg_line = wi.parse_config(log_lines(ctx, parent_id))
    smoke = parent_smoke_task(ctx)
    # Reproductions run one seed (budget output seeds [0]), so the declared margin is the noise scale.
    n, n_src = wi.noise([], parent.get("margin"))
    design = pcfg.get("design") or {}

    def branched(answer):
        """3-4 branches, each changing exactly one key of the parent run's CONFIG"""
        parsed = parse_answer(answer)
        checked_branches = wi.check_branches(parsed.get("branches") or [], cfg)
        out = []
        for b in checked_branches:
            cwd = f"runs/{ctx.pid}/whatif/{ctx.task['id'][:8]}-{b['id']}"
            data_rel = data_dir_rel(cwd)
            out.append({**{k: b[k] for k in ("id", "key", "value", "parent_value", "reason")}, "scale": "smoke",
                        "cwd": cwd, "cmd": wi.branch_cmd(wi.with_data_dir(smoke["input"]["cmd"], data_rel),
                                                         b["key"], b["value"]),
                        "experiment": {"label": f"what-if {b['id']}: {b['key']}={json.dumps(b['value'])} (smoke)",
                                       "parent_id": parent_id, "changed_key": b["key"], "margin": parent.get("margin"),
                                       "config": {**{k: pcfg[k] for k in ("claim_map", "seeds", "design",
                                                                          "margin_reason") if k in pcfg},
                                                  "scale": "smoke", "settings": b["config"],
                                                  "whatif": {"task_id": ctx.task["id"], "branch_id": b["id"],
                                                             "key": b["key"], "value": b["value"],
                                                             "parent_value": b["parent_value"],
                                                             "question": question}}}})
        emit(ctx.db, "whatif_designed", f"what-if: {len(out)} one-change branches: " +
             ", ".join(f"{b['key']}={json.dumps(b['value'])}" for b in out),
             f"code checked each changes exactly one key of the parent CONFIG (log line {cfg_line}); noise {n_src}",
             project_id=ctx.pid, task_id=ctx.task["id"], agent_id=ctx.agent.get("id"))
        return {"question": question, "branches": out, "noise": n, "noise_source": n_src,
                "parent_experiment_id": parent_id, "parent_smoke_experiment_id": smoke["input"]["experiment_id"],
                "parent_full_cmd": (full_run.get("input") or {}).get("cmd"), "parent_config_log_line": cfg_line}
    return checked(ctx, wi.whatif_goal(question, cfg, design.get("experiment")) + ctx.notes(), branched)


def refresh_why(ctx: Ctx, experiment_id: str) -> None:
    """Rebuild a reproduction experiment's config.why (T19), so branch effects measured after its own grading
    show in its settings rows."""
    from lab.agents import analyst

    exp = next((e for e in _experiments(ctx) if e["id"] == experiment_id), None)
    if not exp or (exp.get("config") or {}).get("whatif"):
        return
    w = analyst.why_tables(ctx.db, exp, ctx.settings, read=lambda e: log_lines(ctx, e))
    cfg = {**(exp.get("config") or {}), "why": w}
    ctx.db.table("experiments").update({"config": cfg}).eq("id", experiment_id).execute()


def data_dir_rel(cwd_rel: str) -> str:
    import os
    return os.path.relpath(ROOT / "data", ROOT / cwd_rel).replace(os.sep, "/")


def h_whatif_rank(ctx: Ctx) -> dict:
    from lab.agents import whatif as wi

    tid = ctx.inp["whatif_task_id"]
    rows = ctx.db.table("tasks").select("*").eq("id", tid).execute().data
    d = (rows[0].get("output") or {}) if rows else {}
    if not d.get("branches"):
        raise StepError(f"what-if task {tid} has no branches in its output")
    exps = {(e.get("config") or {}).get("whatif", {}).get("branch_id"): e for e in _experiments(ctx)
            if ((e.get("config") or {}).get("whatif") or {}).get("task_id") == tid
            and (e.get("config") or {}).get("scale") == "smoke"}  # an extend row shares task and branch ids
    runs_by_exp = {(t.get("input") or {}).get("experiment_id"): t for t in
                   ctx.db.table("tasks").select("*").eq("project_id", ctx.pid).eq("capability", "run").execute().data}
    parent = next((e for e in _experiments(ctx) if e["id"] == d["parent_experiment_id"]), {})
    cmap = (parent.get("config") or {}).get("claim_map") or {}
    methods = method_models(cmap, ctx.claims)
    parent_finals = _finals(ctx, d["parent_smoke_experiment_id"], cmap)
    results, errors = {}, {}
    for b in d["branches"]:
        e = exps.get(b["id"])
        run = runs_by_exp.get(e["id"]) if e else None
        finals = _finals(ctx, e["id"], cmap) if e else {}
        if not e or not run or run.get("status") != "done" or not finals:
            results[b["id"]] = None
            errors[b["id"]] = ((run or {}).get("output") or {}).get("error_signature") or \
                ("no smoke run" if not run else f"status {run.get('status')}" if run.get("status") != "done"
                 else "no final metrics")
        else:
            results[b["id"]] = finals
    ranking = wi.rank(results, parent_finals, methods, d["noise"], errors=errors)
    by_branch = {b["id"]: b for b in d["branches"]}
    for r in ranking:
        e = exps.get(r["id"])
        r.update(key=by_branch[r["id"]]["key"], value=by_branch[r["id"]]["value"],
                 experiment_id=e["id"] if e else None)
        if not e:
            continue
        cfg = {**(e.get("config") or {})}
        cfg["whatif"] = {**cfg.get("whatif", {}), "decision": r["decision"], "reason": r["reason"],
                         "effect": r.get("effect"), "score": r.get("score"), "model": r.get("model")}
        patch = {"config": cfg}
        if r["decision"] == "pruned":
            patch.update(status="pruned", pruned_reason=r["reason"])
            emit(ctx.db, "branch_pruned", f"what-if {r['id']} ({r['key']}={json.dumps(r['value'])}) pruned",
                 r["reason"], project_id=ctx.pid, task_id=ctx.task["id"], data={"experiment_id": e["id"]})
        ctx.db.table("experiments").update(patch).eq("id", e["id"]).execute()
    top = next((r for r in ranking if r["decision"] == "extend"), None)
    extend = None
    if top:
        b = by_branch[top["id"]]
        if not d.get("parent_full_cmd"):
            raise StepError("the what-if output has no parent_full_cmd to extend the branch with")
        extend = {"branch_id": b["id"], "key": b["key"], "value": b["value"], "reason": top["reason"],
                  "smoke_experiment_id": top["experiment_id"], "cwd": b["cwd"], "scale": "full",
                  "cmd": wi.branch_cmd(wi.with_data_dir(d["parent_full_cmd"], data_dir_rel(b["cwd"])), b["key"],
                                       b["value"]),
                  "experiment": {**b["experiment"],
                                 "label": f"what-if {b['id']}: {b['key']}={json.dumps(b['value'])} (full)",
                                 "config": {**b["experiment"]["config"], "scale": "full"}}}
    refresh_why(ctx, d["parent_experiment_id"])  # the parent's settings rows gain the branches' smoke effects
    emit(ctx.db, "whatif_ranked",
         f"what-if ranked: extend {top['id'] if top else 'none'}; pruned "
         f"{', '.join(r['id'] for r in ranking if r['decision'] == 'pruned') or 'none'}",
         f"code: |effect on {', '.join(methods)}| / noise {d['noise']:g} ({d.get('noise_source')}) against the parent "
         "smoke run; extending needs approval", project_id=ctx.pid, task_id=ctx.task["id"],
         data={"ranking": ranking, "extend": extend})
    return {"outcome": "passed", "agent_status": "skipped", "tokens": 0, "cpu_s": 0.0, "error": None,
            "answer": "; ".join(f"{r['id']} {r['decision']}: {r['reason']}" for r in ranking),
            "ranking": ranking, "extend": extend, "whatif_task_id": tid,
            "experiment_id": d["parent_experiment_id"]}


HANDLERS = {"design_experiment": h_design, "write_code": h_write_code, "setup_env": h_setup_env,
            "budget": h_budget, "design_whatif": h_design_whatif, "debug": h_debug, "compare": h_grade, "explain_diff": h_grade,
            **{c: h_paper for c in PAPER_CAPS}}
