"""Parser specs: how to read one claim cell's number out of a log, proposed by the linker, applied by code.

A spec names the step whose log holds the number and a line regex (`re.search` on each line):
  value_group       the group that is the number; `sd_group` optionally its spread
  run_start_regex   lines matching it start a new run block (group 1, if any, is the run's label); lines before the
                    first one are ignored. Without it the whole log is one block.
  key_group/value   keep only matches whose `key_group` equals `key_value` (e.g. one domain of a per-domain listing)
  per_epoch / count expected matches per block: one per epoch of the command (`--epochs`), or `count`
The number of a block is its last match. Every value keeps its log and line number (rule 3). `validate` checks a spec
on a short log: one block per run (`--n_runs`), the declared match count in every block, a number in every match."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

FIELDS = ("name", "step", "line_regex", "value_group", "sd_group", "run_start_regex", "key_group", "key_value",
          "per_epoch", "count")


class SpecError(ValueError):
    pass


def compile_spec(spec: dict) -> tuple[re.Pattern, Optional[re.Pattern]]:
    try:
        line = re.compile(spec["line_regex"])
        start = re.compile(spec["run_start_regex"]) if spec.get("run_start_regex") else None
    except re.error as e:
        raise SpecError(f"parser {spec.get('name')!r}: bad regex: {e}")
    for g in ("value_group", "sd_group", "key_group"):
        if spec.get(g) is not None and not (1 <= int(spec[g]) <= line.groups):
            raise SpecError(f"parser {spec.get('name')!r}: {g} {spec[g]} but line_regex has {line.groups} groups")
    if spec.get("key_group") is not None and spec.get("key_value") is None:
        raise SpecError(f"parser {spec.get('name')!r}: key_group without key_value")
    return line, start


def _num(s: str) -> float:
    return float(s)


def apply(spec: dict, log: Path, cite: Callable[[Path], str] = str) -> dict:
    """{"log", "blocks": [{"run", "start_line", "matches", "value", "sd", "line"}]}; value/sd/line of the last match."""
    line_re, start_re = compile_spec(spec)
    vg, sg, kg = spec["value_group"], spec.get("sd_group"), spec.get("key_group")
    blocks: list[dict] = [] if start_re else [{"run": None, "start_line": None, "matches": 0, "value": None,
                                               "sd": None, "line": None}]
    for i, text in enumerate(Path(log).read_text(errors="replace").splitlines(), 1):
        if start_re is not None:
            m = start_re.search(text)
            if m:
                blocks.append({"run": m.group(1) if start_re.groups else str(len(blocks)), "start_line": i,
                               "matches": 0, "value": None, "sd": None, "line": None})
                continue
            if not blocks:
                continue
        m = line_re.search(text)
        if not m or (kg is not None and m.group(kg) != str(spec["key_value"])):
            continue
        b = blocks[-1]
        b["matches"] += 1
        try:
            b["value"] = _num(m.group(vg))
            b["sd"] = _num(m.group(sg)) if sg is not None and m.group(sg) is not None else None
        except (TypeError, ValueError):
            b.update(value=None, sd=None, bad=f"line {i}: group {vg} is {m.group(vg)!r}, not a number")
        b["line"] = i
    return {"log": cite(Path(log)), "blocks": blocks}


def expected_count(spec: dict, epochs: Optional[int]) -> Optional[int]:
    if spec.get("per_epoch"):
        return epochs
    return spec.get("count")


def validate(spec: dict, log: Path, n_runs: Optional[int], epochs: Optional[int],
             cite: Callable[[Path], str] = str) -> dict:
    """Check a spec on a short log. Returns {"ok", "problems", "parsed"}."""
    problems = []
    try:
        parsed = apply(spec, log, cite)
    except SpecError as e:
        return {"ok": False, "problems": [str(e)], "parsed": None}
    blocks = parsed["blocks"]
    if spec.get("run_start_regex") and n_runs is not None and len(blocks) != n_runs:
        problems.append(f"{len(blocks)} run blocks, the command runs {n_runs}")
    want = expected_count(spec, epochs)
    for b in blocks:
        where = f"run {b['run']}" if b["run"] is not None else "the log"
        if want is not None and b["matches"] != want:
            problems.append(f"{where}: {b['matches']} matching lines, the spec expects {want}")
        if b.get("bad"):
            problems.append(f"{where}: {b['bad']}")
        elif b["value"] is None:
            problems.append(f"{where}: no value")
    if not blocks:
        problems.append("no run block")
    return {"ok": not problems, "problems": problems, "parsed": parsed}
