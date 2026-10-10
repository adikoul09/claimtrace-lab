"""Paper PDFs as text with `[page N]` markers, and verbatim quote lookup.

The text is what the paper extractor reads and what code checks its quotes against. A quote is "on a page" when it
equals a stretch of that page's text after Unicode NFKC normalisation (ligatures such as "ﬁ" become "fi") and with all
whitespace removed, so line breaks inside a table row or a sentence do not matter. Each line-end hyphen
("compo-\\nnent") may be kept or dropped by the quote. `locate` returns the page's own text for the match, so code
parses the paper's characters, never the agent's copy of them. `table_span` is the text from a table's caption to the
next caption: a table's rows must be there, not merely on the same page."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from el01.llm.cache import sha256_file

PAGE_RE = re.compile(r"^\[page (\d+)\]$", re.M)


def pdf_pages(pdf: Path) -> list[str]:
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]


def render(pages: list[str]) -> str:
    return "".join(f"[page {i}]\n{t.rstrip()}\n\n" for i, t in enumerate(pages, 1))


def parse_pages(text: str) -> dict[int, str]:
    marks = list(PAGE_RE.finditer(text))
    return {int(m.group(1)): text[m.end():(marks[k + 1].start() if k + 1 < len(marks) else len(text))].strip("\n")
            for k, m in enumerate(marks)}


def pypdf_version() -> str:
    import pypdf
    return pypdf.__version__


@dataclass
class Doc:
    name: str          # "main" | "supplement"
    pdf: Path
    txt: Path
    sha256: str        # of the PDF
    pages: dict[int, str]

    @property
    def text(self) -> str:
        return self.txt.read_text()


def load_doc(name: str, pdf: Path) -> Doc:
    """Extract `pdf` to `<pdf>.txt` next to it (once; re-extracted when the PDF or pypdf changes)."""
    pdf = Path(pdf)
    txt = pdf.with_suffix(".txt")
    stamp = pdf.with_suffix(".txt.sha256")
    want = f"{sha256_file(pdf)} pypdf {pypdf_version()}\n"
    if not (txt.exists() and stamp.exists() and stamp.read_text() == want):
        txt.write_text(render(pdf_pages(pdf)))
        stamp.write_text(want)
    return Doc(name, pdf, txt, want.split()[0], parse_pages(txt.read_text()))


# ---- quotes -----------------------------------------------------------------------------------------------------

BREAK = "\x00"  # a line-end hyphen ("-\n") in the squashed page text


def _squash_page(text: str) -> tuple[str, list[int]]:
    """NFKC page text without whitespace, a line-end hyphen kept as BREAK, plus the index in `text` of every kept
    character."""
    out, idx = [], []
    n = len(text)
    for i, ch in enumerate(text):
        if ch == "-" and i + 1 < n and text[i + 1] == "\n":
            out.append(BREAK)
            idx.append(i)
            continue
        for c in unicodedata.normalize("NFKC", ch):
            if not c.isspace():
                out.append(c)
                idx.append(i)
    return "".join(out), idx


def squash(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", s) if not c.isspace())


def _quote_re(q: str) -> re.Pattern:
    """Each line-end hyphen of the page may be kept ("con-ditional") or dropped ("synthetic") by the quote."""
    parts = ["(?:-|\x00)" if c == "-" else re.escape(c) for c in q]
    return re.compile("\x00?".join(parts))


def locate(page_text: str, quote: str) -> Optional[str]:
    """The page's own text matching `quote` (whitespace collapsed to single spaces), or None."""
    q = squash(quote)
    if not q:
        return None
    s, idx = _squash_page(page_text)
    m = _quote_re(q).search(s)
    if m is None:
        return None
    raw = page_text[idx[m.start()]: idx[m.end() - 1] + 1]
    return " ".join(raw.split())


def find_pages(doc: Doc, quote: str) -> list[int]:
    return [p for p, t in sorted(doc.pages.items()) if locate(t, quote) is not None]


def table_span(page_text: str, table_name: str) -> Optional[str]:
    """Text from the caption `<table_name>.` (or `:`) to the next `Table N.` / `Figure N.` caption, or None.
    Captions sit above tables (the ICML/NeurIPS convention): "Table 11." starts Table 11's span and "Table 12." ends it."""
    m = re.search(rf"(?<![\w.]){re.escape(table_name.strip())}\s*[.:]", page_text)
    if m is None:
        return None
    rest = page_text[m.end():]
    nxt = re.search(r"(?:^|\n)\s*(?:Table|Figure)\s+\d+\s*[.:]", rest)
    return page_text[m.start(): m.end() + (nxt.start() if nxt else len(rest))]

