"""Analyst (SPEC §7.5): verdicts by code, then a plain-language explanation that may use only the table's numbers.

Verdicts, per target claim (absolute):
  Reproduced            |ours - paper| <= margin (declared on the experiment before the run)
  Partially reproduced  outside the margin, but every ordering the paper reports between this claim and the other
                        target claims of the same metric still holds in our numbers (e.g. distilled < hard-label)
  Not reproduced        otherwise
  Not runnable          the run failed or never printed the claim's final_<model> metric
Relative claims (each `method` claim vs each `baseline` claim of the same metric): the same rule on the gap; the
direction must hold for Reproduced or Partially reproduced. Fewer than 3 seeds: the label carries "(n seed)".

Seeds (HoO-B): a claim is graded on the mean over the project's finished, non-what-if experiments that map it with the
same config.cmd except --seed (the seed group); the row carries n, the sample SD and the values, and its label says
"(n seeds)". A method-vs-baseline claim whose two claims are mapped in different experiments (e.g. c3 distilled and
c2 hard-target) is graded across them, for groups whose cmd differs only by --seed and --set hidden_units.*: on the
seeds both groups ran (paired gaps, baseline minus method), the direction counts only if the mean gap exceeds
max(margin, SD of the paired gaps), else "Not reproduced (direction inside the noise)"; with fewer than 2 common seeds,
on the difference of the two group means.

Ported from baseline/el01-auditor/el01/grade/rules.py: the verdict vocabulary, margin = max(paper spread, floor) with
its source, and label(). Changed for Round 1: one or few seeds, so the margin rule replaces the Welch/TOST intervals
(no scipy); relations between claims replace the paired seed test.

The explanation's number check: every number in the text must equal a number in the grade tables (or their absolute
value), spelled at the table's precision. Text with any other number is rejected, never shown as the explanation.

  python -m lab.agents.analyst --experiment-id <id> [--claim-map teacher_test_errors=c7,...] [--reference <json>]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

from lab.db import client, emit

RULES = "SPEC §7.5 v1 (margin rule; relations between claims; ported vocabulary from Round 0 rules 2.1)"
MIN_SEEDS_FOR_NO_NOTE = 3
NUM_RE = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?(?![\w])|(?<![\w.])-?\d+(?:\.\d+)?%?(?![\w])")


def better(a: float, b: float, direction: str) -> bool:
    return a < b if direction == "lower_is_better" else a > b


def _same_kind(a: dict, b: dict) -> bool:
    return (a.get("metric"), a.get("unit"), a.get("direction")) == (b.get("metric"), b.get("unit"), b.get("direction"))


def _num(x) -> float | int:
    x = round(float(x), 4)
    return int(x) if x == int(x) else x


def label(v: dict, seeds: int) -> str:
    s = v["verdict"] + (f" ({v['size_note']})" if v.get("size_note") else "")
    return s + (f" ({seeds} seed{'s' if seeds != 1 else ''})" if seeds < MIN_SEEDS_FOR_NO_NOTE else "")


SEED_RE = re.compile(r"\s--seed\s+\d+")
SEED_VALUE_RE = re.compile(r"--seed\s+(\d+)")
HIDDEN_RE = re.compile(r"\s--set\s+hidden_units\.\w+=\S+")


def config_key(cfg: dict | None) -> str | None:
    """The run's command without its --seed: experiments with the same key differ only by seed."""
    cmd = (cfg or {}).get("cmd")
    return " ".join(SEED_RE.sub("", " " + cmd).split()) if cmd else None


def base_key(cfg: dict | None) -> str | None:
    """config_key without --set hidden_units.*: the hard-target net of the same size is comparable."""
    k = config_key(cfg)
    return " ".join(HIDDEN_RE.sub("", " " + k).split()) if k else None


def seed_group(exp: dict, exps: list[dict]) -> list[dict]:
    """exp and the finished, non-what-if experiments with the same config except the seed (in the given order)."""
    key = config_key(exp.get("config"))
    if key is None:
        return [exp]
    return [e for e in exps if e["id"] == exp["id"] or (
        e.get("status") == "done" and not (e.get("config") or {}).get("whatif")
        and config_key(e.get("config")) == key)]


def seed_of(cfg: dict | None) -> int | None:
    m = SEED_VALUE_RE.search((cfg or {}).get("cmd") or "")
    return int(m.group(1)) if m else None


def pool(values: list[float], seeds: list | None = None) -> dict:
    vals = [_num(v) for v in values]
    out = {"n": len(vals), "mean": _num(sum(vals) / len(vals)),
           "sd": _num(statistics.stdev(vals)) if len(vals) > 1 else None, "values": vals}
    if seeds is not None and len(seeds) == len(vals) and None not in seeds:
        out["by_seed"] = dict(zip(seeds, vals))
    return out


def paired_gaps(m: dict, b: dict, sign: int, margin) -> dict | None:
    """Gaps (baseline minus method, in the better direction) on the seeds both pools ran; None under 2 such seeds."""
    common = sorted(set(m.get("by_seed") or {}) & set(b.get("by_seed") or {}))
    if len(common) < 2:
        return None
    gaps = [_num(sign * (b["by_seed"][s] - m["by_seed"][s])) for s in common]
    mean, sd = _num(sum(gaps) / len(gaps)), _num(statistics.stdev(gaps))
    threshold = _num(max(float(margin), sd))
    return {"seeds": common, "gaps": gaps, "mean_gap": mean, "sd_gap": sd, "threshold": threshold,
            "beyond_noise": mean > threshold}


def _seeds_label(n: int) -> str:
    return f"({n} seed{'s' if n != 1 else ''})"


def annotate_seeds(g: dict, pooled: dict[str, dict]) -> None:
    """Mark the claim rows graded on a seed mean: n, SD, values, and a label that always says "(n seeds)"."""
    for r in g["claims"]:
        p = pooled.get(r["claim_id"])
        if not p or r.get("ours") is None:
            continue
        r.update(n_seeds=p["n"], sd=p["sd"], values=p["values"])
        r["label"] = r["verdict"] + (f" ({r['size_note']})" if r.get("size_note") else "") + " " + \
            _seeds_label(p["n"])


def cross_relative(claims: list[dict], mine: dict[str, dict], other: dict[str, dict], margin) -> list[dict]:
    """Method-vs-baseline claims whose two claims are pooled in different experiment groups (mine / other)."""
    by_id = {c["id"]: c for c in claims}
    both = {**other, **mine}
    out = []
    for m in (c for c in claims if c.get("whose") == "method" and c["id"] in both):
        for b in (c for c in claims if c.get("whose") == "baseline" and c["id"] in both and _same_kind(c, m)):
            if not ((m["id"] in mine and b["id"] in other) or (b["id"] in mine and m["id"] in other)):
                continue
            sign = 1 if m["direction"] == "lower_is_better" else -1
            paper_gap = _num(sign * (b["value"] - m["value"]))
            paired = paired_gaps(both[m["id"]], both[b["id"]], sign, margin)
            g = paired["mean_gap"] if paired else _num(sign * (both[b["id"]]["mean"] - both[m["id"]]["mean"]))
            r = {"claim": f"{m['id']} beats {b['id']}", "method": m["id"], "baseline": b["id"], "paper_gap": paper_gap,
                 "ours_gap": g, "margin": _num(margin), "size_note": None, "across": True, "paired": paired,
                 "n": {m["id"]: both[m["id"]]["n"], b["id"]: both[b["id"]]["n"]},
                 "means": {m["id"]: both[m["id"]]["mean"], b["id"]: both[b["id"]]["mean"]},
                 "sds": {m["id"]: both[m["id"]]["sd"], b["id"]: both[b["id"]]["sd"]}}
            noise = None
            if g <= 0:
                r["verdict"] = "Not reproduced"
            elif paired and not paired["beyond_noise"]:
                r["verdict"] = "Not reproduced"
                noise = (f"direction inside the noise: mean paired gap {g} <= max(margin {_num(margin)}, SD of the "
                         f"paired gaps {paired['sd_gap']})")
            elif abs(g - paper_gap) <= margin:
                r["verdict"] = "Reproduced"
            else:
                r.update(verdict="Partially reproduced",
                         size_note="gap smaller than reported" if g < paper_gap else "gap larger than reported")
            pair_txt = (f"paired on seeds {', '.join(str(x) for x in paired['seeds'])}: gaps "
                        f"{', '.join(str(x) for x in paired['gaps'])}, mean {paired['mean_gap']} ± {paired['sd_gap']}"
                        if paired else "group means (fewer than 2 common seeds)")
            r["label"] = r["verdict"] + (f" ({r['size_note']})" if r["size_note"] else "") + \
                (f" ({len(paired['seeds'])} paired seeds)" if paired else
                 f" ({r['n'][m['id']]} vs {r['n'][b['id']]} seeds)")
            r["note"] = (f"across experiments: {m['id']} mean {r['means'][m['id']]} over {r['n'][m['id']]} seeds, "
                         f"{b['id']} mean {r['means'][b['id']]} over {r['n'][b['id']]} seeds; {pair_txt}; gap = "
                         f"baseline minus method" + (f"; {noise}" if noise else "")
                         + (f"; {r['size_note']}" if r["size_note"] else ""))
            out.append(r)
    return out


def reference_values(golden: dict) -> dict:
    """{paper value: our hand-written reference's value} from a papers/<name>/results*.json (B0)."""
    return {m["paper_test_errors"]: m["test_errors"] for m in golden["models"].values()}


def grade(claims: list[dict], claim_map: dict, finals: dict, margin, seeds: int, ran: bool = True,
          reference: dict | None = None) -> dict:
    """claim_map {model name: claim id}; finals {model name: {value, log_line}} from the final_<model> METRIC lines."""
    if margin is None:
        raise ValueError("a margin must be declared on the experiment before grading (SPEC §7.5)")
    by_id = {c["id"]: c for c in claims}
    name_of = {cid: name for name, cid in claim_map.items()}
    targets = [by_id[cid] for cid in claim_map.values()]
    ours = {c["id"]: _num(finals[name_of[c["id"]]]["value"])
            for c in targets if ran and name_of[c["id"]] in finals}

    relations = []  # orderings the paper reports among target claims of the same metric
    for i, a in enumerate(targets):
        for b in targets[i + 1:]:
            if _same_kind(a, b) and a["value"] != b["value"]:
                hi, lo = (a, b) if better(a["value"], b["value"], a["direction"]) else (b, a)
                holds = (better(ours[hi["id"]], ours[lo["id"]], hi["direction"])
                         if hi["id"] in ours and lo["id"] in ours else None)
                relations.append({"relation": f"{hi['id']} better than {lo['id']}", "a": hi["id"], "b": lo["id"],
                                  "holds": holds})

    rows = []
    for c in targets:
        name = name_of[c["id"]]
        row = {"claim_id": c["id"], "model": name, "paper_model": c.get("model"), "metric": c.get("metric"),
               "unit": c.get("unit"), "direction": c.get("direction"), "whose": c.get("whose"),
               "paper": _num(c["value"]), "quote": c.get("quote"), "page": c.get("page"),
               "metric_name": f"final_{name}", "margin": _num(margin),
               "margin_source": "declared before the run (floor; the paper states no spread)",
               "size_note": None, "reference": (reference or {}).get(c["value"])}
        if c["id"] not in ours:
            row.update(verdict="Not runnable", ours=None, delta=None, log_line=None, broken_relations=[],
                       why="the run failed" if not ran else f"no METRIC final_{name} line")
        else:
            delta = _num(ours[c["id"]] - c["value"])
            mine = [r for r in relations if c["id"] in (r["a"], r["b"]) and r["holds"] is not None]
            broken = [r["relation"] for r in mine if not r["holds"]]
            if abs(delta) <= margin:
                verdict, why = "Reproduced", f"|{delta}| <= margin {_num(margin)}"
            elif mine and not broken:
                verdict = "Partially reproduced"
                why = f"|{delta}| > margin {_num(margin)}; holds: {', '.join(r['relation'] for r in mine)}"
            else:
                verdict = "Not reproduced"
                why = f"|{delta}| > margin {_num(margin)}" + (f"; broken: {', '.join(broken)}" if broken else
                                                              "; no relation to fall back on")
            row.update(verdict=verdict, ours=ours[c["id"]], delta=delta, log_line=finals[name].get("log_line"),
                       broken_relations=broken, why=why)
        row["label"] = label(row, seeds)
        rows.append(row)

    relative = []
    for m in (c for c in targets if c.get("whose") == "method"):
        for b in (c for c in targets if c.get("whose") == "baseline" and _same_kind(c, m)):
            sign = 1 if m["direction"] == "lower_is_better" else -1
            paper_gap = _num(sign * (b["value"] - m["value"]))
            r = {"claim": f"{m['id']} beats {b['id']}", "method": m["id"], "baseline": b["id"],
                 "paper_gap": paper_gap, "margin": _num(margin), "size_note": None}
            if m["id"] not in ours or b["id"] not in ours:
                r.update(verdict="Not runnable", ours_gap=None)
            else:
                g = _num(sign * (ours[b["id"]] - ours[m["id"]]))
                r["ours_gap"] = g
                if g <= 0:
                    r["verdict"] = "Not reproduced"
                elif abs(g - paper_gap) <= margin:
                    r["verdict"] = "Reproduced"
                else:
                    r.update(verdict="Partially reproduced",
                             size_note="gap smaller than reported" if g < paper_gap else "gap larger than reported")
            r["label"] = label(r, seeds)
            relative.append(r)
    return {"rules": RULES, "seeds": seeds, "margin": _num(margin), "claims": rows, "relative": relative,
            "relations": relations}


# ---- the explanation's number check -------------------------------------------------------------------------------

def _numbers_in(obj) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return {float(obj), abs(float(obj))}
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _numbers_in(v)
    return out


def number_check(text: str, tables: dict, allowed_extra=()) -> list[str]:
    """The numbers in `text` that are not in `tables` (numeric values anywhere in it, and their absolute values).
    Quotes are not searched: a number only the paper's prose has is not in the tables. Exact match, no rounding."""
    allowed = _numbers_in({k: v for k, v in tables.items() if k != "quote"}) | {float(x) for x in allowed_extra}
    allowed |= {abs(x) for x in allowed}
    unknown = []
    for tok in NUM_RE.findall(text or ""):
        v = float(tok.rstrip("%").replace(",", ""))
        if v not in allowed and abs(v) not in allowed:
            unknown.append(tok)
    return unknown


def _note(seeds: int, why: str) -> str:
    """The contract's note: starts with the seed count under 3 seeds."""
    if seeds >= MIN_SEEDS_FOR_NO_NOTE:
        return why
    return f"({seeds} seed{'s' if seeds != 1 else ''}) {why}"


def verdict_items(g: dict) -> list[dict]:
    """experiments.verdicts (docs/CONTRACTS.md §5): one item per claim, lower-case verdict, ours/paper/margin numbers,
    a note (starting with the seed note under 3 seeds) and the log line of the METRIC that gave `ours`. Relative
    claims are items '<method>_vs_<baseline>' with the gaps as ours/paper."""
    items = []
    for r in g["claims"]:
        n = r.get("n_seeds")
        if n and n > 1:
            note = (f"({n} seeds: mean {r['ours']} ± {r['sd']} over {', '.join(str(v) for v in r['values'])}) "
                    f"{r['why']}")
        else:
            note = _note(n or g["seeds"], r["why"])
        item = {"claim_id": r["claim_id"], "verdict": r["verdict"].lower(), "ours": r["ours"], "paper": r["paper"],
                "margin": r["margin"], "note": note, "log_line": r["log_line"]}
        if n:
            item.update(n_seeds=n, sd=r.get("sd"))
        if r.get("why_differs"):
            item["why_differs"] = r["why_differs"]
        items.append(item)
    for r in g["relative"]:
        if r.get("across"):
            why = r["note"]
        else:
            why = (f"gap = baseline minus method; {r['size_note']}" if r.get("size_note") else
                   "gap = baseline minus method")
            why = _note(g["seeds"], why)
        item = {"claim_id": f"{r['method']}_vs_{r['baseline']}", "verdict": r["verdict"].lower(),
                "ours": r.get("ours_gap"), "paper": r["paper_gap"], "margin": r["margin"], "note": why,
                "log_line": None}
        if r.get("across"):
            item.update(n_seeds=r["n"], means=r["means"], sds=r["sds"], paired=r.get("paired"))
        items.append(item)
    return items


def tables_text(g: dict) -> str:
    lines = ["Claims (paper vs ours; verdicts computed by code):",
             "claim | model | metric | paper | ours | delta | margin | verdict | our log line"]
    for r in g["claims"]:
        lines.append(f"{r['claim_id']} | {r['model']} ({r['paper_model']}) | {r['metric']} ({r['unit']}) | "
                     f"{r['paper']} | {r['ours']} | {r['delta']} | {r['margin']} | {r['label']} | {r['log_line']}")
    if g["relative"]:
        lines.append("\nRelative claims (gap = baseline minus method, in the better direction):")
        for r in g["relative"]:
            lines.append(f"{r['claim']}: paper gap {r['paper_gap']}, our gap {r.get('ours_gap')}, {r['label']}")
    if g["relations"]:
        lines.append("\nOrderings reported by the paper, and whether ours keep them:")
        lines += [f"{r['relation']}: {'holds' if r['holds'] else 'broken' if r['holds'] is False else 'n/a'}"
                  for r in g["relations"]]
    diff = (g.get("why") or {}).get("settings_diff") or []
    if diff:
        lines.append("\nSettings, paper vs ours (labels computed by code):")
        for r in diff:
            effs = "; ".join(
                f"branch {b['branch_id']} set {r['our_key']}={json.dumps(b['value'])}: smoke effect "
                f"{b['smoke_effect']} on {b['model']} ({b['decision']})"
                + (f", full-budget effect {b['full_effect']}" if b.get("full_effect") is not None else "")
                for b in r.get("branch_effects") or [])
            paper_v = r["paper"] if r["paper"] is not None else "not stated"
            lines.append(f"{r['key']} | paper: {paper_v} | ours: {r['our_key']} = {json.dumps(r['ours'])} | "
                         f"{r['label']}" + (f" | {effs}" if effs else ""))
    lines.append(f"\nSeeds: {g['seeds']}")
    return "\n".join(lines)


# ---- why it differs (T19): settings diff and branch effects --------------------------------------------------------

def read_log(db, experiment_id: str) -> list[str]:
    """An experiment's log: the worker's local copy on this machine, else Storage."""
    from lab.agents.tools import RUNS

    local = RUNS / "logs" / f"{experiment_id}.log"
    if local.is_file():
        return local.read_text(encoding="utf-8", errors="replace").splitlines()
    return db.storage.from_("logs").download(f"{experiment_id}.log").decode("utf-8", "replace").splitlines()


def _finals_of(db, experiment_id: str) -> dict:
    rows = db.table("metrics").select("name,value").eq("experiment_id", experiment_id).execute().data
    return {r["name"][len("final_"):]: r["value"] for r in rows
            if r["name"].startswith("final_") and r["value"] is not None}


def why_tables(db, exp: dict, settings: list[dict], read=None) -> dict:
    """The settings diff of a reproduction experiment and the effects of the what-if branches made from it."""
    from lab.agents import whatif as wi, why
    from lab.agents.reproduce import StepError

    cfg = exp.get("config") or {}
    try:
        config, line = wi.parse_config((read or (lambda e: read_log(db, e)))(exp["id"]))
    except Exception as e:  # StepError or a missing log: the table says why it is empty
        return {"settings_diff": [], "error": str(e) if isinstance(e, StepError) else f"log: {type(e).__name__}"}
    budget = cfg.get("budget") or {k: cfg[k] for k in ("epochs", "subset", "seeds") if cfg.get(k) is not None}
    su = (cfg.get("design") or {}).get("settings_used")
    paper = db.table("papers").select("claims").eq("project_id", exp["project_id"]).execute().data
    rows = why.experiment_diff(settings, (paper[0].get("claims") or []) if paper else [], cfg.get("claim_map") or {},
                               config, budget, set(su) if su is not None else None, exp.get("budget_reason"))
    exps = db.table("experiments").select("*").eq("project_id", exp["project_id"]).execute().data
    parent_finals, branches = _finals_of(db, exp["id"]), []
    for e in exps:
        w = (e.get("config") or {}).get("whatif") or {}
        if e.get("parent_id") != exp["id"] or not w or (e.get("config") or {}).get("scale") != "smoke":
            continue
        full = next((x for x in exps if ((x.get("config") or {}).get("whatif") or {}).get("task_id") == w.get(
            "task_id") and x["config"]["whatif"].get("branch_id") == w.get("branch_id")
            and x["config"].get("scale") == "full" and x.get("status") == "done"), None)
        full_effect = None
        if full and w.get("model") in parent_finals:
            v = _finals_of(db, full["id"]).get(w["model"])
            full_effect = None if v is None else round(v - parent_finals[w["model"]], 4)
        branches.append({"id": w.get("branch_id"), "key": w.get("key"), "value": w.get("value"),
                         "decision": w.get("decision"), "effect": w.get("effect"), "score": w.get("score"),
                         "model": w.get("model"), "experiment_id": e["id"], "full_effect": full_effect})
    rows = why.attach_effects(rows, branches)
    labels: dict[str, int] = {}
    for r in rows:
        labels[r["label"]] = labels.get(r["label"], 0) + 1
    return {"settings_diff": rows, "config_log_line": line, "labels": labels, "our_config": config, "budget": budget}


EXPLAIN_GOAL = ("Explain in plain language, in 3 to 6 sentences, what these verdicts mean for the paper's claims and "
                "why our numbers may differ (fewer epochs, unstated settings, one seed). Use ONLY numbers that appear "
                "in the tables below, spelled exactly as there; no other numbers, no percentages you computed. Code "
                "rejects the text if it contains any other number.\n\n")


def explain(db, g: dict, experiment_id: str, project_id: str | None, llm=None, agent: dict | None = None,
            task_id=None) -> dict:
    """The Analyst agent writes the text; code checks every number. One retry with the unknown numbers listed.
    agent: the task's assigned agent (worker path); otherwise the best active explain_diff agent."""
    from lab.agents.runtime import run_agent

    if agent is None:
        rows = db.table("agents").select("*").eq("status", "active").contains("capabilities", ["explain_diff"]) \
            .order("version", desc=True).execute().data
        if not rows:
            return {"text": None, "accepted": False, "problems": ["no active agent has capability explain_diff"]}
        agent = rows[0]
    feedback, tries = "", []
    workdir = Path(__file__).resolve().parents[2] / "runs" / (project_id or "analyst") / "analyst"
    for attempt in (1, 2):
        res = run_agent(agent, EXPLAIN_GOAL + tables_text(g) + feedback, workdir, db=db, llm=llm,
                        project_id=project_id, task_id=task_id)
        if res.status != "finished":
            tries.append({"status": res.status, "reason": res.reason})
            return {"text": None, "accepted": False, "agent": agent["name"], "tries": tries,
                    "problems": [f"agent {res.status}: {res.reason}"[:500]]}
        unknown = number_check(res.answer, g)
        tries.append({"text": res.answer, "unknown_numbers": unknown, "tokens": res.tokens})
        if not unknown:
            return {"text": res.answer, "accepted": True, "agent": agent["name"], "tries": tries, "problems": []}
        feedback = (f"\n\nYour previous text used numbers that are not in the tables: {', '.join(unknown)}. "
                    "Rewrite it without them.")
    return {"text": None, "accepted": False, "agent": agent["name"], "tries": tries,
            "problems": [f"numbers not in the tables: {', '.join(tries[-1]['unknown_numbers'])}"]}


def run(db, experiment_id: str, claim_map: dict | None = None, reference: dict | None = None,
        with_explanation: bool = True, agent: dict | None = None, task_id=None, llm=None, log_reader=None) -> dict:
    exp = db.table("experiments").select("*").eq("id", experiment_id).single().execute().data
    cfg = exp.get("config") or {}
    claim_map = claim_map or cfg.get("claim_map")
    if not claim_map:
        raise SystemExit("the experiment has no config.claim_map; pass --claim-map name=claim_id,...")
    paper = db.table("papers").select("claims,settings").eq("project_id", exp["project_id"]).single().execute().data
    margin = exp.get("margin")
    margin_note = None
    if margin is None:
        from lab.agents.reproduce import declare_margin
        margin, margin_note = declare_margin([c for c in paper["claims"] if c["id"] in claim_map.values()])
    metrics = db.table("metrics").select("name,value,log_line").eq("experiment_id", experiment_id).execute().data
    finals = {}
    for m in metrics:
        for name in claim_map:
            if m["name"] in (f"final_{name}", name if name.startswith("final_") else None):
                finals[name] = {"value": m["value"], "log_line": m["log_line"]}
    tasks = db.table("tasks").select("status,input").eq("capability", "run").eq("project_id", exp["project_id"]) \
        .execute().data
    mine = [t for t in tasks if (t.get("input") or {}).get("experiment_id") == experiment_id]
    ran = exp.get("status") == "done" or any(t["status"] == "done" for t in mine)
    exps = db.table("experiments").select("id,status,config,parent_id").eq("project_id", exp["project_id"]) \
        .execute().data
    group = seed_group(exp, exps) if ran else [exp]
    pooled = _pool_group(db, exp, group, claim_map, finals)
    graded_finals = {name: {"value": pooled[cid]["mean"], "log_line": finals[name].get("log_line")}
                     for name, cid in claim_map.items() if name in finals and cid in pooled}
    seeds = min([p["n"] for p in pooled.values()] or [len(cfg.get("seeds") or [0])])
    g = grade(paper["claims"], claim_map, {**finals, **graded_finals}, margin, seeds=seeds, ran=ran,
              reference=reference)
    annotate_seeds(g, pooled)
    g["seed_group"] = [e["id"] for e in group]
    if ran and cfg.get("cmd"):
        mapped = set(claim_map.values())
        for key, members in _comparable_groups(exp, exps).items():
            other = _pool_group(db, None, members, None, None, exclude=mapped)
            if other:
                g["relative"] += cross_relative(paper["claims"], pooled, other, margin)
    if margin_note:
        g["margin_note"] = f"margin not set on the experiment; graded with the floor: {margin_note}"
    g["log_path"] = exp.get("log_path")
    if not cfg.get("whatif"):  # a branch is explained through its parent's table
        g["why"] = why_tables(db, exp, paper.get("settings") or [], read=log_reader)
        db.table("experiments").update({"config": {**cfg, "why": g["why"]}}).eq("id", experiment_id).execute()
        from lab.agents.why import attach_why_differs
        attach_why_differs(g, paper["claims"], paper.get("settings") or [])  # verdicts[i].why_differs
    g["explanation"] = (explain(db, g, experiment_id, exp["project_id"], llm=llm, agent=agent, task_id=task_id)
                        if with_explanation else
                        {"text": None, "accepted": False, "problems": ["not requested"]})
    db.table("experiments").update({"verdicts": verdict_items(g)}).eq("id", experiment_id).execute()
    summary = ", ".join(f"{r['claim_id']} {r['label']}" for r in g["claims"])
    emit(db, "graded", f"graded: {summary}",
         f"code verdicts ({RULES}); margin {g['margin']}; explanation "
         + ("accepted by the number check" if g["explanation"]["accepted"] else
            f"not shown: {'; '.join(g['explanation']['problems'])}"[:600]),
         project_id=exp["project_id"], task_id=task_id, agent_id=(agent or {}).get("id"),
         data={"experiment_id": experiment_id, "grade": g})  # rules, relations, explanation and its check
    return g


def _pool_group(db, exp: dict | None, group: list[dict], claim_map: dict | None, finals: dict | None,
                exclude: set = frozenset()) -> dict[str, dict]:
    """claim id -> pool of the final values over the group's experiments that map that claim to the same model.
    With exp/claim_map/finals: the graded experiment's own map and values (the CLI may override its map)."""
    vals: dict[tuple[str, str], list] = {}
    seeds: dict[tuple[str, str], list] = {}
    for e in group:
        own = exp is not None and e["id"] == exp["id"]
        cmap = claim_map if own else (e.get("config") or {}).get("claim_map") or {}
        if claim_map is not None and not own:
            cmap = {n: c for n, c in cmap.items() if claim_map.get(n) == c}
        values = {n: f["value"] for n, f in (finals or {}).items()} if own else _finals_of(db, e["id"])
        for name, cid in cmap.items():
            if cid in exclude or values.get(name) is None:
                continue
            vals.setdefault((name, cid), []).append(values[name])
            seeds.setdefault((name, cid), []).append(seed_of(e.get("config")))
    return {cid: pool(v, seeds[(name, cid)]) for (name, cid), v in vals.items()}


def _comparable_groups(exp: dict, exps: list[dict]) -> dict[str, list[dict]]:
    """Seed groups of finished, non-what-if experiments with the same base_key but another config_key."""
    base, mine = base_key(exp.get("config")), config_key(exp.get("config"))
    out: dict[str, list[dict]] = {}
    for e in exps:
        cfg = e.get("config") or {}
        if e.get("status") != "done" or cfg.get("whatif") or not cfg.get("cmd"):
            continue
        k = config_key(cfg)
        if k != mine and base_key(cfg) == base:
            out.setdefault(k, []).append(e)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Grade an experiment against the paper's claims (SPEC §7.5)")
    ap.add_argument("--experiment-id", required=True)
    ap.add_argument("--claim-map", help="name=claim_id,... (default: experiments.config.claim_map)")
    ap.add_argument("--reference", help="golden reference results JSON (B0), shown as a column only")
    ap.add_argument("--no-explanation", action="store_true")
    a = ap.parse_args(argv)
    cmap = dict(kv.split("=", 1) for kv in a.claim_map.split(",")) if a.claim_map else None
    ref = reference_values(json.loads(Path(a.reference).read_text(encoding="utf-8"))) if a.reference else None
    g = run(client(), a.experiment_id, cmap, ref, with_explanation=not a.no_explanation)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # paper quotes carry ligatures; cp1252 consoles fail
    print(tables_text(g))
    print("\nexplanation:", g["explanation"]["text"] or f"(none: {g['explanation']['problems']})")


if __name__ == "__main__":
    sys.exit(main())
