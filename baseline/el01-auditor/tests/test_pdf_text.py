"""Paper text: page markers, verbatim quote lookup, table spans."""
from pathlib import Path

import pytest

from el01.ingest.pdf_text import load_doc, locate, parse_pages, render, table_span

PAGE = ("Note on method selection Our objective with the syn-\n"
        "thetic slab dataset is to compare the performance of con-\n"
        "ditional distribution matching (CDM) methods.\n"
        "Table 11. Accuracy for Rotated MNIST.\n"
        "Algorithm 0 15 Average\n"
        "ERM 88.2 (1.0) 98.6 (0.5) 94.1\n"
        "C-CORAL 99.9 (0.01) 96.0 (0.27)\n"
        "Table 12. Accuracy using the DomainBed setup.\n"
        "Algorithm 0 15 Average\n"
        "ERM 95.6 (0.1) 99.0 (0.1) 98.0\n")


def test_pages_roundtrip():
    pages = ["first page\ntext", "second", ""]
    assert parse_pages(render(pages)) == {1: "first page\ntext", 2: "second", 3: ""}


def test_locate_whitespace_and_line_breaks():
    assert locate(PAGE, "ERM 88.2 (1.0)  98.6 (0.5)") == "ERM 88.2 (1.0) 98.6 (0.5)"
    assert locate(PAGE, "ERM 88.2(1.0)") == "ERM 88.2 (1.0)"
    assert locate(PAGE, "Table 11. Accuracy for Rotated MNIST. Algorithm 0 15") is not None  # across a line break
    assert locate(PAGE, "ERM 88.3 (1.0)") is None
    assert locate(PAGE, "C-CORAL 99.9") == "C-CORAL 99.9"
    assert locate(PAGE, "CCORAL 99.9") is None  # a mid-line hyphen is not optional


def test_locate_line_end_hyphens_each_optional():
    # the agent dropped one line-end hyphen and kept the other (the first live run did exactly this)
    q = "the synthetic slab dataset is to compare the performance of con- ditional distribution"
    assert locate(PAGE, q) == ("the syn- thetic slab dataset is to compare the performance of con- ditional "
                               "distribution")
    assert locate(PAGE, "the syn-thetic slab") is not None
    assert locate(PAGE, "the synthetic slab") is not None


def test_locate_nfkc():
    assert locate("classiﬁcation accuracy", "classification accuracy") == "classiﬁcation accuracy"


def test_table_span_stops_at_the_next_caption():
    span = table_span(PAGE, "Table 11")
    assert span.startswith("Table 11.")
    assert locate(span, "ERM 88.2 (1.0)") is not None
    assert locate(span, "ERM 95.6 (0.1)") is None          # Table 12's ERM row, same page and header
    assert table_span(PAGE, "Table 1") is None             # "Table 11." is not "Table 1."
    assert locate(table_span(PAGE, "Table 12"), "ERM 95.6 (0.1)") is not None


def test_matchdg_pdf_pages():
    pdf = Path(__file__).resolve().parent.parent / "workspace" / "papers" / "matchdg" / "mahajan21b.pdf"
    if not pdf.exists():
        pytest.skip("MatchDG PDF not downloaded (Phase 0, step 6)")
    doc = load_doc("main", pdf)
    assert len(doc.pages) == 12
    span = table_span(doc.pages[4], "Table 1")
    assert locate(span, "Method Source 1 Source 2 Target") is not None
    assert locate(span, "PerfMatch 99.9 (0.05) 97.8 (0.28) 77.8 (6.01)") is not None
