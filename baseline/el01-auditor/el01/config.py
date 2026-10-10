"""Paths and settings. No module hard-codes a path; everything goes through `Paths`."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parent.parent  # the el01-auditor checkout (editable install)


@dataclass(frozen=True)
class Paths:
    root: Path         # project root
    spike: Path        # inputs/spike-matchdg (read-only)
    logs: Path         # extracted spike logs: workspace/spike/logs/<run>/<file>
    audit: Path        # audits/matchdg: where grade-spike writes metrics/ and grades*.json
    regress_out: Path  # workspace/regress: last regression report (timestamped, not committed)

    @classmethod
    def make(cls, root: Path | None = None, spike: Path | None = None, logs: Path | None = None,
             audit: Path | None = None) -> "Paths":
        root = Path(root or ROOT).resolve()
        return cls(root=root,
                   spike=Path(spike or root / "inputs" / "spike-matchdg").resolve(),
                   logs=Path(logs or root / "workspace" / "spike" / "logs").resolve(),
                   audit=Path(audit or root / "audits" / "matchdg").resolve(),
                   regress_out=root / "workspace" / "regress")

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def repos(self) -> Path:
        return self.workspace / "repos"

    @property
    def envs(self) -> Path:
        return self.workspace / "envs"

    @property
    def worktrees(self) -> Path:
        return self.workspace / "worktrees"

    @property
    def audits(self) -> Path:
        return self.root / "audits"

    def audit_dir(self, audit_id: str) -> Path:
        return self.audits / audit_id

    @property
    def golden(self) -> Path:
        return self.spike / "golden"

    @property
    def spike_metrics(self) -> Path:
        return self.spike / "metrics"

    @property
    def extraction_outputs(self) -> Path:
        return self.spike / "extraction" / "outputs"

    def cite(self, p: Path | str) -> str:
        """The machine-independent name a number cites for its log: `logs/<run>/<file>`."""
        return "logs/" + Path(p).resolve().relative_to(self.logs).as_posix()

    def resolve_cite(self, cited: str) -> Path:
        """Inverse of `cite`: the file on this machine."""
        if not cited.startswith("logs/"):
            raise ValueError(f"not a cited log path: {cited!r}")
        return self.logs / cited[len("logs/"):]


def default_jobs() -> int:
    """Default parallel jobs: max(1, cores - 2) (MASTER_PROMPT section 5)."""
    return max(1, (os.cpu_count() or 1) - 2)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metric(_Model):
    name: str
    unit: str = ""
    floor: float  # practical floor, in the metric's unit


class Target(_Model):
    table: str
    metric: Metric
    seeds: int


class Budget(_Model):
    max_parallel_jobs: Union[int, Literal["auto"]] = "auto"
    max_wall_minutes: float = 120

    @property
    def jobs(self) -> int:
        return default_jobs() if self.max_parallel_jobs == "auto" else max(1, int(self.max_parallel_jobs))


class Repo(_Model):
    url: str
    commit: str


class Paper(_Model):
    title: str
    pdf: Optional[str] = None
    supplement: Optional[str] = None


class LLM(_Model):
    backend: Literal["replay", "claude_cli", "anthropic_api"] = "replay"
    model: str = "sonnet"


class EnvSpec(_Model):
    """What the environment builder needs beyond the repo itself."""
    entry_points: list[str] = []        # scripts the audit runs, relative to the repo root; the import scan starts here
    python: Optional[str] = None        # override, e.g. "3.9"
    requirements: str = "requirements.txt"
    extra: list[str] = []               # extra requirement lines, each logged as an addition


class Smoke(_Model):
    """The run-as-shipped command: one cheap run of one claim (Phase 2). Argv lists; `python` is the env's interpreter."""
    data: Optional[list[str]] = None    # data generation, run first in its own run directory
    name: str = "smoke"
    command: list[str]
    seeds: int = 1
    eval: Optional[list[str]] = None    # evaluation command run after `command` in the same run directory (Phase 3)
    eval_name: str = "eval"


class LinkSpec(_Model):
    """Claim-to-command linking (Phase 4): how dry runs shorten a command, and what data steps may do."""
    epochs_option: Optional[str] = "--epochs"   # dry runs set it to 1 (earlier steps of a multi-step cell: the ladder)
    runs_option: Optional[str] = "--n_runs"     # dry runs set it to 1
    dry_run_epochs: list[int] = [1, 5]          # values tried, in order, for the steps before a cell's last step
    data_network: bool = False                  # data steps may download (rule 11: a separate fetch step); runs never
    max_calls_per_table: int = 2                # linker calls per table: the first answer, then answers to code's findings


class Ablation(_Model):
    """Diff-guided ablation (Phase 6): the baseline branch and what it already contains."""
    baseline: str                               # branch every hypothesis branch starts from (repairs + filled omissions)
    baseline_findings: list[str] = []           # findings the baseline already fills (no branch of their own)
    llm_cap_usd: Optional[float] = None         # live spend allowed for this phase's agent calls (llm_usage.jsonl)


class AuditConfig(_Model):
    id: str
    paper: Paper
    repo: Repo
    targets: list[Target]
    budget: Budget = Budget()
    llm: LLM = LLM()
    import_from: Optional[str] = None
    env: EnvSpec = EnvSpec()
    smoke: Optional[Smoke] = None
    link: LinkSpec = LinkSpec()
    ablation: Optional[Ablation] = None

    @classmethod
    def load(cls, path: Path) -> "AuditConfig":
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    @classmethod
    def for_audit(cls, paths: Paths, audit_id: str) -> "AuditConfig":
        cfg = cls.load(paths.audit_dir(audit_id) / "audit.yaml")
        if cfg.id != audit_id:
            raise ValueError(f"audits/{audit_id}/audit.yaml has id {cfg.id!r}")
        return cfg
