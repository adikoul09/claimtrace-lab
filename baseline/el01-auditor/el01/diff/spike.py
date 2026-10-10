"""Phase 5 acceptance on MatchDG: score the schema-v2 settings diff against the hand-built audit.

Table 1: golden/findings.json (F1-F6). A finding counts in a paper x code pairing when the diff lists it and every
non-null side behind it has at least one evidence item code verified. F1-F3 must be found in every pairing; F4, F5
should be; F6 is a bonus. Detection reuses the spike's matchers (settings_diff.GROUND_TRUTH) for F1-F5.

Suppl. Table 11 (spec section 9, step 3b): F7, SciCoQA row 67 (MASTER_PROMPT Appendix B; the golden file has no F7).
Each code run must report the augmented copy (crop, then horizontal flip, after the rotation) citing
data/data_gen_mnist.py:34-35 and :85, and MatchDG's first-phase selection reading that copy, citing
data/mnist_loader_match_eval.py:38 and algorithms/match_dg.py:263-266, all citations verified by code; every pairing's
diff must then list the augmentation as a paper omission that reaches MatchDG's selection only.

F8 (team-verified 2026-10-04, outside golden/; the Phase 4 lead): Table 1's Source columns are printed by test.py:399
as np.std/sqrt(n), a standard error, where the caption says standard deviation. Counted as known, reported (no pass
rule); golden/verdicts.json is untouched (Target is graded from train.py:314-315's plain sd, so no verdict changes).

These file names and finding numbers live here, in the checker, never in the extractor prompts
(tests/test_settings_prompts.py). F7 and F8 were found after the spike and are not blind results.

Every other finding is listed as "new, unverified", with the lead carried over from Phase 4. Precision is reported
twice: with F1-F7 as the known findings, and with F1-F8."""
from __future__ import annotations

import json
import re

from el01.config import Paths
from el01.diff import settings_diff as xd
from el01.extract.settings import load_settings, setting_id

TABLE1, TABLE11 = "Table 1", "Suppl. Table 11"
LEVEL = {"F1": "must", "F2": "must", "F3": "must", "F4": "should", "F5": "should", "F6": "bonus", "F7": "must",
         "F8": "team-verified"}
KNOWN_F7 = {TABLE1: ("F1", "F2", "F3", "F4", "F5", "F6"),
            TABLE11: ("F3", "F4", "F7")}   # spec section 3: F3 and F4 apply to Table 11 too
KNOWN = {TABLE1: KNOWN_F7[TABLE1] + ("F8",), TABLE11: KNOWN_F7[TABLE11]}
F7_GOLDEN = {"what": "flip after rotation in the augmented Rotated MNIST copy, reaching only MatchDG's first-phase "
                     "checkpoint choice (SciCoQA row 67)", "kind": "paper omission",
             "source": "MASTER_PROMPT Appendix B; spec section 3"}
F7_LINES = [("data/data_gen_mnist.py:34-35, 85", "data/data_gen_mnist.py", {34, 35, 85}, "all"),
            ("data/mnist_loader_match_eval.py:38", "data/mnist_loader_match_eval.py", {38}, "all"),
            ("algorithms/match_dg.py:263-266", "algorithms/match_dg.py", set(range(263, 267)), "any")]
F8_TEAM = {"what": "Table 1 Source columns: test.py:399 prints np.std/sqrt(n), a standard error, where the caption "
                   "says standard deviation (Target is graded from train.py:314-315's plain sd: no verdict changes)",
           "kind": "difference",
           "source": "team-verified 2026-10-04, outside golden/findings.json; found after the spike (Phase 4 linker "
                     "note, Phase 5 extractor), not blind"}
EXTRA = {"F7": F7_GOLDEN, "F8": F8_TEAM}
SE_RE = re.compile(r"mean_se|standard[ _-]?error|sqrt", re.I)
OTHER_METHODS = ("ERM", "RandMatch", "PerfMatch")
FIRST_PHASE_RE = re.compile(r"contrast|first|ctr|phase\s*1|\b1\b", re.I)
LEADS = [   # the Phase 4 test.py:399 lead is F8 now
    {"table": TABLE11, "keys": ["data.train_samples_per_domain", "data.generation_params"],
     "lead": "no repository command makes LeNet-size Rotated MNIST: the README's data step uses --subset_size 2000 "
             "(ResNet-18); the paper (supp. C.1, p.7) and the spike's data use 1000 per domain",
     "source": "Phase 4 (PROGRESS.md, notes for Phase 5)"},
]


def _gt(n: int):
    """The spike's matcher for F<n> (n = 1..5), applied to one finding."""
    fn = list(xd.GROUND_TRUTH.values())[n - 1]
    return lambda f: fn([f])


def _mentions_matchdg(methods) -> bool:
    return bool(methods) and any("matchdg" in xd.mkey(m) for m in methods)


def _matchdg_only(methods) -> bool:
    return _mentions_matchdg(methods) and not any(xd.methods_match([o], methods) for o in OTHER_METHODS)


def _crop_then_flip(e: dict) -> bool:
    ops = [xd.mkey(o) for o in e.get("ops") or []]
    crop = next((i for i, o in enumerate(ops) if "crop" in o), None)
    flip = next((i for i, o in enumerate(ops) if "flip" in o), None)
    return crop is not None and flip is not None and crop < flip


def is_f7(f: dict) -> bool:
    if f["key"] != "data.augmentation" or f["kind"] != "paper omission":
        return False
    e = f.get("code") or {}
    sel = (f.get("reaches") or {}).get("selection_reads_augmented") or []
    return (_crop_then_flip(e) and e.get("relative_to_domain_transform") == "after"
            and any(_matchdg_only(s.get("methods")) for s in sel)
            and all(_matchdg_only(s.get("methods")) for s in sel))


def is_f7_selection(f: dict) -> bool:
    """F7's own selection step: MatchDG's checkpoint choice reading the augmented copy, listed by the diff as its own
    selection-data finding. Reported under F7, not as new."""
    return (f["key"] == "train.model_selection_data" and (f.get("code") or {}).get("version") == "augmented"
            and _matchdg_only(f.get("method")))


RELATED = {"F7": is_f7_selection}
def is_f8(f: dict) -> bool:
    """A Table 1 aggregation difference where the code side prints a standard error and the paper side does not."""
    return (f["key"] == "eval.aggregation" and f["kind"] == "difference"
            and bool(SE_RE.search(json.dumps(f.get("code"), default=str)))
            and not SE_RE.search(json.dumps(f.get("paper"), default=str)))


def is_target_validation_print(f: dict) -> bool:
    """The diff's 'checkpoint reads target test data': train.py:303 takes np.max(final_acc) and train.py:315 only
    prints it as "Final Test Accuracy (Target Validation)"; the saved checkpoint and every reported number use source
    validation (train.py:306-307, algorithms/erm_match.py:155-158), and slab-tune.py reads the Source Validation line."""
    code = f.get("code") or {}
    return (f["key"] == "train.model_selection_data" and f.get("use") == "checkpoint"
            and code.get("domains") == "target" and code.get("split") == "test")


FALSE_ALARMS = {"target-validation print": {
    "match": is_target_validation_print,
    "why": "train.py:303 computes np.max(final_acc) and train.py:315 only prints it as 'Final Test Accuracy (Target "
           "Validation)'; the checkpoint and every reported number use source validation (train.py:306-307, "
           "algorithms/erm_match.py:155-158); reproduce_scripts/slab-tune.py reads the Source Validation line",
    "source": "team-verified 2026-10-04 (DECISIONS.md)"}}


def false_alarm(f: dict):
    return next((name for name, fa in FALSE_ALARMS.items() if fa["match"](f)), None)


MATCH = {"F1": _gt(1), "F2": _gt(2), "F3": _gt(3), "F4": _gt(4), "F5": _gt(5),
         "F6": lambda f: f["key"] == "train.model_selection_data" and f.get("use") == "hyperparameter_tuning",
         "F7": is_f7, "F8": is_f8}


def evidence_ok(f: dict) -> bool:
    """Every side with a value behind the finding has at least one verified evidence item."""
    return all(s in ("verified", "partly", "null") for s in (f.get("evidence") or {}).values())


def score_pairings(pairings: dict, wanted: tuple) -> dict:
    out = {}
    for p, fs in pairings.items():
        out[p] = {}
        for F in wanted:
            hits = [f for f in fs if MATCH[F](f)]
            out[p][F] = {"found": bool(hits), "verified": any(evidence_ok(f) for f in hits),
                         "related": sum(RELATED[F](f) for f in fs) if F in RELATED else 0,
                         "kinds": sorted({f["kind"] for f in hits}), "keys": sorted({f["key"] for f in hits}),
                         "setting_ids": sorted({setting_id(f) for f in hits}),
                         "evidence": [f.get("evidence") for f in hits]}
    return out


def summarise(scored: dict, wanted: tuple, golden: dict) -> dict:
    n = len(scored)
    out = {}
    for F in wanted:
        g = golden.get(F) or EXTRA.get(F, {})
        found = sum(v[F]["found"] for v in scored.values())
        ver = sum(v[F]["verified"] for v in scored.values())
        kinds = sorted({k for v in scored.values() for k in v[F]["kinds"]})
        out[F] = {"what": g.get("what"), "golden_kind": g.get("kind"), "level": LEVEL[F],
                  "found_in": f"{found}/{n}", "verified_in": f"{ver}/{n}", "kinds_found": kinds,
                  "all_pairings": n > 0 and ver == n}
        if F in RELATED:
            rel = sum(v[F].get("related", 0) > 0 for v in scored.values())
            out[F]["related_in"] = f"{rel}/{n}"
    return out


def _covered(checks: list[dict]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for c in checks:
        if c["ok"] and c["lines"]:
            for a, b in c.get("ranges") or [c["lines"]]:
                out.setdefault(c["file"], set()).update(range(a, b + 1))
    return out


def f7_code_run(run: dict) -> dict:
    """The F7 code path in one code run: the augmented copy and MatchDG's first-phase selection, with citations."""
    s = run["settings"]
    aug = [e for e in xd.entries(s["data.augmentation"]["value"]) or [] if isinstance(e, dict)]
    sel = [e for e in xd.entries(s["train.model_selection_data"]["value"]) or [] if isinstance(e, dict)]
    aug_ok = [e for e in aug if _crop_then_flip(e) and e.get("relative_to_domain_transform") == "after"]
    sel_ok = [e for e in sel if e.get("use") == "checkpoint" and e.get("version") == "augmented"
              and _matchdg_only(e.get("methods")) and FIRST_PHASE_RE.search(str(e.get("phase") or ""))]
    others = [e for e in sel if e.get("version") == "augmented" and not _matchdg_only(e.get("methods"))]
    cov = _covered(s["data.augmentation"]["checks"] + s["train.model_selection_data"]["checks"]
                   + s["train.model_selection"]["checks"])   # "selected in match_dg.py:263-266" is the selection rule
    cites = {}
    for label, f, lines, how in F7_LINES:
        got = cov.get(f, set())
        cites[label] = lines <= got if how == "all" else bool(lines & got)
    out = {"augmented_copy": {"ok": bool(aug_ok), "entries": aug_ok or aug},
           "matchdg_first_phase_selection": {"ok": bool(sel_ok), "entries": sel_ok or sel},
           "other_methods_selecting_on_augmented": others,
           "citations_verified": cites,
           "citation_keys": ["data.augmentation", "train.model_selection_data", "train.model_selection"],
           "augmentation_evidence": s["data.augmentation"]["status"],
           "selection_evidence": s["train.model_selection_data"]["status"]}
    out["ok"] = bool(aug_ok and sel_ok and not others and all(cites.values()))
    return out


def short(v, n: int = 160) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n - 3] + "..."


def is_known(table: str, f: dict, known: dict = None) -> bool:
    return any(MATCH[F](f) or (F in RELATED and RELATED[F](f)) for F in (known or KNOWN)[table])


def new_findings(table: str, pairings: dict) -> list[dict]:
    """Findings that match none of the known ones for this table, one group per setting (setting_id: key, kind,
    field, use) across every pairing and run, whatever the methods are called. Each group keeps every distinct
    (method, paper value, code value) it was found with, and which pairings."""
    groups: dict[str, dict] = {}
    for p, fs in pairings.items():
        for f in fs:
            if is_known(table, f):
                continue
            fa = false_alarm(f)
            g = groups.setdefault(setting_id(f), {"table": table, "key": f["key"],
                                                  "status": f"false alarm: {fa}" if fa else "new, unverified",
                                                  "kind": f["kind"], "use": f.get("use"), "field": f.get("field"),
                                                  "pairings": [], "methods": [], "variants": []})
            if p not in g["pairings"]:
                g["pairings"].append(p)
            m = f.get("method")
            if m not in g["methods"]:
                g["methods"].append(m)
            v = {"method": m, "paper": f.get("paper"), "code": f.get("code"), "evidence": f.get("evidence")}
            hit = next((x for x in g["variants"] if {k: x[k] for k in v} == v), None)
            if hit is None:
                g["variants"].append({**v, "pairings": [p]})
            elif p not in hit["pairings"]:
                hit["pairings"].append(p)
    return sorted(groups.values(), key=lambda g: (-len(g["pairings"]), g["key"], g["kind"]))


def precision(table: str, pairings: dict, known_findings: dict = None) -> dict:
    """Distinct settings the diff lists (over all pairings), how many match a known finding of this table, how many
    are new. known / (known + new) is a lower bound on precision: it counts every unverified finding as false."""
    known, new, false = set(), set(), set()
    for fs in pairings.values():
        for f in fs:
            if is_known(table, f, known_findings):
                known.add(setting_id(f))
            elif false_alarm(f):
                false.add(setting_id(f))
            else:
                new.add(setting_id(f))
    new |= false   # a false alarm counts as false, like every unverified finding
    return {"distinct_settings": len(known | new), "known": len(known), "new_unverified": len(new - false),
            "false_alarms": len(false), "not_known": len(new),
            "raw_findings": sum(len(fs) for fs in pairings.values()),
            "precision_lower_bound": f"{len(known)}/{len(known) + len(new)}",
            "precision_lower_bound_value": round(len(known) / (len(known) + len(new)), 3) if known | new else None}


def leads(settings: dict, diffs: dict) -> list[dict]:
    out = []
    for ld in LEADS:
        t = next((x for x in settings["tables"] if x["target"] == ld["table"]), None)
        d = next((x for x in diffs["tables"] if x["target"] == ld["table"]), None)
        if t is None or d is None:
            continue
        n = sum(any(f["key"] in ld["keys"] for f in fs) for fs in d["pairings"].values())
        code = {r: {k: t["runs"][r]["settings"][k]["value"] for k in ld["keys"]}
                for r in sorted(t["runs"]) if r.startswith("code_")}
        paper = {r: {k: t["runs"][r]["settings"][k]["value"] for k in ld["keys"]}
                 for r in sorted(t["runs"]) if r.startswith("paper_")}
        cites = sorted({f"{c['file']}:" + ", ".join(f"{a}-{b}" if b != a else f"{a}"
                                                     for a, b in c.get("ranges") or [c["lines"]])
                        for r in t["runs"] if r.startswith("code_") for k in ld["keys"]
                        for c in t["runs"][r]["settings"][k]["checks"] if c["ok"]})
        out.append({**ld, "status": "new, unverified", "diff_lists_it_in": f"{n}/{len(d['pairings'])}",
                    "code_values": code, "paper_values": paper, "code_citations_verified": cites})
    return out


def run_check(paths: Paths, audit_id: str = "matchdg") -> dict:
    settings, diffs = load_settings(paths, audit_id)
    out = check(settings, diffs, json.loads((paths.golden / "findings.json").read_text()), audit_id)
    (paths.audit_dir(audit_id) / "extraction_score.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n")
    return out


def check(settings: dict, diffs: dict, golden: dict, audit_id: str = "matchdg") -> dict:
    by = {t["target"]: t for t in diffs["tables"]}
    st = {t["target"]: t for t in settings["tables"]}
    out = {"audit": audit_id, "golden": "inputs/spike-matchdg/golden/findings.json (F1-F6); F7 from MASTER_PROMPT "
                                        "Appendix B", "schema_version": settings["schema_version"],
           "blind": {"F1-F6": "scored against the spike's hand audit; the extractor prompts name no finding",
                     "F7": "found after schema v2 added the data-pipeline keys (spec section 3), so not a blind "
                           "result: the spike's blind v1 run and the hand audit missed it",
                     "F8": F8_TEAM["source"]},
           "pass_rule": "F1-F3 found with verified evidence in every paper x code pairing (F4/F5 should, F6 bonus); "
                        "Table 11: every code run reports the F7 code path with verified citations and every pairing "
                        "lists F7 as a paper omission",
           "problems": []}
    t1 = by.get(TABLE1)
    if t1 is None:
        out["problems"].append("no Table 1 diff")
        out["table1"] = None
    else:
        sc = score_pairings(t1["pairings"], KNOWN[TABLE1])
        sm = summarise(sc, KNOWN[TABLE1], golden)
        out["table1"] = {"pairings": sc, "summary": sm,
                         "pass": all(sm[F]["all_pairings"] for F in KNOWN[TABLE1] if LEVEL[F] == "must")}
    t11 = by.get(TABLE11)
    if t11 is None:
        out["problems"].append("no Suppl. Table 11 diff")
        out["table11"] = None
    else:
        runs = {r: f7_code_run(v) for r, v in sorted(st[TABLE11]["runs"].items()) if r.startswith("code_")}
        sc = score_pairings(t11["pairings"], KNOWN[TABLE11])
        sm = summarise(sc, KNOWN[TABLE11], golden)
        out["table11"] = {"code_runs": runs, "pairings": sc, "summary": sm,
                          "pass": bool(runs) and all(r["ok"] for r in runs.values()) and sm["F7"]["all_pairings"]}
    out["new_unverified"] = [g for t in (TABLE1, TABLE11) if t in by for g in new_findings(t, by[t]["pairings"])]
    out["precision"] = {}
    for label, kn in (("F1-F7", KNOWN_F7), ("F1-F8", KNOWN)):
        pr = {t: precision(t, by[t]["pairings"], kn) for t in (TABLE1, TABLE11) if t in by}
        k = sum(v["known"] for v in pr.values())
        n = sum(v["not_known"] for v in pr.values())
        pr["all"] = {"known": k, "new_unverified": sum(v["new_unverified"] for v in pr.values()),
                     "false_alarms": sum(v["false_alarms"] for v in pr.values()), "not_known": n,
                     "precision_lower_bound": f"{k}/{k + n}",
                     "precision_lower_bound_value": round(k / (k + n), 3) if k + n else None}
        out["precision"][label] = pr
    out["precision"]["definition"] = ("distinct settings (key, kind, field, use) over all 4 pairings of a table; "
                                      "known = matches a known finding of that table (F1-F7, or F1-F8); false "
                                      "alarms (team-verified) and every new, unverified finding count as false")
    out["leads"] = leads(settings, diffs)
    out["agreement"] = {t["target"]: {side: a["counts"] for side, a in t["agreement"].items()}
                        for t in settings["tables"]}
    out["evidence"] = {t["target"]: {r: v["evidence"] for r, v in sorted(t["runs"].items())}
                       for t in settings["tables"]}
    out["calls"] = settings["counts"]
    out["pass"] = bool(out["table1"] and out["table1"]["pass"] and out["table11"] and out["table11"]["pass"]
                       and not out["problems"])
    return out

