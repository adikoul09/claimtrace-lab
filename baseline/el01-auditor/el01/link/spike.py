"""Phase 4 acceptance on MatchDG: claim cards, linked commands and parser specs against the spike's hand-built ones.

  cards     golden/claims.json: Table 1 target cells (mean, sd, n), Table 11 cells and averages; the card must be
            verified (row line on its page, value at its column) and PerfMatch tagged `oracle`
  commands  scripts/run_table1.sh (train + test.py per method; `$TD` from run_table1_rest.sh:12, the paper's target
            domain) and scripts/run_matchdg_lenet.sh (per method and test domain; MatchDG = two phases), read from the
            shell scripts themselves. Compared step by step as namespaces of the scripts' own argparse parsers,
            ignoring output paths (none are arguments here) and seed plumbing (`--n_runs`, options named *seed*);
            differences in those are reported, not failed. Table 1 compares per row (the distinct commands of the
            row's cells), Table 11 per cell.
  parsers   each linked cell's parser spec on every spike log of its step (the log name each script redirects that
            command to): values and line numbers must equal el01/grade/parse.py's `parse_train` per seed (Table 1
            Target, Table 11). The Source columns: parse_runs keeps only test.py's summary line (`parse_eval`); a
            whole-log spec must equal it (mean, sd, line), a per-run spec's values must average to its mean (2 dp)
  data      Table 1: the data command equals the spike's; Table 11: the data step prints the same split shapes as the
            spike's log of the shipped MNIST generator (its command was not kept)
  blind     information only: Table 1 cells equal to the spike's two blind extraction runs
The golden key -> printed row label map below is the checker's knowledge, not the code under test's."""
from __future__ import annotations

import json
import re
import shlex
import statistics as st
from pathlib import Path
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.extract.claims import load_claims
from el01.grade.parse import parse_eval, parse_train
from el01.ingest.pdf_text import squash
from el01.link import argspec, parser_spec

LABELS = {"erm": "ERM", "rand": "RandMatch", "perf": "PerfMatch", "mmd": "MMD", "coral": "CORAL", "dann": "DANN",
          "c-mmd": "C-MMD", "c-coral": "C-CORAL", "c-dann": "CDANN", "matchdg": "MatchDG"}
TABLE1, TABLE11 = "Table 1", "Suppl. Table 11"
SOURCE_COLUMNS = {"Source 1": "source_1", "Source 2": "source_2"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", squash(s).lower())


# ---- the hand-written commands ----------------------------------------------------------------------------------

def _command(line: str, subs: dict[str, list[str]]) -> tuple[list[str], Optional[str]]:
    """One shell command line -> (argv from `python` on, with variables expanded; the file stdout goes to)."""
    m = re.search(r'\s>\s*"?([^"\s]+)"?', line)
    log = m.group(1) if m else None
    toks = []
    for t in shlex.split(line[:m.start()] if m else line):
        toks += subs.get(t, [t])
    i = next(k for k, t in enumerate(toks) if t.endswith("python"))
    return ["python"] + toks[i + 1:], log


def handwritten_table1(spike: Path) -> dict[str, list[dict]]:
    text = (spike / "scripts" / "run_table1.sh").read_text()
    rest = (spike / "scripts" / "run_table1_rest.sh").read_text()
    rest_common = re.search(r'^COMMON="([^"]*)"', rest, re.M).group(1).split()
    td = rest_common[rest_common.index("--test_domains") + 1]  # the paper's target domain (run_table1_rest.sh:12)
    common = [td if t == "$TD" else t for t in re.search(r'^COMMON="([^"]*)"', text, re.M).group(1).split()]
    methods = dict(re.findall(r'^M\[([\w-]+)\]="([^"]*)"', text, re.M))
    lines = [l for l in text.splitlines() if re.search(r"python\s+\S+\.py", l)]
    out = {}
    for key, args in methods.items():
        steps = []
        for l in lines:
            argv, log = _command(l, {"$COMMON": common, "${M[$m]}": args.split()})
            steps.append({"argv": argv, "log": log.split("/")[-1].replace("$m", key) if log else None,
                          "source": f"scripts/run_table1.sh:{text.splitlines().index(l) + 1}"})
        out[key] = steps
    return out


def handwritten_table11(spike: Path) -> dict[tuple[str, str], list[dict]]:
    text = (spike / "scripts" / "run_matchdg_lenet.sh").read_text()
    b = re.search(r'^B="([^"]*)"', text, re.M).group(1).split()
    domains = re.search(r"for x in ([\d ]+); do", text).group(1).split()
    block = text[text.index("case $m in") + len("case $m in"): text.index("esac")]
    arms = re.findall(r"(\w+)\)\s*(.*?);;", block, re.S)
    out = {}
    for d in domains:
        a = ["--train_domains"] + [x for x in domains if x != d] + ["--test_domains", d]
        for key, body in arms:
            steps = []
            for part in body.split("&&"):
                part = " ".join(part.split())
                argv, log = _command(part, {"$B": b, "$a": a})
                steps.append({"argv": argv, "log": log.split("/")[-1].replace("$d", d) if log else None,
                              "source": "scripts/run_matchdg_lenet.sh"})
            out[(key, d)] = steps
    return out


# ---- checks -----------------------------------------------------------------------------------------------------

def _table(claims: dict, target: str) -> dict:
    return next(t for t in claims["tables"] if t["target"] == target)


def _card(table: dict, row_label: str, column: str) -> Optional[dict]:
    return next((c for c in table["cards"] if _norm(c["source"]["row"]) == _norm(row_label)
                 and c["source"]["column"] == column), None)


def check_cards(claims: dict, golden: dict) -> dict:
    items, problems = [], []

    def one(table: dict, key: str, column: str, mean, sd, n=None):
        c = _card(table, LABELS[key], column)
        rec = {"table": table["target"], "key": key, "row": LABELS[key], "column": column,
               "golden": {"mean": mean, "sd": sd, "n": n}}
        if c is None:
            rec.update(ok=False, problem="no card")
        else:
            bad = []
            if not c["valid"]:
                bad.append("card not verified: " + "; ".join(c["problems"]))
            if c["reported"]["mean"] != mean:
                bad.append(f"mean {c['reported']['mean']} != {mean}")
            if c["reported"]["sd"] != sd:
                bad.append(f"sd {c['reported']['sd']} != {sd}")
            if n is not None and c["reported"]["n_runs"] != n:
                bad.append(f"n_runs {c['reported']['n_runs']} != {n}")
            rec.update(ok=not bad, problem="; ".join(bad) or None, claim_id=c["claim_id"],
                       doc=c["source"]["doc"], page=c["source"]["page"], row_line=c["source"]["row_line"],
                       role=c["role"], reported=c["reported"])
        items.append(rec)
        if not rec["ok"]:
            problems.append(f"{rec['table']} {rec['row']}/{column}: {rec['problem']}")

    t1, t11 = _table(claims, TABLE1), _table(claims, TABLE11)
    for key, g in golden["table1_target"].items():
        one(t1, key, "Target", g["mean"], g["sd"], g.get("n"))
    for key, cells in golden["table11"].items():
        for d, g in cells.items():
            one(t11, key, d, g["mean"], g["sd"])
    for key, avg in golden["table11_average"].items():
        one(t11, key, "Average", avg, None)
    roles = {}
    for t in (t1, t11):
        c = _card(t, LABELS["perf"], t["columns"][0]) if t["columns"] else None
        roles[t["target"]] = c["role"] if c else None
        if roles[t["target"]] != "oracle":
            problems.append(f"{t['target']}: PerfMatch role is {roles[t['target']]!r}, not 'oracle'")
    count = lambda tab: sum(i["ok"] for i in items if i["table"] == tab and i["column"] != "Average")
    return {"items": items, "perfmatch_role": roles, "problems": problems,
            "table1_target_ok": f"{count(TABLE1)}/{len(golden['table1_target'])}",
            "table11_cells_ok": f"{count(TABLE11)}/{sum(len(v) for v in golden['table11'].values())}",
            "table11_average_ok": f"{sum(i['ok'] for i in items if i['column'] == 'Average')}/"
                                  f"{len(golden['table11_average'])}",
            "ok": not problems}


def _cells_by_id(links: dict, target: str) -> dict[str, dict]:
    t = next(t for t in links["tables"] if t["target"] == target)
    return {c["claim_ids"][0]: c for c in t["cells"] if c["status"] == "linked"}


def _ignored(spec: dict, runs_option: Optional[str]) -> list[str]:
    return [a["dest"] for a in spec["actions"]
            if "seed" in a["dest"] or (runs_option and runs_option in a["option_strings"])]


def check_commands(links: dict, claims: dict, hand1: dict, hand11: dict, probe: Callable, runs_option) -> dict:
    """probe(script, tails) -> argspec spec with results, in the dry-run worktree."""
    hand_argv = [s["argv"] for steps in list(hand1.values()) + list(hand11.values()) for s in steps]
    by_script: dict[str, list[tuple]] = {}
    for a in hand_argv:
        by_script.setdefault(a[1], [])
        if tuple(a[2:]) not in by_script[a[1]]:
            by_script[a[1]].append(tuple(a[2:]))
    specs, ns = {}, {}
    for script, tails in by_script.items():
        spec = probe(script, tails)
        specs[script] = spec
        for t, r in zip(tails, spec["results"]):
            if not r.get("ok"):
                raise RuntimeError(f"the hand-written command {script} {' '.join(t)} does not parse: {r.get('error')}")
            ns[(script, t)] = r["namespace"]

    items, problems = [], []

    def compare(unit: str, ours: list[dict], theirs: list[dict]):
        rec = {"unit": unit, "ours": [s["argv"] for s in ours], "hand": [s["argv"] for s in theirs],
               "hand_source": theirs[0]["source"] if theirs else None, "steps": [], "ok": True}
        if len(ours) != len(theirs):
            rec.update(ok=False, problem=f"{len(ours)} steps, the hand-written command has {len(theirs)}")
        else:
            for o, h in zip(ours, theirs):
                if o["argv"][1] != h["argv"][1]:
                    rec["steps"].append({"ok": False, "problem": f"script {o['argv'][1]} != {h['argv'][1]}"})
                    rec["ok"] = False
                    continue
                if o.get("namespace") is None:
                    rec["steps"].append({"ok": False, "problem": "our command does not parse"})
                    rec["ok"] = False
                    continue
                ign = _ignored(specs[h["argv"][1]], runs_option)
                hn = ns[(h["argv"][1], tuple(h["argv"][2:]))]
                diff = argspec.diff_namespaces(o["namespace"], hn, ignore=ign)
                seeds = argspec.diff_namespaces({k: o["namespace"].get(k) for k in ign}, {k: hn.get(k) for k in ign})
                rec["steps"].append({"script": h["argv"][1], "ok": not diff, "differences": diff,
                                     "seed_plumbing_differences": seeds})
                rec["ok"] &= not diff
        items.append(rec)
        if not rec["ok"]:
            problems.append(f"{unit}: {rec.get('problem') or [s for s in rec['steps'] if not s['ok']]}")

    t1 = _cells_by_id(links, TABLE1)
    t1_table = _table(claims, TABLE1)
    for key, steps in hand1.items():
        ours, seen = [], set()
        for c in t1_table["cards"]:
            if _norm(c["source"]["row"]) == _norm(LABELS[key]) and c["claim_id"] in t1:
                for s in t1[c["claim_id"]]["steps"]:
                    if tuple(s["argv"]) not in seen:
                        seen.add(tuple(s["argv"]))
                        ours.append(s)
        compare(f"{TABLE1} {LABELS[key]}", ours, steps)
    t11 = _cells_by_id(links, TABLE11)
    t11_table = _table(claims, TABLE11)
    for (key, d), steps in hand11.items():
        c = _card(t11_table, LABELS[key], d)
        cell = t11.get(c["claim_id"]) if c else None
        compare(f"{TABLE11} {LABELS[key]}/{d}", cell["steps"] if cell else [], steps)
    n1 = [i for i in items if i["unit"].startswith(TABLE1 + " ")]
    n11 = [i for i in items if i["unit"].startswith(TABLE11)]
    return {"items": items, "problems": problems, "ignored_dests": sorted({d for s in specs.values()
                                                                          for d in _ignored(s, runs_option)}),
            "table1_rows_ok": f"{sum(i['ok'] for i in n1)}/{len(n1)}",
            "table11_cells_ok": f"{sum(i['ok'] for i in n11)}/{len(n11)}",
            "seed_plumbing_differences": sum(bool(s.get("seed_plumbing_differences")) for i in items
                                             for s in i["steps"]),
            "ok": not problems}


def check_parsers(paths: Paths, links: dict, claims: dict, hand1: dict, hand11: dict) -> dict:
    """Each linked cell's parser on every spike log of its step, against parse_train / parse_eval."""
    items, problems = [], []
    n_logs = n_values = 0
    log_dirs = sorted(p for p in paths.logs.iterdir() if p.is_dir())

    def one(unit: str, column: str, cell: dict, hand_steps: list[dict], parsers: dict):
        nonlocal n_logs, n_values
        spec = parsers[cell["parser"]]
        idx = [s["name"] for s in cell["steps"]].index(spec["step"])
        log_name = hand_steps[idx]["log"] if idx < len(hand_steps) else None
        rec = {"unit": unit, "column": column, "parser": spec["name"], "log_name": log_name, "logs": 0,
               "values": 0, "mismatches": []}
        for d in log_dirs:
            f = d / log_name if log_name else None
            if not f or not f.exists():
                continue
            got = parser_spec.apply(spec, f, paths.cite)["blocks"]
            if column in SOURCE_COLUMNS:
                ref = parse_eval(f, paths.cite).get(SOURCE_COLUMNS[column])
                if ref is None:
                    continue
                vals = [b for b in got if b["value"] is not None]
                if spec.get("run_start_regex"):
                    # per-run values: parse_runs has only test.py's summary line for these columns, so the per-run
                    # values must average to its mean (2 decimals, as parse_eval rounds)
                    rec["comparison"] = "mean of per-run values = parse_eval mean"
                    ours = round(st.mean(b["value"] for b in vals), 2) if vals else None
                    theirs = ref["mean"]
                    n = len(vals)
                else:
                    rec["comparison"] = "parse_eval (mean, sd, line)"
                    ours = (round(vals[-1]["value"], 2), round(vals[-1]["sd"], 2) if vals[-1]["sd"] is not None
                            else None, vals[-1]["line"]) if vals else None
                    theirs = (ref["mean"], ref["sd"], ref["line"])
                    n = 1
            else:
                try:
                    ref = parse_train(f, paths.cite)
                except Exception:
                    continue
                rec["comparison"] = "parse_train per seed (run, value, line)"
                ours = [(b["run"], b["value"], b["line"]) for b in got if b["value"] is not None]
                theirs = [(str(r["seed_run"]), r["target_acc"], r["line"]) for r in ref["per_seed"]]
                n = len(theirs)
            rec["logs"] += 1
            rec["values"] += n
            if ours != theirs:
                rec["mismatches"].append({"log": paths.cite(f), "ours": ours, "parse_runs": theirs})
        n_logs += rec["logs"]
        n_values += rec["values"]
        if rec["logs"] == 0:
            rec["mismatches"].append({"log": None, "problem": f"no spike log named {log_name!r}"})
        items.append(rec)
        if rec["mismatches"]:
            problems.append(f"{unit}/{column}: {rec['mismatches'][:2]}")

    for target, hand in ((TABLE1, hand1), (TABLE11, hand11)):
        t = next(t for t in links["tables"] if t["target"] == target)
        parsers = {p["name"]: p for p in t["parsers"]}
        cells = _cells_by_id(links, target)
        tab = _table(claims, target)
        for key_d, steps in hand.items():
            key, d = (key_d, None) if isinstance(key_d, str) else key_d
            cols = tab["columns"] if d is None else [d]
            for col in cols:
                c = _card(tab, LABELS[key], col)
                cell = cells.get(c["claim_id"]) if c else None
                if cell is None or cell.get("parser") not in parsers:
                    if d is None and col not in ("Target",) and col not in SOURCE_COLUMNS:
                        continue
                    items.append({"unit": f"{target} {LABELS[key]}", "column": col, "mismatches": ["not linked"]})
                    problems.append(f"{target} {LABELS[key]}/{col}: not linked")
                    continue
                one(f"{target} {LABELS[key]}", col, cell, steps, parsers)
    return {"items": items, "problems": problems, "logs_compared": n_logs, "values_compared": n_values,
            "ok": not problems}


SHAPE_RE = re.compile(r"Data Case:.*Shape:")


def _shape_lines(log: Path) -> list[str]:
    text = log.read_text(errors="replace").replace("\r", "\n")
    return [" ".join(l.split()) for l in text.splitlines() if SHAPE_RE.search(l)]


def check_data(paths: Paths, links: dict, audit_dir: Path) -> dict:
    """Table 1: the data command equals the spike's (run_table1_rest.sh:11). Table 11: the spike did not keep its MNIST
    data command, but its log of the shipped generator (logs/matchdg_lenet/datagen.log, at 45e7771) prints every
    generated split's shape; our data step's log must print the same lines, in the same order."""
    items, problems = [], []
    rest = (paths.spike / "scripts" / "run_table1_rest.sh").read_text().splitlines()
    k = next(i for i, l in enumerate(rest) if "data_gen" in l)
    hand, _ = _command(rest[k], {})
    t1 = next(t for t in links["tables"] if t["target"] == TABLE1)
    ours = [d["argv"] for d in t1["data_steps"]]
    ok = ours == [hand] and all((d.get("dry_run") or {}).get("exit_code") == 0 for d in t1["data_steps"])
    items.append({"table": TABLE1, "ours": ours, "hand": hand, "hand_source": f"scripts/run_table1_rest.sh:{k + 1}",
                  "ok": ok})
    if not ok:
        problems.append(f"{TABLE1} data step {ours} != {hand} (or it did not run)")
    t11 = next(t for t in links["tables"] if t["target"] == TABLE11)
    ref = paths.logs / "matchdg_lenet" / "datagen.log"
    theirs = _shape_lines(ref)
    for d in t11["data_steps"]:
        log = (d.get("dry_run") or {}).get("log")
        mine = _shape_lines(audit_dir / log) if log and (audit_dir / log).exists() else []
        ok = bool(theirs) and mine == theirs
        items.append({"table": TABLE11, "ours": d["argv"], "log": log, "reference": paths.cite(ref),
                      "shape_lines": len(mine), "reference_shape_lines": len(theirs), "ok": ok,
                      "first_difference": next(({"ours": a, "spike": b} for a, b in zip(mine, theirs) if a != b), None)})
        if not ok:
            problems.append(f"{TABLE11} data step {' '.join(d['argv'])}: {len(mine)} shape lines, the spike's "
                            f"{paths.cite(ref)} has {len(theirs)}; first difference "
                            f"{items[-1]['first_difference']}")
    if not t11["data_steps"]:
        problems.append(f"{TABLE11}: no data step")
    return {"items": items, "problems": problems, "ok": not problems}


def blind_agreement(paths: Paths, claims: dict) -> dict:
    t1 = _table(claims, TABLE1)
    out = {}
    for f in sorted(paths.extraction_outputs.glob("paper_run*.json")):
        runs = json.loads(f.read_text()).get("claims") or []
        eq = tot = 0
        for r in runs:
            c = _card(t1, r.get("method", ""), r.get("column", ""))
            if c is None:
                continue
            tot += 1
            eq += c["reported"]["mean"] == r.get("mean") and c["reported"]["sd"] == r.get("sd")
        out[f.stem] = f"{eq}/{tot}"
    return out


def run_check(paths: Paths, cfg: AuditConfig, probe: Callable) -> dict:
    claims = load_claims(paths, cfg.id)
    lp = paths.audit_dir(cfg.id) / "links.json"
    if not lp.exists():
        raise FileNotFoundError(f"{lp} is missing: run `el01 link {cfg.id}` first")
    links = json.loads(lp.read_text())
    golden = json.loads((paths.golden / "claims.json").read_text())
    hand1, hand11 = handwritten_table1(paths.spike), handwritten_table11(paths.spike)
    out = {"cards": check_cards(claims, golden),
           "commands": check_commands(links, claims, hand1, hand11, probe, cfg.link.runs_option),
           "parsers": check_parsers(paths, links, claims, hand1, hand11),
           "data": check_data(paths, links, paths.audit_dir(cfg.id)),
           "blind_agreement": blind_agreement(paths, claims),
           "dry_run": {t["target"]: {"linked": t["counts"]["linked"], "derived": t["counts"]["derived"],
                                     "linked_valid": sum(c.get("valid", False) for c in t["cells"]
                                                         if c["status"] == "linked"),
                                     "derived_valid": sum(c.get("valid", False) for c in t["cells"]
                                                          if c["status"] == "derived"),
                                     "agent_calls": len(t.get("calls", [t.get("call")]))}
                       for t in links["tables"]},
           "run_head": links["run_head"]}
    out["pass"] = out["cards"]["ok"] and out["commands"]["ok"] and out["parsers"]["ok"] and out["data"]["ok"] and all(
        all(c.get("valid") for c in t["cells"] if c["status"] == "linked") for t in links["tables"])
    (paths.audit_dir(cfg.id) / "link_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out
