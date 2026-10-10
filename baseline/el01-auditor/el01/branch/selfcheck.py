"""Branch self-check (spec section 6): re-run the code extractor on the branch snapshot and require exactly one
changed setting, the one the finding names.

  1. The code extractor (el01/extract/settings.py, the Phase 5 prompt unchanged) runs on a `git archive` snapshot of
     the branch, and on one of the baseline branch, with the same replicate number. Each answer's evidence is checked
     against its own snapshot (check_answer).
  2. Differences, code vs code: diff_v2 in both directions (each run as the "paper" side once; findings diff_v2 also
     gives for an answer against itself are dropped) plus `canon` per key, grouped into settings (key, and the
     selection `use` for train.model_selection_data).
  3. Attribution (Builder, 2026-10-04): two code runs at the same commit already differ (Phase 5: 2 distinct settings
     for Table 1 in diff_v2, canon on 8 of 25 keys), so a difference counts as a change only when either run's
     evidence for that key cites a line the patch touched: a removed line (baseline numbering) or an added line
     (branch numbering). Verified citations count at their lines; an unverified one at the location code found its
     quote (`near`), if any. Other differences are listed as extractor disagreement, not counted.
  4. Pass: at least one attributed setting, and every attributed setting is one of the finding's settings.
Hunks that no evidence item of either run cites are reported (`uncited_hunks`)."""
from __future__ import annotations

import json
from typing import Optional

from el01.diff import settings_diff as xd
from el01.extract import settings as S
from el01.repair.policy import parse_unified_diff

# finding key -> the answer keys behind it (as settings.FINDING_SIDES, both sides)
KEY_SOURCES = {"data.target_domains": ("data.target_domains", "data.domains_data_available"),
               "loss.terms.weight_schedule": ("loss.terms",)}
USE_KEYS = {"train.model_selection_data"}


def raw_keys(key: str) -> tuple[str, ...]:
    return KEY_SOURCES.get(key, (key,))


def setting_of(key: str, use: Optional[str]) -> tuple[str, Optional[str]]:
    """The answer-level setting a diff key names: (raw key, use). loss.terms.weight_schedule -> loss.terms."""
    k = "loss.terms" if key == "loss.terms.weight_schedule" else key
    return k, (use if k in USE_KEYS else None)


def finding_settings(setting_ids: list[str]) -> set[tuple[str, Optional[str]]]:
    out = set()
    for sid in setting_ids:
        key, _kind, _field, use = json.loads(sid)
        for k in raw_keys(key):
            out.add((k, use if k in USE_KEYS else None))
    return out


def touched(diff: str) -> dict:
    """{"old": {file: {removed line numbers}}, "new": {file: {added line numbers}}, "hunks": [...]}."""
    out = {"old": {}, "new": {}, "hunks": []}
    for f in parse_unified_diff(diff):
        out["old"].setdefault(f.path, set()).update(n for n, _ in f.removed)
        out["new"].setdefault(f.path, set()).update(n for n, _ in f.added)
        # hunks: runs of consecutive changed lines, for the uncited-hunk report
        for side, rows in (("old", f.removed), ("new", f.added)):
            nums = sorted(n for n, _ in rows)
            for n in nums:
                h = out["hunks"][-1] if out["hunks"] else None
                if h and h["file"] == f.path and h["side"] == side and n == h["last"] + 1:
                    h["last"] = n
                else:
                    out["hunks"].append({"file": f.path, "side": side, "first": n, "last": n})
    return out


def _ranges(check: dict) -> list[list[int]]:
    if check.get("ok") and check.get("ranges"):
        return check["ranges"]
    if check.get("near"):
        return [check["near"]]
    return []


def cited_lines(checked: dict, key: str) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for c in (checked.get(key) or {}).get("checks") or []:
        for a, b in _ranges(c):
            out.setdefault(c["file"], set()).update(range(a, b + 1))
    return out


def _entries_by_use(v):
    es = xd.entries(v) or []
    out = {}
    for e in es:
        out.setdefault(e.get("use"), []).append(e)
    return out


def differences(base: dict, branch: dict) -> dict[tuple[str, Optional[str]], dict]:
    """Settings whose values differ between two checked code answers: {(key, use): {via, base, branch}}."""
    out: dict = {}

    def add(setting, via, b, r):
        d = out.setdefault(setting, {"via": [], "base": b, "branch": r})
        if via not in d["via"]:
            d["via"].append(via)

    vb, vr = S.values(base), S.values(branch)
    sig = lambda f: json.dumps(f, sort_keys=True, default=str)
    # diff_v2 is a paper-vs-code diff: some of its rules fire on one answer against itself (target domains vs the
    # domains the code generates). Those findings are properties of an answer, not differences between two.
    own = {sig(f) for v in (vb, vr) for f in xd.diff_v2(v, v)}
    for direction, (p, c) in (("diff_v2 base->branch", (vb, vr)), ("diff_v2 branch->base", (vr, vb))):
        for f in xd.diff_v2(p, c):
            if sig(f) in own:
                continue
            k, use = setting_of(f["key"], f.get("use"))
            add((k, use), direction, base.get(k, {}).get("value"), branch.get(k, {}).get("value"))
    for k in S.KEYS:
        b, r = base[k]["value"], branch[k]["value"]
        if k in USE_KEYS:
            eb, er = _entries_by_use(b), _entries_by_use(r)
            for use in sorted(set(eb) | set(er), key=str):
                if S.canon(k, eb.get(use)) != S.canon(k, er.get(use)):
                    add((k, use), "canon", eb.get(use), er.get(use))
        elif S.canon(k, b) != S.canon(k, r):
            add((k, None), "canon", b, r)
    return out


def attribute(diffs: dict, base: dict, branch: dict, patch: dict) -> dict:
    """Split differences into attributed (evidence cites a touched line) and disagreement."""
    attributed, noise = {}, {}
    for setting, d in diffs.items():
        k = setting[0]
        hits = []
        for side, checked, lines in (("baseline", base, patch["old"]), ("branch", branch, patch["new"])):
            for f, ns in cited_lines(checked, k).items():
                common = sorted(ns & lines.get(f, set()))
                if common:
                    hits.append({"run": side, "file": f, "lines": common})
        (attributed if hits else noise)[setting] = {**d, "cites_patch": hits}
    return {"attributed": attributed, "disagreement": noise}


def uncited_hunks(base: dict, branch: dict, patch: dict) -> list[dict]:
    cited = {"old": {}, "new": {}}
    for side, checked in (("old", base), ("new", branch)):
        for k in S.KEYS:
            for f, ns in cited_lines(checked, k).items():
                cited[side].setdefault(f, set()).update(ns)
    return [h for h in patch["hunks"]
            if not set(range(h["first"], h["last"] + 1)) & cited[h["side"]].get(h["file"], set())]


def _fmt(setting) -> str:
    k, use = setting
    return f"{k} ({use})" if use else k


def judge(diff: str, base: dict, branch: dict, wanted: set) -> dict:
    """The self-check verdict on two checked answers (`check_answer(...)["settings"]`)."""
    patch = touched(diff)
    diffs = differences(base, branch)
    att = attribute(diffs, base, branch, patch)
    changed = set(att["attributed"])
    extra = sorted(changed - wanted, key=str)
    ok = bool(changed) and not extra
    if not changed:
        reason = "no difference between the branch and the baseline is attributed to the patch"
    elif extra:
        reason = (f"the patch also changes {', '.join(_fmt(s) for s in extra)} (attributed: evidence cites patched "
                  f"lines); the finding names {', '.join(_fmt(s) for s in sorted(wanted, key=str))}")
    else:
        reason = f"exactly one changed setting: {', '.join(_fmt(s) for s in sorted(changed, key=str))}"
    ser = lambda m: [{"key": s[0], "use": s[1], **v} for s, v in sorted(m.items(), key=lambda kv: str(kv[0]))]
    return {"pass": ok, "reason": reason, "wanted": [{"key": k, "use": u} for k, u in sorted(wanted, key=str)],
            "attributed": ser(att["attributed"]), "disagreement": ser(att["disagreement"]),
            "uncited_hunks": uncited_hunks(base, branch, patch)}
