"""Deterministic settings diff over the blind LLM extractions, scored against the hand-built audit.
Paper side and code side were extracted by separate agents that never saw each other's output or our tables.
This script does no judging beyond fixed rules; it prints which known findings each paper x code pairing recovers."""
import json, re, itertools
from pathlib import Path

B = Path("/home/claude/blind/out")
OUT = Path("/home/claude/spike/evidence/extraction"); OUT.mkdir(parents=True, exist_ok=True)

def settings(d):
    s = d["settings"]
    return s["settings"] if "settings" in s and isinstance(s["settings"], dict) else s

def val(s, k):
    v = s.get(k)
    return v.get("value") if isinstance(v, dict) and "value" in v else v

def nums(x):
    """All numbers mentioned in a value (domains are often written as text, e.g. 'p=1.0 (target)')."""
    if x is None: return set()
    if isinstance(x, (int, float)) and not isinstance(x, bool): return {round(float(x), 4)}
    if isinstance(x, dict): return set().union(*[nums(v) for v in x.values()]) if x else set()
    if isinstance(x, list): return set().union(*[nums(v) for v in x]) if x else set()
    return {round(float(m), 4) for m in re.findall(r"(?<![\w.])\d+\.?\d*", str(x))}

def per_method(x):
    return x if isinstance(x, dict) and not {"name", "weight"} & set(x) else {"all": x}

DEFAULTS = {"optim.momentum": 0.0, "optim.nesterov": False, "optim.lr_schedule": "constant"}

def schedules(terms):
    """Weight schedules of penalty terms, per method if given per method."""
    out = {}
    for m, ts in per_method(terms).items():
        for t in (ts or []):
            if isinstance(t, dict) and t.get("weight_schedule") not in (None, "constant") and not re.search(r"cross[_ -]?entropy", str(t.get("name", "")).lower()):
                out[m] = str(t.get("weight_schedule"))
    return out

def diff(p, c):
    f = []
    # 1. domains the paper evaluates on that the code cannot produce
    tgt, avail = nums(val(p, "data.target_domains")), nums(val(c, "data.domains_data_available"))
    missing = sorted(tgt - avail) if avail else []
    if missing: f.append({"key": "data.target_domains", "kind": "code omission", "paper": sorted(tgt), "code_available": sorted(avail)})
    # 2. paper silent, code sets a non-default value
    for k, dflt in DEFAULTS.items():
        if val(p, k) is None:
            for m, v in per_method(val(c, k)).items():
                if v is not None and str(v).lower() != str(dflt).lower() and not (isinstance(v, (int, float)) and float(v) == float(dflt)):
                    f.append({"key": k, "kind": "paper omission", "method": m, "code": v})
    sch_c, sch_p = schedules(val(c, "loss.terms")), schedules(val(p, "loss.terms"))
    for m, s in sch_c.items():
        if not sch_p: f.append({"key": "loss.terms.weight_schedule", "kind": "paper omission", "method": m, "code": s})
    # 3. both sides state a value and they differ
    for k in ("optim.lr", "optim.weight_decay", "train.epochs", "eval.n_seeds", "data.train_samples_per_domain", "data.val_samples_per_domain"):
        pv = val(p, k)
        if pv is None: continue
        for m, cv in per_method(val(c, k)).items():
            if cv is not None and nums(pv) and nums(cv) and nums(pv) != nums(cv):
                f.append({"key": k, "kind": "difference", "method": m, "paper": pv, "code": cv})
    pv, cv = val(p, "train.batch_size"), val(c, "train.batch_size")
    if pv is not None and cv is not None and nums(pv) != nums(cv):
        f.append({"key": "train.batch_size", "kind": "difference", "paper": pv, "code": cv})
    ps, cs = str(val(p, "train.model_selection") or "").lower(), str(val(c, "train.model_selection") or "").lower()
    if ps and cs and ps.split(":")[0] != cs.split(":")[0]:
        f.append({"key": "train.model_selection", "kind": "difference", "paper": ps, "code": cs})
    return f

# Ground truth: findings in the hand-built audit, plus the ones this round added (see report).
GROUND_TRUTH = {
    "F1 target domain p = 1.0 not generated": lambda fs: any(x["key"] == "data.target_domains" for x in fs),
    "F2 selection: validation loss vs accuracy": lambda fs: any(x["key"] == "train.model_selection" for x in fs),
    "F3 momentum 0.9 + Nesterov not in paper": lambda fs: any(x["key"] in ("optim.momentum", "optim.nesterov") for x in fs),
    "F4 penalty weight ramps from 0, not in paper": lambda fs: any(x["key"] == "loss.terms.weight_schedule" for x in fs),
    "F5 DANN/CDANN lr 0.01 vs paper's 0.1": lambda fs: any(x["key"] == "optim.lr" and "dann" in str(x.get("method", "")).lower() for x in fs),
}
KNOWN_KEYS = {"data.target_domains", "train.model_selection", "optim.momentum", "optim.nesterov", "loss.terms.weight_schedule", "optim.lr"}

# Claims: paper Table 1 target column, checked by hand against the PDF.
TABLE1 = {"ERM": (57.6, 6.58), "DANN": (53.0, 1.41), "MMD": (62.9, 5.01), "CORAL": (63.1, 5.86), "RandMatch": (59.5, 3.50),
          "CDANN": (55.9, 2.47), "C-MMD": (58.9, 3.43), "C-CORAL": (64.7, 4.69), "PerfMatch": (77.8, 6.01)}
ALIAS = {"random-match": "RandMatch", "randmatch": "RandMatch", "rand": "RandMatch", "perfect-match": "PerfMatch", "perfmatch": "PerfMatch",
         "c-dann": "CDANN", "cdann": "CDANN"}

def claim_score(d):
    got = {}
    for c in d["claims"]:
        if "target" in str(c.get("column", "")).lower():
            name = ALIAS.get(str(c["method"]).lower(), c["method"])
            got[name] = (float(c["mean"]), float(c["sd"]))
    right = sum(1 for k, v in TABLE1.items() if got.get(k) == v)
    return right, len(TABLE1), {k: got.get(k) for k in TABLE1}

if __name__ == "__main__":
    P = {f.stem: json.loads(f.read_text()) for f in sorted(B.glob("paper_run*.json"))}
    C = {f.stem: json.loads(f.read_text()) for f in sorted(B.glob("code_run*.json"))}
    report = {"claims": {}, "pairings": {}, "paper_runs_agree_on_all_27_cells": None}
    for n, d in P.items():
        r, tot, got = claim_score(d)
        report["claims"][n] = {"target_cells_correct": f"{r}/{tot}", "values": got}
    cells = [sorted((str(c["method"]), str(c["column"]), c["mean"], c["sd"]) for c in d["claims"]) for d in P.values()]
    report["paper_runs_agree_on_all_27_cells"] = all(x == cells[0] for x in cells)
    for (pn, p), (cn, c) in itertools.product(P.items(), C.items()):
        fs = diff(settings(p), settings(c))
        hit = {g: fn(fs) for g, fn in GROUND_TRUTH.items()}
        extra = [x for x in fs if x["key"] not in KNOWN_KEYS]
        report["pairings"][f"{pn} x {cn}"] = {"recovered": f"{sum(hit.values())}/{len(hit)}", "by_finding": hit,
                                               "extra_findings": extra, "all_findings": fs}
    (OUT / "score.json").write_text(json.dumps(report, indent=1, default=str))
    for n, v in report["claims"].items(): print("claims", n, v["target_cells_correct"])
    print("paper runs agree on all 27 cells:", report["paper_runs_agree_on_all_27_cells"])
    for k, v in report["pairings"].items():
        print(k, v["recovered"], [g for g, h in v["by_finding"].items() if not h], "extras:", [(x["key"], x.get("method"), x.get("paper"), x.get("code")) for x in v["extra_findings"]])
