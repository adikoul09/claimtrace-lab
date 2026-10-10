"""Claim-card validation: code re-reads every number from the page's own table row (the misattribution guard)."""
import copy
import json
from pathlib import Path

import pytest

from el01.extract.claims import parse_cells, strip_label, validate_table
from el01.ingest.pdf_text import Doc

PAGE1 = ("We compare methods. PerfMatch is an oracle method that has access to ground-truth matches.\n"
         "Table 1. Slab dataset: mean and standard deviation over 10 seeds.\n"
         "Method Source 1 Target\n"
         "ERM 100.0 (0.0 ) 57.6 (6.58)\n"
         "PerfMatch 99.9 (0.05) 77.8 (6.01)\n"
         "Table 2. Another table.\n"
         "Method Source 1 Target\n"
         "ERM 1.0 (0.1) 2.0 (0.2)\n")
PAGE2 = "ERM is standard empirical risk minimization."
COLS = ["Source 1", "Target"]


def docs():
    return {"main": Doc("main", Path("main.pdf"), Path("main.txt"), "0" * 64, {1: PAGE1, 2: PAGE2})}


def row(label, line, vals, role="baseline", quote="ERM is standard empirical risk minimization.", page=2):
    return {"label": label, "line": line, "role": role, "role_quote": quote, "role_doc": "main", "role_page": page,
            "provenance": "this_paper", "provenance_quote": None,
            "cells": [{"column": c, "mean": m, "sd": s} for c, (m, s) in zip(COLS, vals)]}


def answer():
    return {"table": "Table 1", "doc": "main", "page": 1,
            "caption_quote": "Table 1. Slab dataset: mean and standard deviation over 10 seeds.",
            "header_line": "Method Source 1 Target", "row_label_header": "Method", "columns": list(COLS),
            "metric": {"name": "accuracy", "split": "target", "unit": "%", "quote": "Table 1. Slab dataset",
                       "quote_doc": "main", "quote_page": 1},
            "aggregation": {"kind": "mean", "spread": "sd", "n_runs": 10,
                            "quote": "mean and standard deviation over 10 seeds", "quote_doc": "main",
                            "quote_page": 1},
            "rows": [row("ERM", "ERM 100.0 (0.0) 57.6 (6.58)", [(100.0, 0.0), (57.6, 6.58)]),
                     row("PerfMatch", "PerfMatch 99.9 (0.05) 77.8 (6.01)", [(99.9, 0.05), (77.8, 6.01)], "oracle",
                         "PerfMatch is an oracle method that has access to ground-truth matches.", 1)],
            "relative_claims": [{"type": "relative", "statement": "PerfMatch beats ERM on target",
                                 "quote": "PerfMatch is an oracle method", "doc": "main", "page": 1,
                                 "rows": ["PerfMatch", "ERM"], "column": "Target"}],
            "notes": ""}


def cards(rec):
    return {c["claim_id"]: c for c in rec["cards"]}


def test_valid_answer():
    rec = validate_table(answer(), docs(), "Table 1")
    assert rec["problems"] == []
    c = cards(rec)
    assert all(x["valid"] for x in c.values()) and len(c) == 4
    t = c["Table 1|PerfMatch|Target"]
    assert (t["reported"]["mean"], t["reported"]["sd"], t["role"]) == (77.8, 6.01, "oracle")
    assert t["source"]["row_line"] == "PerfMatch 99.9 (0.05) 77.8 (6.01)"   # the page's text, not the agent's
    assert c["Table 1|ERM|Source 1"]["source"]["row_line"] == "ERM 100.0 (0.0 ) 57.6 (6.58)"
    assert rec["relative"][0]["valid"] and rec["relative"][0]["cells"] == ["Table 1|PerfMatch|Target",
                                                                           "Table 1|ERM|Target"]


def test_right_number_wrong_row_fails():
    a = answer()
    a["rows"][0]["label"] = "PerfMatch"   # ERM's line, labelled as another row
    rec = validate_table(a, docs(), "Table 1")
    bad = [c for c in rec["cards"] if c["source"]["row"] == "PerfMatch" and not c["valid"]]
    assert bad and "does not start with the label" in bad[0]["problems"][0]


def test_wrong_value_or_column_fails():
    a = answer()
    a["rows"][1]["cells"][1]["sd"] = 4.69
    c = cards(validate_table(a, docs(), "Table 1"))
    assert not c["Table 1|PerfMatch|Target"]["valid"] and c["Table 1|PerfMatch|Source 1"]["valid"]
    assert "the page says 6.01" in c["Table 1|PerfMatch|Target"]["problems"][0]
    a = answer()
    a["rows"][1]["cells"] = list(reversed(a["rows"][1]["cells"]))   # values given under the wrong columns
    c = cards(validate_table(a, docs(), "Table 1"))
    assert not c["Table 1|PerfMatch|Target"]["valid"]


def test_row_from_the_next_table_on_the_same_page_fails():
    a = answer()
    a["rows"][0]["line"] = "ERM 1.0 (0.1) 2.0 (0.2)"                   # Table 2's ERM row
    a["rows"][0]["cells"] = [{"column": "Source 1", "mean": 1.0, "sd": 0.1}, {"column": "Target", "mean": 2.0, "sd": 0.2}]
    c = cards(validate_table(a, docs(), "Table 1"))
    assert not c["Table 1|ERM|Target"]["valid"]
    assert "not between the table's caption" in c["Table 1|ERM|Target"]["problems"][0]


def test_column_count_and_header_checked():
    a = answer()
    a["columns"] = ["Source 1", "Source 2", "Target"]
    rec = validate_table(a, docs(), "Table 1")
    assert rec["problems"] and not any(c["valid"] for c in rec["cards"])


def test_supporting_quote_on_another_page_counts_with_a_note():
    a = answer()
    a["rows"][0]["role_page"] = 1                                          # it is on page 2
    c = cards(validate_table(a, docs(), "Table 1"))["Table 1|ERM|Target"]
    assert c["valid"] and c["role_quote"]["page"] == 2 and "cited main p.1" in c["role_quote"]["note"]
    a["rows"][0]["role_quote"] = "ERM is the best method."                  # in neither document
    c = cards(validate_table(a, docs(), "Table 1"))["Table 1|ERM|Target"]
    assert not c["valid"] and "role quote" in c["problems"][0]


def test_wrong_table_name_fails():
    rec = validate_table(answer(), docs(), "Table 11")
    assert rec["problems"] and not any(c["valid"] for c in rec["cards"])


def test_row_parsing():
    assert strip_label("C-CORAL 99.9 (0.01) 64.7", "C-CORAL") == " 99.9 (0.01) 64.7"
    assert strip_label("DIV A 93.5 (0.3)", "DIVA") == " 93.5 (0.3)"
    assert strip_label("MMD 1.0", "C-MMD") is None
    assert parse_cells(" 100.0 (0.0 ) 96.0 (0.25) 94.1") == [("100.0", "0.0"), ("96.0", "0.25"), ("94.1", None)]
    assert parse_cells(" 57.6 (6.58) extra") is None


def test_committed_claims_replay_identically():
    """The committed cards are what validate_table makes of the recorded agent answers."""
    root = Path(__file__).resolve().parent.parent
    cj = root / "audits" / "matchdg" / "claims.json"
    if not cj.exists():
        pytest.skip("no claims.json yet")
    from el01.config import AuditConfig, Paths
    from el01.extract.claims import load_docs
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, "matchdg")
    try:
        d = load_docs(paths, cfg)
    except FileNotFoundError:
        pytest.skip("MatchDG PDFs not downloaded")
    committed = json.loads(cj.read_text())
    for t in committed["tables"]:
        ans = json.loads((root / "audits" / "matchdg" / t["call"]["answer"]).read_text())
        rec = validate_table(ans, d, t["target"])
        assert json.loads(json.dumps(rec["cards"])) == t["cards"]
