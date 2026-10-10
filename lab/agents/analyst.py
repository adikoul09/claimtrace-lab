"""Analyst (SPEC §7.5): verdicts by code, then a plain-language explanation that may use only the table's numbers.

Verdicts, per target claim (absolute):
  Reproduced            |ours - paper| <= margin (declared on the experiment before the run)
  Partially reproduced  outside the margin, but every ordering the paper reports between this claim and the other
                        target claims of the same metric still holds in our numbers (e.g. distilled < hard-label)
  Not reproduced        otherwise
  Not runnable          the run failed or never printed the claim's final_<model> metric
Relative claims (each `method` claim vs each `baseline` claim of the same metric): the same rule on the gap; the
direction must hold for Reproduced or Partially reproduced. Fewer than 3 seeds: the label carries "(n seed)".

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
        items.append({"claim_id": r["claim_id"], "verdict": r["verdict"].lower(), "ours": r["ours"],
                      "paper": r["paper"], "margin": r["margin"], "note": _note(g["seeds"], r["why"]),
                      "log_line": r["log_line"]})
    for r in g["relative"]:
        why = (f"gap = baseline minus method; {r['size_note']}" if r.get("size_note") else
               "gap = baseline minus method")
        items.append({"claim_id": f"{r['method']}_vs_{r['baseline']}", "verdict": r["verdict"].lower(),
                      "ours": r.get("ours_gap"), "paper": r["paper_gap"], "margin": r["margin"],
                      "note": _note(g["seeds"], why), "log_line": None})
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
    lines.append(f"\nSeeds: {g['seeds']}")
    return "\n".join(lines)


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
        with_explanation: bool = True, agent: dict | None = None, task_id=None, llm=None) -> dict:
    exp = db.table("experiments").select("*").eq("id", experiment_id).single().execute().data
    cfg = exp.get("config") or {}
    claim_map = claim_map or cfg.get("claim_map")
    if not claim_map:
        raise SystemExit("the experiment has no config.claim_map; pass --claim-map name=claim_id,...")
    paper = db.table("papers").select("claims").eq("project_id", exp["project_id"]).single().execute().data
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
    g = grade(paper["claims"], claim_map, finals, margin, seeds=len(cfg.get("seeds") or [0]), ran=ran,
              reference=reference)
    if margin_note:
        g["margin_note"] = f"margin not set on the experiment; graded with the floor: {margin_note}"
    g["log_path"] = exp.get("log_path")
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
    print(tables_text(g))
    print("\nexplanation:", g["explanation"]["text"] or f"(none: {g['explanation']['problems']})")


if __name__ == "__main__":
    sys.exit(main())
