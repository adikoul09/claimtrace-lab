"""Why results differ (SPEC §7.5, T19): the settings diff and the branch effects, computed by code.

settings_diff  one row per (paper setting, matching key of our CONFIG): the paper's value with its quote and page,
               ours with its CONFIG key, and a label decided by code:
                 paper omission            the paper does not state it; our value fills the gap
                 scale reduction (budget)  epochs / data subset / seeds the paper states, cut by the budget step
                 same                      every number of the paper's value is in ours (or, for a setting stated
                                           without numbers such as "dropout", our matching setting is switched on)
                 difference                otherwise, including a stated setting no CONFIG key matches
attach_effects the what-if branches that changed a row's CONFIG key: their smoke effect, decision and, once extended,
               the full-budget effect.
The Analyst's explanation may use only numbers from these rows (lab/agents/analyst.py number check).

Our values come from the run's printed `CONFIG {json}` line and the budget (epochs, subset, seeds); paper values from
papers.settings (Reader, quotes checked by code). Settings are numbered s1, s2, ... in papers.settings order; when the
design names the ones that apply (design.settings_used), only those are compared, plus every unstated one."""
from __future__ import annotations

import re

from lab.agents.paper import numbers
from lab.agents.whatif import flatten

SYNONYMS = {
    "architecture": ("layers", "architecture", "hidden_layers", "depth", "n_layers", "hidden"),
    "hidden_units": ("hidden", "hidden_units", "width", "units"),
    "optimizer": ("optimizer", "optim"),
    "lr": ("lr", "learning_rate"),
    "batch": ("batch", "batch_size"),
    "regularisation": ("dropout", "max_norm", "maxnorm", "weight_decay", "regularization", "regularisation", "l2"),
    "augmentation": ("jitter", "augmentation", "augment", "shift", "translate"),
    "temperature": ("temperature", "temp"),
    "preprocessing": ("normalize", "normalise", "preprocessing", "mean", "std"),
    "epochs": ("epochs",), "data_subset": ("subset",), "seeds": ("seeds", "seed"),
}
SCALE_KEYS = ("epochs", "data_subset", "seeds")
_TOKEN = re.compile(r"[a-z0-9]+")


def _segments(key: str) -> list[str]:
    return [s.lower().replace("-", "_") for s in key.split(".")]


def _strength(key: str, syns) -> int:
    """How well a CONFIG key matches a setting: 3 a segment is a synonym, 2 starts with one, 1 ends with or contains
    one, 0 no match. A key belongs only to the settings it matches most strongly (dropout_hidden is regularisation,
    not hidden_units)."""
    best = 0
    for seg in _segments(key):
        for s in syns:
            if seg == s:
                best = max(best, 3)
            elif seg.startswith(s + "_"):
                best = max(best, 2)
            elif seg.endswith("_" + s) or (len(s) > 3 and s in seg):
                best = max(best, 1)
    return best


def _keys_for(setting_key: str, ours: dict) -> list[str]:
    out = []
    for k in ours:
        mine = _strength(k, SYNONYMS.get(setting_key, (setting_key,)))
        if mine and mine >= max(_strength(k, syns) for name, syns in SYNONYMS.items() if name != setting_key
                                and not {name, setting_key} <= {"architecture", "hidden_units"}):
            out.append(k)
    return out


def _numbers_of(value) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [value]
    if isinstance(value, (list, tuple)):  # a list of layer widths also says how many layers
        return [n for v in value for n in _numbers_of(v)] + ([len(value)] if value else [])
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers_of(v)]
    return numbers(str(value))


def _num(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _switched_on(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value) and str(value).lower() not in ("none", "false", "off", "no")


def our_values(config: dict, budget: dict) -> dict:
    """CONFIG flattened, with the budget's scale settings (they are CLI arguments, not CONFIG keys)."""
    flat = flatten(config or {})
    if budget:
        flat.setdefault("epochs", budget.get("epochs"))
        flat["subset"] = budget.get("subset")
        flat["seeds"] = len(budget.get("seeds") or [0])
    return {k: v for k, v in flat.items() if v is not None}


def settings_diff(settings: list[dict], config: dict, budget: dict | None, used: set | None = None) -> list[dict]:
    ours = our_values(config, budget or {})
    rows = []
    for i, s in enumerate(settings, 1):
        sid, key, paper_value = f"s{i}", s.get("key"), s.get("value")
        stated = paper_value is not None
        if (used is not None and stated and sid not in used) or not s.get("valid", True):
            continue
        keys = _keys_for(key, ours)
        scope = set(_TOKEN.findall(str(s.get("applies_to") or "").lower())) - {"all"}
        narrowed = [k for k in keys if scope & set(t for seg in _segments(k) for t in seg.split("_"))]
        keys = narrowed or keys
        base = {"key": key, "setting_id": sid, "applies_to": s.get("applies_to"), "paper": paper_value,
                "quote": s.get("quote"), "page": s.get("page"),
                "paper_numbers": [_num(n) for n in numbers(str(paper_value))] if stated else []}
        if not keys:
            rows.append({**base, "our_key": None, "ours": None, "our_numbers": [],
                         "label": "difference" if stated else "paper omission",
                         "why": "no CONFIG key matches this setting; our run does not set it explicitly"
                                + ("" if stated else "; the paper does not state it either")})
            continue
        candidates = []
        for k in keys:
            v = ours[k]
            ours_n = [_num(n) for n in _numbers_of(v)]
            row = {**base, "our_key": k, "ours": v, "our_numbers": ours_n}
            if not stated:
                row.update(label="paper omission", why="the paper does not state it; this is our choice")
            elif key in SCALE_KEYS and base["paper_numbers"] and ours_n and min(ours_n) < min(base["paper_numbers"]):
                row.update(label="scale reduction (budget)",
                           why=f"the budget step chose {v} to fit the project's CPU cap")
            elif base["paper_numbers"]:
                same = set(base["paper_numbers"]) <= set(ours_n)
                row.update(label="same" if same else "difference",
                           why="the paper's numbers are all in ours" if same else "different numbers")
            else:
                on = _switched_on(v)
                row.update(label="same" if on else "difference",
                           why=f"stated without numbers; our {k} is {'on' if on else 'off'}")
            candidates.append(row)
        if not stated:
            rows += candidates  # every key is our own choice: one row each
            continue
        # A stated setting is one value for the model it applies to: one row, the key that carries it if any.
        order = {"same": 0, "scale reduction (budget)": 1, "difference": 2}
        best = min(candidates, key=lambda r: order[r["label"]])
        rows.append({**best, "also": [r["our_key"] for r in candidates if r is not best]})
    return rows


def attach_effects(rows: list[dict], branches: list[dict]) -> list[dict]:
    """branches: what-if rows {id, key, value, decision, effect, score, model, experiment_id, full_effect?}."""
    out = []
    for r in rows:
        eff = [{"branch_id": b["id"], "value": b["value"], "model": b.get("model"), "smoke_effect": b.get("effect"),
                "score": b.get("score"), "decision": b.get("decision"), "full_effect": b.get("full_effect"),
                "experiment_id": b.get("experiment_id")}
               for b in branches if r.get("our_key") and b.get("key") == r["our_key"]]
        out.append({**r, "branch_effects": eff})
    return out
