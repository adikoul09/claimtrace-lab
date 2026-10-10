# Blind extraction: the exact prompts

Two independent LLM agents per side (run 1 and run 2), each started fresh with no access to our hand-built tables, report, or the other side's output. The paper agents read the paper through a web fetcher; the code agents read a `git archive` snapshot of robustdg at `3eee173` (no git history, no audit branches). Both fill the same schema (`schema.md`). The diff and the scoring are a fixed script (`scripts/extraction_diff.py`); no LLM judges the result.

Runs 1 and 2 on each side used the same prompt; the run-2 prompt differs only in the output file name (`*_run2.json`).

## Paper side

```text
You are the paper-parsing step of an automated ML reproducibility pipeline. Work only from the paper itself.

Paper: Mahajan, Tople, Sharma, "Domain Generalization using Causal Matching", ICML 2021, arXiv 2006.07500.
Read it with the WebFetch tool from https://arxiv.org/pdf/2006.07500 . The fetch tool summarises long documents, so make several focused fetches and ask each time for VERBATIM text of one part (e.g. "quote verbatim Section 3.2 and the Table 1 caption and all rows", "quote verbatim Appendix A.1", "quote verbatim any sentence about the weight of the matching penalty, lambda, or how it changes over training", "quote verbatim any sentence about model selection, early stopping or validation"). If the PDF fetch fails, try https://arxiv.org/abs/2006.07500 or https://ar5iv.labs.arxiv.org/html/2006.07500 .

Rules:
- Do not read any local file except /home/claude/blind/schema.md. Do not look at any code repository.
- Do not search for or read reproductions, reviews, blog posts, datasets, GitHub issues or discussions about this paper. Use only the paper.
- Never fill a value the paper does not state; use null. Every non-null value must carry a verbatim quote and where it is (section/appendix/table).

Task A, claim cards. For the slab dataset experiment (Table 1): output every reported number in Table 1 as a claim object {"method", "column", "mean", "sd", "where", "aggregation"}. Then list the relative or trend claims the text makes about Table 1 (which method beats which, by how much if stated), each with the verbatim sentence, typed as "relative" or "trend". Also say in one line how the paper describes PerfMatch (what it matches on, and whether that information is available in practice).

Task B, settings. Fill the schema in /home/claude/blind/schema.md for the experiment that produces Table 1, from the paper only (main text and appendix).

Write one JSON file to /home/claude/blind/out/paper_run1.json with top-level keys "claims", "relative_claims", "perfmatch_description", "settings", "notes". Validate it parses with python3 -c "import json;json.load(open('/home/claude/blind/out/paper_run1.json'))".
Your final message: the path written, how many Table 1 numbers you extracted, and anything you could not read.
```

## Code side

```text
You are the repository-analysis step of an automated ML reproducibility pipeline. Work only from the code, by reading it.

Input: a snapshot of the repository microsoft/robustdg at commit 3eee173, exactly as shipped, at /home/claude/blind/repo .
Experiment: the slab (synthetic) dataset experiment, which the associated paper reports in its Table 1.

Steps:
1. Find the command(s) the repository provides to reproduce this experiment (look in reproduce_scripts/, README, docs).
2. Trace what that command actually does, statically: argument values and defaults; which data the data-generation script produces versus which domains the command asks for; the model; how the optimizer is constructed (type, momentum, nesterov, lr, weight decay, any schedule); the training loop and every loss term with its weight and how that weight changes across epochs; how the reported epoch/checkpoint is chosen (model selection) and which number is printed as the result; the number of seeds and how seeds are set; the metric and how results are aggregated across seeds.
3. Fill the schema in /home/claude/blind/schema.md for this experiment from the code only. Evidence for each value = "path:line" plus the code on that line. Use null only when the code genuinely does not determine the value.

Rules:
- Read only files under /home/claude/blind/repo and the file /home/claude/blind/schema.md. Do not open any other path on this machine (in particular nothing under /home/claude/spike, /mnt, /tmp or /root). Do not use the web. Do not look for or read the paper.
- Do not run the code or install anything; read it (cat, grep, sed are fine).

Write one JSON file to /home/claude/blind/out/code_run1.json with top-level keys "command", "settings", "notes". Validate it parses with python3 -c "import json;json.load(open('/home/claude/blind/out/code_run1.json'))".
Your final message: the path written, the exact command you traced, and anything you could not determine.
```
