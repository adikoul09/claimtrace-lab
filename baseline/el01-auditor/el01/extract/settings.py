"""Settings extraction, schema v2 (spec section 3): one schema, filled from each side by its own agent.

  paper_extractor  tool-less; both documents' pypdf text is in the prompt (as for the claim cards)
  code_extractor   Read/Grep/Glob on a `git archive` snapshot of the audited commit (no git history, no audit
                   branches), copied into its working directory as ./repo. It is told only the table's name, its
                   caption, its columns and the paper's own row labels (from claims.json), never the linked commands
                   (links.json takes values from the paper where the repository gives none) or the paper's settings.

Each side runs twice per target table (spec: report agreement between runs). The two runs get the same prompt; the
replicate number is a cache input, so each run is its own recorded call.

Code checks every piece of evidence: a paper quote must be on the page it names, or on another page (noted), as for
the claim cards; a code citation must name a file in the snapshot and a line range in it, and its quoted code must be
on those lines (whitespace ignored, "..." skips lines). Nothing is corrected: each key keeps its value and a status
(verified, partly, unverified, no evidence, null). The diff (el01/diff/settings_diff.diff_v2) runs on every paper run x
code run pairing. Output: audits/<id>/settings.json, audits/<id>/settings_diff.json, evidence in audits/<id>/settings/.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.diff import settings_diff as xd
from el01.extract.claims import _quote, documents_block, load_claims, load_docs, slug
from el01.ingest.pdf_text import Doc, pypdf_version, squash
from el01.ingest.repo import ensure_clone, resolve, snapshot, tree_id
from el01.llm.backend import AGENT_TOOLS, LLM, LLMError, Request

EXTRACT_DIR = Path(__file__).resolve().parent
LLM_DIR = EXTRACT_DIR.parent / "llm"
SCHEMA_V2 = json.loads((EXTRACT_DIR / "schema_v2.json").read_text())
KEYS = [k["key"] for k in SCHEMA_V2["keys"]]
V2_KEYS = [k["key"] for k in SCHEMA_V2["keys"] if k["since"] == 2]
AGENTS = {"paper": "paper_extractor", "code": "code_extractor"}
PROMPTS = {"paper": "paper_extractor_settings", "code": "code_extractor"}
MAX_TURNS = {"paper": 4, "code": 120}
RUNS = 2
ANY = {"type": ["string", "number", "boolean", "array", "object", "null"]}
EVIDENCE = {
    "paper": {"type": "object", "additionalProperties": False, "required": ["doc", "page", "quote"],
              "properties": {"doc": {"type": "string", "enum": ["main", "supplement"]},
                             "page": {"type": "integer"},
                             "quote": {"type": "string", "description": "verbatim from that page"}}},
    "code": {"type": "object", "additionalProperties": False, "required": ["file", "lines", "code"],
             "properties": {"file": {"type": "string", "description": "path relative to the repository root"},
                            "lines": {"type": "string", "description": "\"42\" or \"34-35\""},
                            "code": {"type": "string", "description": "the code on those lines, verbatim"}}},
}
LINES_RE = re.compile(r"^\s*L?(\d+)\s*(?:[-–]\s*L?(\d+))?\s*$")
ELLIPSIS_RE = re.compile(r"\.\.\.|…")


# ---- schema -----------------------------------------------------------------------------------------------------

def answer_schema(side: str) -> dict:
    """The structured-answer schema of one side, built from schema_v2.json."""
    props = {}
    for k in SCHEMA_V2["keys"]:
        value = {"type": ["array", "null"], "items": k["entry"]} if k["since"] == 2 else ANY
        props[k["key"]] = {"type": "object", "additionalProperties": False, "required": ["value", "evidence"],
                           "properties": {"value": value, "evidence": {"type": "array", "items": EVIDENCE[side]}}}
    top = {"experiment": {"type": "string"},
           "settings": {"type": "object", "additionalProperties": False, "required": KEYS, "properties": props},
           "notes": {"type": "array", "items": {"type": "string"}}}
    if side == "code":
        top["commands"] = {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["command", "source"],
            "properties": {"command": {"type": "string"}, "source": {"type": "string", "description": "path:line"}}}}
    return {"type": "object", "additionalProperties": False, "required": sorted(top), "properties": top}


def _shape(s: dict) -> str:
    """A compact rendering of an entry schema for the prompt: {field: a|b, list: [{...}]}."""
    if "enum" in s:
        return "|".join(str(e) for e in s["enum"])
    t = s.get("type")
    types = t if isinstance(t, list) else [t]
    if "object" in types and "properties" in s:
        return "{" + ", ".join(f"{k}: {_shape(v)}" if ("enum" in v or "properties" in v or "items" in v) else k
                               for k, v in s["properties"].items()) + "}"
    if "array" in types and "items" in s:
        inner = s["items"]
        return f"[{_shape(inner)}]" if ("properties" in inner or "enum" in inner) else "[..]"
    return "..."


def keys_block(side: str) -> str:
    out = []
    for k in SCHEMA_V2["keys"]:
        shape = f"entries [{_shape(k['entry'])}]" if k["since"] == 2 else k["hint"]
        out.append(f"- `{k['key']}`: {shape}: {k.get('describe_' + side) or k['describe']}")
    return "\n".join(out)


# ---- prompts ----------------------------------------------------------------------------------------------------

def _template(side: str) -> Template:
    return Template((LLM_DIR / "prompts" / f"{PROMPTS[side]}.md").read_text())


def experiment_of(table: dict) -> dict:
    """What the code side is told about the experiment: the claim table's name, caption, columns and own rows."""
    return {"table": table["target"], "caption": (table.get("caption") or {}).get("text") or table["table"],
            "columns": list(table.get("columns") or []),
            "rows": [r["label"] for r in table.get("rows") or [] if r.get("provenance") != "cited"]}


TABLE_LINE_RE = re.compile(r"(?:^|\n)[ \t]*(Table[ \t]+\d+)[ \t]*[.:][ \t]*([^\n]*(?:\n[^\n]*)?)")


def table_index(docs: dict[str, Doc]) -> str:
    """Every line that starts with `Table N.` in either document, with its page and first sentence. A table's
    caption is usually one of them; a sentence that happens to start a line with a table reference may be too."""
    out = []
    for n, d in docs.items():
        for p, text in sorted(d.pages.items()):
            for m in TABLE_LINE_RE.finditer(text):
                first = re.split(r"(?<=[a-z0-9)])\.\s", " ".join(m.group(2).split()))[0][:200]
                out.append(f"- {m.group(1)} ({n}, page {p}): {first}")
    return "\n".join(dict.fromkeys(out)) or "(none found)"


def paper_prompt(cfg: AuditConfig, table: dict, docs: dict[str, Doc], documents: Optional[str] = None) -> str:
    e = experiment_of(table)
    return _template("paper").substitute(title=cfg.paper.title, table=e["table"], caption=e["caption"],
                                         keys=keys_block("paper"), tables=table_index(docs),
                                         documents=documents if documents is not None else documents_block(docs))


def code_prompt(cfg: AuditConfig, table: dict) -> str:
    e = experiment_of(table)
    return _template("code").substitute(repo_url=cfg.repo.url, table=e["table"], caption=e["caption"],
                                        columns=", ".join(e["columns"]), rows=", ".join(e["rows"]),
                                        keys=keys_block("code"))


def instructions(prompt: str) -> str:
    """A prompt without the paper's own text (the documents block): what we wrote, not what the paper says."""
    return re.sub(r"=== document: (\w+) ===\n.*?=== end of document: \1 ===\n", "", prompt, flags=re.S)


# ---- evidence checks --------------------------------------------------------------------------------------------

def _repo_file(snap: Path, name: str) -> Optional[Path]:
    rel = str(name or "").strip().strip("`")
    for pre in ("./", "repo/"):
        rel = rel.removeprefix(pre)
    if not rel or rel.startswith("/"):
        return None
    p = (snap / rel).resolve()
    root = snap.resolve()
    return p if p.is_file() and p.is_relative_to(root) and p.name != ".el01-snapshot" else None


def _pieces_in(pieces: list[str], window: str) -> bool:
    at = 0
    for q in pieces:
        k = window.find(q, at)
        if k < 0:
            return False
        at = k + len(q)
    return True


def parse_lines(text) -> Optional[list[list[int]]]:
    """"42", "34-35" or a comma-separated list of them ("11, 30-35"): [[a, b], ...], or None."""
    parts = [x for x in str(text or "").split(",") if x.strip()]
    out = []
    for x in parts:
        m = LINES_RE.match(x)
        if m is None:
            return None
        out.append([int(m.group(1)), int(m.group(2) or m.group(1))])
    return out or None


def check_code_item(snap: Path, item: dict) -> dict:
    """{file, lines: [first, last], ranges: [[a, b], ...], ok, problem, near}: the quoted code must be on the cited
    lines of the snapshot's file, its "..."-separated pieces in order across the cited ranges."""
    out = {"file": item.get("file"), "lines": None, "ranges": None, "ok": False, "problem": None, "near": None}
    p = _repo_file(snap, item.get("file"))
    if p is None:
        out["problem"] = "no such file in the snapshot"
        return out
    out["file"] = p.relative_to(snap.resolve()).as_posix()
    ranges = parse_lines(item.get("lines"))
    if ranges is None:
        out["problem"] = f"lines {item.get('lines')!r} is not N, N-M or a list of them"
        return out
    out["ranges"] = ranges
    out["lines"] = [ranges[0][0], ranges[-1][1]]
    text = p.read_text(errors="replace").splitlines()
    bad = [r for r in ranges if not (1 <= r[0] <= r[1] <= len(text))]
    if bad:
        out["problem"] = f"lines {bad[0][0]}-{bad[0][1]} outside the file (1-{len(text)})"
        return out
    pieces = [squash(x) for x in ELLIPSIS_RE.split(item.get("code") or "") if squash(x)]
    if not pieces:
        out["problem"] = "no code quoted"
        return out
    if _pieces_in(pieces, "".join(squash("\n".join(text[a - 1:b])) for a, b in ranges)):
        out["ok"] = True
        return out
    out["problem"] = "the quoted code is not on those lines"
    if len(ranges) == 1:
        a, b = ranges[0]
        for d in sorted(range(-20, 21), key=abs):   # where it is, if close by (a note only; the item stays unverified)
            lo, hi = a + d, b + d
            if 1 <= lo and hi <= len(text) and _pieces_in(pieces, squash("\n".join(text[lo - 1:hi]))):
                out["near"] = [lo, hi]
                break
    return out


def check_paper_item(docs: dict[str, Doc], item: dict) -> dict:
    q = _quote(docs, item.get("quote"), item.get("doc"), item.get("page"))
    return {"doc": q["doc"], "page": q["page"], "ok": q["found"], "problem": q["problem"], "note": q["note"]}


def status_of(value, checks: list[dict]) -> str:
    if value is None:
        return "null"
    if not checks:
        return "no evidence"
    ok = sum(c["ok"] for c in checks)
    return "verified" if ok == len(checks) else "partly" if ok else "unverified"


def check_answer(side: str, ans: dict, snap: Optional[Path] = None, docs: Optional[dict[str, Doc]] = None) -> dict:
    s = ans.get("settings") or {}
    out, items = {}, []
    for k in KEYS:
        e = s.get(k) or {}
        value = e.get("value") if isinstance(e, dict) else None
        ev = e.get("evidence") if isinstance(e, dict) else None
        checks = [check_code_item(snap, i) if side == "code" else check_paper_item(docs, i)
                  for i in (ev or []) if isinstance(i, dict)]
        items += checks
        out[k] = {"value": value, "status": status_of(value, checks), "evidence": ev or [], "checks": checks}
    counts = {"items": len(items), "items_ok": sum(c["ok"] for c in items)}
    for st in ("verified", "partly", "unverified", "no evidence", "null"):
        counts[f"keys_{st.replace(' ', '_')}"] = sum(v["status"] == st for v in out.values())
    return {"settings": out, "evidence": counts}


# ---- agreement between runs -------------------------------------------------------------------------------------

NUMERIC = {"data.source_domains", "data.target_domains", "data.domains_data_available", "data.train_samples_per_domain",
           "data.val_samples_per_domain", "data.generation_params", "optim.momentum", "optim.lr", "optim.weight_decay",
           "train.batch_size", "train.epochs", "eval.n_seeds"}
ENUMISH = {"optim.name", "optim.nesterov", "optim.lr_schedule", "train.model_selection", "eval.aggregation"}
V2_FIELDS = {"data.preprocessing.resize": ("height", "width"),
             "data.preprocessing.normalization": ("kind", "mean", "std"),
             "data.augmentation": ("ops", "relative_to_domain_transform", "applies_to"),
             "data.domain_transform": ("kind", "domains", "direction"),
             "train.model_selection_data": ("use", "split", "domains", "version")}


def _canon_field(k: str, v):
    if k == "ops":
        return [xd.mkey(o) for o in v or []]
    if k == "applies_to":
        return sorted({(a.get("split"), a.get("domains"), a.get("use")) for a in v or [] if isinstance(a, dict)})
    if k in ("mean", "std", "domains", "height", "width"):
        return sorted(xd.nums(v))
    return xd.mkey(v) if v is not None else None


def canon(key: str, v):
    """A value with wording removed, for comparing two runs of one side: numbers as sets, enumerated heads, v2
    entries reduced to their enumerated fields (method names dropped: the two runs may spell them differently)."""
    if v is None:
        return None
    if key in V2_FIELDS:
        es = xd.entries(v) or []
        return sorted(json.dumps({f: _canon_field(f, e.get(f)) for f in V2_FIELDS[key]}, sort_keys=True) for e in es)
    pm = xd.per_method(v)
    if key == "loss.terms":
        return {m: sorted(json.dumps([sorted(xd.nums(t.get("weight"))), xd.head(t.get("weight_schedule"))])
                          for t in (ts if isinstance(ts, list) else [ts]) if isinstance(t, dict))
                for m, ts in pm.items()}
    if key in NUMERIC:
        return {xd.mkey(m): sorted(xd.nums(x)) for m, x in pm.items()}
    if key in ENUMISH:
        return {xd.mkey(m): xd.head(x) for m, x in pm.items()}
    return {xd.mkey(m): xd.mkey(json.dumps(x, sort_keys=True) if not isinstance(x, str) else x) for m, x in pm.items()}


def agreement(a: dict, b: dict) -> dict:
    """Per key: both_null | same | differ | one_null, between two checked runs of one side."""
    per = {}
    for k in KEYS:
        x, y = canon(k, a[k]["value"]), canon(k, b[k]["value"])
        per[k] = ("both_null" if x is None and y is None else "one_null" if x is None or y is None
                  else "same" if x == y else "differ")
    counts = {s: sum(v == s for v in per.values()) for s in ("same", "differ", "one_null", "both_null")}
    return {"per_key": per, "counts": counts}


# ---- diff over pairings -----------------------------------------------------------------------------------------

FINDING_SIDES = {"data.target_domains": ("data.target_domains", "data.domains_data_available"),
                 "loss.terms.weight_schedule": ("loss.terms", "loss.terms")}


def values(checked: dict) -> dict:
    return {k: {"value": v["value"]} for k, v in checked.items()}


def setting_id(f: dict) -> str:
    """The setting a finding is about: key, kind, entry field and selection use. Not the method or the run: two runs
    that spell a method differently (rand / RandMatch), or report one setting per method, name the same setting, and
    a branch changes one setting (rule 6)."""
    return json.dumps([f["key"], f["kind"], f.get("field"), f.get("use")])


def diff_pairings(runs: dict[str, dict]) -> dict:
    """diff_v2 on every paper run x code run; each finding carries both sides' evidence status for its keys.
    `in_all_pairings` / `in_some_pairings` list distinct settings (setting_id), not raw findings."""
    papers = sorted(n for n in runs if n.startswith("paper_"))
    codes = sorted(n for n in runs if n.startswith("code_"))
    pairings = {}
    for pn in papers:
        for cn in codes:
            ps, cs = runs[pn]["settings"], runs[cn]["settings"]
            fs = xd.diff_v2(values(ps), values(cs))
            for f in fs:
                pk, ck = FINDING_SIDES.get(f["key"], (f["key"], f["key"]))
                f["evidence"] = {"paper": ps[pk]["status"] if pk in ps else None,
                                 "code": cs[ck]["status"] if ck in cs else None}
            pairings[f"{pn} x {cn}"] = fs
    sigs = {p: {setting_id(f) for f in fs} for p, fs in pairings.items()}
    every = set.intersection(*sigs.values()) if sigs else set()
    some = set.union(*sigs.values()) - every if sigs else set()
    return {"pairings": pairings, "in_all_pairings": sorted(every), "in_some_pairings": sorted(some)}


# ---- the agents -------------------------------------------------------------------------------------------------

@dataclass
class Job:
    side: str
    run: int
    table: dict
    request: Request
    saved_prompt: str

    @property
    def name(self) -> str:
        return f"{self.side}_run{self.run}"


def repo_and_snapshot(paths: Paths, cfg: AuditConfig, ref: Optional[str] = None) -> tuple[Path, str, Path]:
    """(clone, sha, snapshot dir) of `ref` (default: the audited commit)."""
    repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
    sha = resolve(repo, ref or cfg.repo.commit)
    return repo, sha, snapshot(repo, sha, paths.workspace / "snapshots" / cfg.id)


def code_request(cfg: AuditConfig, table: dict, repo: Path, sha: str, snap: Path, run: int) -> Request:
    return Request(agent=AGENTS["code"], prompt=code_prompt(cfg, table), schema=answer_schema("code"),
                   model=cfg.llm.model, inputs={"repo_tree": tree_id(repo, sha), "replicate": str(run)},
                   tools=AGENT_TOOLS, repo_copy=snap, max_turns=MAX_TURNS["code"])


def paper_request(cfg: AuditConfig, table: dict, docs: dict[str, Doc], run: int) -> Request:
    return Request(agent=AGENTS["paper"], prompt=paper_prompt(cfg, table, docs),
                   schema=answer_schema("paper"), model=cfg.llm.model,
                   inputs={**{f"pdf:{n}": d.sha256 for n, d in docs.items()}, "replicate": str(run)},
                   tools=(), max_turns=MAX_TURNS["paper"])


def _call_record(resp) -> dict:
    meta = resp.record["response"]
    return {"key": resp.key, "cache": resp.cache, "backend": resp.backend,
            "recorded_backend": resp.record.get("backend"), "cli_version": resp.record.get("cli_version"),
            "total_cost_usd": meta.get("total_cost_usd"), "num_turns": meta.get("num_turns"),
            "models": meta.get("models"), "created_utc": resp.record.get("created_utc")}


def extract_settings(paths: Paths, cfg: AuditConfig, llm: LLM, runs: int = RUNS, jobs: int = 4,
                     echo: Callable[[str], None] = print) -> dict:
    audit_dir = paths.audit_dir(cfg.id)
    claims = load_claims(paths, cfg.id)
    tables = {t["target"]: t for t in claims["tables"]}
    missing = [t.table for t in cfg.targets if t.table not in tables]
    if missing:
        raise ValueError(f"claims.json has no cards for {missing}: run `el01 claims {cfg.id}` first")
    docs = load_docs(paths, cfg)
    repo, sha, snap = repo_and_snapshot(paths, cfg)
    doc_lines = "\n".join(f"=== document: {n} === (text of {d.pdf.name}, sha256 {d.sha256}, extracted with pypdf "
                          f"{pypdf_version()}: {len(d.pages)} pages)" for n, d in docs.items())

    work: list[Job] = []
    for t in cfg.targets:
        table = tables[t.table]
        for run in range(1, runs + 1):
            req = paper_request(cfg, table, docs, run)
            work.append(Job("paper", run, table, req, paper_prompt(cfg, table, docs, doc_lines)))
            req = code_request(cfg, table, repo, sha, snap, run)
            work.append(Job("code", run, table, req, req.prompt))

    def do(job: Job):
        echo(f"  {job.table['target']}: {AGENTS[job.side]} run {job.run} ({llm.mode})")
        return llm.call(job.request)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [pool.submit(do, j) for j in work]
    results, errors = [], []
    for j, fu in zip(work, futures):
        try:
            results.append(fu.result())
        except LLMError as e:
            results.append(None)
            errors.append(f"{j.table['target']} {j.name}: {e}")
    if errors:
        raise LLMError("; ".join(errors) + " (calls that finished are cached; run again to continue)")

    out = {"audit": cfg.id, "schema_version": SCHEMA_V2["version"], "model": cfg.llm.model,
           "agents": AGENTS, "runs_per_side": runs,
           "repo": {"url": cfg.repo.url, "commit": sha, "tree": tree_id(repo, sha),
                    "read_by_code_extractor": "git archive snapshot (no history, no audit branches)"},
           "docs": {n: {"pdf": d.pdf.name, "sha256": d.sha256, "pages": len(d.pages)} for n, d in docs.items()},
           "pypdf": pypdf_version(), "tables": [], "counts": {}}
    diffs = {"audit": cfg.id, "schema_version": SCHEMA_V2["version"],
             "rules": "el01/diff/settings_diff.py: diff_v2 (the spike's three rules, plus the schema-v2 keys)",
             "tables": []}
    calls = []
    for t in cfg.targets:
        table = tables[t.table]
        s = slug(t.table)
        ev = audit_dir / "settings" / s
        ev.mkdir(parents=True, exist_ok=True)
        rec = {"target": t.table, "slug": s, "experiment_given_to_code_side": experiment_of(table), "runs": {}}
        for j, resp in zip(work, results):
            if j.table is not table:
                continue
            ans = resp.output if isinstance(resp.output, dict) else {}
            (ev / f"{j.name}.prompt.md").write_text(j.saved_prompt)
            (ev / f"{j.name}.answer.json").write_text(json.dumps(ans, indent=1, ensure_ascii=False) + "\n")
            checked = check_answer(j.side, ans, snap=snap, docs=docs)
            call = {**_call_record(resp), "prompt": f"settings/{s}/{j.name}.prompt.md",
                    "answer": f"settings/{s}/{j.name}.answer.json"}
            calls.append(call)
            rec["runs"][j.name] = {"call": call, "experiment": ans.get("experiment"), "commands": ans.get("commands"),
                                   "notes": ans.get("notes"), **checked}
            c = checked["evidence"]
            echo(f"  {t.table} {j.name}: evidence items {c['items_ok']}/{c['items']} verified; keys verified "
                 f"{c['keys_verified']}, partly {c['keys_partly']}, unverified {c['keys_unverified']}, no evidence "
                 f"{c['keys_no_evidence']}, null {c['keys_null']}; call: cache {resp.cache}")
        rec["agreement"] = {}
        for side in ("paper", "code"):
            names = sorted(n for n in rec["runs"] if n.startswith(side))
            if len(names) >= 2:
                rec["agreement"][side] = {"runs": names[:2], **agreement(rec["runs"][names[0]]["settings"],
                                                                          rec["runs"][names[1]]["settings"])}
        out["tables"].append(rec)
        d = diff_pairings({n: r for n, r in rec["runs"].items()})
        diffs["tables"].append({"target": t.table, **d})
    out["counts"] = {"agent_calls": len(calls), "cache_hits": sum(c["cache"] == "hit" for c in calls),
                     "cost_usd_recorded": round(sum(c["total_cost_usd"] or 0 for c in calls), 4)}
    (audit_dir / "settings.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    (audit_dir / "settings_diff.json").write_text(json.dumps(diffs, indent=1, ensure_ascii=False, default=str) + "\n")
    return {"settings": out, "diff": diffs}


def load_settings(paths: Paths, audit_id: str) -> tuple[dict, dict]:
    d = paths.audit_dir(audit_id)
    if not (d / "settings.json").exists():
        raise FileNotFoundError(f"{d / 'settings.json'} is missing: run `el01 settings {audit_id}` first")
    return json.loads((d / "settings.json").read_text()), json.loads((d / "settings_diff.json").read_text())
