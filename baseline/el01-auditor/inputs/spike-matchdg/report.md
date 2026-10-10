# Reproducibility audit: MatchDG (ICML 2021)

**Paper:** Mahajan, Tople, Sharma, *Domain Generalization using Causal Matching*, ICML 2021 (PMLR v139): Sec 3.2, Table 1, App. A.1, Tables 7 to 9 and Suppl. Table 11.
**Code:** github.com/microsoft/robustdg at `3eee173` (2022-03-20).
**Environment:** Python 3.9, torch 1.11.0, every package pinned to 2022-03-21 (`env/requirements-pinned.txt`); 4 vCPUs, 16 GB RAM, no GPU.
**Run date:** 2026-10-03. 542 training runs, 383 minutes of single-thread compute.

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
| Regression against golden outputs | script (`regression.py`): 73 verdicts and 53 other graded numbers re-derived from the raw logs, plus 6 extraction checks: 0 mismatches (2026-10-03) |

Working today: the runner and the grader. Repairs, branch patches and claim-to-command links were done by hand.

**Rules version 2.** After the final review, the verdict rules moved into one module (`scripts/verdicts.py`): one verdict list (a relative claim whose direction holds but whose size differs is *Partially reproduced*, with a size note), a "setup differs" flag computed by rule, and a practical floor on the equivalence margin. Version 1 and its outputs are kept (`scripts/v1/`, `metrics/v1/`). For Table 1 the change is in labels only: every Table 1 sd is above the floor, so no verdict moves.

## Part A. MatchDG itself: Suppl. Table 11 (Rotated MNIST, LeNet)

**Setup check.** The paper's Tables 8 and 9 give, for this experiment: learning rate 0.01, batch 16, weight decay 5e-4, 100 epochs, match penalty 1.0; MatchDG's contrastive phase 50 epochs, batch 512, τ 0.05. The repo's commands and defaults match all of them. Two slab findings carry over unchanged: SGD with undocumented momentum and Nesterov (F3), and a matching weight that ramps up from about 0 (F4). The paper does not say how many runs Table 11 averages; we used the code's default of 3 and assumed 3 for the paper. Runs used the three repairs only, no hypothesis changes (`audit/repair-env`, 45e7771). One data difference does reach this table, through MatchDG's checkpoint choice: F7 (SciCoQA row 67), tested in A3.

**Two runs, two rules.** Table 11 was run twice, with the repo's own commands both times.

- **First run** (MNIST subsets 0–2, training seeds 0–20). Its rule was written and hashed before any run finished (`logs/matchdg_lenet/PREREGISTERED.txt`): a cell is *Reproduced* only if the 90% CI of (ours − paper) lies inside ± the paper's sd for that cell. Those sds are as small as 0.1 points. After seeing the results we added a practical floor, margin = max(paper's sd, 1 point) (rules version 2), so the first run's counts under the floor are post hoc. That pre-registration also hashed `grade_lenet.py` but not the module it imported; see Limits.
- **Confirmation** (fresh MNIST subsets 3–5, training seeds 30, 40, 50; branch `audit/lenet-confirm` adds only the two seed options). The floor was declared and every rule file hashed before any confirmation run started (`logs/matchdg_lenet_confirm/PREREGISTERED.txt`). It is graded alone, not pooled with the first run. **The headline numbers for Table 11 are this run's.**

In both runs a cell is *Not reproduced* if the 95% CI of (ours − paper) excludes 0 and equivalence fails, and *Inconclusive* otherwise. The six-domain average is graded per run, with the paper's sd for it derived from its per-domain sds.

| Run | Margin | Margin declared | Reproduced | Inconclusive | Not reproduced | MatchDG beats ERM |
|---|---|---|---|---|---|---|
| First, MNIST subsets 0–2 | paper's sd | before the run | 0 | 28 | 0 | Reproduced |
| First, MNIST subsets 0–2 | max(paper's sd, 1 point) | after the run | 14 | 14 | 0 | Reproduced |
| **Confirmation, fresh subsets 3–5** | max(paper's sd, 1 point) | **before the run** | 13 | 15 | 0 | Reproduced |

Counts are over 28 claims: 24 cells and 4 six-domain averages.

### A1. Confirmation run (graded with the rule declared beforehand)

Ours / paper, target accuracy (%), 3 runs; R = Reproduced, I = Inconclusive, N = Not reproduced, margin = max(paper's sd, 1 point):

| Method | 0° | 15° | 30° | 45° | 60° | 75° | Average |
|---|---|---|---|---|---|---|---|
| ERM | 85.6 / 88.2 I | 98.5 / 98.6 I | 97.2 / 97.7 I | 97.5 / 97.5 R | 96.9 / 97.0 R | 85.0 / 85.6 I | 93.5 / 94.1 I |
| RandMatch | 90.5 / 91.0 I | 99.4 / 99.7 R | 99.6 / 99.6 R | 99.6 / 99.4 R | 99.5 / 99.7 R | 93.7 / 93.1 I | 97.0 / 97.1 R |
| **MatchDG** (the paper's method) | 93.2 / 93.0 I | 99.5 / 99.5 R | 99.4 / 99.9 R | 99.0 / 99.4 I | 99.5 / 99.7 R | 91.8 / 93.3 I | 97.1 / 97.4 R |
| PerfMatch (oracle) | 96.5 / 96.5 I | 99.3 / 99.1 R | 98.7 / 99.2 I | 98.3 / 98.6 I | 99.4 / 98.6 I | 94.7 / 94.9 I | 97.8 / 97.8 R |

| Method | Reproduced | Inconclusive | Not reproduced | Median tightest margin the data supports (points) |
|---|---|---|---|---|
| ERM | 2 | 4 | 0 | 1.9 |
| RandMatch | 4 | 2 | 0 | 0.6 |
| **MatchDG** (the paper's method) | 3 | 3 | 0 | 1.2 |
| PerfMatch (oracle) | 1 | 5 | 0 | 1.6 |

No cell is Not reproduced: every 95% CI of (ours − paper) contains 0.

Six-domain average:

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

**Setup differs.** No Table 11 claim carries the flag: no code omission had to be filled for this table, and the one branch run on it (F7, A3) had no detectable effect. The notes record what was tested and what applies but was not tested here:

- **MatchDG beats ERM**: no reason (nothing filled, no Holm-surviving effect). Notes: F3 applies, not tested for MatchDG, ERM; F4 applies, not tested for MatchDG; F7 tested (h7, MatchDG only): no Holm-surviving effect.
- **MatchDG beats RandMatch**: no reason (nothing filled, no Holm-surviving effect). Notes: F3 applies, not tested for MatchDG, RandMatch; F4 applies, not tested for MatchDG, RandMatch; F7 tested (h7, MatchDG only): no Holm-surviving effect.
- **PerfMatch (oracle) beats MatchDG**: no reason (nothing filled, no Holm-surviving effect). Notes: F3 applies, not tested for PerfMatch (oracle), MatchDG; F4 applies, not tested for PerfMatch (oracle), MatchDG; F7 tested (h7, MatchDG only): no Holm-surviving effect.

F4 (the ramped matching weight) had no detectable effect on Table 1, so it is a note here, not a reason.

The text's claim about prior work ("RandMatch and MatchDG outperform prior work on all the domains except the test domain 0"), against the prior-work numbers printed in Table 11 (copied from other papers; we did not re-run them), confirmation run:

| Test domain | Best prior work in Table 11 | RandMatch, ours (95% CI) | MatchDG, ours (95% CI) |
|---|---|---|---|
| 0° | 93.5 (DIVA) | 90.5 (87.5 to 93.6): not graded | 93.2 (91.1 to 95.3): not graded |
| 15° | 99.3 (DIVA) | 99.4 (98.8 to 99.9): not separable | 99.5 (98.5 to 100.5): not separable |
| 30° | 99.1 (DIVA) | 99.6 (98.8 to 100.3): not separable | 99.4 (98.8 to 100.1): not separable |
| 45° | 99.2 (DIVA) | 99.6 (99.1 to 100.1): not separable | 99.0 (96.8 to 101.3): not separable |
| 60° | 99.3 (DIVA) | 99.5 (99.0 to 100.0): not separable | 99.5 (98.7 to 100.3): not separable |
| 75° | 93.0 (DIVA) | 93.7 (92.4 to 95.0): not separable | 91.8 (90.2 to 93.5): not separable |

### A2. First run, under both margins

Each cell shows the verdict with the paper's sd as the margin (the rule hashed before the run), then with the 1-point floor (added after the run):

| Method | 0° | 15° | 30° | 45° | 60° | 75° | Average |
|---|---|---|---|---|---|---|---|
| ERM | 87.3 / 88.2 I, I | 98.4 / 98.6 I, I | 97.3 / 97.7 I, I | 97.7 / 97.5 I, R | 97.0 / 97.0 I, R | 85.1 / 85.6 I, I | 93.8 / 94.1 I, I |
| RandMatch | 91.3 / 91.0 I, I | 99.7 / 99.7 I, R | 99.6 / 99.6 I, R | 99.6 / 99.4 I, R | 99.8 / 99.7 I, R | 92.8 / 93.1 I, I | 97.1 / 97.1 I, R |
| **MatchDG** (the paper's method) | 92.3 / 93.0 I, I | 99.9 / 99.5 I, R | 99.7 / 99.9 I, R | 99.3 / 99.4 I, R | 99.8 / 99.7 I, R | 93.5 / 93.3 I, I | 97.4 / 97.4 I, R |
| PerfMatch (oracle) | 96.2 / 96.5 I, I | 98.6 / 99.1 I, I | 99.2 / 99.2 I, R | 99.1 / 98.6 I, I | 99.2 / 98.6 I, I | 95.4 / 94.9 I, I | 98.0 / 97.8 I, R |

| Six-domain average | Paper | Ours, mean over 3 runs | Δ (95% CI) | Tightest margin the data supports | Margin used | Verdict |
|---|---|---|---|---|---|---|
| ERM | 94.1 | 93.79 ± 0.29 | −0.31 (−1.35 to 0.73) | ±1.10 | ±1.00 (practical floor) | Inconclusive |
| RandMatch | 97.1 | 97.14 ± 0.07 | +0.04 (−0.63 to 0.71) | ±0.51 | ±1.00 (practical floor) | Reproduced |
| **MatchDG** (the paper's method) | 97.4 | 97.42 ± 0.24 | +0.02 (−0.62 to 0.66) | ±0.51 | ±1.00 (practical floor) | Reproduced |
| PerfMatch (oracle) | 97.8 | 97.95 ± 0.15 | +0.15 (−0.86 to 1.16) | ±0.88 | ±1.00 (practical floor) | Reproduced |

**In plain words.** Nothing in MatchDG's own table is refuted. On fresh data, with the rule and the 1-point floor fixed beforehand, 13 of 28 numbers are confirmed within max(paper's sd, 1 point) and 15 are Inconclusive, including every cell at the two hardest rotations (0° and 75°). Every cell is within 2.6 points of the paper. MatchDG's six-domain average is Reproduced (97.1 against 97.4; tightest margin ±0.82), and its gain over ERM reproduces in both runs (+3.62 on fresh data against the paper's +3.3). The finer ordering does not resolve: MatchDG's edge over RandMatch is +0.28 in the first run and +0.03 in the confirmation (paper +0.3), and the oracle's edge over MatchDG is Inconclusive in both. Against the prior-work rows, the first run was clearly above the best prior number at 15°, 30° and 60°; the confirmation is not separable from it at any graded domain, so the text's claim to beat prior work is not confirmed. The first run's counts under the floor (14 Reproduced, 14 Inconclusive) are close to the confirmation's, but the floor was chosen after that run, so we do not quote them as the result. More runs per cell would sharpen all of this; F3 and F4 apply to this table and were not re-tested here. F7, the one data difference on this table's path, was tested and moved nothing detectable (A3).

### A3. F7: SciCoQA's second row for this repo (data augmentation; MatchDG only)

**The finding.** SciCoQA lists two discrepancies for robustdg, both from the MLRC report below: F1 (03255952, [row 68](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L68)) and this one (90c14330, [row 67](https://github.com/UKPLab/scicoqa/blob/463162906459be508ed4a2294fcaede9fa072036/data/scicoqa-real-v1.1.jsonl#L67)), which says the Rotated MNIST generator applies rotations in inconsistent directions. The mechanism at 3eee173: `data/data_gen_mnist.py` saves two copies of every rotated digit, a plain one (`*_org_data.pt`) and an augmented one (`*_data.pt`) made by `RandomResizedCrop` and then `RandomHorizontalFlip` *after* the rotation (lines 34–35 and 85). A flipped +θ digit is a mirrored digit at −θ. The paper never says Rotated MNIST is augmented (the supplement describes augmentation for PACS and Chest X-ray only), and it does not say how MatchDG's contrastive phase picks its checkpoint. Kind: paper omission. Neither our hand audit nor the blind extraction found it, so our recall against SciCoQA on this repo is 1 of 2; the 20-key extraction schema had no slot for augmentation (schema version 2 adds one, spec §3).

**Is it on the Table 11 path?** Every method trains and tests on the plain copy (`--mnist_aug 0`, `data/mnist_loader.py:37-40`). The augmented copy is read at one point on this table's path: MatchDG's contrastive phase validates with `--match_func_aug_case 1` (`reproduce_rmnist_lenet.py:25` → `train.py:217-218` → `utils/helper.py:173-175`, `MnistRotatedAugEval` → `data/mnist_loader_match_eval.py:38`, which loads `*_data.pt`; the default `--test_metric` is `match_score`, `train.py:155`). Every 5 epochs it scores how often each plain image's own augmented copy ranks in the top k, and saves the epoch with the best score (`algorithms/match_dg.py:263-266`). The second phase then builds its matches with that checkpoint. So F7 can move MatchDG's Table 11 numbers and no other method's; ERM, RandMatch and the oracle were not re-run. The obvious reading, that the flipped copy is never loaded because `--mnist_aug` defaults to 0, is right for training and testing but misses this checkpoint choice.

**Branch h7** (`audit/h7-no-flip`, 2a57284) replaces the flip with a step that draws the same random number and returns the image unchanged, so every crop stays the same. Data check (`scripts/check_f7_data.py`, `metrics/f7_data_check.json`): 108 of 108 plain and label files are byte-identical to the confirmation's; of 21,600 augmented images, 10,848 are unchanged, 10,752 differ only by a horizontal flip, and 0 differ in any other way.

**Rule, hashed before any run** (`logs/h7_no_flip/PREREGISTERED.txt`, commit 26caa88): MatchDG re-run on the confirmation's subsets and seeds, paired with the confirmation by (test domain, run). Primary test: the six-domain average, 95% t CI over 3 runs. Cells: paired t-tests, Holm across six. F7 becomes a "setup differs" reason for a MatchDG claim only if its effect survives.

| Test domain | MatchDG, shipped data | MatchDG, no flips | Effect, paired by run (95% CI) | Holm p | Same contrastive-phase checkpoint |
|---|---|---|---|---|---|
| 0° | 93.2 | 93.4 | +0.23 (−0.77 to 1.24) | 1.00 | 2 of 3 runs |
| 15° | 99.5 | 99.5 | +0.03 (−1.09 to 1.15) | 1.00 | 1 of 3 runs |
| 30° | 99.4 | 99.4 | −0.03 (−0.91 to 0.84) | 1.00 | 1 of 3 runs |
| 45° | 99.0 | 99.0 | 0.00 (all 3 runs identical) | 1.00 | 2 of 3 runs |
| 60° | 99.5 | 99.0 | −0.47 (−2.06 to 1.13) | 1.00 | 1 of 3 runs |
| 75° | 91.8 | 91.8 | 0.00 (all 3 runs identical) | 1.00 | 3 of 3 runs |
| **Six-domain average** (primary test) | 97.07 | 97.03 | −0.04 (−0.41 to 0.34) | | |

**Result.** Without flips the selection score at the chosen epoch rises from about 45% to 68%, and the chosen checkpoint changes in 8 of 18 runs (the "Current Best Epoch" lines in `logs/matchdg_lenet_confirm/train_matchdg_*.log` and `logs/h7_no_flip/train_matchdg_*.log`; line numbers in `metrics/grades_f7.json`). Where the checkpoint did not change, the final accuracy was identical in 10 of 10 runs, so the pipeline is deterministic and any difference comes through the checkpoint. Where it changed, the accuracy moved in 7 of 8 runs, by up to 1.2 points, in both directions. On the six-domain average the effect is −0.04 points (95% CI −0.41 to 0.34), and 0 of 6 cells survive Holm. **F7 is on the path and was tested; it has no detectable effect on Table 11, so it is a note on MatchDG's claims, not a "setup differs" reason, and no Table 11 verdict changes.** The 18 runs took 14.6 minutes of wall-clock, 6 at a time.

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

| Claim (Table 1, target accuracy) | Paper | Ours | Δ (95% CI) | 90% CI inside ±margin? | Tightest margin the data supports | Verdict | Setup differs |
|---|---|---|---|---|---|---|---|
| ERM | 57.6 ± 6.58 | 53.8 ± 4.09 | −3.8 (−9.3 to 1.7) | no (±6.58) | ±8.3 | Inconclusive | yes: F1, F2 |
| RandMatch | 59.5 ± 3.50 | 54.7 ± 3.96 | −4.8 (−8.5 to −1.1) | no (±3.50) | ±7.9 | Not reproduced | yes: F1, F2 |
| PerfMatch | 77.8 ± 6.01 | 80.4 ± 7.49 | +2.6 (−4.1 to 9.4) | no (±6.01) | ±8.2 | Inconclusive | yes: F1, F2, F3 |
| MMD | 62.9 ± 5.01 | 60.7 ± 5.47 | −2.2 (−7.4 to 3.0) | no (±5.01) | ±6.5 | Inconclusive | yes: F1 |
| CORAL | 63.1 ± 5.86 | 59.5 ± 4.65 | −3.6 (−8.9 to 1.6) | no (±5.86) | ±8.0 | Inconclusive | yes: F1 |
| DANN | 53.0 ± 1.41 | 50.2 ± 1.39 | −2.8 (−4.2 to −1.4) | no (±1.41) | ±4.0 | Not reproduced | yes: F1 |
| C-MMD | 58.9 ± 3.43 | 58.8 ± 5.51 | −0.1 (−4.7 to 4.5) | no (±3.43) | ±3.9 | Inconclusive | yes: F1 |
| C-CORAL | 64.7 ± 4.69 | 59.6 ± 4.28 | −5.1 (−9.6 to −0.7) | no (±4.69) | ±8.8 | Not reproduced | yes: F1 |
| CDANN | 55.9 ± 2.47 | 50.1 ± 1.58 | −5.8 (−7.9 to −3.7) | no (±2.47) | ±7.5 | Not reproduced | yes: F1 |

Relative claims are graded on direction (our paired CI must exclude 0), then on size, with the paper's own uncertainty included (its gap has a standard error of about 3 points from its reported sds).

| Claim | Paper gap | Our gap, paired (95% CI) | Our gap − paper gap (95% CI, both uncertainties) | Verdict | Setup differs |
|---|---|---|---|---|---|
| PerfMatch (oracle) beats ERM | +20.2 | +26.6 (21.0 to 32.3) | +6.4 (−1.5 to 14.4) | Reproduced | yes: F1, F2, F3 |
| PerfMatch (oracle) beats RandMatch | +18.3 | +25.8 (19.9 to 31.7) | +7.5 (0.2 to 14.7) | Partially reproduced (gap larger than reported) | yes: F1, F2, F3 |

**Setup differs, by rule** (`verdicts.setup_flag`): a claim gets the flag when a code omission had to be filled to run it, or when a finding's branch has a Holm-surviving effect on a method the claim names. Findings that apply but were not tested, or had no Holm-surviving effect, are notes.

- **ERM**: F1 filled: target domain p = 1.0 never generated (code omission); F2 (h1) moves ERM by +4.8 points, survives Holm. Notes: F3 tested: no Holm-surviving effect.
- **RandMatch**: F1 filled: target domain p = 1.0 never generated (code omission); F2 (h1b) moves RandMatch by +5.5 points, survives Holm. Notes: F3 tested: no Holm-surviving effect; F4 tested: no Holm-surviving effect; F6 tested by re-tuning (h5), not as a paired branch.
- **PerfMatch**: F1 filled: target domain p = 1.0 never generated (code omission); F2 (h1) moves PerfMatch by −25.8 points, survives Holm; F3 (h2) moves PerfMatch by −28.7 points, survives Holm. Notes: F4 tested: no Holm-surviving effect; F6 tested by re-tuning (h5), not as a paired branch.
- **MMD**: F1 filled: target domain p = 1.0 never generated (code omission). Notes: F2 applies, not tested for MMD; F3 applies, not tested for MMD.
- **CORAL**: F1 filled: target domain p = 1.0 never generated (code omission). Notes: F2 applies, not tested for CORAL; F3 applies, not tested for CORAL.
- **DANN**: F1 filled: target domain p = 1.0 never generated (code omission). Notes: F2 applies, not tested for DANN; F3 applies, not tested for DANN; F5 tested: no Holm-surviving effect.
- **C-MMD**: F1 filled: target domain p = 1.0 never generated (code omission). Notes: F2 applies, not tested for C-MMD; F3 applies, not tested for C-MMD.
- **C-CORAL**: F1 filled: target domain p = 1.0 never generated (code omission). Notes: F2 applies, not tested for C-CORAL; F3 applies, not tested for C-CORAL.
- **CDANN**: F1 filled: target domain p = 1.0 never generated (code omission). Notes: F2 applies, not tested for CDANN; F3 applies, not tested for CDANN; F5 tested: no Holm-surviving effect.
- **PerfMatch beats ERM**: F1 filled: target domain p = 1.0 never generated (code omission); F2 (h1) moves PerfMatch by −25.8 points, survives Holm; F2 (h1) moves ERM by +4.8 points, survives Holm; F3 (h2) moves PerfMatch by −28.7 points, survives Holm. Notes: F4 tested: no Holm-surviving effect; F6 tested by re-tuning (h5), not as a paired branch.
- **PerfMatch beats RandMatch**: F1 filled: target domain p = 1.0 never generated (code omission); F2 (h1) moves PerfMatch by −25.8 points, survives Holm; F2 (h1b) moves RandMatch by +5.5 points, survives Holm; F3 (h2) moves PerfMatch by −28.7 points, survives Holm. Notes: F4 tested: no Holm-surviving effect; F6 tested by re-tuning (h5), not as a paired branch.

**In plain words.** The oracle's advantage over ERM reproduces with the released code; over RandMatch the direction holds but our gap is larger than reported, so that claim is Partially reproduced. No single number in Table 1 can be confirmed to within the paper's own spread at 10 seeds, because the paper's sds are as large as the effects. Four numbers are outside it: RandMatch, C-CORAL, DANN and CDANN.

Source-domain accuracy, and which epoch the code's rule reports:

| Method | Source 1 (p = 0.0) | Source 2 (p = 0.1) | Target (p = 1.0) | Epoch picked (median) | Target at last epoch |
|---|---|---|---|---|---|
| ERM | 100.0 | 95.8 | 53.8 | 18 | 59.1 |
| RandMatch | 100.0 | 95.9 | 54.7 | 28 | 60.9 |
| PerfMatch | 99.8 | 98.2 | 80.4 | 73.5 | 86.4 |
| MMD | 99.9 | 96.4 | 60.7 | 69.5 | 65.4 |
| CORAL | 100.0 | 96.4 | 59.5 | 61 | 64.8 |
| DANN | 99.9 | 95.0 | 50.2 | 39 | 50.1 |
| C-MMD | 99.9 | 96.2 | 58.8 | 80.5 | 60.2 |
| C-CORAL | 100.0 | 96.4 | 59.6 | 61.5 | 64.7 |
| CDANN | 100.0 | 95.1 | 50.1 | 38 | 50.1 |

### B5. Which differences move the number

Each finding became a branch changing one thing. Effects are branch − baseline on the same seeds (paired), 95% CI. Holm correction is applied across all exploratory effects in the table; the confirmation run is a separate, pre-specified test.

| Branch | Method | Branch mean | Effect vs baseline (95% CI) | Holm-adjusted p | Epoch picked (median) | Source val. acc. at that epoch |
|---|---|---|---|---|---|---|
| h1: select by validation cross-entropy (one reading of the paper) | PerfMatch | 54.6 | −25.8 (−34.4 to −17.2) | 1.4e-03 (survives) | 1 | 98.2 |
| h1: select by validation cross-entropy (one reading of the paper) | RandMatch | 50.9 | −3.8 (−6.8 to −0.7) | 2.1e-01 (CI excludes 0, not after Holm) | 1 | 98.1 |
| h1: select by validation cross-entropy (one reading of the paper) | ERM | 58.5 | +4.8 (2.9 to 6.6) | 4.3e-03 (survives) | 99 | 98.4 |
| h1b: select by full validation objective (the other reading) | PerfMatch | 85.2 | +4.7 (−2.5 to 11.9) | 1.0e+00 (no detectable effect) | 88 | 99.0 |
| h1b: select by full validation objective (the other reading) | RandMatch | 60.2 | +5.5 (2.8 to 8.2) | 1.7e-02 (survives) | 85.5 | 98.5 |
| h2: plain SGD, as the paper states | PerfMatch | 51.7 | −28.7 (−34.7 to −22.8) | 3.3e-05 (survives) | 27.5 | 98.6 |
| h2: plain SGD, as the paper states | RandMatch | 50.6 | −4.1 (−6.9 to −1.3) | 1.1e-01 (CI excludes 0, not after Holm) | 9.5 | 98.6 |
| h2: plain SGD, as the paper states | ERM | 50.0 | −3.8 (−6.4 to −1.1) | 1.3e-01 (CI excludes 0, not after Holm) | 2.5 | 98.5 |
| h2 diagnostic: plain SGD for 1000 epochs | PerfMatch | 80.7 | +0.3 (−5.2 to 5.8) | 1.0e+00 (no detectable effect) | 531.5 | 99.5 |
| h2 diagnostic: plain SGD for 1000 epochs | RandMatch | 59.6 | +5.0 (−0.8 to 10.7) | 7.3e-01 (no detectable effect) | 398 | 99.0 |
| h2 diagnostic: plain SGD for 1000 epochs | ERM | 53.3 | −0.5 (−1.8 to 0.7) | 1.0e+00 (no detectable effect) | 232 | 98.7 |
| h1 + h2 together | PerfMatch | 51.3 | −29.2 (−35.0 to −23.3) | 2.7e-05 (survives) | 4 | 98.3 |
| h1 + h2 together | ERM | 51.3 | −2.5 (−5.9 to 0.9) | 1.0e+00 (no detectable effect) | 99 | 98.2 |
| h3: evaluate on p = 0.9, the domain the code generates | PerfMatch | 82.5 | +2.1 (0.6 to 3.6) | 1.3e-01 (CI excludes 0, not after Holm) | 73.5 | 99.5 |
| h3: evaluate on p = 0.9, the domain the code generates | RandMatch | 59.4 | +4.8 (2.8 to 6.7) | 5.7e-03 (survives) | 28 | 98.8 |
| h3: evaluate on p = 0.9, the domain the code generates | ERM | 58.7 | +4.9 (3.1 to 6.7) | 3.2e-03 (survives) | 18 | 98.5 |
| h4: constant matching weight (code ramps it from 0) | PerfMatch | 78.0 | −2.4 (−10.5 to 5.7) | 1.0e+00 (no detectable effect) | 55.5 | 99.4 |
| h4: constant matching weight (code ramps it from 0) | RandMatch | 57.8 | +3.2 (−1.3 to 7.6) | 1.0e+00 (no detectable effect) | 53 | 98.8 |
| h6: DANN and CDANN at lr 0.1, as the paper states (code hard-codes 0.01) | DANN | 50.3 | +0.1 (−0.8 to 1.0) | 1.0e+00 (no detectable effect) | 9 | 98.4 |
| h6: DANN and CDANN at lr 0.1, as the paper states (code hard-codes 0.01) | CDANN | 49.6 | −0.5 (−2.9 to 2.0) | 1.0e+00 (no detectable effect) | 2 | 77.4 |
| h1 confirmation, fresh seeds 10–19 vs their own baseline | ERM | 60.4 | +4.3 (2.9 to 5.7) | 7.3e-05 (pre-specified, not in Holm family) | 99 | |
| h1 confirmation, fresh seeds 10–19 vs their own baseline | PerfMatch | 52.4 | −25.4 (−30.8 to −20.1) | 1.9e-06 (pre-specified, not in Holm family) | 1 | |

#### What the branches show
1. **F2, model selection, is ambiguous and decisive.** Read as cross-entropy (h1), early stopping halts PerfMatch at epoch 1 (median), before the ramped matching weight (F4) has any effect, and PerfMatch scores like ERM; this held on ten fresh seeds. Read as the full training objective (h1b), it stops near epoch 88 and PerfMatch keeps its advantage. Training is identical in all three cases (the last-epoch numbers match exactly); only the reported checkpoint changes. The paper's text does not say which loss it meant.
2. **F3, momentum, changes the training budget, not the result.** h2 is not a failure to train: with plain SGD for the paper's 100 epochs every method reaches about 98.5% source validation accuracy, using the linear spurious feature, but none learns the non-linear slab feature in that budget, so the oracle's advantage does not appear. Given 1000 epochs, plain SGD reaches the code's result (PerfMatch 80.7, +0.3 against the code's settings, 95% CI −5.2 to 5.8; ERM 53.3, −0.5, CI −1.8 to 0.7). The undocumented momentum is a tenfold training budget in effect.
3. **F2 and F3 interact.** Combined, PerfMatch loses 29.2 points, not the 54.5 their separate effects add up to; accuracy cannot go below chance. So the report never gives a "share of the gap".
4. **F4 alone has no detectable effect** under the code's selection rule. It matters only through F2.
5. **F6 does not change the oracle result.** Re-tuning λ on source validation, over the repo's own grid, picks λ = 1.0 for PerfMatch, the published value (h5 table below). For RandMatch, source validation cannot separate λ = 0.1 from 1.0; λ = 0.1 gives 59.4, the paper's number.
6. **F5 does not explain DANN and CDANN.** At the paper's learning rate both stay at chance (h6). Their gap is reported as *unexplained by the tested differences*.
7. **The missing domain, as a branch (h3).** Pointing the evaluation at p = 0.9, the nearest domain the code generates, is what a "make it run" agent might do silently. Every claim then lands near the paper and RandMatch's gap closes (59.4 vs 59.5). We report this as an open question for the authors, not a conclusion, because RandMatch's gap is fragile: three unrelated changes each bring it near the paper's 59.5 (h3: 59.4; λ = 0.1: 59.4; plain SGD for 1000 epochs: 59.6, an effect not detectable at 10 seeds). The report does not attribute it to any of them.

h5, λ grid from `slab-tune.py`:

| Method | λ | Source val. acc. (seeds 0–2) | Target (seeds 0–2) | Target (10 seeds) |
|---|---|---|---|---|
| PerfMatch | 0.1 | 99.00 | 72.3 | 67.4 |
| PerfMatch | 1.0 | 99.67 | 85.7 | 80.4 |
| PerfMatch | 10.0 | 99.20 | 83.0 | 73.3 |
| RandMatch | 0.1 | 98.73 | 62.3 | 59.4 |
| RandMatch | 1.0 | 98.73 | 58.0 | 54.7 |
| RandMatch | 10.0 | 98.60 | 60.3 | 56.6 |

## Comparison with the human reproduction
The ML Reproducibility Challenge report on this paper (Jiles and Chakraborty, ReScience C 8(2) #18, 2022, DOI 10.5281/zenodo.6574661) also had to add p = 1.0 to the generator. Its Table 1 (as printed in the submission version; we could not open the ReScience PDF from our environment) reports target accuracy ERM 64.6 ± 4.50, RandMatch 66.9 ± 2.64, PerfMatch 87.9 ± 4.26: higher than both the paper and us. Three runs of the same table disagree by more than the paper's sd, which is why the verdict rule uses an equivalence margin and reports Inconclusive rather than forcing a yes or no.

SciCoQA took two discrepancies for this repo from that report: F1 and F7. Our hand audit and blind extraction found F1 and missed F7, so our recall against SciCoQA on this repo is 1 of 2. F2 to F6 are not in SciCoQA.

## Cost
4 vCPUs, no GPU. One method × 10 seeds × 100 epochs: 43–49 s (ERM, RandMatch, PerfMatch), 47–57 s (CORAL, DANN variants), 79–84 s (MMD variants), measured with one thread per job and four jobs in parallel (`logs/*/progress.txt`). 1000-epoch runs: 383–415 s. Rotated MNIST, LeNet (Part A): 202–220 s for ERM, RandMatch or PerfMatch; 547–571 s for MatchDG (both phases). Total: 542 training runs, 383 minutes of single-thread compute. An earlier MMD timing of 593 s is withdrawn: its log was deleted by mistake, and the re-run, with its log kept, took 79 s.

| Run set | Training runs | Single-thread compute | Wall-clock |
|---|---|---|---|
| Table 1 (slab): baseline, all branches, fresh-seed confirmation | 380 | 49 min | not separable (run sets overlapped) |
| Table 11, first run | 72 | 118 min | 32.5 min (24 jobs, 4 at a time) |
| Table 11, confirmation | 72 | 129 min | 35.2 min (24 jobs, 4 at a time) |
| F7 branch, MatchDG only | 18 | 87 min | 14.6 min (6 jobs, 6 at a time) |
| **Whole audit** | 542 | 383 min | |

Wall-clock is reported only for run sets that had the machine to themselves (`scripts/wallclock.py`, `metrics/wallclock.json`). Selection-rule branches need no retraining: the per-epoch traces of h1 and h1b are identical to the baseline's (24,000 lines in 8 logs, `metrics/selection_traces.json`).

## Limits
- One paper, two tables. The settings diff and most ablation branches were run on Table 1; on Table 11 only F7 was branched, so F3 and F4, which apply to it, are notes there, not tested reasons. The extraction test is on the same paper we audited by hand, so it shows the step works on MatchDG, not that it generalises.
- The extractors were LLM agents (Claude) with fixed prompts (`extraction/prompts.md`), reading the paper through a web fetcher and the repo through files. They did not see our tables. One differ bug (a name filter that also matched "cross-domain") was fixed after the first scoring run; before the fix, F4 was missed in all pairings.
- h1b implements one version of "full objective" (cross-entropy plus λ times the matching penalty on matched validation pairs, at the final λ). Other versions are possible.
- MatchDG is audited on its one CPU-feasible table (Table 11: LeNet, 3 runs). The ResNet-18, ResNet-50 and DenseNet-121 tables are not audited. The paper does not state Table 11's run count; we assumed 3, the code's default. With 3 runs and a margin equal to the paper's sd (as small as 0.1 points), every Table 11 number was Inconclusive in the first pass. The 1-point floor was added after that pass; only the confirmation run on fresh data was graded with the floor declared beforehand. The "tightest margin" column shows what the data supports under any margin a reader prefers.
- The first Table 11 pre-registration hashed `grade_lenet.py` but not `grade.py`, which it imported its rule from, so that rule could in principle have changed after the hash. The confirmation's pre-registration hashes every rule file (`verdicts.py`, `grade_lenet.py`, `parse_runs.py`) and the run script.
- F7 was found by SciCoQA, not by us: our hand audit and the blind extraction both missed it. Schema version 2 adds the data-pipeline keys that would let the extractors express it; whether they then find it is build step 4 (spec §9).
- F7 disclosures. The F7 pre-registration says 72 plain and label files were checked; the correct count is 108 of 108 (training, validation and test), all byte-identical (`metrics/f7_data_check.json`). `grade_f7.py` was edited after the runs only to cast two numpy booleans to Python booleans for JSON output; the statistics are unchanged, and the hashed copy is `scripts/preregistered/grade_f7.py`. With 3 paired runs, an effect on the average smaller than the CI (−0.41 to 0.34) cannot be excluded.
- The run-count assumption matters for Table 11: if the paper averaged more than 3 runs, its sds are tighter estimates and our intervals slightly wider than they should be.
