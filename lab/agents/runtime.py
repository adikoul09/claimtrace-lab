"""Generic agent runtime (SPEC §2): runs any agents row, i.e. its role_prompt plus the tools it is granted, in a loop.

Each step is one LLM call that must answer with a JSON action, either a tool call or "finish". Code executes the tool
and feeds the result back as the next step's observation. Code also enforces the agent's budget before every step:

  max_steps   LLM calls made
  max_tokens  tokens_in + tokens_out over all calls (replayed calls count their recorded tokens)
  max_cpu_s   CPU time of this process plus the wall time of tools that start a process (`run`, `make_env`)

Events: agent_started, agent_tool (one per tool call, the model's stated reason), then one of agent_finished,
agent_stopped (a budget limit, with the numbers) or agent_failed (the LLM call raised).

  python -m lab.agents.runtime --agent reader-v1 --dir runs/<id> --goal "Summarise notes.txt"
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from lab.agents.tools import RUNS, TOOL_DOCS, TOOL_PARAMS, ToolBox, ToolError
from lab.db import ROOT, client, emit
from lab.llm import LLM, Request

cpu_clock = time.process_time
PROCESS_TOOLS = ("run", "make_env")
OBS_IN_PROMPT = 2_000  # earlier observations are cut to this in the prompt; the latest is shown in full
OBS_TIGHT = 300  # ...and to this when the prompt would pass MAX_PROMPT_BYTES
MAX_PROMPT_BYTES = 36_000  # with the system prompt, every request stays under 40 KB
AGENT_MAX_OUTPUT = 4_000  # the gateway's output cap incl. reasoning; at the default the model ran out before answering


@dataclass
class RunResult:
    status: str                       # finished | stopped | failed
    answer: str | None
    reason: str
    steps: int
    tokens: int
    cpu_s: float
    transcript: list[dict] = field(default_factory=list)


def action_schema(tools: list[str]) -> dict:
    params = {k: v for t in tools for k, v in TOOL_PARAMS[t].items()}
    return {"type": "object",
            "properties": {"action": {"type": "string", "enum": [*tools, "finish"]},
                           "args": {"type": "object", "properties": params,
                                    "description": "the arguments of the chosen tool only"},
                           "reason": {"type": "string", "description": "one line: why this step"},
                           "answer": {"type": "string", "description": "the final answer, with action finish"}},
            "required": ["action", "reason"]}


def system_prompt(agent: dict) -> str:
    tools = "\n".join(f"- {TOOL_DOCS[t]}" for t in agent["tools"]) or "- (none)"
    return (f"{agent['role_prompt']}\n\n"
            f"You work in steps. Each reply is one JSON object: either a tool call "
            f'{{"action": <tool>, "args": {{...}}, "reason": <one line>}} or, when you are done, '
            f'{{"action": "finish", "answer": <your answer>, "reason": <one line>}}.\n'
            f"Paths are relative to your run directory. Your tools:\n{tools}")


def step_prompt(goal: str, transcript: list[dict]) -> str:
    """The step's prompt, under MAX_PROMPT_BYTES (paper text per request stays under 40 KB with the system prompt):
    earlier observations are cut to OBS_IN_PROMPT, then harder, then the latest one is cut to fit."""
    def build(older: int, latest: int | None) -> str:
        parts = [f"Task:\n{goal}"]
        for i, t in enumerate(transcript):
            obs, cap = t["observation"], older if i < len(transcript) - 1 else latest
            if cap is not None and len(obs) > cap:
                obs = obs[:cap] + " [cut]"
            parts.append(f"Step {t['step']}: {t['action']} {json.dumps(t['args'], ensure_ascii=False)}\n"
                         f"Result:\n{obs}")
        parts.append("Reply with the next action as JSON.")
        return "\n\n".join(parts)

    size = lambda text: len(text.encode("utf-8"))  # noqa: E731
    prompt = build(OBS_IN_PROMPT, None)
    if size(prompt) <= MAX_PROMPT_BYTES:
        return prompt
    prompt = build(OBS_TIGHT, None)
    if size(prompt) <= MAX_PROMPT_BYTES or not transcript:
        return prompt
    over = size(prompt) - MAX_PROMPT_BYTES
    latest = max(0, len(transcript[-1]["observation"]) - over - 200)
    return build(OBS_TIGHT, latest)


def short(args: dict, n: int = 120) -> str:
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def run_agent(agent: dict, goal: str, workdir: Path, *, db=None, llm: LLM | None = None, task_id=None,
              project_id=None, runs_root: Path = RUNS, model: str = "fast") -> RunResult:
    db = db if db is not None else client()
    llm = llm or LLM(db=db)
    budget = agent["budget"]
    max_steps, max_tokens, max_cpu_s = budget["max_steps"], budget["max_tokens"], budget["max_cpu_s"]
    name, agent_id = agent["name"], agent.get("id")
    box = ToolBox(workdir, agent["tools"], runs_root=runs_root, db=db, project_id=project_id, agent_id=agent_id,
                  task_id=task_id)
    system, schema = system_prompt(agent), action_schema(agent["tools"])
    ctx = {"project_id": project_id, "agent_id": agent_id, "task_id": task_id}

    emit(db, "agent_started", f"{name} started: {goal[:200]}",
         f"budget: {max_steps} steps, {max_tokens} tokens, {max_cpu_s} CPU s; tools {agent['tools']}",
         data={"workdir": box.workdir.relative_to(ROOT).as_posix() if box.workdir.is_relative_to(ROOT) else None},
         **ctx)
    c0, child_s = cpu_clock(), 0.0
    steps = tokens = 0
    transcript: list[dict] = []

    def result(status, answer, reason, type_, message):
        cpu = round(cpu_clock() - c0 + child_s, 1)
        emit(db, type_, message, reason, data={"steps": steps, "tokens": tokens, "cpu_s": cpu}, **ctx)
        return RunResult(status, answer, reason, steps, tokens, cpu, transcript)

    while True:
        cpu = cpu_clock() - c0 + child_s
        limit = (f"max_steps reached: {steps} of {max_steps} steps used" if steps >= max_steps else
                 f"max_tokens reached: {tokens} of {max_tokens} tokens used" if tokens >= max_tokens else
                 f"max_cpu_s reached: {cpu:.1f} of {max_cpu_s} CPU s used" if cpu >= max_cpu_s else None)
        if limit:
            return result("stopped", None, limit, "agent_stopped", f"{name} stopped by its budget")

        try:
            resp = llm.call(Request(agent=name, system=system, prompt=step_prompt(goal, transcript), schema=schema,
                                    model=model, max_output=AGENT_MAX_OUTPUT), agent_id=agent_id, task_id=task_id)
        except Exception as e:
            return result("failed", None, f"LLM call failed: {type(e).__name__}: {e}"[:500], "agent_failed",
                          f"{name} failed")
        steps += 1
        tokens += resp.tokens_in + resp.tokens_out
        act = resp.output if isinstance(resp.output, dict) else {}
        action, args, why = act.get("action"), act.get("args") or {}, act.get("reason") or ""

        if action == "finish":
            answer = act.get("answer")
            if answer is not None and not isinstance(answer, str):  # a JSON object instead of text: keep it as JSON
                answer = json.dumps(answer, ensure_ascii=False)
            return result("finished", answer or "", why or "the agent returned its answer",
                          "agent_finished", f"{name} finished in {steps} steps")

        t0 = time.monotonic()
        try:
            if not action:
                raise ToolError("the reply had no action; answer with a JSON object as instructed")
            obs = box.call(action, args if isinstance(args, dict) else {})
        except ToolError as e:
            obs = f"error: {e}"
        if action in PROCESS_TOOLS:
            child_s += time.monotonic() - t0
        transcript.append({"step": steps, "action": action, "args": args, "reason": why, "observation": obs})
        emit(db, "agent_tool", f"{name}: {action} {short(args)}", why or "no reason given by the agent",
             data={"step": steps, "ok": not obs.startswith("error:")}, **ctx)


def load_agent(db, name: str) -> dict:
    rows = db.table("agents").select("*").eq("name", name).execute().data
    if not rows:
        raise SystemExit(f"no agent named {name!r}")
    return rows[0]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run one agent from the agents table")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--dir", required=True, help="run directory under runs/")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--task-id")
    ap.add_argument("--project-id")
    ap.add_argument("--model", default="fast")
    a = ap.parse_args(argv)
    db = client()
    res = run_agent(load_agent(db, a.agent), a.goal, ROOT / a.dir, db=db, task_id=a.task_id,
                    project_id=a.project_id, model=a.model)
    print(f"{res.status}: {res.reason} ({res.steps} steps, {res.tokens} tokens, {res.cpu_s} CPU s)")
    if res.answer:
        print(res.answer)


if __name__ == "__main__":
    main()
