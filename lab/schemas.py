"""Shared shapes between the controller, the agents and the executors.

Task input contract (tasks.input, written by the controller for every plan step):
  goal            what the agent must do (the plan step's instructions)
  title           a short label for the UI
  step, of        0-based index of this step and the number of steps in the plan
  plan_task_id    the `plan` task that produced this step (also tasks.parent_task_id)
  workdir         the project's run folder, runs/<project_id> (relative to the repo root)
  budget          {max_cpu_s, max_tokens}: CPU from the plan (clipped to the project cap by code), tokens from the
                  assigned agent's own budget
  scale           run steps only: "smoke" or "full"
  cmd, cwd, timeout_s   run steps only: what the executor worker runs (cwd = workdir; timeout has a floor)
tasks.acceptance holds {"text": <acceptance check in words>}; code turns it into an outcome when the task is scored.

Task output fields the reward reads (lab/controller/reward.py), written by whoever ran the task:
  outcome         passed | partial | failed, when code checked the acceptance (wins over everything else)
  agent_status    finished | stopped | failed, the agent runtime's RunResult.status (stopped scores partial)
  metrics         run tasks: number of METRIC lines stored (0 scores partial)
Tokens come from llm_calls rows with the task's id. Feedback (👍/👎) is an events row: type 'feedback', task_id,
data {"value": "up" | "down"}; the controller rescores the task when it sees a newer one.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# SPEC §2.3. `plan` is not here: it is the controller's own work, never an agent's.
CAPABILITIES = ("read_paper", "extract_claims", "extract_settings", "design_experiment", "budget", "write_code",
                "setup_env", "run", "debug", "compare", "explain_diff", "design_whatif", "write_report",
                "write_notes")

Scale = Literal["smoke", "full"]


class PlanStep(BaseModel):
    capability: str
    title: str
    instructions: str
    acceptance: str
    budget_cpu_s: int = Field(ge=1)
    scale: Optional[Scale] = None
    cmd: Optional[str] = None
    requires_approval: bool = False


# What the planner LLM must return (JSON schema for structured output; kept flat for Gemini).
_S, _I, _B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string", "description": "two or three sentences: why this plan, and which lessons it uses"},
        "steps": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "capability": {"type": "string", "enum": list(CAPABILITIES)},
                "title": _S,
                "instructions": {"type": "string", "description": "what the agent must do, self-contained"},
                "acceptance": {"type": "string", "description": "how code can check the step succeeded"},
                "budget_cpu_s": _I,
                "scale": {"type": "string", "enum": ["smoke", "full"], "description": "run steps only"},
                "cmd": {"type": "string", "description": "run steps only: the command, run in the project folder"},
                "requires_approval": _B,
            },
            "required": ["capability", "title", "instructions", "acceptance", "budget_cpu_s"],
        }},
    },
    "required": ["reason", "steps"],
}
