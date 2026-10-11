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

import json
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
            elif key == "data_subset" and v == 0 and not isinstance(v, bool):  # --subset 0 is the full training set
                full = any(w in str(paper_value).lower() for w in ("all", "full", "entire", "whole"))
                row.update(label="same" if full else "difference",
                           why="our run used the full training set (subset 0 = all)")
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


# ---- why ours differs, per claim (shown under the verdict) ---------------------------------------------------------
# The design names the settings it used; a claim's explanation compares every setting the paper states for that
# claim's own model (e.g. the teacher's dropout and input jitter), matched by code: the words of the claim's model and
# section against each setting's applies_to. The paper's text, our CONFIG line and the budget are the only sources.

_STOP = {"the", "and", "for", "with", "without", "net", "nets", "model", "models", "neural", "network", "networks",
         "experiment", "experiments", "preliminary", "results", "result", "section", "table", "using", "all"}


def _words(text) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", str(text or "").lower()) if len(t) > 2 and t not in _STOP}


def _match(a: str, b: str) -> float:
    if a == b:
        return 1.0
    short, long_ = sorted((a, b), key=len)
    return 0.9 if len(short) >= 4 and long_.startswith(short) else 0.0  # small ~ smaller


def claim_settings(claim: dict, settings: list[dict]) -> list[str]:
    """Ids (s1, s2, ...) of the valid stated settings for this claim's model: the best word match between the claim's
    model + section and the setting's applies_to, plus settings stated for everything (applies_to 'all')."""
    mine = _words(claim.get("model")) | _words(claim.get("table_or_section"))
    scored, general = [], []
    for i, s in enumerate(settings, 1):
        if s.get("value") is None or not s.get("valid", True):
            continue
        theirs = _words(s.get("applies_to"))
        if not theirs:
            general.append(f"s{i}")
            continue
        scored.append((sum(max((_match(t, m) for m in mine), default=0.0) for t in theirs), f"s{i}"))
    best = max((sc for sc, _ in scored), default=0.0)
    return [sid for sc, sid in scored if best >= 1.0 and sc == best] + general


def _model_value(flat: dict, key: str, model: str):
    """Our value of `key` for one model: epochs.teacher for teacher_mlp_compact, else the plain key."""
    tokens = set(str(model).lower().replace("-", "_").split("_"))
    keys = [k for k in flat if _segments(k)[0] == key]
    for k in keys:
        if tokens & set(_segments(k)[1:]):
            return flat[k]
    return flat.get(key, flat[keys[0]] if keys else None)


def why_differs(row: dict, claim: dict, settings: list[dict], our_config: dict, budget: dict) -> dict | None:
    """Code-made 'why ours differs' for one graded claim row (analyst.grade): the stated paper settings of the claim's
    model that differ from our run, those that are the same, and our training length; None when nothing ran."""
    if row.get("ours") is None:
        return None
    ids = claim_settings(claim, settings)
    scoped = [{**s, "applies_to": row.get("model")} if f"s{i}" in ids else s for i, s in enumerate(settings, 1)]
    rows = [r for r in settings_diff(scoped, our_config, budget, used=set(ids)) if r["setting_id"] in ids]
    keep = ("setting_id", "key", "applies_to", "paper", "quote", "page", "our_key", "ours", "label", "why")
    reasons, same, seen = [], [], set()
    for r in rows:
        r = {k: r.get(k) for k in keep}
        r["applies_to"] = settings[int(r["setting_id"][1:]) - 1].get("applies_to")
        if r["label"] == "same":
            same.append(r)
        elif r["label"] in ("difference", "scale reduction (budget)") and str(r["paper"]) not in seen:
            seen.add(str(r["paper"]))
            reasons.append(r)
    epochs = _model_value(flatten(our_config or {}), "epochs", row.get("model")) or (budget or {}).get("epochs")
    seeds = len((budget or {}).get("seeds") or (our_config or {}).get("seeds") or [0])
    delta, unit = row.get("delta"), claim.get("unit") or ""
    text = [f"Ours {_num(row['ours'])} vs paper {_num(row['paper'])}"
            + (f" ({'+' if delta > 0 else ''}{_num(delta)} {unit})".replace(" )", ")") if delta is not None else "")
            + "."]
    if reasons:
        text.append("Setup differences: " + "; ".join(
            f"{r['key']}: paper {r['paper']}" + (f" (p. {r['page']})" if r["page"] else "") + ", ours "
            + (f"{r['our_key']} = {json.dumps(r['ours'], ensure_ascii=False)}" if r["our_key"] else "not set")
            for r in reasons) + ".")
    else:
        text.append("No stated setup difference found for this model.")
    text.append(f"Training: ours {_num(epochs) if epochs is not None else '?'} epochs, {seeds} seed"
                + ("s" if seeds != 1 else "")
                + ("" if any(r["key"] == "epochs" for r in rows) else "; the paper does not state its training length")
                + ".")
    if same:
        text.append("Same as the paper: " + ", ".join(f"{r['key']} ({r['paper']})" for r in same) + ".")
    return {"summary": " ".join(text), "reasons": reasons, "same": same, "epochs": epochs, "seeds": seeds,
            "settings": ids, "source": "code: papers.settings vs the run's CONFIG line and budget; no LLM"}


def experiment_diff(settings: list[dict], claims: list[dict], claim_map: dict, config: dict, budget: dict,
                    used: set | None = None, budget_reason: str | None = None) -> list[dict]:
    """experiments.config.why.settings_diff: settings_diff over the design's settings plus every stated setting of
    each graded claim's model (claim_settings), each matched to that model's CONFIG keys (teacher_mlp_compact ->
    *.teacher) and naming the claims it explains (claim_ids); then one compute_budget row: the compute the paper's
    claims state (Reader facts) vs our budget."""
    by_id = {c["id"]: c for c in claims}
    claims_of, models_of = {}, {}
    for model, cid in (claim_map or {}).items():
        for sid in claim_settings(by_id.get(cid, {}), settings) if cid in by_id else []:
            claims_of.setdefault(sid, []).append(cid)
            models_of.setdefault(sid, set()).add(model)
    scoped = [{**s, "applies_to": next(iter(models_of[f"s{i}"]))} if len(models_of.get(f"s{i}", ())) == 1 else s
              for i, s in enumerate(settings, 1)]
    rows = settings_diff(scoped, config, budget, (set(used) | set(claims_of)) if used is not None else None)
    for r in rows:
        r["applies_to"] = settings[int(r["setting_id"][1:]) - 1].get("applies_to")
        r["claim_ids"] = claims_of.get(r["setting_id"], [])
    stated, cids = [], []
    for cid in (claim_map or {}).values():
        facts = ((by_id.get(cid) or {}).get("runnable") or {}).get("facts") or {}
        said = [str(facts[k]) for k in ("hardware", "compute") if facts.get(k)] + \
            ([f"{facts['gpu_hours']} GPU-hours"] if facts.get("gpu_hours") else [])
        if said:
            cids.append(cid)
            stated += [x for x in said if x not in stated]
    ours = budget_reason or (f"{budget.get('epochs')} epochs" if (budget or {}).get("epochs") else None)
    rows.append({"key": "compute_budget", "setting_id": None, "applies_to": "all", "paper": "; ".join(stated) or None,
                 "quote": None, "page": None, "paper_numbers": [], "our_key": "budget", "ours": ours,
                 "our_numbers": [_num(n) for n in numbers(str(ours or ""))],
                 "label": "scale reduction (budget)" if stated else "paper omission",
                 "why": ("the paper's compute as the Reader found it, vs the budget step's plan for the project's CPU "
                         "cap" if stated else "the paper does not state its compute; ours is the budget step's plan"),
                 "also": [], "claim_ids": cids})
    return rows


def attach_why_differs(g: dict, claims: list[dict], settings: list[dict]) -> None:
    """Sets g['claims'][i]['why_differs'] (analyst.grade rows) from g['why'] (our_config, budget)."""
    w = g.get("why") or {}
    if w.get("our_config") is None:
        return
    by_id = {c["id"]: c for c in claims}
    for r in g["claims"]:
        r["why_differs"] = why_differs(r, by_id.get(r["claim_id"], {}), settings, w["our_config"],
                                       w.get("budget") or {})


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
