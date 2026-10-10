"""Paper intake and the Reader (SPEC §7.1).

fetch_paper   arXiv PDF -> text with "--- page N ---" markers (PyMuPDF); both files go to the run dir and to Storage
              (bucket `papers`), and the papers row for the project is created or updated.
extract       one structured LLM call with the Reader's role prompt over the whole text: claims and settings, each
              with a verbatim quote and page. Code then checks every one; nothing is corrected:
                - the quote must be on a page of the paper (NFKC, whitespace ignored, line-end hyphens optional); a
                  quote found on another page than the one cited moves to that page, with a note;
                - a claim's value must be one of the numbers in its quote, as the page prints it;
                - every number in a setting's value must be in its quote ("two" counts as 2); a setting the paper
                  does not state has value and quote null.
              Failing items are kept with valid: false and their problems.

  python -m lab.agents.paper --project-id <id> --arxiv 1503.02531 [--reference papers/distillation/results.json]

Ported from baseline/el01-auditor/el01/ingest/pdf_text.py (squash, locate) and the extraction rules of
el01/llm/prompts/paper_extractor*.md. Changed for Round 1: claims are SPEC §7.1 cards (running text as well as
tables), settings use the §7.1 keys plus hidden_units, PyMuPDF replaces pypdf."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from lab.db import ROOT, client, emit

PAGE_RE = re.compile(r"^--- page (\d+) ---$", re.M)
BUCKET = "papers"

SETTING_KEYS = ("architecture", "hidden_units", "optimizer", "lr", "epochs", "batch", "regularisation", "data_subset",
                "preprocessing", "augmentation", "temperature", "seeds")

_STR, _INT = {"type": "string"}, {"type": "integer"}
_NSTR, _NINT = {"type": ["string", "null"]}, {"type": ["integer", "null"]}
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "quote": {**_STR, "description": "verbatim sentence or table row that states the value"},
        "page": {**_INT, "description": "the --- page N --- marker of the page the quote is on"},
        "table_or_section": {**_STR, "description": "e.g. Table 2, or 3 Preliminary experiments on MNIST"},
        "metric": {**_STR, "description": "what is measured, e.g. test errors, accuracy"},
        "value": {"type": "number", "description": "the number exactly as the quote prints it"},
        "unit": {**_STR, "description": "e.g. errors, %, BLEU"},
        "direction": {"type": "string", "enum": ["lower_is_better", "higher_is_better"]},
        "whose": {"type": "string", "enum": ["method", "baseline", "oracle"],
                  "description": "method: what the paper proposes; baseline: what it compares against; oracle: a "
                                 "reference that uses more than the method may (e.g. a large teacher or ensemble)"},
        "model": {**_STR, "description": "which model or system the value belongs to, in a few words"},
    },
    "required": ["quote", "page", "table_or_section", "metric", "value", "unit", "direction", "whose", "model"],
}
SETTING_SCHEMA = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "enum": list(SETTING_KEYS)},
        "applies_to": {**_STR, "description": "the model the setting is for, or all"},
        "value": {**_NSTR, "description": "the value only, no explanation; null if the paper does not state it"},
        "quote": {**_NSTR, "description": "verbatim text that states it; null if not stated"},
        "page": _NINT,
    },
    "required": ["key", "applies_to", "value", "quote", "page"],
}
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": CLAIM_SCHEMA},
                   "settings": {"type": "array", "items": SETTING_SCHEMA}},
    "required": ["claims", "settings"],
}

PROMPT = """Paper: {title} (arXiv {arxiv_id})

The text below was extracted from the paper's PDF. Each page starts with a marker line `--- page N ---`.

Task: extract
1. claims: every quantitative result the paper reports for its own experiments (the paper's key results first),
   one card per number, with the verbatim quote that states it and the quote's page.
2. settings: for each model in the main experiments, the settings among these keys: {keys}. One entry per key and
   model; applies_to "all" when the setting is shared. A key the paper does not state for an experiment gets value,
   quote and page null.

Rules:
- Use only this text. Do not use anything you know about this paper from elsewhere.
- Verbatim means copied character for character from the text; a line break may become a space. No ellipses, no
  paraphrase. Code checks every quote against the page you name and every number against the quote; an item that
  fails is marked invalid, so copy exactly.
- A claim's value is the number exactly as its quote prints it. A setting's value is the value only, in a few words.
- Never fill a value the paper does not state; use null.

{text}"""


# ---- page text ----------------------------------------------------------------------------------------------------

def render(pages: list[str], first: int = 1) -> str:
    return "".join(f"--- page {i} ---\n{t.rstrip()}\n\n" for i, t in enumerate(pages, first))


def parse_pages(text: str) -> dict[int, str]:
    marks = list(PAGE_RE.finditer(text))
    return {int(m.group(1)): text[m.end():(marks[k + 1].start() if k + 1 < len(marks) else len(text))].strip("\n")
            for k, m in enumerate(marks)}


BREAK = "\x00"  # a line-end hyphen ("-\n") in the squashed page text


def squash(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", s) if not c.isspace())


def _squash_page(text: str) -> tuple[str, list[int]]:
    """NFKC page text without whitespace, a line-end hyphen kept as BREAK, plus the index in `text` of every kept
    character."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch == "-" and i + 1 < len(text) and text[i + 1] == "\n":
            out.append(BREAK)
            idx.append(i)
            continue
        for c in unicodedata.normalize("NFKC", ch):
            if not c.isspace():
                out.append(c)
                idx.append(i)
    return "".join(out), idx


def locate(page_text: str, quote: str) -> Optional[str]:
    """The page's own text matching `quote` (whitespace collapsed to single spaces), or None. Each line-end hyphen of
    the page may be kept ("con-ditional") or dropped ("conditional") by the quote."""
    q = squash(quote)
    if not q:
        return None
    s, idx = _squash_page(page_text)
    pattern = f"{BREAK}?".join("(?:-|\x00)" if c == "-" else re.escape(c) for c in q)
    m = re.search(pattern, s)
    if m is None:
        return None
    return " ".join(page_text[idx[m.start()]: idx[m.end() - 1] + 1].split())


NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
NUM_RE = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|-?\d+(?:\.\d+)?|\b(?:"
                    + "|".join(NUMBER_WORDS) + r")\b", re.I)


def numbers(text: str) -> list[float]:
    """Every number in `text` as printed: digits (60,000 -> 60000) and the number words zero to twelve."""
    out = []
    for m in NUM_RE.finditer(unicodedata.normalize("NFKC", text)):
        t = m.group(0).lower()
        out.append(float(NUMBER_WORDS[t]) if t in NUMBER_WORDS else float(t.replace(",", "")))
    return out


FOOTER_RE = re.compile(r"\n\s*\d{1,3}\s*$")  # a page number alone on the page's last line


def find_quote(pages: dict[int, str], quote: Optional[str],
               page: Optional[int]) -> tuple[Optional[int], Optional[str], bool]:
    """(page, the page's own text, spans two pages) for a quote: the cited page first, then any page, then a sentence
    that runs over a page break (the first page's page number dropped); the page is the one the quote starts on."""
    if not quote:
        return None, None, False
    order = ([page] if page in pages else []) + [p for p in sorted(pages) if p != page]
    for p in order:
        hit = locate(pages[p], quote)
        if hit is not None:
            return p, hit, False
    for p in sorted(pages):
        if p + 1 in pages:
            hit = locate(FOOTER_RE.sub("", pages[p].rstrip()) + "\n" + pages[p + 1], quote)
            if hit is not None:
                return p, hit, True
    return None, None, False


# ---- checks -------------------------------------------------------------------------------------------------------

def _placed(item: dict, pages: dict[int, str]) -> tuple[dict, Optional[str], list[str]]:
    out, problems = dict(item), []
    found_page, hit, spans = find_quote(pages, item.get("quote"), item.get("page"))
    out["note"] = None
    if hit is None:
        problems.append("quote not found in the paper text")
    else:
        if found_page != item.get("page"):
            out["note"] = f"quote is on page {found_page}, not page {item.get('page')} as cited"
        elif spans:
            out["note"] = f"quote runs over pages {found_page}-{found_page + 1}"
        out["page"], out["quote"] = found_page, hit
    return out, hit, problems


def check_claim(item: dict, pages: dict[int, str]) -> dict:
    out, hit, problems = _placed(item, pages)
    in_quote = hit is not None and float(item["value"]) in numbers(hit)
    if hit is not None and not in_quote:
        problems.append(f"value {float(item['value']):g} is not a number in the quote")
    out.update(checks={"quote_found": hit is not None, "value_in_quote": in_quote}, valid=not problems,
               problems=problems)
    return out


def check_claims(items: list[dict], pages: dict[int, str]) -> list[dict]:
    return [{"id": f"c{i}", **check_claim(c, pages)} for i, c in enumerate(items, 1)]


def check_setting(item: dict, pages: dict[int, str]) -> dict:
    if item.get("value") in (None, "") and not item.get("quote"):
        return {**item, "value": None, "quote": None, "page": None, "note": None, "checks": {"stated": False},
                "valid": True, "problems": []}
    if not item.get("quote"):
        return {**item, "note": None, "checks": {"stated": True, "quote_found": False}, "valid": False,
                "problems": ["a stated value needs a quote"]}
    out, hit, problems = _placed(item, pages)
    missing = [n for n in numbers(str(item.get("value"))) if hit is not None and n not in numbers(hit)]
    if missing:
        problems.append(f"numbers {[f'{n:g}' for n in missing]} of the value are not in the quote")
    out.update(checks={"stated": True, "quote_found": hit is not None, "numbers_in_quote": hit is not None
                       and not missing}, valid=not problems, problems=problems)
    return out


def compare_with_reference(claims: list[dict], reference: dict, suffix: str = "_test_errors") -> dict:
    """For each reference value whose key ends in `suffix`: the first valid claim with that value, or None."""
    out = {}
    for k, v in reference.items():
        if k.endswith(suffix) and isinstance(v, (int, float)):
            hit = next((c["id"] for c in claims if c["valid"] and float(c["value"]) == float(v)), None)
            out[k] = {"expected": v, "claim_id": hit}
    return out


# ---- relevant sections (paper text per request stays under 40 KB; never the whole PDF text) -----------------------

MAX_REQUEST_BYTES = 40_000
READER_MAX_OUTPUT = 4_000  # the gateway's maximum output (reasoning included); claims and settings each get a call
SECTION_BUDGET = 20_000  # bytes of paper text per request (measured: keeps all of 1503.02531 section 3)
CHUNK_BYTES = 3_000
NAMED_HEADINGS = ("abstract", "introduction", "references", "bibliography", "acknowledgments", "acknowledgements",
                  "appendix", "conclusion", "conclusions", "related work", "discussion")
DROP_TITLES = ("references", "bibliography", "acknowledg", "related work")
KEYWORDS = ("experiment", "result", "setup", "train", "test", "error", "accuracy", "dataset", "table", "epoch",
            "learning rate", "batch", "hidden", "layer", "units", "dropout", "temperature", "baseline", "evaluat",
            "optimi", "regulari", "augment", "implementation", "hyperparameter", "seed", "loss")
TITLE_BONUS = ("experiment", "result", "setup", "evaluat", "implementation", "training", "mnist", "abstract")
NUM_RE_SIMPLE = re.compile(r"\d+(?:[.,]\d+)?")
HEAD_NUM_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\.?$")
HEAD_TITLE_RE = re.compile(r"^[A-Z][A-Za-z0-9 ,:&()'/-]{1,70}$")


def _heading(lines: list[str], i: int) -> Optional[tuple[str, int]]:
    """(title, lines used) if a heading starts at lines[i]: a known name alone on its line, or a section number on
    its own line followed by a short capitalised title (the way PyMuPDF splits '3 Experiments')."""
    s = lines[i].strip()
    if s.lower().rstrip(".:") in NAMED_HEADINGS:
        return s.rstrip(".:"), 1
    if HEAD_NUM_RE.match(s) and i + 1 < len(lines):
        t = lines[i + 1].strip()
        if HEAD_TITLE_RE.match(t) and not t.endswith(".") and len(t.split()) <= 8:
            return f"{s.rstrip('.')} {t}", 2
    m = re.match(r"^(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z0-9 ,:&()'/-]{1,70})$", s)
    if m and not s.endswith(".") and len(m.group(2).split()) <= 8:
        return f"{m.group(1)} {m.group(2)}", 1
    return None


def sections(text: str) -> list[dict]:
    """The paper split at its headings: [{title, lines: [(page, line)]}], in order; '(front)' before the first."""
    out = [{"title": "(front)", "lines": []}]
    for page, body in sorted(parse_pages(text).items()):
        lines = body.splitlines()
        i = 0
        while i < len(lines):
            h = _heading(lines, i)
            if h:
                out.append({"title": h[0], "lines": []})
                i += h[1]
                continue
            out[-1]["lines"].append((page, lines[i]))
            i += 1
    return [s for s in out if s["lines"] or s["title"] != "(front)"]


def _score(title: str, body: str) -> float:
    low, n = body.lower(), max(len(body), 1)
    kw = sum(low.count(k) for k in KEYWORDS) * 1000 / n
    nums = len(NUM_RE_SIMPLE.findall(body)) * 1000 / n
    bonus = 10 if any(b in title.lower() for b in TITLE_BONUS) else 0
    return kw * 2 + nums * 0.5 + bonus


def _render_chunk(lines: list[tuple[int, str]], title: str) -> str:
    out, page = [], None
    for p, line in lines:
        if p != page:
            out.append(f"--- page {p} ---")
            page = p
        out.append(line)
    return f"[section: {title}]\n" + "\n".join(out)


def select_sections(text: str, budget: int = SECTION_BUDGET) -> tuple[str, dict]:
    """The paper's relevant sections, under `budget` bytes, in paper order, page markers kept. Code decides: drop
    references, acknowledgements and related work; always keep the abstract (or the front matter); rank the rest by
    setup/results keywords and number density (results tables are number-dense); fill greedily."""
    secs = sections(text)
    chunks, dropped = [], []
    for si, s in enumerate(secs):
        if any(d in s["title"].lower() for d in DROP_TITLES):
            dropped.append(s["title"])
            continue
        cur, size = [], 0
        for pl in s["lines"] + [None]:
            if pl is None or (size + len(pl[1].encode("utf-8")) + 1 > CHUNK_BYTES and cur):
                if cur:
                    body = "\n".join(l for _, l in cur)
                    must = s["title"].lower() == "abstract" or (s["title"] == "(front)" and not chunks)
                    chunks.append({"order": len(chunks), "title": s["title"], "lines": cur, "must": must,
                                   "score": float("inf") if must else _score(s["title"], body)})
                cur, size = [], 0
                if pl is None:
                    break
            cur.append(pl)
            size += len(pl[1].encode("utf-8")) + 1
    chosen, used = [], 0
    for c in sorted(chunks, key=lambda c: -c["score"]):
        piece = _render_chunk(c["lines"], c["title"])
        n = len(piece.encode("utf-8")) + 2
        if used + n <= budget:
            chosen.append((c, piece))
            used += n
    chosen.sort(key=lambda cp: cp[0]["order"])
    sel = "\n\n".join(p for _, p in chosen)
    kept = list(dict.fromkeys(c["title"] for c, _ in chosen))
    return sel, {"sent_bytes": len(sel.encode("utf-8")), "total_bytes": len(text.encode("utf-8")),
                 "sections": kept, "dropped": dropped,
                 "skipped": sorted({c["title"] for c in chunks} - set(kept))}


def check_request_size(prompt: str, system: str = "") -> None:
    n = len((system + prompt).encode("utf-8"))
    if n > MAX_REQUEST_BYTES:
        raise ValueError(f"request is {n} bytes; paper text per request must stay under {MAX_REQUEST_BYTES} bytes")


# ---- the Reader ---------------------------------------------------------------------------------------------------

READER_SYSTEM = ("You are the Reader. You extract claims and settings from the paper text in the message, in one "
                 "structured answer. You have no tools: do not try to read, write or save files; everything you need "
                 "is in the message. Answer with exactly the JSON object the schema asks for and nothing else: no "
                 "extra keys, no prose.")
COMPACT_SETTINGS = ("\n\nThis call: return only the settings, compactly: each value in a few words and each quote the "
                    "shortest verbatim span that states it. The claims were extracted in a separate call.")


def reader_system(agent: dict) -> str:
    """The code's Reader instruction first; the agent's own role prompt (refined by the controller) only as additional
    guidance after it, so the schema and the no-tools rule win."""
    role = (agent.get("role_prompt") or "").strip()
    return READER_SYSTEM + (f"\n\nAdditional guidance from the agent's role (the rules above win):\n{role}" if role
                            else "")


PART_BYTES = 7_000  # paper text per claims call: one answer for the whole excerpt overran the 4000-token output cap
CLAIMS_PER_PART = 25  # a 44-cell per-row table in one part ran through the cap; 18 claims took 1702 tokens out
CLAIMS_PART = ("\n\nThis call: return only the claims stated in THIS part of the paper's text (part {i} of {n}); the "
               "other parts are read in separate calls. Return at most {cap} claims for this part: the headline "
               "results first; from a long per-row breakdown table keep only its main rows. Keep each claim compact: "
               "the quote at most 20 words (the shortest verbatim span that states the value) and its page number; "
               "no other context.")


def halves(part: str) -> list[str]:
    """A part cut in two at the line nearest its middle byte (for a part whose claims answer overran the cap)."""
    lines, total, run = part.split("\n"), len(part.encode("utf-8")), 0
    for k, line in enumerate(lines[:-1], 1):
        run += len(line.encode("utf-8")) + 1
        if run >= total / 2:
            return [p for p in ("\n".join(lines[:k]), "\n".join(lines[k:])) if p.strip()]
    return [part]


def overran(e: Exception) -> bool:
    return "output cap" in str(e) and "ran out" in str(e)


def split_parts(sel: str, limit: int = PART_BYTES) -> list[str]:
    """The selected excerpt in parts of at most `limit` bytes, cut only between section chunks (each keeps its
    [section: ...] header and page markers)."""
    chunks = [c if i == 0 else "[section:" + c for i, c in enumerate(sel.split("\n\n[section:"))]
    total = len(sel.encode("utf-8"))
    n = max(1, -(-total // limit))  # the fewest parts at `limit`; then balanced, up to 15% over it
    target = min(total / n * 1.15, limit * 1.15)
    parts, cur = [], ""
    for c in chunks:
        if cur and len((cur + "\n\n" + c).encode("utf-8")) > target:
            parts.append(cur)
            cur = c
        else:
            cur = cur + "\n\n" + c if cur else c
    return parts + ([cur] if cur else [])


def _claim_key(c: dict) -> tuple:
    try:
        return round(float(c.get("value")), 6), c.get("page")
    except (TypeError, ValueError):
        return c.get("value"), c.get("page")


def merge_claims(batches: list[list[dict]]) -> list[dict]:
    """Claims from all parts in order; a claim with the same value and page as one already kept, whose quote contains
    or is contained in the kept one's (whitespace ignored), is the same claim read twice."""
    kept: list[tuple[tuple, str, dict]] = []
    for c in (c for batch in batches for c in batch):
        key, q = _claim_key(c), squash(c.get("quote") or "")
        if not any(k == key and q and kq and (q in kq or kq in q) for k, kq, _ in kept):
            kept.append((key, q, c))
    return [c for _, _, c in kept]


def extract(text: str, *, llm, agent: dict, title: str = "", arxiv_id: str = "", task_id=None,
            model: str = "smart") -> dict:
    """The model sees only the selected sections; quotes are checked against every page of the full text.
    Claims: one compact call per part of the excerpt (PART_BYTES), merged and de-duplicated by code. Settings: taken
    from the claims answer when the excerpt is one part and that answer carries them, else one compact call."""
    from lab.llm import LLMError, Request

    sel, report = select_sections(text)
    base = dict(title=title or "(untitled)", arxiv_id=arxiv_id or "?", keys=", ".join(SETTING_KEYS))
    system = reader_system(agent)
    parts = split_parts(sel)
    tokens, resp, batches, settings = 0, None, [], None

    def call(p, part):
        nonlocal tokens, resp
        check_request_size(p, system)
        schema = {"type": "object", "properties": {part: EXTRACT_SCHEMA["properties"][part]}, "required": [part]}
        resp = llm.call(Request(agent=agent["name"], system=system, prompt=p, schema=schema,
                                model=model, max_output=READER_MAX_OUTPUT), agent_id=agent.get("id"), task_id=task_id)
        tokens += resp.tokens_in + resp.tokens_out
        return resp.output if isinstance(resp.output, dict) else {}

    def claims(part_text, label):
        return call(PROMPT.format(**base, text=part_text)
                    + CLAIMS_PART.format(i=label, n=len(parts), cap=CLAIMS_PER_PART), "claims")

    skipped, last_err = [], None
    for i, part_text in enumerate(parts, 1):
        try:
            got = claims(part_text, i)
        except LLMError as e:  # the answer ran through the output cap: read the part in two halves
            if not overran(e):
                raise
            for label, half in zip(("first half", "second half"), halves(part_text)):
                try:
                    batches.append(claims(half, f"{i}, {label}").get("claims") or [])
                except LLMError as e2:  # still over: skip this half, keep the other parts' claims
                    if not overran(e2):
                        raise
                    last_err = e2
                    skipped.append({"part": f"{i}, {label}", "bytes": len(half.encode("utf-8")), "error": str(e2)})
            continue
        batches.append(got.get("claims") or [])
        if len(parts) == 1 and isinstance(got.get("settings"), list):
            settings = got["settings"]  # one part and its answer already has them: no settings call
    if not batches:
        raise last_err
    if settings is None:
        settings = call(PROMPT.format(**base, text=sel) + COMPACT_SETTINGS, "settings").get("settings") or []
    pages = parse_pages(text)
    report = {**report, "parts": len(parts), "part_bytes": [len(p.encode("utf-8")) for p in parts], "skipped": skipped}
    return {"claims": check_claims(merge_claims(batches), pages),
            "settings": [check_setting(s, pages) for s in settings],
            "tokens": tokens, "model": resp.model, "mode": resp.mode, "cache_key": resp.key, "sections": report}


# ---- intake -------------------------------------------------------------------------------------------------------

def arxiv_title(arxiv_id: str) -> Optional[str]:
    import httpx

    r = httpx.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id}, timeout=30,
                  follow_redirects=True)
    r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    t = ET.fromstring(r.text).find("a:entry/a:title", ns)
    return " ".join(t.text.split()) if t is not None and t.text else None


def _upload(db, path: str, data: bytes, content_type: str) -> str:
    try:
        db.storage.get_bucket(BUCKET)
    except Exception:
        db.storage.create_bucket(BUCKET, options={"public": False})
    db.storage.from_(BUCKET).upload(path, data, {"content-type": content_type, "upsert": "true"})
    return f"{BUCKET}/{path}"


def fetch_paper(arxiv_id: str, workdir: Path, *, db, project_id) -> dict:
    """Download, extract and store the paper; upsert the papers row. Returns {title, pages, chars, pdf_path,
    text_path}."""
    import httpx
    import pymupdf

    r = httpx.get(f"https://arxiv.org/pdf/{arxiv_id}", timeout=60, follow_redirects=True)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise ValueError(f"arXiv returned {r.headers.get('content-type')} for {arxiv_id}, not a PDF")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "paper.pdf").write_bytes(r.content)
    with pymupdf.open(workdir / "paper.pdf") as doc:
        text = render([p.get_text() for p in doc])
        n_pages = doc.page_count
    (workdir / "paper.txt").write_text(text, encoding="utf-8")
    sel, report = select_sections(text)
    (workdir / "paper_sections.txt").write_text(sel, encoding="utf-8")  # what agents read; never the whole text
    try:
        title = arxiv_title(arxiv_id)
    except Exception:
        title = None  # the metadata API is optional; the PDF is what is read

    base = f"{project_id}/{arxiv_id}"
    pdf_path = _upload(db, f"{base}.pdf", r.content, "application/pdf")
    text_path = _upload(db, f"{base}.txt", text.encode("utf-8"), "text/plain; charset=utf-8")
    db.table("papers").upsert({"project_id": project_id, "arxiv_id": arxiv_id, "title": title, "pdf_path": pdf_path,
                               "text_path": text_path}, on_conflict="project_id").execute()
    emit(db, "paper_fetched", f"paper fetched: {title or arxiv_id}",
         f"arXiv {arxiv_id}: {n_pages} pages, {len(text)} chars of text extracted with PyMuPDF",
         project_id=project_id, data={"pdf_path": pdf_path, "text_path": text_path, "pages": n_pages})
    return {"title": title, "pages": n_pages, "chars": len(text), "pdf_path": pdf_path, "text_path": text_path,
            "sections": report}


def read_paper(project_id: str, arxiv_id: str, *, db, llm, agent: dict, workdir: Path, task_id=None,
               reference: Optional[dict] = None, model: str = "smart", cap_min: float = 20) -> dict:
    """fetch_paper, then extract, then tag each claim runnable or not (lab/agents/triage.py), then store
    papers.claims and papers.settings, with an event for each step."""
    from lab.agents.triage import extract_facts, summary, triage

    info = fetch_paper(arxiv_id, workdir, db=db, project_id=project_id)
    text = (Path(workdir) / "paper.txt").read_text(encoding="utf-8")
    try:
        res = extract(text, llm=llm, agent=agent, title=info["title"] or "", arxiv_id=arxiv_id, task_id=task_id,
                      model=model)
    except Exception as e:
        emit(db, "reader_failed", f"{agent['name']} could not extract claims", f"{type(e).__name__}: {e}"[:500],
             project_id=project_id, agent_id=agent.get("id"), task_id=task_id)
        raise
    claims, settings = res["claims"], res["settings"]
    try:  # facts only (a small call); a failure leaves every claim "unverified", never fails the Reader
        facts, facts_tokens, facts_error = *extract_facts(text, claims, llm=llm, agent=agent, title=info["title"] or "",
                                                          arxiv_id=arxiv_id, task_id=task_id, model=model), None
    except Exception as e:
        facts, facts_tokens, facts_error = [], 0, f"{type(e).__name__}: {e}"[:300]
    claims = triage(claims, facts, cap_min)
    res = {**res, "claims": claims, "tokens": res["tokens"] + facts_tokens}
    emit(db, "claims_triaged", f"claims triaged: {summary(claims)}",
         "code rules on the facts the Reader extracted (no public data, dataset too big, compute over budget, needs "
         f"GPU; cap {cap_min:g} CPU-min)" + (f"; the facts call failed: {facts_error}" if facts_error else ""),
         project_id=project_id, agent_id=agent.get("id"), task_id=task_id,
         data={"claims": [{"claim_id": c["id"], **{k: c["runnable"][k] for k in ("status", "reason")}}
                          for c in claims], "facts_tokens": facts_tokens})
    db.table("papers").update({"claims": claims, "settings": settings}).eq("project_id", project_id).execute()
    n_ok = sum(c["valid"] for c in claims)
    stated = [s for s in settings if s["checks"].get("stated")]
    cmp = compare_with_reference(claims, reference) if reference else None
    reason = (f"{n_ok} of {len(claims)} claims passed the code checks (quote on the page, value in the quote); "
              f"{sum(s['valid'] for s in stated)} of {len(stated)} stated settings passed")
    if cmp is not None:
        found = [k for k, v in cmp.items() if v["claim_id"]]
        reason += f"; reference values matched: {len(found)} of {len(cmp)}"
    emit(db, "claims_extracted", f"{agent['name']} extracted {len(claims)} claims and {len(settings)} settings",
         reason, project_id=project_id, agent_id=agent.get("id"), task_id=task_id,
         data={"tokens": res["tokens"], "model": res["model"], "mode": res["mode"], "cache_key": res["cache_key"],
               "invalid_claims": [c["id"] for c in claims if not c["valid"]], "reference": cmp})
    return {**res, "info": info, "reference": cmp}


def main(argv=None) -> None:
    from lab.agents.runtime import load_agent
    from lab.llm import LLM

    ap = argparse.ArgumentParser(description="Fetch a paper and run the Reader on it")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--arxiv", required=True)
    ap.add_argument("--agent", default="reader-v1")
    ap.add_argument("--model", default="smart")
    ap.add_argument("--reference", help="a B0 results.json; its `paper` block is compared with the claims")
    a = ap.parse_args(argv)
    db = client()
    ref = json.loads(Path(a.reference).read_text(encoding="utf-8"))["paper"] if a.reference else None
    res = read_paper(a.project_id, a.arxiv, db=db, llm=LLM(db=db), agent=load_agent(db, a.agent),
                     workdir=ROOT / "runs" / f"paper-{a.project_id}", reference=ref, model=a.model)
    for c in res["claims"]:
        print(f"{c['id']} {'ok ' if c['valid'] else 'BAD'} p{c['page']} {c['model']}: {c['value']:g} {c['unit']} "
              f"({c['whose']}) | {c['quote'][:90]}" + (f" | {c['problems']}" if c["problems"] else ""))
    for s in res["settings"]:
        print(f"   {'ok ' if s['valid'] else 'BAD'} {s['key']} [{s['applies_to']}] = {s['value']}"
              + (f" | {s['problems']}" if s["problems"] else ""))
    if res["reference"]:
        print("reference:", res["reference"])


if __name__ == "__main__":
    main()
