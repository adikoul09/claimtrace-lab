# EL-01 Team Notes (internal, not for submission)

Everything here is for the team only. The submission material is `EL-01-deep-analysis.md` (concept note), `EL-01-features-and-diagrams.md` (technical spec), the blueprint page and its PDF (`EL-01-blueprint.pdf`), the short cuts (`EL-01-one-page.pdf` and the 5-slide deck), and the evidence (report, logs, grades) published with the blueprint page.

The final review gave a green light to start the prototype (8/10, 9 with fixes). The final screening review, against the judging criteria, kept the green light at 8/10 and named new gaps: architecture and scaling missing from the short cuts, a second SciCoQA row for this repo (row 67), and presentation bugs. What was done about each is in the second table below.

## Needed from the team before submission

1. **Team table** (concept note §8): four rows with name, role and what each person owns. The roles are drafted; only names are missing.
2. **Freeze the evidence on GitHub.** The blueprint page can still be edited after you submit, so judges should see a tagged copy that cannot drift. Fork `microsoft/robustdg` on GitHub, then either attach the fork to this project (Claude pushes and switches every link), or push it yourself:
   ```
   git clone https://github.com/<your-account>/robustdg && cd robustdg
   git fetch /path/to/matchdg-audit.bundle 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
   git push origin --all && git push origin round0-submission
   ```
   The tag `round0-submission` points at the `audit-evidence` branch as submitted. Its message carries the sha256 of `manifest.json`, which lists the sha256 of every evidence file; the same hash is printed in the blueprint's Evidence section and PDF. Then send Claude the fork URL so the links point at `https://github.com/<your-account>/robustdg/tree/round0-submission`.
3. **The host's PPT template.** Round 0 is submitted on a template from the organisers. Its slides should be filled from the blueprint (section "For the host's PPT template" below lists what goes where). The 5-slide deck and the one-pager were left as they are; only wording errors in the one-pager were fixed.
4. **Three user interviews.** Three quotes beat zero. Questions below.
5. **One number to check by hand:** the MLRC report's Table 1 (ERM 64.6, RandMatch 66.9, PerfMatch 87.9) came from the submission copy; check it against the ReScience PDF (DOI 10.5281/zenodo.6574661), which neither we nor the reviewer could open. The "submission version" caveat stays until someone does.

## What changed after the final review (3 Oct 2026)

| Review point | What we did | Where |
|---|---|---|
| Features 3 and 4 marked "working" although repairs, branch patches and the claim-to-command link were by hand | Status now reads "runner and grader working; repairs by hand" and "...; branch patches by hand"; the automation table has a claim-to-command row | concept §2.1, §3; spec §1; blueprint features |
| One case labelled three ways ("gap larger than reported") | One verdict list in code (`scripts/verdicts.py`): *Partially reproduced* with a size note; one `label()` function writes every verdict string on every page | concept §4, spec §5, report, blueprint |
| "Setup differs" applied inconsistently | Now a flag set by a rule in code: a code omission had to be filled, or a finding's branch has a Holm-surviving effect on a method the claim names; untested findings become notes. Table 1: every claim flagged (F1), plus F2 or F3 where they move the number; F4 is a reason nowhere. Table 11: no flag, note that F3 and F4 apply but were not tested | spec §5, report B4 and Part A, blueprint report card |
| Table 11 headline said "reproduce closely" while all 28 verdicts said Inconclusive | Margin = max(paper's sd, a practical floor), default 1 point. Because the floor came after the first run, Table 11 was re-run on fresh MNIST subsets with the floor declared and hashed first; the headline now quotes that run's counts | concept §2.2, report Part A, blueprint |
| Evidence lives on a page we keep editing | Every evidence file is hashed in `manifest.json`; the manifest's hash is printed on the page and in the PDF; the bundle carries a `round0-submission` tag. Pushing the tag (item 2) finishes this | blueprint Evidence, `matchdg-audit.bundle` |
| MLRC numbers unchecked | Caveat kept; item 5 above | concept §2.4, report |
| autoarxiv cited loosely | Cites `src/local/skills.rs` lines 30–31 at `f4cec9f`, and says autoarxiv *appears to* use that template | concept §6, blueprint |
| Three agentic steps untested | Build plan puts the repair agent, the claim-to-command linker and the branch-patch writer first, each with a named test | spec §9, concept §8, blueprint |
| Branch-patch writer should check itself | Spec: re-run the code extractor on each branch, require exactly one changed setting | spec §6 |
| MatchDG as the regression test | Done: `golden/` holds the hand-built tables, findings F1–F6 and every verdict, number and flag; `scripts/regression.py` re-derives them all from the raw logs and extractor outputs | spec §7, §9 |
| Grader rules before any UI | Done (rules version 2); version 1 and its outputs are kept for the record | `scripts/verdicts.py`, `scripts/v1/` |
| First milestone: a second paper, blind | Candidates picked (spec §9); do not read their SciCoQA rows before the run | spec §9 |
| Prepare a 1-page and a 5-slide cut | Done | `EL-01-one-page.pdf`, deck link |

**Table 11 confirmation result.** Nothing in MatchDG's own table is refuted; the counts and every cell are in the report, Part A. Two things did not confirm on fresh data: MatchDG's small edge over RandMatch (Inconclusive in both runs) and the text's claim that MatchDG beats prior work at every domain but 0° (clearly above at three domains in the first run, not separable anywhere in the confirmation). Both are stated on every page.

## What changed after the final screening review (3 Oct 2026)

| Review point | What we did | Where |
|---|---|---|
| SciCoQA lists a second discrepancy for robustdg (row 67, rotation direction) that no file mentioned | Traced it in the code, ran it as branch F7 with a pre-registered rule, and report it everywhere; SciCoQA recall on this repo is now stated: our hand audit and blind extraction found 1 of its 2 rows | report Part A3, concept §2.2, spec §3, blueprint |
| "Tables 8 and 9 match the code's settings" and "5 not in SciCoQA" read as complete | Both now say what F7 adds | all files |
| Schema has no preprocessing keys | Schema version 2 adds resizing, normalisation, augmentation, domain construction and the data a selection metric reads; the blind test is re-run with it as a build step | spec §3, §9 |
| Scaling gets one risk row | New "Cost and scaling" section with measured numbers: compute per run set, wall-clock per Table 11 pass, and the measured no-retraining lever for selection-rule branches | blueprint, concept §2.5, spec §8 |
| No user path or UI | Wireframe: paper and repo in, job status, report out; the report screen exists already (the blueprint page is rendered by script from `grades.json`) | blueprint "What the user sees" |
| Three of four second-paper candidates are graph papers | Label-Free Explainability (ICML 2022, PyTorch, MNIST) replaces BUDDY as pick 2; BUDDY is a backup | spec §9, concept §8, blueprint |
| Build plan | Adds the code extractor's data-pipeline test (row 67) and measuring wall-clock and tokens per paper during the second-paper run | spec §9, concept §8, blueprint |
| Deck and one-pager: architecture, scaling, slide 3 number wrap, stat wording, hash label, names | Left to the host's PPT template (see below). Only the one-pager's wording errors were fixed: the stat now says "change in the oracle's accuracy", the hash is labelled "first 16 hex digits", and the SciCoQA count is corrected | one-pager |

**F7 result.** The flipped copy reaches Table 11 at one point: MatchDG's first phase picks its checkpoint on plain-augmented pairs. Removing the flips changed that checkpoint in 8 of 18 runs but moved MatchDG's six-domain average by −0.04 points (95% CI −0.41 to 0.34), and 0 of 6 cells survive Holm. So F7 is a note, not a "setup differs" reason, and no verdict changes. Two small disclosures are in the report's Limits: the pre-registration miscounted the byte-identical plain and label files (it says 72; the correct count is 108 of 108), and `grade_f7.py` was edited after the runs only to cast two numpy booleans for JSON (statistics unchanged; the hashed copy is kept). If a judge asks how we found F7: we did not; SciCoQA did, and we say so (recall 1 of 2 on this repo).

## For the host's PPT template

Fill whatever slides the template has from these parts of the blueprint, in this order of importance:
1. **Problem:** CORE-Bench reported solved; REPRO-Bench best agent 36.6% against 25% random; SciCoQA best LLMs find 46.7% of real discrepancies.
2. **User path:** the wireframe (paper and repo in, job status, report out). Say the report screen exists today.
3. **Architecture:** the blueprint's architecture figure, with its one-line caption: models read, code sets every number and verdict.
4. **The audit:** Table 11 confirmation counts and "MatchDG beats ERM: Reproduced"; Table 1's oracle and the "validation loss" reading; F7 and its result.
5. **Scaling:** compute = claims × seeds × (1 + branches); the run-set table; selection-rule branches need no retraining (measured); caching, parallel branches, smoke-run budget; tokens measured on the second paper; CPU papers only.
6. **What is new:** the prior-art table.
7. **Prototype status and build plan,** then **team**.

The reviewer's presentation points apply to any slide: no "(names pending)" anywhere; big numbers must not wrap (keep "−25.8" on one line); write "change in the oracle's accuracy", never "accuracy of −25.8"; a shortened hash is labelled "sha256, first 16 hex digits".

## Prototype: what to build first

Follow spec §9 in order. The short version:
1. Repair agent, tested against our three repair commits and the missing-domain branch on MatchDG.
2. Claim-to-command linker, tested against our hand-written commands (9 Table 1 rows, 24 Table 11 cells).
3. Branch-patch writer with the one-setting self-check.
4. Second paper end to end, blind, before any UI.
5. `scripts/regression.py` must report 0 mismatches before any change ships.
6. Then the UI. The demo is precomputed, plus one live run.

### Interview questions (5 minutes each)
1. Last time you tried to run a paper's code, what happened and how long did it take?
2. When your numbers didn't match, how did you decide whether it was you, the code or the paper?
3. Which would you trust more: a list of paper-code differences, or a re-run that shows which difference moves the number?
4. What would you need to see to cite a "reproduced" verdict in your own report?
5. Would you run this before submitting your own paper?

Who to ask: final-year students doing ML projects, a faculty member who reviews papers, someone who has tried to rerun a paper for an MLRC-style project.

## How to split the work between Claude Cowork and Claude Code

| Phase | Tool | What |
|---|---|---|
| Research and positioning | Cowork | Judging criteria, demo papers from the organisers' set |
| Agentic steps (spec §9, steps 1 to 3) | Claude Code | One step at a time, each with its MatchDG test |
| Second paper, blind | Claude Code | Full pipeline before any UI |
| Architecture | Claude Code plan mode | Feed it the technical spec and the evidence repo |
| Submission writing and review | Cowork | Fit the material to the required format |

## Spike artefacts (`analysis/spike-matchdg/`)
- `report.md`: the full audit report (Part A: Table 11, both runs; Part B: Table 1), every table rendered from the grades.
- `metrics/`: `grades.json` (Table 1), `grades_lenet.json` (Table 11, first run), `grades_lenet_confirm.json` (Table 11, confirmation), `v1/` (the same under rules version 1), `epochs.json`, `run_counts.json`, and one parsed file per run directory with log line numbers.
- `golden/`: the regression targets, plus `last_check.json` from the latest regression run.
- `logs.tar.gz`: every raw log the line numbers point into, plus both `PREREGISTERED.txt` files for Table 11.
- `repairs.patch`, `hypotheses.patch`, `branches.txt`: every code change and which commit each run used.
- `extraction/`: prompts, schema, the four blind outputs and `score.json`.
- `scripts/`: everything that ran, parsed, graded and rendered (`render_all.sh` re-derives every output in order).
- `matchdg-audit.bundle`: the audit branches, the `audit-evidence` branch and the `round0-submission` tag.

## Known gaps
- Table 11's seed count is not stated in the paper; we assumed 3.
- The settings diff and branches were run on Table 1 only; Table 11 was run as specified.
- The extraction test is on the paper we audited by hand; the second paper is the real test.
- h1b is one implementation of "full objective" (cross-entropy plus λ times the matching penalty on matched validation pairs).
- The first Table 11 pre-registration hashed `grade_lenet.py` but not the module it imported; the confirmation's pre-registration hashes every rule file.
