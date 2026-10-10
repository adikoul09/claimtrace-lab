"""Deterministic settings diff over the blind LLM extractions, scored against the hand-built audit.
Port of the spike's scripts/extraction_diff.py (schema v1 keys), plus `diff_v2` for the schema v2 keys (Phase 5).
Paper side and code side were extracted by separate agents that never saw each other's output or our tables.
This module does no judging beyond fixed rules; it reports which known findings each paper x code pairing recovers."""
import itertools
import json
import re
from pathlib import Path


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


def load_outputs(outputs_dir):
    """The extraction outputs: ({paper_runN: json}, {code_runN: json})."""
    B = Path(outputs_dir)
    P = {f.stem: json.loads(f.read_text()) for f in sorted(B.glob("paper_run*.json"))}
    C = {f.stem: json.loads(f.read_text()) for f in sorted(B.glob("code_run*.json"))}
    return P, C


def score_report(outputs_dir):
    """The spike's extraction/score.json content (returned, not written)."""
    P, C = load_outputs(outputs_dir)
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
    return report


# ---- schema v2 (Phase 5) ----------------------------------------------------------------------------------------
# The v1 rules above stay exactly as the spike ran them (`el01 regress` re-scores the spike's four outputs with them).
# `diff_v2` keeps v1's rules 1 and 2 (code omission of a domain; paper silent, code non-default) and replaces its
# rule 3 with a per-method version: v1 compares a per-method value with the paper's whole value (a per-phase paper
# answer then "differs" from every method) and compares train.model_selection as one string (a per-method code answer
# then always differs). On top come the same three kinds of rule on the schema-v2 keys, whose values are lists of
# entries with enumerated fields (el01/extract/schema_v2.json): `null` = the source says nothing, `[]` = it has no
# such step. Enumerated fields (a domain transform's `kind`, ...) are compared as enum values; the agents choose the
# value by reading, code only compares.

V2_KEYS = ("data.preprocessing.resize", "data.preprocessing.normalization", "data.augmentation",
           "data.domain_transform", "train.model_selection_data")
NUMBER_KEYS = ("optim.lr", "optim.weight_decay", "train.epochs", "eval.n_seeds", "data.train_samples_per_domain",
               "data.val_samples_per_domain", "train.batch_size")   # v1 rule 3, now per method
ENUM_KEYS = ("optim.name", "eval.aggregation", "train.model_selection")   # compared by enumerated head, per method
_SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "extract" / "schema_v2.json").read_text())
DOMAIN_KINDS = tuple(next(k for k in _SCHEMA["keys"] if k["key"] == "data.domain_transform")
                     ["entry"]["properties"]["kind"]["enum"])
MISSING = object()


def entries(x):
    """A v2 value as a list of entry dicts, or None when the source is silent."""
    if x is None:
        return None
    if isinstance(x, dict):
        return [x]
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else None


def mkey(name) -> str:
    """A method name for matching across sides: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def methods_match(a, b) -> bool:
    """`methods: null` (every method) matches anything; otherwise some name of one side contains one of the other."""
    if not a or not b:
        return True
    return any(x and y and (x in y or y in x) for x in map(mkey, a) for y in map(mkey, b))


def head(v) -> str:
    """The enumerated head of a free-text value: 'min_val_loss: ...' -> 'min_val_loss'."""
    return re.split(r"[:(]", str(v).lower())[0].strip().replace(" ", "_").replace("-", "_")


def known(v) -> bool:
    return v not in (None, "", "unknown", "other", "not_applicable")


def paper_value_for(pm: dict, m: str):
    """The paper's value for the code's method `m`: the paper's entry with the same name (letters and digits only),
    or the spike's alias for it (rand -> RandMatch), or the one paper name containing or contained in it; else the
    paper's value for every method; else MISSING (the paper gives this method no value)."""
    if m in pm:
        return pm[m]
    mk = mkey(m)
    for k in pm:
        if mkey(k) == mk or mkey(k) == mkey(ALIAS.get(mk, ALIAS.get(str(m).lower(), ""))):
            return pm[k]
    near = [k for k in pm if k != "all" and mkey(k) and (mkey(k) in mk or mk in mkey(k))]
    if len(near) == 1:
        return pm[near[0]]
    return pm.get("all", MISSING)


def method_pairs(pv, cv):
    """(method, paper value, code value) for every method both sides give a value for. A code value for every
    method is paired with each of the paper's per-method values."""
    pm, cm = per_method(pv), per_method(cv)
    if set(cm) == {"all"} and set(pm) != {"all"}:
        return [(m, x, cm["all"]) for m, x in pm.items()]
    out = []
    for m, y in cm.items():
        x = paper_value_for(pm, m)
        if x is not MISSING:
            out.append((m, x, y))
    return out


def leaves(v) -> list:
    """The scalar values inside a value (per-phase dicts and lists flattened)."""
    if isinstance(v, dict):
        return [x for y in v.values() for x in leaves(y)]
    if isinstance(v, list):
        return [x for y in v for x in leaves(y)]
    return [v]


def _number_rules(p, c):
    """v1 rule 3 per method: both sides state numbers for a method and the sets differ."""
    f = []
    for k in NUMBER_KEYS:
        pv, cv = val(p, k), val(c, k)
        if pv is None or cv is None:
            continue
        for m, x, y in method_pairs(pv, cv):
            if nums(x) and nums(y) and nums(x) != nums(y):
                f.append({"key": k, "kind": "difference", "method": m, "paper": x, "code": y})
    return f


def _enum_rules(p, c):
    """Both sides name an enumerated value for a method (per phase, if given) and the sets of named values differ.
    `other: ...`, `unknown` and `not_applicable` name nothing a fixed rule can compare and are skipped."""
    f = []
    for k in ENUM_KEYS:
        pv, cv = val(p, k), val(c, k)
        if pv is None or cv is None:
            continue
        for m, x, y in method_pairs(pv, cv):
            px = {head(v) for v in leaves(x) if v is not None and known(head(v))}
            cy = {head(v) for v in leaves(y) if v is not None and known(head(v))}
            if px and cy and px != cy:
                f.append({"key": k, "kind": "difference", "method": m, "paper": x, "code": y})
    return f


def _augmentation(p, c):
    pe, ce = entries(val(p, "data.augmentation")), entries(val(c, "data.augmentation"))
    if not ce:
        return []
    sel = entries(val(c, "train.model_selection_data")) or []
    reads_aug = [{k: s.get(k) for k in ("use", "split", "domains", "version", "methods", "phase")}
                 for s in sel if s.get("version") == "augmented"]
    f = []
    if pe is None:   # paper silent, code augments
        for e in ce:
            f.append({"key": "data.augmentation", "kind": "paper omission", "code": e,
                      "reaches": {"applies_to": e.get("applies_to") or [], "selection_reads_augmented": reads_aug}})
        return f
    pops = sorted({mkey(o) for e in pe for o in e.get("ops") or []})
    cops = sorted({mkey(o) for e in ce for o in e.get("ops") or []})
    porder = {e.get("relative_to_domain_transform") for e in pe if known(e.get("relative_to_domain_transform"))}
    corder = {e.get("relative_to_domain_transform") for e in ce if known(e.get("relative_to_domain_transform"))}
    if pops != cops or (porder and corder and porder != corder):
        f.append({"key": "data.augmentation", "kind": "difference", "paper": pe, "code": ce,
                  "reaches": {"selection_reads_augmented": reads_aug}})
    return f


def _selection_data(p, c):
    pe, ce = entries(val(p, "train.model_selection_data")) or [], entries(val(c, "train.model_selection_data")) or []
    f = []
    for e in ce:
        same = [x for x in pe if x.get("use") == e.get("use") and methods_match(x.get("methods"), e.get("methods"))]
        code = {k: e.get(k) for k in ("split", "domains", "version")}
        if not same:   # paper silent on this step: only a non-default reading (not plain source data) is an omission
            if e.get("version") not in ("plain", None) or e.get("domains") not in ("source", "unknown", None):
                f.append({"key": "train.model_selection_data", "kind": "paper omission", "use": e.get("use"),
                          "method": e.get("methods"), "phase": e.get("phase"), "code": code})
            continue
        for x in same:
            paper = {k: x.get(k) for k in ("split", "domains", "version")}
            diff_fields = [k for k in paper if known(paper[k]) and known(code[k]) and paper[k] != code[k]]
            if diff_fields:
                f.append({"key": "train.model_selection_data", "kind": "difference", "use": e.get("use"),
                          "method": e.get("methods"), "phase": e.get("phase"), "fields": diff_fields,
                          "paper": paper, "code": code})
    return f


def _simple_entries(p, c, key, fields, non_default, enums=None):
    """resize / normalization / domain transform: paper silent and code sets a non-default step -> paper omission;
    both stated and their `fields` differ (numbers compared as sets) -> difference. A field listed in `enums` is
    compared only when both sides chose one of its enumerated values."""
    pe, ce = entries(val(p, key)), entries(val(c, key))
    if not ce:
        return []
    if pe is None:
        return [{"key": key, "kind": "paper omission", "method": e.get("methods"), "code": e}
                for e in ce if non_default(e)]
    f = []
    for e in ce:
        same = [x for x in pe if methods_match(x.get("methods"), e.get("methods"))] or pe
        for k in fields:
            cv, pv = e.get(k), [x.get(k) for x in same]
            if enums and k in enums:
                cv = cv if cv in enums[k] else None
                pv = [v for v in pv if v in enums[k]]
            if not known(cv) or not any(known(v) for v in pv):
                continue
            if isinstance(cv, (int, float, list)) and not isinstance(cv, bool):
                if all(nums(v) != nums(cv) for v in pv if known(v)):
                    f.append({"key": key, "kind": "difference", "field": k, "method": e.get("methods"),
                              "paper": pv, "code": cv})
            elif all(mkey(v) != mkey(cv) for v in pv if known(v)):
                f.append({"key": key, "kind": "difference", "field": k, "method": e.get("methods"),
                          "paper": pv, "code": cv})
    return f


def diff_v2(p, c):
    """v1 rules 1 and 2, v1 rule 3 per method, then the schema-v2 rules. Each finding names its key and kind
    (difference, code omission, paper omission); no rule judges how much a finding matters."""
    f = [x for x in diff(p, c) if x["key"] not in NUMBER_KEYS + ("train.model_selection",)]
    f += _number_rules(p, c)
    f += _enum_rules(p, c)
    f += _augmentation(p, c)
    f += _selection_data(p, c)
    f += _simple_entries(p, c, "data.preprocessing.resize", ("height", "width"),
                         lambda e: e.get("height") is not None or e.get("width") is not None)
    f += _simple_entries(p, c, "data.preprocessing.normalization", ("kind", "mean", "std"),
                         lambda e: e.get("kind") not in ("none", None))
    f += _simple_entries(p, c, "data.domain_transform", ("kind", "domains", "direction"),
                         lambda e: known(e.get("kind")), enums={"kind": DOMAIN_KINDS})
    return f
