"""Read a run's stdout by code: metric lines and the error signature, each tied to its 1-based log line.

Metric lines have exactly one format (CLAUDE.md, SPEC §7.2):  METRIC name=value step=N
The traceback reader is ported from baseline/el01-auditor/el01/run/classify.py (last_traceback)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Optional

METRIC_RE = re.compile(r"^METRIC (?P<name>[A-Za-z_][\w.\-/]*)=(?P<value>\S+) step=(?P<step>-?\d+)\s*$")
TB_START = "Traceback (most recent call last):"
EXC_RE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(: ?(?P<msg>.*))?$")
MODULE_RE = re.compile(r"No module named '(?P<mod>[^'.]+)")
MISSING_FILE_RE = re.compile(r"No such file or directory: ['\"](?P<path>.+?)['\"]")


@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    step: int
    log_line: int

    def as_row(self, experiment_id: str) -> dict:
        return {"experiment_id": experiment_id, "name": self.name, "value": self.value,
                "step": self.step, "log_line": self.log_line}


def parse_metric(line: str, log_line: int) -> Optional[Metric]:
    """The metric on this line, or None. Non-finite values are rejected (they cannot be stored as numbers)."""
    m = METRIC_RE.match(line)
    if not m:
        return None
    try:
        value = float(m["value"])
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return Metric(m["name"], value, int(m["step"]), log_line)


@dataclass(frozen=True)
class Divergence:
    name: str
    raw: str          # the value as printed: nan, inf, -inf, ...
    step: int
    log_line: int


def parse_divergence(line: str, log_line: int) -> Optional[Divergence]:
    """A METRIC line whose value is NaN or infinite (a diverged run), or None."""
    m = METRIC_RE.match(line)
    if not m:
        return None
    try:
        value = float(m["value"])
    except ValueError:
        return None
    return None if math.isfinite(value) else Divergence(m["name"], m["value"], int(m["step"]), log_line)


def parse_log(lines: Iterable[str]) -> list[Metric]:
    return [m for i, l in enumerate(lines, 1) if (m := parse_metric(l, i))]


@dataclass(frozen=True)
class Traceback:
    exc_type: str
    message: str
    log_line: int     # line of the exception message
    start_line: int   # line of "Traceback (most recent call last):"


def last_traceback(lines: list[str]) -> Optional[Traceback]:
    """The last traceback in the log (with chained exceptions, the one raised last)."""
    starts = [i for i, l in enumerate(lines) if l.strip() == TB_START]
    if not starts:
        return None
    for i in range(starts[-1] + 1, len(lines)):
        l = lines[i]
        if l and not l[0].isspace():
            e = EXC_RE.match(l.strip())
            if e:
                return Traceback(e["type"], (e["msg"] or "").strip(), i + 1, starts[-1] + 1)
            return Traceback("Unknown", l.strip(), i + 1, starts[-1] + 1)
    return Traceback("Unknown", "", len(lines), starts[-1] + 1)


def error_signature(lines: list[str]) -> Optional[str]:
    """A stable tag for memory lookups (SPEC §6), e.g. `ModuleNotFoundError:torchvision`; None without a traceback."""
    tb = last_traceback(lines)
    if tb is None:
        return None
    exc = tb.exc_type.rsplit(".", 1)[-1]
    if m := MODULE_RE.search(tb.message):
        return f"{exc}:{m['mod']}"
    if m := MISSING_FILE_RE.search(tb.message):
        return f"{exc}:{PurePosixPath(m['path'].replace(chr(92), '/')).name}"
    return exc
