"""Claim cards (spec section 2): the paper extractor reads the paper's text; code checks every number and quote.

One agent call per target table (tool-less: both documents' text is in the prompt; it never sees the repository).
The agent returns the table's rows with verbatim quotes. Code then:
  - finds the caption, the header line and every row line on the cited page, between the table's own caption and the
    next caption (el01/ingest/pdf_text.table_span: Table 11 and Table 12 share a page, a header and an ERM row), and
    parses the page's own row text into `mean (sd)` cells; the number of cells must equal the number of columns, the
    header must read row-label header + columns, and the agent's value at each column must equal code's parse. A right number from the
    wrong row or column fails: this is the spec's misattribution guard;
  - finds the quote behind each row's role (method / baseline / oracle) and provenance; a supporting quote counts on
    the page code finds it on (a wrong page cited by the agent is noted, not fatal: no number depends on it);
  - checks the metric and aggregation quotes, and the quotes and row names of relative / trend claims.
A card that fails a check is kept with `valid: false` and its problems; nothing is corrected. The reported numbers on a
card are code's parse of the page text. Output: audits/<id>/claims.json, evidence in audits/<id>/claims/."""
from __future__ import annotations

import json
import re
from pathlib import Path
from string import Template
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.ingest.pdf_text import Doc, load_doc, locate, pypdf_version, squash, table_span
from el01.llm.backend import LLM, Request

LLM_DIR = Path(__file__).resolve().parent.parent / "llm"
SCHEMA = json.loads((LLM_DIR / "schemas" / "claims.json").read_text())
AGENT = "paper_extractor"
MAX_TURNS = 4
NUM = r"-?\d+(?:\.\d+)?"
CELL = rf"({NUM})\s*(?:\(\s*({NUM})\s*\))?"
ROW_CELLS_RE = re.compile(rf"\s*(?:{CELL}\s*)+")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def claim_id(table: str, row: str, column: str) -> str:
    return f"{table}|{row}|{column}"


# ---- checks -----------------------------------------------------------------------------------------------------

def strip_label(line: str, label: str) -> Optional[str]:
    """`line` without its leading row label (compared without whitespace), or None if it does not start with it."""
    want = squash(label)
    if not want:
        return None
    for k in range(1, len(line) + 1):
        got = squash(line[:k])
        if got == want:
            return line[k:]
        if not want.startswith(got):
            return None
    return None


def parse_cells(rest: str) -> Optional[list[tuple[str, Optional[str]]]]:
    """The cells of a row after its label, as printed: [(mean, sd or None)], or None if anything else is there."""
    if not ROW_CELLS_RE.fullmatch(rest):
        return None
    return [(m.group(1), m.group(2)) for m in re.finditer(CELL, rest)]


def _quote(docs: dict[str, Doc], text: Optional[str], doc: Optional[str], page: Optional[int]) -> dict:
    """A supporting quote (role, provenance, metric, aggregation, relative claim): {"text": the page's own text,
    "doc", "page" (where code found it), "found", "problem", "note"}. A quote the agent placed on the wrong page still
    counts, at the page code found it on, with a note; one in neither document does not."""
    out = {"text": None, "doc": doc, "page": page, "found": False, "problem": None, "note": None}
    if not text:
        out["problem"] = "no quote"
        return out
    d = docs.get(doc or "")
    hit = locate(d.pages[page], text) if d is not None and page in d.pages else None
    if hit is not None:
        out.update(text=hit, found=True)
        return out
    for n, dd in docs.items():
        for p, t in sorted(dd.pages.items()):
            hit = locate(t, text)
            if hit is not None:
                out.update(text=hit, doc=n, page=p, found=True,
                           note=f"the agent cited {doc} p.{page}; code found the quote on {n} p.{p}")
                return out
    out["problem"] = "not found in either document"
    out["agent_text"] = text
    return out


def _in_span(span: Optional[str], text: Optional[str], what: str) -> dict:
    """A line of the table itself (caption, header, row): it must be in the table's span on its page."""
    out = {"text": None, "found": False, "problem": None}
    if not text:
        out["problem"] = f"no {what}"
    elif span is None:
        out["problem"] = "the table's caption is not on the cited page"
    else:
        hit = locate(span, text)
        if hit is None:
            out["problem"] = f"{what} is not between the table's caption and the next caption on the cited page"
            out["agent_text"] = text
        else:
            out.update(text=hit, found=True)
    return out


def validate_table(ans: dict, docs: dict[str, Doc], target: str) -> dict:
    doc = docs.get(ans.get("doc"))
    page = ans.get("page")
    table = ans.get("table") or target
    problems: list[str] = []
    page_text = doc.pages.get(page) if doc else None
    if page_text is None:
        problems.append(f"no page {page} in document {ans.get('doc')!r}")
    if not squash(target).lower().endswith(squash(table).lower()):
        problems.append(f"the agent's table {table!r} is not the target {target!r}")
    span = table_span(page_text, table) if page_text is not None else None
    caption = _in_span(span, ans.get("caption_quote"), "caption")
    if not caption["found"]:
        problems.append(f"caption: {caption['problem']}")
    header = _in_span(span, ans.get("header_line"), "header line")
    columns = list(ans.get("columns") or [])
    header_ok = header["found"] and squash(header["text"]) == squash(ans.get("row_label_header", "")) + \
        squash("".join(columns))
    if not header["found"]:
        problems.append(f"header line: {header['problem']}")
    elif not header_ok:
        problems.append(f"header line {header['text']!r} is not the row-label header "
                        f"{ans.get('row_label_header')!r} followed by the columns {columns}")
    table_ok = not problems

    m, a = ans.get("metric") or {}, ans.get("aggregation") or {}
    metric_q = _quote(docs, m.get("quote"), m.get("quote_doc"), m.get("quote_page"))
    agg_q = (_quote(docs, a.get("quote"), a.get("quote_doc"), a.get("quote_page")) if a.get("quote")
             else {"text": None, "found": False, "problem": "not stated"})
    if not metric_q["found"]:
        problems.append(f"metric quote: {metric_q['problem']}")
    if a.get("quote") and not agg_q["found"]:
        problems.append(f"aggregation quote: {agg_q['problem']}")
    metric = {"name": m.get("name"), "split": m.get("split"), "unit": m.get("unit"), "quote": metric_q}
    aggregation = {"kind": a.get("kind"), "spread": a.get("spread"), "n_runs": a.get("n_runs"), "quote": agg_q}

    cards, labels, seen = [], [], {}
    for row in ans.get("rows") or []:
        label = row.get("label", "")
        labels.append(label)
        rp: list[str] = []
        line = _in_span(span, row.get("line"), "row line")
        parsed = None
        if not line["found"]:
            rp.append(f"row line: {line['problem']}")
        else:
            rest = strip_label(line["text"], label)
            if rest is None:
                rp.append(f"row line {line['text']!r} does not start with the label {label!r}")
            else:
                parsed = parse_cells(rest)
                if parsed is None:
                    rp.append(f"row line {line['text']!r}: text other than `mean (sd)` cells after the label")
                elif len(parsed) != len(columns):
                    rp.append(f"row line has {len(parsed)} cells, the header has {len(columns)} columns")
                    parsed = None
        if not table_ok:
            rp.append("the table itself is not verified (see the table's problems), so no cell is")
        role_q = _quote(docs, row.get("role_quote"), row.get("role_doc"), row.get("role_page"))
        if not role_q["found"]:
            rp.append(f"role quote: {role_q['problem']}")
        prov_q = None
        if row.get("provenance") == "cited":
            prov_q = _quote(docs, row.get("provenance_quote"), None, None)
            if not prov_q["found"]:
                rp.append(f"provenance quote: {prov_q['problem']}")
        given = {c.get("column"): c for c in row.get("cells") or []}
        if [c.get("column") for c in row.get("cells") or []] != columns:
            rp.append(f"cells name columns {[c.get('column') for c in row.get('cells') or []]}, "
                      f"the table has {columns}")
        n = seen[label] = seen.get(label, 0) + 1
        row_name = label if n == 1 else f"{label}#{n}"
        for k, col in enumerate(columns):
            cp = list(rp)
            mean_t, sd_t = parsed[k] if parsed else (None, None)
            g = given.get(col)
            if parsed and g is None:
                cp.append(f"no value given for column {col!r}")
            elif parsed:
                if float(mean_t) != float(g.get("mean")):
                    cp.append(f"{col}: agent says {g.get('mean')}, the page says {mean_t}")
                if (sd_t is None) != (g.get("sd") is None) or (sd_t is not None and float(sd_t) != float(g["sd"])):
                    cp.append(f"{col}: agent says sd {g.get('sd')}, the page says {sd_t}")
            cards.append({
                "claim_id": claim_id(table, row_name, col), "type": "absolute",
                "role": row.get("role"), "role_quote": role_q,
                "provenance": row.get("provenance"), "provenance_quote": prov_q,
                "source": {"doc": ans.get("doc"), "page": page, "table": table, "row": row_name, "column": col,
                           "column_index": k, "row_line": line["text"], "header_line": header["text"]},
                "metric": {"name": metric["name"], "split": metric["split"], "unit": metric["unit"]},
                "reported": {"mean": float(mean_t) if mean_t is not None else None,
                             "sd": float(sd_t) if sd_t is not None else None,
                             "mean_text": mean_t, "sd_text": sd_t, "aggregation": aggregation["kind"],
                             "spread": aggregation["spread"], "n_runs": aggregation["n_runs"]},
                "valid": not cp, "problems": cp})

    relative = []
    for n_rel, rc in enumerate(ans.get("relative_claims") or [], 1):
        q = _quote(docs, rc.get("quote"), rc.get("doc"), rc.get("page"))
        rp = [] if q["found"] else [f"quote: {q['problem']}"]
        unknown = [r for r in rc.get("rows") or [] if r not in labels]
        if unknown:
            rp.append(f"rows not in the table: {unknown}")
        col = rc.get("column")
        if col is not None and col not in columns:
            rp.append(f"column {col!r} not in the table")
        cells = [claim_id(table, r, col) for r in rc.get("rows") or [] if col is not None and r in labels]
        relative.append({"claim_id": f"{table}|R{n_rel}", "type": rc.get("type"), "statement": rc.get("statement"),
                         "quote": q, "rows": rc.get("rows"), "column": col, "cells": cells,
                         "valid": not rp, "problems": rp})

    return {"target": target, "table": table, "doc": ans.get("doc"), "page": page,
            "caption": caption, "header_line": header["text"], "row_label_header": ans.get("row_label_header"),
            "columns": columns, "metric": metric, "aggregation": aggregation, "problems": problems,
            "rows": [{"label": c["source"]["row"], "role": c["role"], "provenance": c["provenance"]}
                     for c in cards if c["source"]["column_index"] == 0],
            "cards": cards, "relative": relative, "notes": ans.get("notes")}


# ---- the agent --------------------------------------------------------------------------------------------------

def documents_block(docs: dict[str, Doc]) -> str:
    return "\n".join(f"=== document: {n} ===\n{d.text.rstrip()}\n=== end of document: {n} ===\n"
                     for n, d in docs.items())


def build_prompt(cfg: AuditConfig, target: str, docs: dict[str, Doc]) -> str:
    return Template((LLM_DIR / "prompts" / f"{AGENT}.md").read_text()).substitute(
        title=cfg.paper.title, table=target, documents=documents_block(docs))


def load_docs(paths: Paths, cfg: AuditConfig) -> dict[str, Doc]:
    docs = {}
    for name, rel in (("main", cfg.paper.pdf), ("supplement", cfg.paper.supplement)):
        if rel:
            p = (paths.root / rel) if not Path(rel).is_absolute() else Path(rel)
            if not p.exists():
                raise FileNotFoundError(f"{p} is missing (audit.yaml paper.{'pdf' if name == 'main' else name})")
            docs[name] = load_doc(name, p)
    if not docs:
        raise ValueError(f"audits/{cfg.id}/audit.yaml names no paper PDF")
    return docs


def extract_claims(paths: Paths, cfg: AuditConfig, llm: LLM, echo: Callable[[str], None] = print) -> dict:
    audit_dir = paths.audit_dir(cfg.id)
    ev = audit_dir / "claims"
    ev.mkdir(parents=True, exist_ok=True)
    docs = load_docs(paths, cfg)
    out = {"audit": cfg.id, "paper": cfg.paper.title, "agent": AGENT, "model": cfg.llm.model,
           "pypdf": pypdf_version(),
           "docs": {n: {"pdf": d.pdf.relative_to(paths.root).as_posix() if d.pdf.is_relative_to(paths.root)
                        else d.pdf.name, "sha256": d.sha256, "pages": len(d.pages)} for n, d in docs.items()},
           "tables": [], "counts": {}}
    for t in cfg.targets:
        prompt = build_prompt(cfg, t.table, docs)
        req = Request(agent=AGENT, prompt=prompt, schema=SCHEMA, model=cfg.llm.model,
                      inputs={f"pdf:{n}": d.sha256 for n, d in docs.items()}, tools=(), max_turns=MAX_TURNS)
        s = slug(t.table)
        # the prompt without the paper's text (that is in workspace/papers/, regenerated from the PDFs)
        (ev / f"{s}.prompt.md").write_text(Template((LLM_DIR / "prompts" / f"{AGENT}.md").read_text()).substitute(
            title=cfg.paper.title, table=t.table,
            documents="\n".join(f"=== document: {n} === (text of {out['docs'][n]['pdf']}, sha256 {d.sha256}, "
                                f"extracted with pypdf {out['pypdf']}: {len(d.pages)} pages)" for n, d in docs.items())))
        echo(f"{t.table}: paper_extractor ({llm.mode})")
        resp = llm.call(req)
        ans = resp.output if isinstance(resp.output, dict) else {}
        (ev / f"{s}.answer.json").write_text(json.dumps(ans, indent=1, ensure_ascii=False) + "\n")
        rec = validate_table(ans, docs, t.table)
        meta = resp.record["response"]
        rec["call"] = {"key": resp.key, "cache": resp.cache, "backend": resp.backend,
                       "recorded_backend": resp.record.get("backend"), "cli_version": resp.record.get("cli_version"),
                       "total_cost_usd": meta.get("total_cost_usd"), "num_turns": meta.get("num_turns"),
                       "models": meta.get("models"), "prompt": f"claims/{s}.prompt.md",
                       "answer": f"claims/{s}.answer.json"}
        out["tables"].append(rec)
        ok = sum(c["valid"] for c in rec["cards"])
        echo(f"  {rec['table']} ({rec['doc']} p.{rec['page']}): {len(rec['rows'])} rows x {len(rec['columns'])} "
             f"columns, {ok}/{len(rec['cards'])} cells verified; {len(rec['relative'])} relative/trend claims "
             f"({sum(r['valid'] for r in rec['relative'])} verified); call: cache {resp.cache}")
        for p in rec["problems"]:
            echo(f"  table problem: {p}")
    cards = [c for t in out["tables"] for c in t["cards"]]
    out["counts"] = {"tables": len(out["tables"]), "cells": len(cards), "cells_valid": sum(c["valid"] for c in cards),
                     "relative": sum(len(t["relative"]) for t in out["tables"]),
                     "agent_calls": len(out["tables"]),
                     "cache_hits": sum(t["call"]["cache"] == "hit" for t in out["tables"]),
                     "cost_usd_recorded": round(sum(t["call"]["total_cost_usd"] or 0 for t in out["tables"]), 4)}
    (audit_dir / "claims.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def load_claims(paths: Paths, audit_id: str) -> dict:
    p = paths.audit_dir(audit_id) / "claims.json"
    if not p.exists():
        raise FileNotFoundError(f"{p} is missing: run `el01 claims {audit_id}` first")
    return json.loads(p.read_text())
