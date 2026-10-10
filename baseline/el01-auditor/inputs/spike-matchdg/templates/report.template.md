# Reproducibility audit: MatchDG (ICML 2021)

**Paper:** Mahajan, Tople, Sharma, *Domain Generalization using Causal Matching*, ICML 2021 (PMLR v139): Sec 3.2, Table 1, App. A.1, Tables 7 to 9 and Suppl. Table 11.
**Code:** github.com/microsoft/robustdg at `3eee173` (2022-03-20).
**Environment:** Python 3.9, torch 1.11.0, every package pinned to 2022-03-21 (`env/requirements-pinned.txt`); 4 vCPUs, 16 GB RAM, no GPU.
**Run date:** 2026-10-03. {{TOTAL_RUNS}} training runs, {{TOTAL_MIN}} minutes of single-thread compute.

Every number below is rendered by `scripts/report_tables.py` from `metrics/grades.json`, `metrics/grades_lenet.json`, `metrics/grades_lenet_confirm.json` and `metrics/grades_f7.json`, which scripts compute from the raw logs in `logs/` (each value carries its log file and line number). Accuracy is target-domain accuracy (%), mean ± population sd over seeds, as the paper reports it.

## What was audited, exactly

The paper's method is **MatchDG**. Its CPU-feasible evaluation is **Suppl. Table 11**: Rotated MNIST with a LeNet, 1,000 images per domain, six rotation domains, each held out in turn. The other tables that include MatchDG use ResNet-18, ResNet-50 or DenseNet-121 and are out of a CPU budget. **Part A** audits Table 11 with the repo's own commands (`reproduce_scripts/reproduce_rmnist_lenet.py`).

**Part B** audits **Table 1**, the paper's *motivating experiment* on a synthetic "slab" dataset. MatchDG is not in it. Its headline row is **PerfMatch, an oracle**: it matches inputs across domains on the true stable feature, which the paper says is not available in practice. The claim audited there is the motivating one: matching on the stable feature lifts out-of-domain accuracy far above ERM ("out-of-domain accuracy is now 78%"). Part B is where the settings diff and the ablation branches were run.

## What was automatic and what was by hand

| Step | How it was done |
|---|---|
| Run the shipped code, capture the failure | script |
| Pin dependencies to the commit date | script (`uv`, `UV_EXCLUDE_NEWER`) |
| Repairs to make it run (3) | by hand, each a logged commit |
| Claim cards (Table 1 numbers) | by hand; then re-done **blind by an LLM extractor**: 9/9 target cells right in both runs, and it caught a typo in our hand table (C-CORAL sd) |
| Paper vs code settings diff | by hand (3 findings); then re-done **blind**: separate paper and code extractors plus a fixed diff script recover all 3 in all 4 run pairings and add 3 we had missed (see `extraction/`); neither found F7 (Part A3) |
| Link each claim to a runnable command | by hand, from `reproduce_scripts/` |
| Hypothesis branches | code edits by hand, one commit each; runs scripted |
| Parsing, statistics, verdicts, "setup differs" flags | script (`parse_runs.py`, `parse_epochs.py`, `verdicts.py`, `grade.py`, `grade_lenet.py`); no LLM involved |
| Table 11 numbers and settings (Part A) | by hand from the supplement; each Table 11 grading rule was written and hashed before its runs (`logs/matchdg_lenet/PREREGISTERED.txt`, `logs/matchdg_lenet_confirm/PREREGISTERED.txt`, `logs/h7_no_flip/PREREGISTERED.txt`) |
| Regression against golden outputs | script (`regression.py`): {{REGRESSION}} |

Working today: the runner and the grader. Repairs, branch patches and claim-to-command links were done by hand.

**Rules version 2.** After the final review, the verdict rules moved into one module (`scripts/verdicts.py`): one verdict list (a relative claim whose direction holds but whose size differs is *Partially reproduced*, with a size note), a "setup differs" flag computed by rule, and a practical floor on the equivalence margin. Version 1 and its outputs are kept (`scripts/v1/`, `metrics/v1/`). For Table 1 the change is in labels only: every Table 1 sd is above the floor, so no verdict moves.

## Part A. MatchDG itself: Suppl. Table 11 (Rotated MNIST, LeNet)

**Setup check.** The paper's Tables 8 and 9 give, for this experiment: learning rate 0.01, batch 16, weight decay 5e-4, 100 epochs, match penalty 1.0; MatchDG's contrastive phase 50 epochs, batch 512, τ 0.05. The repo's commands and defaults match all of them. Two slab findings carry over unchanged: SGD with undocumented momentum and Nesterov (F3), and a matching weight that ramps up from about 0 (F4). The paper does not say how many runs Table 11 averages; we used the code's default of 3 and assumed 3 for the paper. Runs used the three repairs only, no hypothesis changes (`audit/repair-env`, 45e7771). One data difference does reach this table, through MatchDG's checkpoint choice: F7 (SciCoQA row 67), tested in A3.

**Two runs, two rules.** Table 11 was run twice, with the repo's own commands both times.

- **First run** (MNIST subsets 0–2, training seeds 0–20). Its rule was written and hashed before any run finished (`logs/matchdg_lenet/PREREGISTERED.txt`): a cell is *Reproduced* only if the 90% CI of (ours − paper) lies inside ± the paper's sd for that cell. Those sds are as small as 0.1 points. After seeing the results we added a practical floor, margin = max(paper's sd, 1 point) (rules version 2), so the first run's counts under the floor are post hoc. That pre-registration also hashed `grade_lenet.py` but not the module it imported; see Limits.
- **Confirmation** (fresh MNIST subsets 3–5, training seeds 30, 40, 50; branch `audit/lenet-confirm` adds only the two seed options). The floor was declared and every rule file hashed before any confirmation run started (`logs/matchdg_lenet_confirm/PREREGISTERED.txt`). It is graded alone, not pooled with the first run. **The headline numbers for Table 11 are this run's.**

In both runs a cell is *Not reproduced* if the 95% CI of (ours − paper) excludes 0 and equivalence fails, and *Inconclusive* otherwise. The six-domain average is graded per run, with the paper's sd for it derived from its per-domain sds.

{{T11_SUMMARY}}

### A1. Confirmation run (graded with the rule declared beforehand)

Ours / paper, target accuracy (%), 3 runs; R = Reproduced, I = Inconclusive, N = Not reproduced, margin = max(paper's sd, 1 point):

{{T11_CELLS}}

{{T11_COUNTS}}

{{T11_NOTREP}}

Six-domain average:

{{T11_AVG}}

Relative claims on the average, both runs:

{{T11_REL}}

**Setup differs.** No Table 11 claim carries the flag: no code omission had to be filled for this table, and the one branch run on it (F7, A3) had no detectable effect. The notes record what was tested and what applies but was not tested here:

{{T11_SETUP}}

F4 (the ramped matching weight) had no detectable effect on Table 1, so it is a note here, not a reason.

The text's claim about prior work ("RandMatch and MatchDG outperform prior work on all the domains except the test domain 0"), against the prior-work numbers printed in Table 11 (copied from other papers; we did not re-run them), confirmation run:

{{T11_PRIOR}}

### A2. First run, under both margins

Each cell shows the verdict with the paper's sd as the margin (the rule hashed before the run), then with the 1-point floor (added after the run):

{{T11_CELLS_FIRST}}

{{T11_AVG_FIRST}}

**In plain words.** Nothing in MatchDG's own table is refuted. On fresh data, with the rule and the 1-point floor fixed beforehand, {{N11:confirm:floor:Reproduced}} of 28 numbers are confirmed within max(paper's sd, 1 point) and {{N11:confirm:floor:Inconclusive}} are Inconclusive, including every cell at the two hardest rotations (0° and 75°). Every cell is within {{CMAX}} points of the paper. MatchDG's six-domain average is Reproduced ({{CA:matchdg:ours}} against {{CA:matchdg:paper}}; tightest margin ±{{CA:matchdg:tight}}), and its gain over ERM reproduces in both runs ({{CR:matchdg_vs_erm:ours}} on fresh data against the paper's {{CR:matchdg_vs_erm:paper}}). The finer ordering does not resolve: MatchDG's edge over RandMatch is {{LR:matchdg_vs_rand:ours}} in the first run and {{CR:matchdg_vs_rand:ours}} in the confirmation (paper {{CR:matchdg_vs_rand:paper}}), and the oracle's edge over MatchDG is Inconclusive in both. Against the prior-work rows, the first run was clearly above the best prior number at {{LPRIOR1:matchdg:above}}; the confirmation is not separable from it at any graded domain, so the text's claim to beat prior work is not confirmed. The first run's counts under the floor ({{N11:first:floor:Reproduced}} Reproduced, {{N11:first:floor:Inconclusive}} Inconclusive) are close to the confirmation's, but the floor was chosen after that run, so we do not quote them as the result. More runs per cell would sharpen all of this; F3 and F4 apply to this table and were not re-tested here. F7, the one data difference on this table's path, was tested and moved nothing detectable (A3).

### A3. F7: SciCoQA's second row for this repo (data augmentation; MatchDG only)

**The finding.** SciCoQA lists two discrepancies for robustdg, both from the MLRC report below: F1 (03255952, [row 68](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L68)) and this one (90c14330, [row 67](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L67)), which says the Rotated MNIST generator applies rotations in inconsistent directions. The mechanism at 3eee173: `data/data_gen_mnist.py` saves two copies of every rotated digit, a plain one (`*_org_data.pt`) and an augmented one (`*_data.pt`) made by `RandomResizedCrop` and then `RandomHorizontalFlip` *after* the rotation (lines 34–35 and 85). A flipped +θ digit is a mirrored digit at −θ. The paper never says Rotated MNIST is augmented (the supplement describes augmentation for PACS and Chest X-ray only), and it does not say how MatchDG's contrastive phase picks its checkpoint. Kind: paper omission. Neither our hand audit nor the blind extraction found it, so our recall against SciCoQA on this repo is 1 of 2; the 20-key extraction schema had no slot for augmentation (schema version 2 adds one, spec §3).

**Is it on the Table 11 path?** Every method trains and tests on the plain copy (`--mnist_aug 0`, `data/mnist_loader.py:37-40`). The augmented copy is read at one point on this table's path: MatchDG's contrastive phase validates with `--match_func_aug_case 1` (`reproduce_rmnist_lenet.py:25` → `train.py:217-218` → `utils/helper.py:173-175`, `MnistRotatedAugEval` → `data/mnist_loader_match_eval.py:38`, which loads `*_data.pt`; the default `--test_metric` is `match_score`, `train.py:155`). Every 5 epochs it scores how often each plain image's own augmented copy ranks in the top k, and saves the epoch with the best score (`algorithms/match_dg.py:263-266`). The second phase then builds its matches with that checkpoint. So F7 can move MatchDG's Table 11 numbers and no other method's; ERM, RandMatch and the oracle were not re-run. The obvious reading, that the flipped copy is never loaded because `--mnist_aug` defaults to 0, is right for training and testing but misses this checkpoint choice.

**Branch h7** (`audit/h7-no-flip`, 2a57284) replaces the flip with a step that draws the same random number and returns the image unchanged, so every crop stays the same. Data check (`scripts/check_f7_data.py`, `metrics/f7_data_check.json`): {{F7:data:plain}} plain and label files are byte-identical to the confirmation's; of {{F7:data:aug}} augmented images, {{F7:data:unchanged}} are unchanged, {{F7:data:flip}} differ only by a horizontal flip, and {{F7:data:other}} differ in any other way.

**Rule, hashed before any run** (`logs/h7_no_flip/PREREGISTERED.txt`, commit 26caa88): MatchDG re-run on the confirmation's subsets and seeds, paired with the confirmation by (test domain, run). Primary test: the six-domain average, 95% t CI over 3 runs. Cells: paired t-tests, Holm across six. F7 becomes a "setup differs" reason for a MatchDG claim only if its effect survives.

{{F7_TABLE}}

**Result.** Without flips the selection score at the chosen epoch rises from about {{F7:topk:base}}% to {{F7:topk:branch}}%, and the chosen checkpoint changes in {{F7:changed}} runs (the "Current Best Epoch" lines in `logs/matchdg_lenet_confirm/train_matchdg_*.log` and `logs/h7_no_flip/train_matchdg_*.log`; line numbers in `metrics/grades_f7.json`). Where the checkpoint did not change, the final accuracy was identical in {{F7:same_identical}} runs, so the pipeline is deterministic and any difference comes through the checkpoint. Where it changed, the accuracy moved in {{F7:changed_moved}} runs, by up to {{F7:maxrun}} points, in both directions. On the six-domain average the effect is {{F7:avg:effect}} points (95% CI {{F7:avg:ci}}), and {{F7:holm}} of 6 cells survive Holm. **F7 is on the path and was tested; it has no detectable effect on Table 11, so it is a note on MatchDG's claims, not a "setup differs" reason, and no Table 11 verdict changes.** The 18 runs took {{WALL:h7_no_flip}} minutes of wall-clock, 6 at a time.

## Part B. The motivating oracle result: Table 1 (slab)

### B1. Run as shipped: Not runnable
1. `FileNotFoundError: /home/t-dimaha/RobustDG/robustdg/data/datasets/slab/...` (hard-coded author path, `utils/slab_data.py:75`).
2. `RuntimeError: Found no NVIDIA driver` (device hard-coded to CUDA, `train.py:169`, `test.py:183`).
3. `AttributeError: module 'opacus' has no attribute 'autograd_grad_sample'` (unconditional DP hook call, `algorithms/algo.py:276`).
4. `FileNotFoundError: ...spur_corr_1.0_case_test_seed_0.pickle` (the paper's target domain is never generated, `data_gen_syn.py:42`).
Also: `more_itertools` and `opacus` are imported but missing from `requirements.txt`.

### B2. Repairs (allowed, logged) and hypotheses (not repairs)
| Commit | Class | Change | Inertness evidence |
|---|---|---|---|
| 9b4a263 | REPAIR(env) | data path made repo-relative | path only |
| 3f08ff7 | REPAIR(env) | CPU fallback when no GPU | device only |
| 45e7771 | REPAIR(compat) | DP hook call guarded by `dp_noise`, like its twin at line 243 | runtime trace: **0** opacus calls during a training run with the repair (`logs/inertness_opacus_trace.log`); the hooks the skipped call would enable are only installed when `dp_noise` is set |
| 7dde854 | HYPOTHESIS h0 | add target domain p = 1.0 as stated in the paper; baseline for everything below | same change the MLRC reproducers made (SciCoQA case 03255952) |

Every branch and its commits: `patches/branches.txt`; diffs: `patches/repairs.patch`, `patches/hypotheses.patch`.

### B3. Settings diff (paper vs code)
| # | Setting | Paper | Code | Kind | Found by |
|---|---|---|---|---|---|
| F1 | Target domain | p = 1.0 (Sec 3.2, App. A.1) | never generated (`data_gen_syn.py:42`) | code omission | hand diff, blind extractor, SciCoQA 03255952 |
| F2 | Model selection | "early stopping based on the validation loss" (App. A.1) | epoch with best validation *accuracy* (`train.py:306`, `erm_match.py:155`) | difference | hand diff, blind extractor |
| F3 | Optimizer | "SGD" (App. A.1) | SGD + momentum 0.9 + Nesterov (`algo.py:185`) | paper omission | hand diff, blind extractor |
| F4 | Matching weight over training | λ (Table 7), no schedule stated | ramps linearly from ≈0 to λ: λ·(epoch+1)/101 (`erm_match.py:109`) | paper omission | epoch trace (this round), blind extractor |
| F5 | DANN / CDANN learning rate | "All the methods were trained using SGD ... learning rate 0.1" | hard-coded 0.01, no momentum (`algorithms/dann.py:38`) | difference | blind extractor only |
| F6 | Hyperparameter tuning | "for hyperparameter tuning (model selection), we sample additional 250 data points per source domain" | `reproduce_scripts/slab-tune.py:82-100` ranks settings by the log line "Final Test Accuracy (Source Validation)", which holds **target-domain test accuracy** | difference | blind extractor (1 of 2 runs) |

Also noted, not branched: matching methods train on 128 matched pairs per step, i.e. 256 samples (the paper says batch 128); DANN alternates discriminator and generator per *epoch*, so its classifier is updated in 20 of 100 epochs (CDANN 33).

### B4. Verdicts

**Rule (fixed before grading).** Absolute claims: *Reproduced* only if the 90% Welch CI of (ours − paper) lies inside ±margin (an equivalence test, two one-sided tests at α = 0.05); *Not reproduced* if the 95% CI excludes 0 and equivalence fails; otherwise *Inconclusive*. The margin is the paper's own reported sd, declared before the runs; rules version 2 uses max(sd, 1 point), which is the same here because every Table 1 sd is above 1. Because the paper's sd widens both the margin and the CI, a noisier paper is not easier to pass; the last numeric column shows the tightest margin our data could support, so a reader can apply their own.

{{VERDICTS}}

Relative claims are graded on direction (our paired CI must exclude 0), then on size, with the paper's own uncertainty included (its gap has a standard error of about 3 points from its reported sds).

{{RELATIVE}}

**Setup differs, by rule** (`verdicts.setup_flag`): a claim gets the flag when a code omission had to be filled to run it, or when a finding's branch has a Holm-surviving effect on a method the claim names. Findings that apply but were not tested, or had no Holm-surviving effect, are notes.

{{T1_SETUP}}

**In plain words.** The oracle's advantage over ERM reproduces with the released code; over RandMatch the direction holds but our gap is larger than reported, so that claim is Partially reproduced. No single number in Table 1 can be confirmed to within the paper's own spread at 10 seeds, because the paper's sds are as large as the effects. Four numbers are outside it: RandMatch, C-CORAL, DANN and CDANN.

Source-domain accuracy, and which epoch the code's rule reports:

{{SOURCE}}

### B5. Which differences move the number

Each finding became a branch changing one thing. Effects are branch − baseline on the same seeds (paired), 95% CI. Holm correction is applied across all exploratory effects in the table; the confirmation run is a separate, pre-specified test.

{{EFFECTS}}

#### What the branches show
1. **F2, model selection, is ambiguous and decisive.** Read as cross-entropy (h1), early stopping halts PerfMatch at epoch 1 (median), before the ramped matching weight (F4) has any effect, and PerfMatch scores like ERM; this held on ten fresh seeds. Read as the full training objective (h1b), it stops near epoch 88 and PerfMatch keeps its advantage. Training is identical in all three cases (the last-epoch numbers match exactly); only the reported checkpoint changes. The paper's text does not say which loss it meant.
2. **F3, momentum, changes the training budget, not the result.** h2 is not a failure to train: with plain SGD for the paper's 100 epochs every method reaches about 98.5% source validation accuracy, using the linear spurious feature, but none learns the non-linear slab feature in that budget, so the oracle's advantage does not appear. Given 1000 epochs, plain SGD reaches the code's result ({{H2_LONG}}). The undocumented momentum is a tenfold training budget in effect.
3. **F2 and F3 interact.** Combined, PerfMatch loses 29.2 points, not the 54.5 their separate effects add up to; accuracy cannot go below chance. So the report never gives a "share of the gap".
4. **F4 alone has no detectable effect** under the code's selection rule. It matters only through F2.
5. **F6 does not change the oracle result.** Re-tuning λ on source validation, over the repo's own grid, picks λ = 1.0 for PerfMatch, the published value (h5 table below). For RandMatch, source validation cannot separate λ = 0.1 from 1.0; λ = 0.1 gives 59.4, the paper's number.
6. **F5 does not explain DANN and CDANN.** At the paper's learning rate both stay at chance (h6). Their gap is reported as *unexplained by the tested differences*.
7. **The missing domain, as a branch (h3).** Pointing the evaluation at p = 0.9, the nearest domain the code generates, is what a "make it run" agent might do silently. Every claim then lands near the paper and RandMatch's gap closes (59.4 vs 59.5). We report this as an open question for the authors, not a conclusion, because RandMatch's gap is fragile: three unrelated changes each bring it near the paper's 59.5 (h3: 59.4; λ = 0.1: 59.4; plain SGD for 1000 epochs: 59.6, an effect not detectable at 10 seeds). The report does not attribute it to any of them.

h5, λ grid from `slab-tune.py`:

{{TUNING}}

## Comparison with the human reproduction
The ML Reproducibility Challenge report on this paper (Jiles and Chakraborty, ReScience C 8(2) #18, 2022, DOI 10.5281/zenodo.6574661) also had to add p = 1.0 to the generator. Its Table 1 (as printed in the submission version; we could not open the ReScience PDF from our environment) reports target accuracy ERM 64.6 ± 4.50, RandMatch 66.9 ± 2.64, PerfMatch 87.9 ± 4.26: higher than both the paper and us. Three runs of the same table disagree by more than the paper's sd, which is why the verdict rule uses an equivalence margin and reports Inconclusive rather than forcing a yes or no.

SciCoQA took two discrepancies for this repo from that report: F1 and F7. Our hand audit and blind extraction found F1 and missed F7, so our recall against SciCoQA on this repo is 1 of 2. F2 to F6 are not in SciCoQA.

## Cost
4 vCPUs, no GPU. One method × 10 seeds × 100 epochs: 43–49 s (ERM, RandMatch, PerfMatch), 47–57 s (CORAL, DANN variants), 79–84 s (MMD variants), measured with one thread per job and four jobs in parallel (`logs/*/progress.txt`). 1000-epoch runs: 383–415 s. Rotated MNIST, LeNet (Part A): {{LENET_JOB}}. Total: {{TOTAL_RUNS}} training runs, {{TOTAL_MIN}} minutes of single-thread compute. An earlier MMD timing of 593 s is withdrawn: its log was deleted by mistake, and the re-run, with its log kept, took 79 s.

{{SCALING}}

Wall-clock is reported only for run sets that had the machine to themselves (`scripts/wallclock.py`, `metrics/wallclock.json`). Selection-rule branches need no retraining: the per-epoch traces of h1 and h1b are {{SEL:identical}} to the baseline's ({{SEL:lines}} lines in {{SEL:checks}} logs, `metrics/selection_traces.json`).

## Limits
- One paper, two tables. The settings diff and most ablation branches were run on Table 1; on Table 11 only F7 was branched, so F3 and F4, which apply to it, are notes there, not tested reasons. The extraction test is on the same paper we audited by hand, so it shows the step works on MatchDG, not that it generalises.
- The extractors were LLM agents (Claude) with fixed prompts (`extraction/prompts.md`), reading the paper through a web fetcher and the repo through files. They did not see our tables. One differ bug (a name filter that also matched "cross-domain") was fixed after the first scoring run; before the fix, F4 was missed in all pairings.
- h1b implements one version of "full objective" (cross-entropy plus λ times the matching penalty on matched validation pairs, at the final λ). Other versions are possible.
- MatchDG is audited on its one CPU-feasible table (Table 11: LeNet, 3 runs). The ResNet-18, ResNet-50 and DenseNet-121 tables are not audited. The paper does not state Table 11's run count; we assumed 3, the code's default. With 3 runs and a margin equal to the paper's sd (as small as 0.1 points), every Table 11 number was Inconclusive in the first pass. The 1-point floor was added after that pass; only the confirmation run on fresh data was graded with the floor declared beforehand. The "tightest margin" column shows what the data supports under any margin a reader prefers.
- The first Table 11 pre-registration hashed `grade_lenet.py` but not `grade.py`, which it imported its rule from, so that rule could in principle have changed after the hash. The confirmation's pre-registration hashes every rule file (`verdicts.py`, `grade_lenet.py`, `parse_runs.py`) and the run script.
- F7 was found by SciCoQA, not by us: our hand audit and the blind extraction both missed it. Schema version 2 adds the data-pipeline keys that would let the extractors express it; whether they then find it is build step 4 (spec §9).
- F7 disclosures. The F7 pre-registration says 72 plain and label files were checked; the correct count is {{F7:data:plain}} (training, validation and test), all byte-identical (`metrics/f7_data_check.json`). `grade_f7.py` was edited after the runs only to cast two numpy booleans to Python booleans for JSON output; the statistics are unchanged, and the hashed copy is `scripts/preregistered/grade_f7.py`. With 3 paired runs, an effect on the average smaller than the CI ({{F7:avg:ci}}) cannot be excluded.
- The run-count assumption matters for Table 11: if the paper averaged more than 3 runs, its sds are tighter estimates and our intervals slightly wider than they should be.
