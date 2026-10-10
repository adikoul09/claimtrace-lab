"""Plan (SPEC §3.2): one LLM call turns the goal, the paper summary and matching lessons into ordered steps, each with
the capability it needs, instructions, an acceptance check, a budget and the agent it chooses. Code then checks the
plan: capabilities come from the registry, a reproduction follows REPRO_ORDER exactly (docs/CONTRACTS.md §2), budgets
are clipped to the project cap. A rejected plan goes back to the LLM once, with the reason."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

from pydantic import ValidationError

from lab.schemas import CAPABILITIES, PLAN_SCHEMA, PlanStep

MAX_STEPS = 12
LLM_AGENT = "controller"  # cache folder and llm_calls context for the controller's own calls
PLAN_ATTEMPTS = 2
# One slot per step; a slot lists the capabilities allowed there (run steps as run:<scale>).
REPRO_ORDER = (("read_paper", "extract_claims"), ("design_experiment",), ("write_code",), ("setup_env",),
               ("run:smoke",), ("budget",), ("run:full",), ("compare", "explain_diff"), ("write_report",))


def slot_key(step: dict) -> str:
    cap = step.get("capability")
    return f"run:{step.get('scale')}" if cap == "run" else str(cap)


def order_problem(raw_steps: list[dict], order=REPRO_ORDER) -> Optional[str]:
    keys = [slot_key(s) for s in raw_steps]
    want = " → ".join("/".join(slot) for slot in order)
    if len(keys) != len(order):
        return f"wrong order: {len(keys)} steps ({' → '.join(keys)}), the reproduction order has {len(order)}: {want}"
    for n, (k, slot) in enumerate(zip(keys, order), 1):
        if k not in slot:
            return f"wrong order: step {n} is {k}, expected {'/'.join(slot)}; the order is {want}"
    return None


class PlanError(ValueError):
    pass


@dataclass
class CheckedPlan:
    steps: list[PlanStep]
    reason: str
    dropped: list[str] = field(default_factory=list)  # steps removed by code, each with why
    notes: list[str] = field(default_factory=list)    # changes code made to kept steps


def check_plan(raw: dict, budget_cpu_min: int, order=REPRO_ORDER) -> CheckedPlan:
    """order=None checks steps one by one only (no reproduction order)."""
    if order is not None:
        problem = order_problem(raw.get("steps") or [], order)
        if problem:
            raise PlanError(problem)
    cap_s = int(budget_cpu_min) * 60
    steps, dropped, notes = [], [], []
    for i, s in enumerate(raw.get("steps") or [], 1):
        label = f"step {i} ({(s.get('title') or '?')[:60]})"
        if s.get("capability") not in CAPABILITIES:
            dropped.append(f"{label}: capability {s.get('capability')!r} is not in the registry")
            continue
        try:
            st = PlanStep(**s)
        except ValidationError as e:
            dropped.append(f"{label}: {e.errors()[0]['loc']} {e.errors()[0]['msg']}")
            continue
        if st.capability == "run":
            if st.scale is None:
                st.scale = "smoke"
                notes.append(f"{label}: no scale given, so it runs as a smoke run")
        else:
            st.scale, st.cmd = None, None
        if st.budget_cpu_s > cap_s:
            notes.append(f"{label}: budget clipped from {st.budget_cpu_s} to {cap_s} CPU s (project cap)")
            st.budget_cpu_s = cap_s
        steps.append(st)
    if len(steps) > MAX_STEPS:
        notes.append(f"plan cut from {len(steps)} to {MAX_STEPS} steps")
        steps = steps[:MAX_STEPS]
    if not steps:
        raise PlanError("the plan has no valid steps: " + "; ".join(dropped or ["empty"]))
    return CheckedPlan(steps, str(raw.get("reason") or "").strip(), dropped, notes)


# ---- prompt -------------------------------------------------------------------------------------------------------

def arxiv_abstract(arxiv_id: str) -> tuple[Optional[str], Optional[str]]:
    """(title, abstract) from the arXiv metadata API; (None, None) if it cannot be reached."""
    import httpx

    try:
        r = httpx.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id}, timeout=20,
                      follow_redirects=True)
        r.raise_for_status()
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = ET.fromstring(r.text).find("a:entry", ns)
        get = lambda tag: " ".join((entry.findtext(f"a:{tag}", "", ns) or "").split()) or None  # noqa: E731
        return (get("title"), get("summary")) if entry is not None else (None, None)
    except Exception:
        return None, None


def paper_summary(project: dict, paper: Optional[dict], abstract: Optional[str]) -> str:
    lines = [f"arXiv {project.get('arxiv_id') or '?'}: {(paper or {}).get('title') or project.get('title')}"]
    if project.get("repo_url"):
        lines.append(f"Code repository: {project['repo_url']}")
    claims = (paper or {}).get("claims") or []
    if claims:
        lines.append("Claims already extracted (checked by code):")
        lines += [f"- {c.get('metric')} = {c.get('value')} {c.get('unit') or ''} ({c.get('whose')}): "
                  f"{(c.get('quote') or '')[:120]}" for c in claims[:12]]
    elif abstract:
        lines.append(f"Abstract: {abstract}")
    else:
        lines.append("(the paper has not been read yet)")
    return "\n".join(lines)


def build_prompt(project: dict, paper: Optional[dict], lessons: list[dict], agents: list[dict],
                 abstract: Optional[str] = None, scores: Optional[dict] = None) -> str:
    team = {c: [a["name"] + (f" (rolling reward {scores[a['id']]:.2f})" if a.get("id") in (scores or {}) else "")
                for a in agents if a.get("status") == "active" and c in (a.get("capabilities") or [])]
            for c in CAPABILITIES}
    team_lines = "\n".join(f"- {c}: {', '.join(n) if n else '(no agent yet; one is spawned if needed)'}"
                           for c, n in team.items())
    lesson_lines = "\n".join(f"- [{l['id']}] ({l['kind']}) {l['text']}" for l in lessons) or "- (none match)"
    return f"""Goal: reproduce the key result of this paper on CPU, within {project.get('budget_cpu_min') or 20} \
CPU-minutes in total.

Paper:
{paper_summary(project, paper, abstract)}

Team (capability: agents):
{team_lines}

Lessons from earlier projects (apply them where they fit and say which in the reason):
{lesson_lines}

Write an ordered plan. Rules:
- Exactly these nine steps, in this order (code rejects any other order): {" → ".join("/".join(s) for s in REPRO_ORDER)}.
  read_paper extracts claims and settings; design_experiment picks the models and the margin; write_code writes
  train.py (every metric printed as `METRIC name=value step=N`); setup_env pins the requirements; run:smoke is 1 epoch
  on a small subset; budget picks epochs and seeds from the smoke timing; run:full is the budgeted run; compare grades
  ours against the paper; write_report writes the report.
- run steps: set scale ("smoke" or "full"); code builds the command.
- agent: choose one agent from the team list for each step (prefer a higher rolling reward) and say why in the reason.
- Do not plan debug steps; the controller adds them when something fails.
- budget_cpu_s per step; the run steps together must fit the budget.
- instructions must be self-contained: the agent sees only its step and the outputs of earlier steps.
- acceptance: one sentence that code can check (a file exists, a metric line was printed, claims include X).
- requires_approval: true only for a step a human should confirm before it spends the budget."""


def make_plan(llm, project: dict, paper: Optional[dict], lessons: list[dict], agents: list[dict], *,
              task_id=None, abstract: Optional[str] = None, scores: Optional[dict] = None, extra: str = ""):
    """(CheckedPlan, llm Response). A plan code rejects goes back once with the reason. Raises PlanError or the
    LLM's error."""
    from lab.llm import Request

    prompt = build_prompt(project, paper, lessons, agents, abstract, scores) + extra
    for attempt in range(1, PLAN_ATTEMPTS + 1):
        resp = llm.call(Request(agent=LLM_AGENT, system="You are the planner of an AI research team.", prompt=prompt,
                                schema=PLAN_SCHEMA, model="smart"), task_id=task_id)
        raw = resp.output if isinstance(resp.output, dict) else {}
        try:
            return check_plan(raw, project.get("budget_cpu_min") or 20), resp
        except PlanError as e:
            if attempt == PLAN_ATTEMPTS:
                raise
            prompt += (f"\n\nYour previous plan was rejected by code: {e}\nReply with a corrected plan that "
                       f"follows the rules.")


STEP_SCHEMA = {"type": "object",
               "properties": {"reason": {"type": "string", "description": "one or two sentences: what changed and why"},
                              "step": PLAN_SCHEMA["properties"]["steps"]["items"]},
               "required": ["reason", "step"]}


def replan_step(llm, project: dict, steps: list[PlanStep], i: int, note: str, *, task_id=None):
    """A researcher redirected step i (SPEC §9): the LLM rewrites that one step with the note; code keeps its slot
    (capability and scale) and its budget limit. (PlanStep, reason, llm Response); raises PlanError."""
    from lab.llm import Request

    old = steps[i]
    plan_lines = "\n".join(f"{n + 1}. {s.capability}{f' ({s.scale})' if s.scale else ''}: {s.title}"
                            for n, s in enumerate(steps))
    prompt = f"""The research plan:
{plan_lines}

Step {i + 1} as planned:
{old.model_dump_json(indent=1)}

A researcher redirected step {i + 1} with this note:
{note}

Rewrite step {i + 1} so it follows the note. Keep its capability ({old.capability}){f" and scale ({old.scale})" if old.scale else ""};
change the title, instructions, acceptance check, budget or agent as the note requires."""
    resp = llm.call(Request(agent=LLM_AGENT, system="You are the planner of an AI research team.", prompt=prompt,
                            schema=STEP_SCHEMA, model="smart"), task_id=task_id)
    out = resp.output if isinstance(resp.output, dict) else {}
    raw = out.get("step") or {}
    if slot_key(raw) != slot_key(old.model_dump()):
        raise PlanError(f"the redirected step must stay {slot_key(old.model_dump())}, got {slot_key(raw)}")
    checked = check_plan({"reason": out.get("reason"), "steps": [raw]}, project.get("budget_cpu_min") or 20,
                         order=None)
    return checked.steps[0], str(out.get("reason") or "").strip(), resp
