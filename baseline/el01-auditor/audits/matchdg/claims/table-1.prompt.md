You are the paper-parsing step of an automated ML reproducibility pipeline. Work only from the paper text below.

Paper: Domain Generalization using Causal Matching (ICML 2021)
Target: Table 1

The text below was extracted from the paper's PDFs. Each page starts with a marker line `[page N]`. Document `main` is
the paper and document `supplement` its supplementary material; each has its own page numbers. A table comes out as one
line per row (a long row may wrap onto the next line).

Task: claim cards for Table 1. Find the table, then fill the answer schema:
- `table`, `doc`, `page`: the table's name as its caption prints it, the document, and the page of its rows.
- `caption_quote`: the caption's first sentence, verbatim. `header_line`: the column-header line, verbatim.
  `columns`: the numeric columns left to right, as printed (not the row-label column).
- `rows`: every row of the table, including rows whose numbers the paper took from other papers. `line` is the whole
  row as printed, from the label to the last cell. `cells`: one entry per numeric column, in order: `mean` is the
  number, `sd` the number in brackets (null when there is none).
- `role` of each row: `method` = a method this paper proposes; `baseline` = a method it compares against; `oracle` = a
  method that uses information not available in practice (for example ground-truth matches or labels that a real user
  would not have). Decide from what the paper says and quote the sentence that supports it, from anywhere in either
  document, with its document and page.
- `provenance`: `cited` when the paper says the row's numbers were taken from other work (quote that sentence),
  otherwise `this_paper`.
- `metric` and `aggregation`: quote the sentences that say what the numbers measure and how they are aggregated (mean
  over how many runs or seeds, what the bracketed number is). If the paper does not say, use kind `not_stated` and a
  null quote.
- `relative_claims`: sentences in the text that compare rows of this table (which beats which, by how much if stated,
  or a trend), each typed `relative` or `trend`, with the verbatim sentence, its document and page, and the row labels
  it compares.

Rules:
- Use only this text. Do not use anything you know about this paper, its code or its reproductions from elsewhere.
- Verbatim means copied character for character from the text below; a line break may become a space. No ellipses, no
  paraphrase, no corrected typos. Code checks every quote against the page you name and every number against the row
  line you quote; a row that fails is discarded, so copy exactly.
- Never fill a value the paper does not state; use null.

=== document: main === (text of workspace/papers/matchdg/mahajan21b.pdf, sha256 c9d9f8a4fc7fabd12534630f3268a3dff52eae611eefbebd501f78718ca07c21, extracted with pypdf 6.19.0: 12 pages)
=== document: supplement === (text of workspace/papers/matchdg/mahajan21b-supp.pdf, sha256 2726d78e4d55150c7c208bb37195545ccc32338edff04e9919f1325b94530e67, extracted with pypdf 6.19.0: 19 pages)
