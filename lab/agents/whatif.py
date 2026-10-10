"""What-if fan-out (SPEC §7.4): one-change branches of a reproduction, smoke-tested, ranked and pruned by code.

  design_whatif  the Designer answers a researcher's question with 3-4 branches {key, value, reason}; code checks
                 that each changes exactly one key of the parent run's CONFIG (train.py's printed hyperparameters) and
                 gives each a smoke command: the parent's smoke command plus `--set key=<json value>`
  rank           after the branches' smoke runs: effect = branch minus parent smoke value of the method's model(s);
                 score = |effect| / noise, noise = the parent's seed spread (sd), or the declared margin with one seed.
                 The top branch is extended (behind approval); branches inside noise are pruned; if none is, the one
                 with the smallest effect is; a failed smoke run is pruned with its error. Every decision has a reason.

The controller creates the tasks (docs/CONTRACTS.md); this module decides what they contain."""
from __future__ import annotations

import json
import shlex
import statistics

from lab.agents.reproduce import StepError

MIN_BRANCHES, MAX_BRANCHES = 3, 4
CONFIG_PREFIX = "CONFIG "


def parse_config(lines: list[str]) -> tuple[dict, int]:
    """The first `CONFIG {json}` line of a run's log, and its 1-based line number."""
    for i, line in enumerate(lines, 1):
        if line.startswith(CONFIG_PREFIX):
            try:
                cfg = json.loads(line[len(CONFIG_PREFIX):])
            except json.JSONDecodeError as e:
                raise StepError(f"the CONFIG line {i} is not JSON: {e}") from None
            if not isinstance(cfg, dict):
                raise StepError(f"the CONFIG line {i} is not a JSON object")
            return cfg, i
    raise StepError("the parent run printed no CONFIG line, so its settings are unknown")


def flatten(cfg: dict, prefix: str = "") -> dict:
    """Nested settings as dotted keys: {"lr": {"teacher": 0.03}} -> {"lr.teacher": 0.03}."""
    out = {}
    for k, v in cfg.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def check_branches(branches: list[dict], parent_config: dict) -> list[dict]:
    """Each branch changes exactly one existing key of the parent's flattened CONFIG to a different value."""
    flat = flatten(parent_config)
    if not MIN_BRANCHES <= len(branches) <= MAX_BRANCHES:
        raise StepError(f"propose 3 to 4 branches, not {len(branches)}")
    problems, seen, out = [], set(), []
    for i, b in enumerate(branches, 1):
        key, value = b.get("key"), b.get("value")
        if not isinstance(key, str):
            problems.append(f"branch {i}: change exactly one setting (key must be one string, got {key!r})")
            continue
        if key not in flat:
            problems.append(f"branch {i}: {key!r} is not in the parent CONFIG (one of: {', '.join(sorted(flat))})")
            continue
        if value == flat[key]:
            problems.append(f"branch {i}: {key}={value!r} does not change the parent value")
            continue
        sig = (key, json.dumps(value, sort_keys=True))
        if sig in seen:
            problems.append(f"branch {i}: {key}={value!r} is proposed twice")
            continue
        seen.add(sig)
        out.append({"id": f"b{len(out) + 1}", "key": key, "value": value, "parent_value": flat[key],
                    "reason": b.get("reason") or "", "config": {**flat, key: value}})
    if problems:
        raise StepError("; ".join(problems))
    return out


def branch_cmd(base_cmd: str, key: str, value) -> str:
    return f"{base_cmd} --set {shlex.quote(f'{key}={json.dumps(value)}')}"


def noise(parent_values: list[float], margin: float | None) -> tuple[float, str]:
    """The noise scale for effects: sd over the parent's seeds, or the declared margin when there is one seed."""
    if len(parent_values) >= 2:
        sd = statistics.stdev(parent_values)
        return round(sd, 4), f"sd over {len(parent_values)} seeds"
    if margin is None:
        raise StepError("one seed and no declared margin: there is no noise scale to rank against")
    return margin, f"margin {margin:g} (1 seed: no seed spread to measure)"


def rank(results: dict, parent_finals: dict, method_models: list[str], noise: float,
         errors: dict | None = None) -> list[dict]:
    """results: branch id -> {model: final value} (None when the smoke run failed). Returns one row per branch with
    effect, score, decision (extend | kept | pruned) and reason."""
    errors = errors or {}
    rows = []
    for bid, finals in results.items():
        if finals is None:
            rows.append({"id": bid, "effect": None, "score": None, "decision": "pruned",
                         "reason": f"smoke run failed: {errors.get(bid) or 'no final metrics'}"})
            continue
        missing = [m for m in method_models if m not in finals or m not in parent_finals]
        if missing:
            rows.append({"id": bid, "effect": None, "score": None, "decision": "pruned",
                         "reason": f"smoke run printed no final value for {', '.join(missing)}"})
            continue
        effects = {m: round(finals[m] - parent_finals[m], 4) for m in method_models}
        model, effect = max(effects.items(), key=lambda kv: abs(kv[1]))
        rows.append({"id": bid, "model": model, "effect": effect, "effects": effects,
                     "score": round(abs(effect) / noise, 4) if noise else None, "decision": None, "reason": None})
    ok = sorted((r for r in rows if r["decision"] is None), key=lambda r: -(r["score"] or 0))
    if ok:
        top = ok[0]
        inside = top["score"] is not None and top["score"] <= 1
        top["decision"] = "extend"
        top["reason"] = (f"largest effect: {top['model']} {top['effect']:+g} ({top['score']:g}× noise {noise:g})"
                         + ("; still inside noise, so the full run tests whether it is real" if inside else ""))
        for r in ok[1:]:
            if r["score"] is not None and r["score"] <= 1:
                r["decision"] = "pruned"
                r["reason"] = f"effect inside noise: |{r['effect']:g}| ≤ {noise:g} on {r['model']}"
        if not any(r["decision"] == "pruned" for r in rows) and len(ok) > 1:
            low = ok[-1]
            low["decision"] = "pruned"
            low["reason"] = f"smallest effect: {low['model']} {low['effect']:+g} ({low['score']:g}× noise {noise:g})"
        for r in ok[1:]:
            if r["decision"] is None:
                r["decision"] = "kept"
                r["reason"] = f"{r['model']} {r['effect']:+g} ({r['score']:g}× noise {noise:g}); not the largest"
    return rows


def with_data_dir(cmd: str, data_rel: str) -> str:
    """The same command with --data-dir pointing at data/ from another run folder (a branch runs in its own)."""
    argv = shlex.split(cmd)
    if "--data-dir" in argv:
        i = argv.index("--data-dir")
        if i + 1 < len(argv):
            argv[i + 1] = data_rel
    else:
        argv += ["--data-dir", data_rel]
    return shlex.join(argv)


def whatif_goal(question: str, parent_config: dict, experiment: str | None) -> str:
    flat = flatten(parent_config)
    lines = "\n".join(f"- {k} = {json.dumps(v)}" for k, v in sorted(flat.items()))
    return (f"A researcher asks about the reproduction of: {experiment or 'the paper'}\nQuestion: {question}\n\n"
            "Propose 3 to 4 what-if branches that would answer it. Each branch changes EXACTLY ONE setting below to "
            "one new value (code rejects anything else); everything else stays as in the parent run. Prefer the "
            "changes most likely to explain or test the question.\n\nThe parent run's settings (CONFIG keys):\n"
            f"{lines}\n\nFinish with answer = a JSON object: "
            '{"branches": [{"key": "<one key from the list>", "value": <new JSON value>, '
            '"reason": "<what this branch tests>"}]}')
