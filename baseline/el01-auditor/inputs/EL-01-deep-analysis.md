# EL-01 Concept Note: a claim-level reproducibility auditor
ELEVATE 1.0 · Problem statement EL-01 (AI-Powered ML Paper Reproducibility Platform) · Round 0

**One line:** we check each claim in an ML paper against its own code, and when the two disagree we re-run the code to measure which difference actually moves the number.

We ran the core of it on a real paper before writing this. Section 2.1 says which steps were automatic and which were done by hand. Every number marked **[measured]** is rendered by a script from the run logs; the logs, commits, grades and scripts are published at https://claude.ai/artifact/2ah3Kw65GddPpPUt7mZLGa#evidence.

---

## 1. The problem

ML papers report numbers, repositories are supposed to produce them, and nothing checks the link. In Nature's 2016 survey of 1,576 researchers, more than 70% had tried and failed to reproduce another scientist's experiment, and more than half had failed to reproduce their own (Baker, *Nature* 533, 2016). The problem statement asks for "an evidence-backed assessment of individual experiments" and says the system "should go beyond checking whether code exists or generating a paper summary".

Agents have become good at running research code: CORE-Bench, which asks them to reproduce results from authors' own code, was reported solved in late 2025, although the NLPCC 2026 shared task on reproducing 150 papers (arXiv 2609.11117) still finds execution the main bottleneck. Judging is harder. On REPRO-Bench, which asks agents to *assess* whether a paper reproduces, the best agent scores 36.6% against 25% for random guessing. On SciCoQA, the best LLMs find 46.7% of real paper-code discrepancies. So our system is built around judgement: which claims hold, which paper-code differences exist, and which of those differences matter.

## 2. A real audit: MatchDG (ICML 2021)

**Paper:** Mahajan, Tople, Sharma, *Domain Generalization using Causal Matching*, ICML 2021. **Code:** `microsoft/robustdg` at commit `3eee173` (20 March 2022).

**Why this paper:** two of its tables run on a CPU, and two of its paper-code discrepancies are ground-truth cases in SciCoQA ([row 67](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L67) and [row 68](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L68)), both found by an ML Reproducibility Challenge report. That lets us check our own output: we found one of the two (§2.2, §2.3).

**What we audited.** The paper's method is **MatchDG**. Its CPU-feasible evaluation is **Suppl. Table 11** (Rotated MNIST with a LeNet); its other tables use ResNet or DenseNet models. We also audited **Table 1**, the paper's *motivating experiment* on a synthetic "slab" dataset. MatchDG is not in Table 1. Its headline row, **PerfMatch, is an oracle**: it matches inputs on the true stable feature, which the paper says is not available in practice. The claim we audit there is the motivating one, that matching on the stable feature lifts out-of-domain accuracy far above ERM.

**What we found.** Nothing in MatchDG's own table is refuted. Re-run on fresh data with the rule fixed beforehand, 13 of its 28 Table 11 numbers are Reproduced within a point, the other 15 are Inconclusive, and its gain over ERM reproduces. The motivating oracle result in Table 1 also reproduces with the released code, but its size depends on how one sentence of the appendix is read: under one reading of "early stopping based on the validation loss" the oracle's advantage disappears (−25.8 points), under the other it stays. SciCoQA's second row for this repo (F7, a flipped copy of the augmented data) turned out to reach MatchDG's checkpoint choice; tested as a branch, it moves MatchDG's Table 11 average by −0.04 points (95% CI −0.41 to 0.34).

### 2.1 What was automatic and what was by hand

| Step | In this audit |
|---|---|
| Run the shipped code, pin dependencies to the commit date, run seeds | script |
| Three repairs to make it run | by hand, each a logged commit; inertness check scripted |
| Claim cards (Table 1 numbers) | by hand; then re-done **blind by LLM extractors** as a test: 9/9 target cells right in both runs, and they caught a typo in our hand table |
| Paper vs code settings diff | by hand (3 findings); then re-done **blind** by separate paper and code extractors plus a fixed diff script: all 3 recovered in 4 of 4 run pairings, plus 3 we had missed |
| Link each claim to a runnable command | by hand, from the repo's reproduce scripts |
| Hypothesis branches | code edits by hand, one commit each; runs scripted |
| Parsing, statistics, verdicts, every number in this note | script; no LLM involved |

**Working today: the runner and the grader. Repairs, branch patches and claim-to-command links were done by hand.** Section 8 says how those three become agents, and how each will be tested.

### 2.2 MatchDG itself: Table 11 [measured]

The paper's Tables 8 and 9 match the repo's training settings for this experiment; one data difference reaches it (F7, below). We ran ERM, RandMatch, MatchDG and PerfMatch on all six rotation domains, 3 runs each (the code's default; the paper does not say how many it used), with the three repairs only.

**Two runs.** The first run's rule, hashed before any run finished, used the paper's sd as the margin. Those sds are as small as 0.1 points, so with 3 runs all 28 numbers came out Inconclusive. We then set the margin to max(paper's sd, 1 point), but only after seeing that run. So we re-ran the whole table on fresh MNIST subsets and new seeds, with the floor declared and every rule file hashed first, and graded that run alone. The headline is the confirmation's.

| Run | Margin | Margin declared | Reproduced | Inconclusive | Not reproduced | MatchDG beats ERM |
|---|---|---|---|---|---|---|
| First, MNIST subsets 0–2 | paper's sd | before the run | 0 | 28 | 0 | Reproduced |
| First, MNIST subsets 0–2 | max(paper's sd, 1 point) | after the run | 14 | 14 | 0 | Reproduced |
| **Confirmation, fresh subsets 3–5** | max(paper's sd, 1 point) | **before the run** | 13 | 15 | 0 | Reproduced |

Counts are over 28 claims: 24 cells and 4 six-domain averages.

Confirmation run, six-domain averages:

| Six-domain average | Paper | Ours, mean over 3 runs | Δ (95% CI) | Tightest margin the data supports | Margin used | Verdict |
|---|---|---|---|---|---|---|
| ERM | 94.1 | 93.45 ± 0.37 | −0.65 (−1.74 to 0.44) | ±1.49 | ±1.00 (practical floor) | Inconclusive |
| RandMatch | 97.1 | 97.04 ± 0.34 | −0.06 (−0.91 to 0.79) | ±0.71 | ±1.00 (practical floor) | Reproduced |
| **MatchDG** (the paper's method) | 97.4 | 97.07 ± 0.24 | −0.33 (−0.97 to 0.31) | ±0.82 | ±1.00 (practical floor) | Reproduced |
| PerfMatch (oracle) | 97.8 | 97.82 ± 0.19 | +0.02 (−0.95 to 0.99) | ±0.74 | ±1.00 (practical floor) | Reproduced |

Relative claims on the average, both runs:

| Claim (six-domain average) | Paper gap | First run: our gap (95% CI) | Verdict | Confirmation: our gap (95% CI) | Verdict |
|---|---|---|---|---|---|
| MatchDG beats ERM | +3.3 | +3.63 (2.08 to 5.17) | Reproduced | +3.62 (1.84 to 5.41) | Reproduced |
| MatchDG beats RandMatch | +0.3 | +0.28 (−0.25 to 0.81) | Inconclusive | +0.03 (−0.34 to 0.40) | Inconclusive |
| PerfMatch (oracle) beats MatchDG | +0.4 | +0.53 (−0.63 to 1.70) | Inconclusive | +0.74 (−0.11 to 1.60) | Inconclusive |

**Nothing in MatchDG's own table is refuted.** In the confirmation 13 of 28 numbers are Reproduced and 15 are Inconclusive, including every cell at the two hardest rotations (0° and 75°); every cell is within 2.6 points of the paper. MatchDG's six-domain average is 97.1 against the paper's 97.4 (Reproduced), and its gain over ERM reproduces in both runs (+3.62 on fresh data against +3.3). The finer ordering does not resolve: MatchDG's edge over RandMatch is +0.28 in the first run and +0.03 in the confirmation (paper +0.3), Inconclusive both times. The text's claim that MatchDG beats prior work at every domain but 0° is not confirmed: the first run was clearly above the best prior row at 15°, 30° and 60°, the confirmation at none. So the audit separates the two tables: the method's own numbers hold where 3 runs can tell, and the open questions concern the motivating experiment.

**F7: SciCoQA's second row, tested [measured].** SciCoQA lists a second discrepancy for robustdg ([row 67](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L67)): rotations in the Rotated MNIST generator go in inconsistent directions. Our hand audit and blind extraction both missed it. The mechanism: the generator saves a plain and an augmented copy of every rotated digit, and the augmented copy is randomly cropped and then horizontally flipped *after* rotation (`data_gen_mnist.py:34-35, 85`), so half of it is mirrored digits at −θ. The paper never says Rotated MNIST is augmented (kind: paper omission). Every method trains and tests on the plain copy (`--mnist_aug 0`), so the obvious reading is that F7 never touches Table 11. It does, once: MatchDG's first phase validates on plain-augmented pairs and keeps the epoch with the best match score (`reproduce_rmnist_lenet.py:25` → `train.py:217-218` → `mnist_loader_match_eval.py:38`; `match_dg.py:263-266`), and the second phase matches with that checkpoint. Branch h7 removes only the flips (10,752 of 21,600 augmented images change, nothing else) and re-runs MatchDG on the confirmation's subsets and seeds, with the rule hashed first:

| Test domain | MatchDG, shipped data | MatchDG, no flips | Effect, paired by run (95% CI) | Holm p | Same contrastive-phase checkpoint |
|---|---|---|---|---|---|
| 0° | 93.2 | 93.4 | +0.23 (−0.77 to 1.24) | 1.00 | 2 of 3 runs |
| 15° | 99.5 | 99.5 | +0.03 (−1.09 to 1.15) | 1.00 | 1 of 3 runs |
| 30° | 99.4 | 99.4 | −0.03 (−0.91 to 0.84) | 1.00 | 1 of 3 runs |
| 45° | 99.0 | 99.0 | 0.00 (all 3 runs identical) | 1.00 | 2 of 3 runs |
| 60° | 99.5 | 99.0 | −0.47 (−2.06 to 1.13) | 1.00 | 1 of 3 runs |
| 75° | 91.8 | 91.8 | 0.00 (all 3 runs identical) | 1.00 | 3 of 3 runs |
| **Six-domain average** (primary test) | 97.07 | 97.03 | −0.04 (−0.41 to 0.34) | | |

The chosen checkpoint changed in 8 of 18 runs; where it did not, the final accuracy was identical (10 of 10). The six-domain average moved by −0.04 points (95% CI −0.41 to 0.34) and 0 of 6 cells survive Holm. So F7 is real and on the path, but no Table 11 verdict changes; it is a note on MatchDG's claims, not a "setup differs" reason. Details in the report, Part A3.

### 2.3 The motivating oracle result: Table 1 [measured]

**As shipped, the code does not run.** It reads data from a hard-coded path on the authors' machine, then needs a GPU, then calls a privacy-library hook the pinned version lacks, then fails because the target domain the paper evaluates on is never generated. We made three logged repairs (data path, CPU fallback, and a guard on the privacy hook call; a traced run with the guard makes zero calls into that library). We did not silently add the missing target domain (p = 1.0): it changes what is measured, so it is hypothesis branch h0, the baseline for everything below.

**Verdicts.** All nine rows of Table 1, target-domain accuracy (%), mean ± sd over 10 seeds. *Reproduced* requires the whole 90% CI of (ours − paper) inside ± max(the paper's sd, 1 point), an equivalence test (every Table 1 sd is above 1 point); "tightest margin" is the smallest margin our data could confirm. "Setup differs" is set by code (§4): every Table 1 claim needed the target domain the code never generates (F1), and F2 or F3 add to it where their branches move the number.

| Claim (Table 1, target accuracy) | Paper | Ours | Δ (95% CI) | Tightest margin the data supports | Verdict | Setup differs |
|---|---|---|---|---|---|---|
| ERM | 57.6 ± 6.58 | 53.8 ± 4.09 | −3.8 (−9.3 to 1.7) | ±8.3 | Inconclusive | yes: F1, F2 |
| RandMatch | 59.5 ± 3.50 | 54.7 ± 3.96 | −4.8 (−8.5 to −1.1) | ±7.9 | Not reproduced | yes: F1, F2 |
| PerfMatch (oracle) | 77.8 ± 6.01 | 80.4 ± 7.49 | +2.6 (−4.1 to 9.4) | ±8.2 | Inconclusive | yes: F1, F2, F3 |
| MMD | 62.9 ± 5.01 | 60.7 ± 5.47 | −2.2 (−7.4 to 3.0) | ±6.5 | Inconclusive | yes: F1 |
| CORAL | 63.1 ± 5.86 | 59.5 ± 4.65 | −3.6 (−8.9 to 1.6) | ±8.0 | Inconclusive | yes: F1 |
| DANN | 53.0 ± 1.41 | 50.2 ± 1.39 | −2.8 (−4.2 to −1.4) | ±4.0 | Not reproduced | yes: F1 |
| C-MMD | 58.9 ± 3.43 | 58.8 ± 5.51 | −0.1 (−4.7 to 4.5) | ±3.9 | Inconclusive | yes: F1 |
| C-CORAL | 64.7 ± 4.69 | 59.6 ± 4.28 | −5.1 (−9.6 to −0.7) | ±8.8 | Not reproduced | yes: F1 |
| CDANN | 55.9 ± 2.47 | 50.1 ± 1.58 | −5.8 (−7.9 to −3.7) | ±7.5 | Not reproduced | yes: F1 |

Relative claims, with the paper's own uncertainty included:

| Claim | Paper gap | Our gap, paired (95% CI) | Our gap − paper gap (95% CI, both uncertainties) | Verdict | Setup differs |
|---|---|---|---|---|---|
| PerfMatch (oracle) beats ERM | +20.2 | +26.6 (21.0 to 32.3) | +6.4 (−1.5 to 14.4) | Reproduced | yes: F1, F2, F3 |
| PerfMatch (oracle) beats RandMatch | +18.3 | +25.8 (19.9 to 31.7) | +7.5 (0.2 to 14.7) | Partially reproduced (gap larger than reported) | yes: F1, F2, F3 |

**Settings diff.**

| # | Setting | Paper | Code | Kind |
|---|---|---|---|---|
| F1 | Target domain | p = 1.0 (Sec 3.2, App. A.1) | never generated (`data_gen_syn.py:42`) | code omission (also in SciCoQA) |
| F2 | Model selection | "early stopping based on the validation loss" | epoch with the best validation *accuracy* (`train.py:306`) | difference |
| F3 | Optimizer | "SGD" | SGD with momentum 0.9 and Nesterov (`algo.py:185`) | paper omission |
| F4 | Matching weight | λ (Table 7), no schedule | ramps from about 0 to λ over training (`erm_match.py:109`) | paper omission |
| F5 | DANN/CDANN learning rate | 0.1 for all methods | hard-coded 0.01 (`dann.py:38`) | difference |
| F6 | Hyperparameter tuning | on 250 extra source-domain points | ranks settings by a log line that holds *target* accuracy (`slab-tune.py:82-100`) | difference |

F7 concerns Table 11 (§2.2). SciCoQA lists F1 and F7 for this repo; we found F1 and missed F7, so our recall against SciCoQA on this repo is 1 of 2. F2 to F6 are not in SciCoQA.

**Which differences matter.** Each finding became a git branch changing one thing; an ambiguous one got a branch per reading. Effects are branch minus baseline, paired by seed, with a 95% CI; ✓ marks effects that survive a Holm correction across all 20 exploratory effects.

| Branch | ERM | RandMatch | PerfMatch (oracle) | PerfMatch: epoch picked (median), source val. acc. |
|---|---|---|---|---|
| h1: select by validation cross-entropy (one reading of the paper) | +4.8 (2.9 to 6.6) ✓ | −3.8 (−6.8 to −0.7) | −25.8 (−34.4 to −17.2) ✓ | 1, 98.2% |
| h1b: select by full validation objective (the other reading) | same as h1 (ERM has no matching term) | +5.5 (2.8 to 8.2) ✓ | +4.7 (−2.5 to 11.9) | 88, 99.0% |
| h2: plain SGD, as the paper states | −3.8 (−6.4 to −1.1) | −4.1 (−6.9 to −1.3) | −28.7 (−34.7 to −22.8) ✓ | 27.5, 98.6% |
| h2 diagnostic: plain SGD for 1000 epochs | −0.5 (−1.8 to 0.7) | +5.0 (−0.8 to 10.7) | +0.3 (−5.2 to 5.8) | 531.5, 99.5% |
| h1 + h2 together | −2.5 (−5.9 to 0.9) | not run | −29.2 (−35.0 to −23.3) ✓ | 4, 98.3% |
| h3: evaluate on p = 0.9, the domain the code generates | +4.9 (3.1 to 6.7) ✓ | +4.8 (2.8 to 6.7) ✓ | +2.1 (0.6 to 3.6) | 73.5, 99.5% |
| h4: constant matching weight (code ramps it from 0) | not run | +3.2 (−1.3 to 7.6) | −2.4 (−10.5 to 5.7) | 55.5, 99.4% |
| h1 confirmation, fresh seeds 10–19 | +4.3 (2.9 to 5.7) | not run | −25.4 (−30.8 to −20.1) | 1 |

**What this means.** The motivating oracle result reproduces with the released code, and its size depends on one ambiguous sentence. The appendix says "early stopping based on the validation loss". Read as cross-entropy (h1), it stops PerfMatch at epoch 1, when the model already has 98.2% source accuracy but the matching weight (F4) has barely started to ramp up, and the oracle's advantage disappears (−25.8 (95% CI −34.4 to −17.2); on ten fresh seeds −25.4 (95% CI −30.8 to −20.1)). Read as the full training objective (h1b), it stops near epoch 88 and the advantage stays (+4.7 (95% CI −2.5 to 11.9)). Training is identical under all three rules; only the reported checkpoint changes. The paper does not say which loss it meant, so the report marks F2 as load-bearing and ambiguous and asks the authors, rather than calling the paper wrong.

**h2 is not a failure to train.** With the paper's plain SGD for its 100 epochs, every method reaches about 98.5% source accuracy using the spurious feature, but none learns the stable slab feature, so the oracle shows no advantage (−28.7 (95% CI −34.7 to −22.8)). Given 1000 epochs, plain SGD matches the code's result (+0.3 (95% CI −5.2 to 5.8)). The undocumented momentum acts as a tenfold training budget; it does not change the finding.

**The missing domain, as a branch.** A "make it run" agent could have pointed the evaluation at p = 0.9, the nearest domain the code does generate. Done silently, every claim would look close to the paper and nobody would know the experiment had changed. Run as branch h3, it is informative instead: RandMatch's gap closes (59.4 against the paper's 59.5). Two other changes also bring RandMatch near 59.5 (λ = 0.1, and plain SGD for 1000 epochs), so we report an open question for the authors, not a cause. DANN and CDANN stay at chance at the paper's learning rate (F5), so their gap is reported as unexplained by the tested differences.

### 2.4 Against the human reproduction

The ML Reproducibility Challenge report on this paper (Jiles and Chakraborty, ReScience C 8(2) #18, 2022) also had to add p = 1.0 to the generator. Its Table 1, as printed in the submission version (we could not open the ReScience PDF from our environment), gives ERM 64.6 ± 4.50, RandMatch 66.9 ± 2.64 and PerfMatch 87.9 ± 4.26: higher than both the paper and us. Three runs of the same table disagree by more than the paper's sd, which is why our rule demands equivalence within a declared margin and otherwise says Inconclusive. SciCoQA took both of its robustdg rows (F1 and F7) from this report.

### 2.5 Cost and scaling [measured]

4 vCPUs, 16 GB RAM, no GPU, one thread per job. Compute grows with claims × seeds × (1 + branches): every claim needs its seeds, and every finding adds a branch that re-runs the methods it touches.

| Run set | Training runs | Single-thread compute | Wall-clock |
|---|---|---|---|
| Table 1 (slab): baseline, all branches, fresh-seed confirmation | 380 | 49 min | not separable (run sets overlapped) |
| Table 11, first run | 72 | 118 min | 32.5 min (24 jobs, 4 at a time) |
| Table 11, confirmation | 72 | 129 min | 35.2 min (24 jobs, 4 at a time) |
| F7 branch, MatchDG only | 18 | 87 min | 14.6 min (6 jobs, 6 at a time) |
| **Whole audit** | 542 | 383 min | |

A full 72-run Table 11 pass took 32.5 and 35.2 minutes of wall-clock with 4 jobs at a time, and the 18-run F7 branch 14.6 minutes with 6 at a time; the whole audit is about 96 minutes at that rate [inferred]. What keeps it affordable:

- **Selection-rule branches need no retraining [measured].** h1 and h1b only change which checkpoint is reported, and their per-epoch traces are identical to the baseline's (24,000 lines). Logging every candidate selection metric once turns such a branch into a lookup; 80 of the 380 slab runs were branches of this kind.
- **Caching:** environments by commit date (done), datasets by checksum (planned; the F7 check found the generated training and test files byte-identical across branches).
- **Parallel branches:** each branch is a git worktree and each job one (method, test domain) pair, so jobs spread across cores and machines.
- **A budget from a smoke run:** one seed and a few epochs first; branches the cap cannot cover are listed in the report.
- **Tokens per paper are not measured yet**; the second-paper run measures them together with wall-clock time.
- **CPU papers only,** as the problem statement allows. GPU papers are out of scope.

These are a tiny MLP and a LeNet; heavier papers will cost more, which is why the budget is computed per paper.

## 3. How it works: four features

1. **Claim cards.** Every reported number becomes a typed claim (absolute, relative or trend), pinned to page, table cell and quoted text, with how it was aggregated, and tagged as the paper's method, a baseline or an oracle. Relative claims are tested by running both arms on the same seeds. *Status: blind extraction tested on MatchDG; the link from a claim to a runnable command was done by hand.*
2. **Paper vs code settings diff.** Separate extractors read the paper and the code into one schema; a fixed script labels every mismatch a difference, a code omission or a paper omission. No severity labels: in our audit the finding a reader would rank highest moved the oracle result by +2.1 points while two "medium" ones moved it by more than 25, so every finding gets a branch. *Status: blind extraction tested on MatchDG.*
3. **Controlled runs with honest statistics.** Execution ladder (shipped results, then Dockerfile, then dependencies pinned to the repo's commit date), a written repair policy with an inertness check, seeds = max(5, the paper's count), a check for hard-coded seeds, and verdicts computed by code from parsed logs. *Status: runner and grader working; repairs by hand.*
4. **Diff-guided ablation.** One branch per finding, one per reading of an ambiguous finding, run in parallel git worktrees. Effects are paired by seed with 95% CIs and Holm-corrected; the largest is confirmed on fresh seeds; the top two are combined to check for interaction. *Status: runner and grader working; branch patches by hand.*

The technical spec (`EL-01-features-and-diagrams.md`) gives schemas, rules and diagrams.

## 4. Verdicts

| Verdict | Absolute claim | Relative claim |
|---|---|---|
| Reproduced | 90% CI of (ours − paper) inside ± margin, where margin = max(the paper's sd, a practical floor) | direction holds; gap consistent with the paper's, counting both uncertainties |
| Partially reproduced | n/a | direction holds, but the gap is significantly larger or smaller than the paper's; a note says which ("gap larger than reported") |
| Not reproduced | 95% CI excludes 0 and not equivalent | direction not shown and gap significantly smaller |
| Inconclusive | anything else within the seed budget | anything else |
| Not runnable | no number after the execution ladder and allowed repairs | same |
| Not assessable | the paper does not pin the experiment | same |

**"Setup differs" is a flag next to the verdict, set by code.** A claim gets it when a code omission had to be filled to run it, or when a finding's branch has an effect on a method the claim names that survives the Holm correction. Findings that apply but were not tested, or were tested with no such effect, are listed as notes.

**The practical floor** is the smallest difference a reader would care about, a user setting declared before the runs (default 1 accuracy point). Without it, a paper whose sds are 0.1 points (one test image in 1,000) can only ever grade Inconclusive, however close the numbers are. Every report still prints the tightest margin the data supports.

A number in the report that cannot be traced to a log line and commit is a bug in our pipeline and blocks the report. It is never shown as a verdict about the paper.

## 5. Feasibility and risks

| Risk | Why it is real | What we do |
|---|---|---|
| The settings diff misses things | SciCoQA: best LLMs find 46.7% of real discrepancies, worst on paper omissions | Omission ablations on code-only components; "unexplained" is an allowed answer; we measure our own recall (on robustdg we found 1 of SciCoQA's 2 rows); schema version 2 adds data-pipeline keys |
| Repairs change results | Old repos rarely run cleanly | Environment and compatibility fixes only, each a logged commit that must pass an inertness check; anything else becomes a hypothesis branch |
| Noise mistaken for an effect | Seed sd is 4–7 points on the slab data | Paired CIs, Holm correction, confirmation on fresh seeds |
| Ambiguous paper text | "validation loss" here | One branch per reading; flagged, never called wrong |
| Effects don't add up | Settings interact | Interaction branch; no "share of the gap" numbers |
| Runtime on bigger papers | Our timings come from a tiny MLP and a LeNet | Smoke run first; seed and branch budget from its timing; selection-rule branches without retraining; demo uses precomputed runs plus one live run (§2.5) |
| Hard-coded seeds, datasets behind the network, figure-only claims | Common in real repos | Static scan plus variance check; online fetch with checksums then offline runs; figure-only claims marked and skipped |

## 6. Prior art and what is new

| | Runs the code | Verdict per claim | Finds paper-code differences | Measures which difference moves the number |
|---|---|---|---|---|
| alphaXiv autoarxiv (2026)\* | yes; the template allows toy-scale runs when full scale is out of budget | aligned / partially aligned / inconclusive; the template tells the agent not to call a claim "not reproduced" | not as a systematic step | tests changes the agent chooses; no fixed statistics |
| NLPCC 2026 Shared Task 11 (arXiv 2609.11117) | yes, 150 papers | process rubrics on agent traces | no | no |
| SciCoQA (arXiv 2601.12910) | no | no | yes, static | no |
| REPRO-Bench (arXiv 2507.18901) | assesses reproduction packages | yes; best 36.6%, random 25% | partly | no |
| CORE-Bench (2409.11363), SUPER (2409.07440) | yes (benchmarks) | answers task questions | no | no |
| RECLAIM (2609.28850), PaperBench (2504.01848), Paper2Agent (2509.06917) | yes | per paper, rubric or tool output | no | no |
| **This project** | yes, at the paper's own configuration | yes, typed, with an equivalence rule | by hand in the audit; blind extraction tested | **yes, every finding, paired CIs, Holm** |

\* autoarxiv appears to use alphaXiv's reproduce-paper template (`src/local/skills.rs`, lines 30–31, in openresearch-cli at commit `f4cec9f`); the row describes that template.

Under that template the agent may run a scaled-down reproduction, with a smaller model or fewer steps, and such a run cannot grade a published number; we ran the paper's own configuration and graded its actual numbers. Our method is a one-factor-at-a-time ablation whose factors come from the settings diff, the same idea as delta debugging (Zeller) and `git bisect` applied to experiment settings. The idea is simple on purpose. What is new is wiring it to the diff and the verdicts, so every difference the system flags is tested and every gap it measures is either explained with an effect size or marked unexplained.

## 7. How we will know it works

| What | Ground truth | Metric | So far [measured] |
|---|---|---|---|
| Claim extraction | hand-labelled tables, 10 papers | exact match on value and table coordinates | MatchDG Table 1: 9/9 cells in 2 of 2 runs |
| Settings diff | SciCoQA's 92 real discrepancies from 72 papers | recall and precision per kind | MatchDG: all 3 hand findings in 4 of 4 pairings, plus 3 new; 1 of SciCoQA's 2 robustdg rows found |
| Verdicts | ML Reproducibility Challenge reports on CPU-runnable papers | agreement with the human reproducer, per claim | MatchDG compared (§2.4) |
| Determinism | each paper run twice | identical verdicts | grading is pure code; extraction runs agreed on all 27 cells |
| Regression | MatchDG golden outputs: the hand-built tables and every verdict | every pipeline change reproduces them exactly | 73 verdicts and 53 other graded numbers re-derived from the raw logs, plus 6 extraction checks: 0 mismatches (2026-10-03) |
| Generality | a second paper, run blind end to end | findings against its known discrepancy | first milestone (§8) |

## 8. Hackathon scope and team

**Demo:** upload paper and repo, see claim cards, the settings diff, the verdict tables and the ablation table for MatchDG (precomputed), then one live run of a single method (under a minute) and one curated paper from the organisers' set.

**Build order.** The extraction steps have had a blind test; the three agentic steps that make this an automated auditor have not, so they come first, each with its own test:

1. **Repair agent:** classify each patch (environment, compatibility, hypothesis), then run the inertness check. Test: on MatchDG it reproduces our three repair commits and sends the missing target domain to a branch.
2. **Claim-to-command linker:** turn "Table 1, PerfMatch" into a runnable command. Test: it produces the commands we wrote by hand for all 9 Table 1 rows and all 24 Table 11 cells.
3. **Branch-patch writer:** one commit per finding, with a self-check: re-run the code extractor on the branch and require that exactly one setting changed, the one the finding names.
4. **Code extractor on a data-pipeline question.** With schema version 2 (it adds resizing, normalisation, augmentation, domain construction and the data the selection metric reads), the code extractor must trace SciCoQA row 67 on robustdg to the path we traced by hand for F7.
5. **First milestone: a second paper, end to end, blind,** before any UI, measuring wall-clock time and tokens per paper. Two CPU-runnable papers with a SciCoQA row or an MLRC report; the known discrepancy is read only after the run. **Second-paper candidates** (picked from SciCoQA rows; the team stays blind to the discrepancy text until after the run):

- **PGExplainer: Parameterized Explainer for Graph Neural Network** (NeurIPS 2020; flyingdoog/PGExplainer @ ec57ea2). Six SciCoQA rows from an MLRC 2020 report, all on the code path behind the audited table; GNN explanation, so a different kind of paper from MatchDG. Audit target: Table 2, PGExplainer explanation AUC, 6 cells, mean ± sd over 10 stated runs. Runtime: about 1 to 2.5 h for 10 seeds (estimated from the notebooks' saved timings, not run). Main risk: setup: TensorFlow 2.0 on Python 3.7, notebooks only, no seed loop, some wrong paths; its README links the reproduction report, which the blind run must not see.
- **Label-Free Explainability for Unsupervised Models** (ICML 2022; JonathanCrabbe/Label-Free-XAI @ 3f6fd5e). Not a graph paper: small PyTorch autoencoders on MNIST, so the pair covers two frameworks (TensorFlow, PyTorch) and two kinds of model. One SciCoQA row, from an MLRC 2022 report. Audit target: Tables 1–2, pretext-task sensitivity on MNIST: 12 Pearson-correlation cells, mean ± sd over 5 runs. Runtime: about 1.5 to 4 h for 5 runs (inferred from 20 small trainings with early stopping, not run). Main risk: closest to MatchDG (PyTorch, MNIST); its known row is not on the audited table's path, so only the settings diff can score it; may exceed a 2 h budget.
- Backups: BUDDY / ELPH (ICLR 2023), graph link prediction; GNNInterpreter (ICLR 2023), graph explanation.
6. **MatchDG is the regression test:** its hand-built tables and every verdict are golden outputs, and every pipeline change must reproduce them (`scripts/regression.py`).
7. Report UI, then the organisers' papers. The demo is precomputed, plus one live run.

The grader rules (verdict list, "setup differs" rule, practical floor) were fixed before any UI, in `scripts/verdicts.py`.

**Team:**

| Name | Role | Owns |
|---|---|---|
| _(name)_ | Extraction lead | paper and code extractors, claim cards, settings diff |
| _(name)_ | Runner and grader lead | sandbox, repair policy, branches, statistics |
| _(name)_ | Product lead | report UI, demo, user interviews |
| _(name)_ | Evaluation lead | SciCoQA and MLRC evaluation, organisers' papers |

## 9. Who it is for

Students and engineers deciding whether to build on a paper; reviewers and reproducibility-challenge participants checking claims; authors checking their own release before submission. We have not interviewed users yet. Before Round 1 we will run five-minute interviews with 3 to 5 final-year ML students and a faculty reviewer, asking how they currently decide whether a mismatch is their fault, the code's or the paper's, and what they would need to see to trust a verdict.

## References
Baker, M. "1,500 scientists lift the lid on reproducibility." *Nature* 533, 452–454 (2016) · Mahajan et al., ICML 2021 (PMLR v139) and supplement · Jiles and Chakraborty, ReScience C 8(2) #18 (2022) · SciCoQA, arXiv 2601.12910 · REPRO-Bench, arXiv 2507.18901 · NLPCC 2026 Shared Task 11, arXiv 2609.11117 · CORE-Bench, arXiv 2409.11363, and HAL's report that it is solved · RECLAIM, arXiv 2609.28850 · PaperBench, arXiv 2504.01848 · SUPER, arXiv 2409.07440 · Paper2Agent, arXiv 2509.06917 · alphaXiv openresearch-cli, reproduce-paper template, `src/local/skills.rs` lines 30–31 (commit f4cec9f) · "What Papers Don't Tell You", arXiv 2603.01801 · Zeller, "Yesterday, my program worked. Today, it does not. Why?" (ESEC/FSE 1999).
