"""`el01 <command>`."""
import json
from pathlib import Path
from typing import Optional

import typer

from el01.config import Paths

app = typer.Typer(no_args_is_help=True, add_completion=False, help="ClaimTrace: claim-level reproducibility auditor")

SPIKE_OPT = typer.Option(None, "--spike", help="The spike folder (default: inputs/spike-matchdg).")
LOGS_OPT = typer.Option(None, "--logs", help="The extracted spike logs (default: workspace/spike/logs).")


@app.command()
def regress(spike: Optional[Path] = SPIKE_OPT, logs: Optional[Path] = LOGS_OPT):
    """Re-derive every MatchDG result from the raw logs and compare with <spike>/golden/ and the spike's files."""
    from el01.grade.spike.regress import run_regression
    paths = Paths.make(spike=spike, logs=logs)
    rep = run_regression(paths)
    paths.regress_out.mkdir(parents=True, exist_ok=True)
    (paths.regress_out / "last_check.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(f"{rep['graded_items_checked']} graded items ({rep['verdict_labels_checked']} verdicts) + "
          f"{rep['extraction_checks']} extraction checks: {len(rep['mismatches'])} mismatches")
    for m in rep["mismatches"][:20]: print(" ", m)
    print(f"{rep['file_checks']} regenerated files vs the spike's copies (cited logs normalised to logs/<run>/<file>): "
          f"{len(rep['file_mismatches'])} mismatches")
    for m in rep["file_mismatches"][:10]:
        print(" ", m["file"])
        for d in m["differences"][:5]: print("    ", d)
    raise typer.Exit(0 if rep["pass"] else 1)


@app.command("grade-spike")
def grade_spike(spike: Optional[Path] = SPIKE_OPT, logs: Optional[Path] = LOGS_OPT,
                out: Optional[Path] = typer.Option(None, "--out", help="Audit folder (default: audits/matchdg).")):
    """Parse the spike logs and grade them: writes <out>/metrics/<run>.json, <out>/metrics/epochs.json, <out>/grades*.json."""
    from el01.grade.spike.regress import GRADE_FILES, grade_all, parse_all
    paths = Paths.make(spike=spike, logs=logs, audit=out)
    parsed = parse_all(paths)
    graded = grade_all(paths, parsed)
    mdir = paths.audit / "metrics"
    mdir.mkdir(parents=True, exist_ok=True)
    for run, m in parsed["metrics"].items():
        (mdir / f"{run}.json").write_text(json.dumps(m, indent=1))
    (mdir / "epochs.json").write_text(json.dumps(parsed["epochs"], indent=1))
    for key, name in GRADE_FILES.items():
        if key in graded:
            (paths.audit / name).write_text(json.dumps(graded[key], indent=1))
    print(f"parsed {len(parsed['metrics'])} run directories -> {mdir.relative_to(paths.root) if mdir.is_relative_to(paths.root) else mdir}")
    print(f"per-epoch traces skipped (no selection trace): {len(parsed['epochs_skipped'])}")
    t1 = graded["table1"]
    print("Table 1:", ", ".join(f"{v['method']} {v['label']}" for v in t1["absolute"].values()))
    print("Table 1 relative:", ", ".join(f"{k} {v['label']}" for k, v in t1["relative"].items()))
    for name in ("table11_first", "table11_confirm"):
        g = graded.get(name)
        if not g: continue
        labels = [v["label"] for cells in g["cells"].values() for v in cells.values()] + [v["label"] for v in g["average"].values()]
        counts = {lab: labels.count(lab) for lab in sorted(set(labels))}
        print(f"{name} ({g['run_dir']}): cells + averages {counts}; relative:",
              ", ".join(f"{k} {v['label']}" for k, v in g["relative"].items()))
    if "f7" in graded:
        a = graded["f7"]["average"]
        print(f"F7 six-domain average effect {a['effect']:+.2f} (95% CI {a['ci95'][0]} to {a['ci95'][1]}), excludes 0: {a['excludes_zero']}")
    print("wrote:", ", ".join(n for k, n in GRADE_FILES.items() if k in graded))


@app.command("run-shipped")
def run_shipped_cmd(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml.")):
    """Run the smoke command as shipped (no repairs) and classify the first failure. Writes audits/<id>/run_as_shipped.json."""
    from el01.config import AuditConfig
    from el01.run.shipped import run_shipped
    paths = Paths.make()
    s = run_shipped(paths, AuditConfig.for_audit(paths, audit_id))
    print(f"commit {s['commit'][:7]}; env python {s['env']['python']}, torch {s['env']['torch']}, numpy {s['env']['numpy']}")
    if s["data_step"]:
        d = s["data_step"]
        print(f"data step: {' '.join(d['command'])}: {d['status']} (exit {d['exit_code']}) in {d['seconds']}s -> {d['log']}")
    r = s["run"]
    print(f"run as shipped: {' '.join(r['command'])}\n  {r['status']} (exit {r['exit_code']}) in {r['seconds']}s -> {r['log']}")
    f = s["failure"]
    if f is None:
        print("outcome: ran without a failure")
        return
    print(f"first failure: {f['class']} ({f['rule']})")
    print(f"  {f['exception']}: {f['message']}")
    if f.get("raised_at"):
        print(f"  raised at {f['raised_at']['file']}:{f['raised_at']['line']} ({f['log']}:{f['raised_at']['log_line']})")
    if f.get("origin"):
        print(f"  path literal at {f['origin']['file']}:{f['origin']['line']}: {f['origin']['literal']!r}")
    if f.get("same_name_in_worktree"):
        print(f"  a file with that name exists in the worktree: {f['same_name_in_worktree'][0]}")
    print(f"  location: {f['location']}  (exception at {f['log']}:{f['log_line']})")


LLM_OPT = typer.Option("replay", "--llm", help="replay (default, no quota) | live | claude_cli | anthropic_api.")


@app.command()
def repair(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."),
           llm: str = LLM_OPT,
           max_attempts: int = typer.Option(5, "--max-attempts", help="Repair attempts before the verdict Not runnable."),
           restart: bool = typer.Option(False, "--restart", help="Delete a previous repair run (branches, runs, records) first.")):
    """Repair loop: run the smoke command, let the repair agent patch failures, commit REPAIR / HYPOTHESIS. Writes audits/<id>/repair.json."""
    from el01.config import AuditConfig
    from el01.llm.backend import LLM, LLMError
    from el01.repair.agent import RepairError, run_repair
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    backend = LLM(llm, cache_dir=paths.root / ".cache" / "llm", usage_log=paths.audit_dir(audit_id) / "llm_usage.jsonl")
    try:
        rec = run_repair(paths, cfg, backend, max_attempts=max_attempts, restart=restart)
    except (RepairError, LLMError) as e:
        print(f"repair stopped: {e}")
        raise typer.Exit(1)
    c = rec["counts"]
    print(f"verdict: {rec['verdict']}" + (f" ({rec['verdict_reason']})" if rec.get("verdict_reason") else ""))
    print(f"runs {c['runs']}, agent calls {c['agent_calls']} (cache hits {c['cache_hits']}, misses {c['cache_misses']}), "
          f"repair attempts {c['repair_attempts']}, recorded cost ${c['cost_usd_recorded']}")
    for r in rec["repairs"]:
        print(f"  {r['commit'][:7]} {r['message'][:150]}")
    for h in rec["hypotheses"]:
        print(f"  {h['commit'][:7]} {h['message'][:150]}  [{h['branch']}, {'run by the loop' if h['run_by_loop'] else 'not run'}]")
    for i in rec["inertness"]:
        print(f"  inertness {i['repair'][:7]}: {i['verdict']}: {i['summary']}")
    print("branches:", ", ".join(f"{b} {s[:7]}" for b, s in rec["branches"].items()))
    raise typer.Exit(0 if rec["verdict"] == "runs" else 1)


@app.command("repair-compare")
def repair_compare(audit_id: str = typer.Argument(..., help="Audit id."),
                   ours: list[str] = typer.Option(..., "--ours", help="Reference repair commits, in order (repeat the option)."),
                   hypothesis: Optional[str] = typer.Option(None, "--hypothesis", help="Reference commit for the missing-domain hypothesis."),
                   test_domain: Optional[str] = typer.Option(None, "--test-domain", help="Test domain for the repairs-only smoke run (one the shipped generator builds).")):
    """Compare the repair agent's commits and smoke results with reference commits. Writes audits/<id>/repair/compare.json."""
    from el01.config import AuditConfig
    from el01.repair.compare import compare
    paths = Paths.make()
    out = compare(paths, AuditConfig.for_audit(paths, audit_id), ours, hypothesis, test_domain)
    rc = out["repair_count"]
    print(f"repair commits: agent {rc['agent']}, ours {rc['ours']} ({'equal' if rc['equal'] else 'NOT equal'})")
    for r in out["repairs"] + ([out["hypothesis"]] if out["hypothesis"] else []):
        print(f"  ours {r['ours'][:7]} {r['ours_subject'][:70]}")
        print(f"    agent {(r['agent'] or '-------')[:7]} {r.get('agent_subject', '')[:100]}")
        print(f"    {r['level']}: files {r['ours_files']}, removed lines {r['ours_removed']}")
    for run in out["runs"]:
        print(f"smoke {run['label']}: both ran {run['both_ran']}; metric lines identical {run['metric_lines_identical']} "
              f"({run['metric_lines_compared']})")
        for who in ("agent", "ours"):
            for l in run["final_lines"][who]:
                print(f"    {who:5s} {l}")
    for i in out["inertness"]:
        print(f"inertness {i['repair'][:7]}: {i['verdict']}: {i['summary']}")
    print("pass" if out["pass"] else "FAIL")
    raise typer.Exit(0 if out["pass"] else 1)


def _llm(paths: Paths, audit_id: str, mode: str):
    from el01.llm.backend import LLM
    return LLM(mode, cache_dir=paths.root / ".cache" / "llm", usage_log=paths.audit_dir(audit_id) / "llm_usage.jsonl")


@app.command()
def claims(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."), llm: str = LLM_OPT):
    """Claim cards for the audit's target tables: the paper extractor reads the PDFs' text; code checks every number
    against the table row on its page. Writes audits/<id>/claims.json."""
    from el01.config import AuditConfig
    from el01.extract.claims import extract_claims
    from el01.llm.backend import LLMError
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    try:
        out = extract_claims(paths, cfg, _llm(paths, audit_id, llm))
    except LLMError as e:
        print(f"claims stopped: {e}")
        raise typer.Exit(1)
    c = out["counts"]
    print(f"{c['cells_valid']}/{c['cells']} cells verified, {c['relative']} relative/trend claims; agent calls "
          f"{c['agent_calls']} (cache hits {c['cache_hits']}), recorded cost ${c['cost_usd_recorded']}")
    for t in out["tables"]:
        roles = {}
        for r in t["rows"]:
            roles.setdefault(r["role"], []).append(r["label"] + (" (cited)" if r["provenance"] == "cited" else ""))
        print(f"  {t['target']}: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(roles.items())))
    raise typer.Exit(0 if c["cells_valid"] == c["cells"] else 1)


@app.command("link")
def link_cmd(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."), llm: str = LLM_OPT,
             dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Run every linked command for 1 epoch.")):
    """Claim-to-command links: the linker proposes commands and parser specs per claim cell; code checks each option
    against the script's own parser, dry-runs it and checks the parser on its log. Writes audits/<id>/links.json."""
    from el01.config import AuditConfig
    from el01.link.linker import LinkError, link
    from el01.llm.backend import LLMError
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    try:
        out = link(paths, cfg, _llm(paths, audit_id, llm), dry_run=dry_run)
    except (LinkError, LLMError) as e:
        print(f"link stopped: {e}")
        raise typer.Exit(1)
    ok = all(c.get("valid") for t in out["tables"] for c in t["cells"] if c["status"] == "linked")
    print(f"agent calls {out['counts']['agent_calls']} (cache hits {out['counts']['cache_hits']}), recorded cost "
          f"${out['counts']['cost_usd_recorded']}; every linked cell valid: {ok}")
    raise typer.Exit(0 if ok else 1)


@app.command("link-check")
def link_check(audit_id: str = typer.Argument("matchdg", help="Audit id (the MatchDG acceptance)."),
               spike: Optional[Path] = SPIKE_OPT, logs: Optional[Path] = LOGS_OPT):
    """Phase 4 acceptance on MatchDG: cards vs golden/claims.json, commands vs the spike's run scripts, parser specs
    vs parse_runs on the spike logs. Writes audits/<id>/link_check.json."""
    from el01.config import AuditConfig
    from el01.link import argspec
    from el01.link.linker import make_ctx
    from el01.link.spike import run_check
    paths = Paths.make(spike=spike, logs=logs)
    cfg = AuditConfig.for_audit(paths, audit_id)
    ctx = make_ctx(paths, cfg, None, print)
    out = run_check(paths, cfg, lambda script, tails: argspec.probe(ctx.py, ctx.wt, script, tails))
    cd, cm, ps = out["cards"], out["commands"], out["parsers"]
    print(f"Table 1: {cd['table1_target_ok']} target cells = golden; PerfMatch role: {cd['perfmatch_role'].get('Table 1')}")
    print(f"Table 11: {cd['table11_cells_ok']} cells + {cd['table11_average_ok']} averages = golden; PerfMatch role: "
          f"{cd['perfmatch_role'].get('Suppl. Table 11')}")
    print(f"commands: Table 1 {cm['table1_rows_ok']} rows (train + eval), Table 11 {cm['table11_cells_ok']} cells "
          f"equal as normalised argument dicts (ignored: {', '.join(cm['ignored_dests'])}; "
          f"{cm['seed_plumbing_differences']} steps differ only there)")
    print(f"parser specs: {ps['values_compared']} values in {ps['logs_compared']} spike logs; "
          f"{len(ps['problems'])} mismatches with parse_runs")
    for d in out["data"]["items"]:
        extra = (f"; {d['shape_lines']} split shapes vs the spike's {d['reference_shape_lines']} "
                 f"({d['reference']})") if "shape_lines" in d else f" (spike: {' '.join(d['hand'])}, {d['hand_source']})"
        print(f"data step {d['table']}: {' '.join(d['ours'] if 'shape_lines' in d else d['ours'][0] if d['ours'] else [])}"
              f"{extra}: {'equal' if d['ok'] else 'DIFFERENT'}")
    print("dry runs:", "; ".join(f"{k}: {v['linked_valid']}/{v['linked']} linked cells ran and parsed, "
                                 f"{v['derived_valid']}/{v['derived']} derived cells valid ({v['agent_calls']} linker calls)"
                                 for k, v in out["dry_run"].items()))
    print("blind extraction runs (Table 1 cells equal):", ", ".join(f"{k} {v}" for k, v in out["blind_agreement"].items()))
    for p in (cd["problems"] + cm["problems"] + ps["problems"] + out["data"]["problems"])[:20]:
        print("  ", str(p)[:300])
    print("pass" if out["pass"] else "FAIL")
    raise typer.Exit(0 if out["pass"] else 1)


@app.command("settings")
def settings_cmd(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."), llm: str = LLM_OPT,
                 runs: int = typer.Option(2, "--runs", help="Runs per side per table (the spec asks for two)."),
                 jobs: int = typer.Option(4, "--jobs", help="Agent calls at a time.")):
    """Settings diff (schema v2): the paper extractor reads the PDFs' text, the code extractor a snapshot of the audited
    commit; code checks every quote and file:line citation, measures agreement between runs and diffs every paper x
    code pairing. Writes audits/<id>/settings.json and settings_diff.json."""
    from el01.config import AuditConfig
    from el01.extract.settings import extract_settings
    from el01.llm.backend import LLMError
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    try:
        out = extract_settings(paths, cfg, _llm(paths, audit_id, llm), runs=runs, jobs=jobs)
    except (LLMError, ValueError, FileNotFoundError) as e:
        print(f"settings stopped: {e}")
        raise typer.Exit(1)
    s, d = out["settings"], out["diff"]
    for t, dt in zip(s["tables"], d["tables"]):
        agree = "; ".join(f"{side} runs: same {a['counts']['same']}, differ {a['counts']['differ']}, one null "
                          f"{a['counts']['one_null']}, both null {a['counts']['both_null']}"
                          for side, a in t["agreement"].items())
        print(f"{t['target']}: agreement between runs ({len(t['agreement'].get('paper', {}).get('per_key', {}))} keys): "
              f"{agree}")
        sizes = ", ".join(f"{p.replace(' x ', 'x')} {len(fs)}" for p, fs in dt["pairings"].items())
        print(f"  findings per pairing: {sizes}; in every pairing {len(dt['in_all_pairings'])}, in some "
              f"{len(dt['in_some_pairings'])}")
    c = s["counts"]
    print(f"agent calls {c['agent_calls']} (cache hits {c['cache_hits']}), recorded cost ${c['cost_usd_recorded']}")


PHASE6_TAG = "phase6"


def _llm_capped(paths: Paths, cfg, mode: str):
    """The LLM for Phase 6's agents: usage lines tagged, live calls refused past audit.yaml `ablation.llm_cap_usd`."""
    from el01.llm.backend import LLM
    from el01.llm.budget import Cap
    log = paths.audit_dir(cfg.id) / "llm_usage.jsonl"
    cap = cfg.ablation.llm_cap_usd if cfg.ablation else None
    return LLM(mode, cache_dir=paths.root / ".cache" / "llm", usage_log=log, tag=PHASE6_TAG,
               guard=Cap(log, cap, PHASE6_TAG) if cap is not None else None)


@app.command("branches")
def branches_cmd(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."), llm: str = LLM_OPT,
                 restart: bool = typer.Option(False, "--restart", help="Delete earlier branches and records first."),
                 only: Optional[str] = typer.Option(None, "--only", help="Comma-separated findings, e.g. F2,F3.")):
    """Branch-patch writer: one HYPOTHESIS branch per numbered finding and reading off the baseline, each self-checked
    by re-running the code extractor (exactly one changed setting). Writes audits/<id>/branches.json."""
    from el01.branch.writer import BranchError, run_branches
    from el01.config import AuditConfig
    from el01.llm.backend import LLMError
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    try:
        rec = run_branches(paths, cfg, _llm_capped(paths, cfg, llm), restart=restart,
                           only=only.split(",") if only else None)
    except (BranchError, LLMError) as e:
        print(f"branches stopped: {e}")
        raise typer.Exit(1)
    for f in rec["findings"]:
        for r in f["readings"]:
            print(f"{f['finding']} [{r['label']}]: {r['status']}" + (f" {r['branch']} {r['commit'][:7]}: {r['message']}"
                                                                    if r["status"] == "written" else
                                                                    f" ({r['attempts'][-1]['reason'] if r.get('attempts') else r.get('reason')})"))
    c = rec["counts"]
    print(f"written {c['written']}, not written {c['not_written']}; agent calls {c['agent_calls']} (cache hits "
          f"{c['cache_hits']}, misses {c['cache_misses']}), recorded cost ${c['cost_usd_recorded']}")


@app.command("ablate")
def ablate_cmd(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."),
               run_set: str = typer.Option(..., "--set", help="exploratory | confirm | interaction"),
               prereg: bool = typer.Option(False, "--prereg", help="Write the pre-registration (then commit it)."),
               grade: bool = typer.Option(False, "--grade", help="Only grade the finished run sets."),
               table: str = typer.Option("Table 1", "--table", help="The table whose branches run."),
               llm: str = LLM_OPT):
    """Diff-guided ablation: --prereg writes audits/<id>/prereg/<set>.{json,txt} (commit it before running); without
    it the pre-registered set runs (refused if the pre-registration is missing, uncommitted or stale) and every
    finished set is graded into audits/<id>/ablation/grades.json."""
    from el01.branch import ablate as A
    from el01.config import AuditConfig
    from el01.grade.ablation import AblationError
    from el01.grade.prereg import PreregError
    from el01.llm.backend import LLMError
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    try:
        ctx = A.Ctx(paths, cfg, table, print)
        if prereg:
            if run_set == "exploratory":
                plan = A.plan_exploratory(ctx)
            elif run_set == "confirm":
                plan = A.plan_confirm(ctx, _llm_capped(paths, cfg, llm), print)
            elif run_set == "interaction":
                plan = A.plan_interaction(ctx)
            else:
                raise A.AblateError(f"unknown run set {run_set!r}")
            rec = A.write_prereg(ctx, run_set, plan)
            print(f"pre-registered {run_set}: {len(rec['plan']['arms'])} arms, {len(rec['plan']['family'])} effects, "
                  f"seeds {rec['plan']['seeds'][0]}-{rec['plan']['seeds'][-1]} (graded "
                  f"{rec['plan']['seeds_graded'][0]}-{rec['plan']['seeds_graded'][-1]}); written {rec['written_utc']}")
            for a, x in rec["plan"]["arms"].items():
                print(f"  {a}: {x['commit'][:7]} {', '.join(x['methods'])}")
            for a, why in (rec["plan"].get("not_measured") or {}).items():
                print(f"  {a}: not measured: {why}")
            print(f"commit audits/{cfg.id}/prereg/{run_set}.json and .txt before running")
            return
        if not grade:
            r = A.run_set(ctx, run_set)
            print(f"{run_set}: {r['jobs']} training jobs done")
        g = A.grade_sets(ctx)
    except (A.AblateError, AblationError, PreregError, LLMError) as e:
        print(f"ablate stopped: {e}")
        raise typer.Exit(1)
    e = g["exploratory"]
    print(f"exploratory family ({', '.join(e['run_sets'])}): {e['family_size']} effects, Holm at alpha {e['alpha']}")
    for arm, d in e["effects"].items():
        for m, x in d.items():
            if isinstance(x, dict):
                print(f"  {arm:14s} {m:10s} {x['effect']:+7.2f} [{x['ci'][0]:+.2f}, {x['ci'][1]:+.2f}] p {x['p']:.1e} "
                      f"holm {x['p_holm']:.1e} {'survives' if x['survives_holm'] else '-':8s} sel.ep "
                      f"{x.get('selected_epoch_median')} src.val {x.get('source_val_acc')} "
                      f"({x['per_seed'][0]['branch']['log']}:{x['per_seed'][0]['branch']['line']})")
    for a, why in (g.get("not_measured") or {}).items():
        print(f"  {a}: not measured: {why}")
    if "confirmation" in g:
        c = g["confirmation"]
        for arm, d in c["effects"].items():
            for m, x in d.items():
                if isinstance(x, dict):
                    print(f"confirmation {arm}/{m} seeds {c['seeds'][0]}-{c['seeds'][-1]}: {x['effect']:+.2f} "
                          f"[{x['ci'][0]:+.2f}, {x['ci'][1]:+.2f}] p {x['p']:.1e}")
        for k, v in c["determinism"].items():
            print(f"  determinism {k} vs {v['compared_with']}: {v['equal']}/{v['seeds']} seeds equal")
    if "interaction" in g:
        i = g["interaction"]
        for m, r in i["methods"].items():
            singles = ", ".join(f"{p} {s['effect']:+.2f}" for p, s in r["singles"].items() if s)
            print(f"interaction {i['arm']}/{m}: combined {r['combined']['effect']:+.2f} {r['combined']['ci']}; "
                  f"single effects {singles}; sum {r.get('sum_of_single_effects')}")


@app.command("branch-check")
def branch_check(audit_id: str = typer.Argument("matchdg", help="Audit id (the MatchDG acceptance)."),
                 ref: list[str] = typer.Option(..., "--ref", help="name=reference branch (repeat)."),
                 ref_base: str = typer.Option(..., "--ref-base", help="The references' baseline commit."),
                 effect: Optional[str] = typer.Option(None, "--effect", help="name:method, e.g. h1:perfmatch: the "
                                                      "branch equivalent to reference `name` must move `method` "
                                                      "down, CI excluding 0, surviving Holm."),
                 table: str = typer.Option("Table 1", "--table")):
    """Phase 6 acceptance: written branches vs reference branches (diff + behaviour, read-only) and one ablation effect.
    Writes audits/<id>/branch_check.json."""
    from el01.branch.compare import compare_refs, effect_check
    from el01.config import AuditConfig
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    refs = dict(r.split("=", 1) for r in ref)
    out = compare_refs(paths, cfg, refs, ref_base, table)
    for name, v in out["refs"].items():
        print(f"{name}: {'equivalent: ' + v['equivalent_branch'] if v['equivalent_branch'] else 'NO equivalent branch'}")
    if effect:
        name, method = effect.split(":")
        b = out["refs"][name]["equivalent_branch"]
        out["effect"] = effect_check(paths, cfg, b, method) if b else {"pass": False, "reason": f"no branch for {name}"}
        x = out["effect"]
        print(f"effect {name} ({b}) on {method}: " + (f"{x['effect']:+.2f} [{x['ci'][0]:+.2f}, {x['ci'][1]:+.2f}], "
              f"p {x['p']:.1e}, Holm p {x['p_holm']:.1e} over {x['family_size']} effects, survives "
              f"{x['survives_holm']}; baseline {x['base_mean']} -> branch {x['branch_mean']} ({x['cites'][0]})"
              if "effect" in x else x["reason"]))
        out["pass"] = out["pass"] and x["pass"]
    (paths.audit_dir(audit_id) / "branch_check.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("pass" if out["pass"] else "FAIL")
    raise typer.Exit(0 if out["pass"] else 1)


@app.command("settings-check")
def settings_check(audit_id: str = typer.Argument("matchdg", help="Audit id (the MatchDG acceptance)."),
                   spike: Optional[Path] = SPIKE_OPT):
    """Phase 5 acceptance on MatchDG: Table 1 findings vs golden/findings.json (F1-F6), Table 11's data-pipeline
    finding (F7, SciCoQA row 67); every other finding listed as new, unverified. Writes
    audits/<id>/extraction_score.json."""
    from el01.diff.spike import run_check, short
    paths = Paths.make(spike=spike)
    try:
        out = run_check(paths, audit_id)
    except FileNotFoundError as e:
        print(f"settings-check stopped: {e}")
        raise typer.Exit(1)
    for name, key in (("Table 1", "table1"), ("Suppl. Table 11", "table11")):
        t = out[key]
        if t is None:
            continue
        print(f"{name}:")
        for F, v in t["summary"].items():
            rel = (f"; its selection step (MatchDG's checkpoint on the augmented copy) listed in {v['related_in']}"
                   if "related_in" in v else "")
            print(f"  {F} [{v['level']}] {v['what']} ({v['golden_kind']}): found in {v['found_in']} pairings, with "
                  f"verified evidence in {v['verified_in']}; kind found: {', '.join(v['kinds_found']) or '-'}{rel}")
        for r, v in (t.get("code_runs") or {}).items():
            cites = ", ".join(f"{k} {'ok' if ok else 'MISSING'}" for k, ok in v["citations_verified"].items())
            a, sel = v["augmented_copy"], v["matchdg_first_phase_selection"]
            print(f"  {r}: augmented copy (crop then flip, after rotation): {'yes' if a['ok'] else 'NO'} "
                  f"{short([e.get('ops') for e in a['entries']], 100)}; MatchDG first-phase selection on it: "
                  f"{'yes' if sel['ok'] else 'NO'} {short([(e.get('methods'), e.get('phase')) for e in sel['entries']], 120)}; "
                  f"other methods selecting on it: {len(v['other_methods_selecting_on_augmented'])}")
            print(f"    citations verified: {cites}")
        print(f"  pass: {t['pass']}")
    print("agreement between runs:", "; ".join(f"{t} {side} same {c['same']}/differ {c['differ']}/one null "
                                                 f"{c['one_null']}/both null {c['both_null']}"
                                                 for t, a in out["agreement"].items() for side, c in a.items()))
    print("evidence items verified:", "; ".join(f"{t} {r} {e['items_ok']}/{e['items']}"
                                                for t, rs in out["evidence"].items() for r, e in rs.items()))
    print(f"new, unverified ({len(out['new_unverified'])} distinct settings beyond F1-F7, de-duplicated across runs; "
          f"hypotheses for branches, not results):")
    for g in out["new_unverified"]:
        what = g["key"] + (f".{g['field']}" if g.get("field") else "") + (f" [{g['use']}]" if g.get("use") else "")
        print(f"  {g['status']}: {g['table']}: {what} ({g['kind']}): in {len(g['pairings'])} pairings; methods "
              f"{short(g['methods'], 120)}")
        for v in g["variants"]:
            print(f"      {short(v['method'], 50)}: paper {short(v['paper'], 90)}; code {short(v['code'], 130)}; "
                  f"evidence {short(v['evidence'], 60)} ({len(v['pairings'])} pairings)")
    for ld in out["leads"]:
        print(f"  new, unverified (lead from {ld['source']}): {ld['table']}: {ld['lead']}; the diff lists it in "
              f"{ld['diff_lists_it_in']} pairings; code runs say {short(ld['code_values'], 160)}; paper runs say "
              f"{short(ld['paper_values'], 120)}; code citations verified: {', '.join(ld['code_citations_verified'])}")
    for label in ("F1-F7", "F1-F8"):
        pr = out["precision"][label]
        print(f"precision, known = {label} (lower bound, distinct settings): " + "; ".join(
            f"{t} {v['precision_lower_bound']}" for t, v in pr.items())
              + f" (false alarms {pr['all']['false_alarms']}, new unverified {pr['all']['new_unverified']})")
    print(f"  ({out['precision']['definition']})")
    print(f"note: F7 {out['blind']['F7']}")
    print(f"note: F8 {out['blind']['F8']}")
    for p in out["problems"]:
        print("  problem:", p)
    print("pass" if out["pass"] else "FAIL")
    raise typer.Exit(0 if out["pass"] else 1)


env_app = typer.Typer(no_args_is_help=True, help="Environment builder: the execution ladder (spec section 4).")
app.add_typer(env_app, name="env")


@env_app.command("build")
def env_build(audit_id: str = typer.Argument(..., help="Audit id: audits/<id>/audit.yaml."),
              rebuild: bool = typer.Option(False, "--rebuild", help="Rebuild even if the plan is unchanged.")):
    """Build workspace/envs/<id>/: date-pinned uv env for the repo at its commit. Writes env.json there and in audits/<id>/."""
    from el01.config import AuditConfig
    from el01.env.builder import EnvBuildError, build_env
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, audit_id)
    try:
        rep = build_env(paths, cfg, rebuild=rebuild)
    except EnvBuildError as e:
        print(f"environment build failed: {e}")
        raise typer.Exit(1)
    pk = rep["packages"]
    print(f"python {rep['python']['installed']} ({rep['python']['rule']})")
    print(f"commit {rep['commit'][:7]} ({rep['commit_date']}), UV_EXCLUDE_NEWER={rep['exclude_newer']}")
    print("added (imported, not in requirements):", ", ".join(a["dist"] for a in pk["added"]) or "none")
    print("listed but not imported (not installed):", ", ".join(n["line"] for n in pk["not_imported"]) or "none")
    print("guarded imports (not installed):", ", ".join(g["module"] for g in pk["guarded"]) or "none")
    print("lazy kept:", ", ".join(k["line"] for k in pk["lazy_kept"]) or "none")
    for d in pk["lazy_dropped"]:
        print(f"lazy dropped: {d['line']}: {d['reason'][:200]}")
    for b in pk["wheel_bumps"]:
        print(f"wheel gap: {b['why']} (released {b['to_released']})")
    bad = {m: v for m, v in rep["import_check"].items() if v not in ("imported", "found")}
    print(f"import check: {len(rep['import_check']) - len(bad)} of {len(rep['import_check'])} modules present; "
          f"absent: {', '.join(f'{m} ({v})' for m, v in sorted(bad.items())) or 'none'}")
    freeze = {l.split('==')[0].lower(): l.split('==')[1] for l in rep["freeze"] if '==' in l}
    print("key versions:", ", ".join(f"{k} {freeze.get(k, '-')}" for k in ("torch", "numpy", "scipy", "opacus")))


@env_app.command("compare")
def env_compare(audit_id: str = typer.Argument(..., help="Audit id."),
                against: Path = typer.Argument(..., help="A pip freeze / pinned requirements file.")):
    """List every difference between the built env (freeze.txt) and another pinned list."""
    from el01.env.builder import compare_freeze, parse_lock
    paths = Paths.make()
    freeze = paths.envs / audit_id / "freeze.txt"
    if not freeze.exists():
        print(f"{freeze} is missing: run `el01 env build {audit_id}` first")
        raise typer.Exit(1)
    d = compare_freeze(parse_lock(freeze.read_text()), parse_lock(Path(against).read_text()))
    print(f"same version: {d['same']}; different version: {len(d['changed'])}; only ours: {len(d['only_ours'])}; "
          f"only theirs: {len(d['only_theirs'])}")
    for c in d["changed"]:
        print(f"  changed  {c['package']}: ours {c['ours']}, theirs {c['theirs']}")
    for c in d["only_ours"]:
        print(f"  ours     {c['package']}=={c['version']}")
    for c in d["only_theirs"]:
        print(f"  theirs   {c['package']}=={c['version']}")


if __name__ == "__main__":
    app()
