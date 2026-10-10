"""Plan (SPEC §3.2): one LLM call turns the goal, the paper summary and matching lessons into ordered steps, each with
the capability it needs, instructions, an acceptance check and a budget. Code then checks the plan: capabilities come
from the registry, run steps get a scale, budgets are clipped to the project cap, and the step count is bounded."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

from pydantic import ValidationError

from lab.schemas import CAPABILITIES, PLAN_SCHEMA, PlanStep

MAX_STEPS = 12
LLM_AGENT = "controller"  # cache folder and llm_calls context for the controller's own calls


class PlanError(ValueError):
    pass


@dataclass
class CheckedPlan:
    steps: list[PlanStep]
    reason: str
    dropped: list[str] = field(default_factory=list)  # steps removed by code, each with why
    notes: list[str] = field(default_factory=list)    # changes code made to kept steps


def check_plan(raw: dict, budget_cpu_min: int) -> CheckedPlan:
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
                 abstract: Optional[str] = None) -> str:
    team = {c: [a["name"] for a in agents if a.get("status") == "active" and c in (a.get("capabilities") or [])]
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
- Each step uses exactly one capability from the team list and is done by one agent; steps run one after another.
- A typical reproduction reads the paper (claims and settings), designs the experiment at a scale that fits the \
budget, writes train.py (it prints every metric as `METRIC name=value step=N`), sets up the environment, does a smoke \
run, does the full run, compares with the paper and writes the report.
- run steps: set scale (smoke = 1 epoch on a small subset; full = the budgeted run) and cmd, the command run in the \
project folder, e.g. `python train.py --smoke`.
- Do not plan debug steps; the controller adds them when something fails.
- budget_cpu_s per step; the run steps together must fit the budget.
- instructions must be self-contained: the agent sees only its step.
- acceptance: one sentence that code can check (a file exists, a metric line was printed, claims include X).
- requires_approval: true only for a step a human should confirm before it spends the budget."""


def make_plan(llm, project: dict, paper: Optional[dict], lessons: list[dict], agents: list[dict], *,
              task_id=None, abstract: Optional[str] = None):
    """(CheckedPlan, llm Response). Raises PlanError or the LLM's error."""
    from lab.llm import Request

    resp = llm.call(Request(agent=LLM_AGENT, system="You are the planner of an AI research team.",
                            prompt=build_prompt(project, paper, lessons, agents, abstract), schema=PLAN_SCHEMA,
                            model="smart"), task_id=task_id)
    raw = resp.output if isinstance(resp.output, dict) else {}
    return check_plan(raw, project.get("budget_cpu_min") or 20), resp
