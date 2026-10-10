# Second-paper candidates for the blind end-to-end audit

> **Update after the final screening review (3 Oct 2026).** Three of the four candidates below are graph neural network papers, which share one dependency world. Label-Free Explainability (Backup 2) is promoted to the second pick, so the pair is one graph paper in TensorFlow (PGExplainer) and one non-graph paper in PyTorch. BUDDY / ELPH moves to backup.


Date: 2026-10-03. Source: `scicoqa-real-v1.1.jsonl` (92 rows; "row N" = line N). MatchDG/robustdg (rows 67-68) excluded.
I read only the dataset's metadata columns plus each candidate's README and code at the pinned commit (via a blobless clone and raw.githubusercontent.com). I read the paper tables through WebFetch summaries. I did not run any training.

Tags: **[checked]** = I saw it in the paper, the code or the dataset. **[inferred]** = my estimate or recall, not verified.

**Blind protocol:** do not open the SciCoQA rows' description or origin columns, the linked MLRC reports, or the repo issue trackers before the run. Each pick below has a contamination hazard listed under its risks.

---

## Pick 1: PGExplainer

| | |
|---|---|
| Paper | *Parameterized Explainer for Graph Neural Network*, Luo et al., **NeurIPS 2020** |
| Links | arXiv https://arxiv.org/abs/2011.04573. SciCoQA pins the proceedings PDF https://proceedings.nips.cc/paper/2020/file/e37b08dd3015330dcbb5d6663667b8b8-Paper.pdf, so audit against that version. |
| Repo @ commit | https://github.com/flyingdoog/PGExplainer @ `ec57ea2db3b196da7eb93179acffc64ec6958828` (2021-03-25) [checked] |
| Known answer | **SciCoQA rows 73-78 (6 rows).** Categories: Algorithm/Paper Omission ×2, Model/Paper Omission ×1, Evaluation/Paper Omission ×3. The origin is an MLRC 2020 / ReScience C report (https://zenodo.org/record/4834242). I did not open that report. All six rows sit on the code path that produces the audited table [checked]. |
| Table to audit | **Table 2, the PGExplainer explanation-AUC row: 6 cells**, for BA-Shapes, BA-Community, Tree-Cycles, Tree-Grid, BA-2motifs and MUTAG. Each cell is mean ± sd over 10 runs; the paper says "we repeat each experiment 10 times" [checked]. Skip the inference-time row: those numbers are in ms on a GPU. |
| Data / model | All data is shipped in the repo under `dataset/`, about 17 MB [checked]. Node-classification graphs: BA-Shapes 700, BA-Community 1,400, Tree-Cycles 871 and Tree-Grid 1,231 nodes. Graph classification: BA-2motifs has 1,000 graphs [checked]. Mutagenicity has 4,337 graphs [inferred], of which the notebook explains 1,015 [checked]. The pretrained 3-layer GCN (20-20-20) checkpoints are shipped and each is under 60 KB [checked]. The explainer is an MLP with 64 hidden units [checked]. |
| CPU runtime | **About 1-2.5 h for all 6 cells × 10 seeds [inferred]. The 4 node-classification cells take about 20-60 min.** Evidence: the saved output of `BA-shapes.ipynb` shows explainer training at 10 epochs in 12 s (1.26 s/epoch) [checked; hardware unknown, the paper used an RTX 2070S]. The models are tiny and TF eager is latency-bound, so I expect a similar speed on CPU [inferred]. BA-2motifs and MUTAG update one graph at a time over about 1,000 graphs, so I estimate 3-8 min per seed [inferred]. Calibrate the estimate with one seed. |
| Main risk | **Environment and harness.** <br>• The code is TF 2.0 and the notebooks are its only entry points. Kernels are Python 3.6.8 for the node notebooks and 3.8.7 for the graph notebooks [checked]. <br>• TF 2.0 does not install on Python 3.11. You need Python 3.7, e.g. `uv python install 3.7` plus the `tensorflow==2.0.0` cp37 wheel [inferred, not tested]. <br>• There is no 10-seed loop; the config fixes seed 12345 [checked]. <br>• Some notebook paths are hard-coded and wrong; e.g. BA-2motifs loads `./BA-2motif.pkl`, but the file is in `dataset/` [checked]. <br>• The BA-Shapes notebook reloads a shipped explainer checkpoint after training [checked]. Decide whether you measure retrained or shipped explainers. <br>• **Contamination:** the repo README links to the reproduction reports. Strip those links from the pipeline's input. |

## Pick 2: BUDDY / ELPH (subgraph sketching)

| | |
|---|---|
| Paper | *Graph Neural Networks for Link Prediction with Subgraph Sketching*, Chamberlain et al., **ICLR 2023 (oral)** |
| Links | https://arxiv.org/abs/2209.15486 and https://openreview.net/forum?id=m1oqEOAozQU |
| Repo @ commit | https://github.com/melifluos/subgraph-sketching @ `3732cc75d8da216b41b972620dc545ff5aa1f6e1` (2023-05-09) [checked] |
| Known answer | **SciCoQA row 15**, category Algorithm/Difference. Its origin is a GitHub issue on this repo. The row sits on the code path for the audited table [checked]. |
| Table to audit | **Table 2, the Planetoid columns (Cora, Citeseer, Pubmed; HR@100).** The BUDDY row gives 3 cells; add the ELPH row for 3 more if time allows. Skip the OGB columns. Results are mean ± sd ("± one standard deviation", App. B.1) [checked]. **The paper does not state the number of runs** (not found in two WebFetch passes) [checked]. `run.py --reps N` reports the mean and sd over N runs [checked]. |
| Data / model | Planetoid datasets download automatically through PyG into `./dataset`. Sizes: Cora 2,708 nodes / 5,278 edges, Citeseer 3,327 / 4,552, Pubmed 19,717 / 44,324 [inferred, standard sizes]. Edges are split 70/10/20 at random [checked]. BUDDY is an MLP over node features plus MinHash/HyperLogLog structure features [checked]. Code defaults: hidden 1024, 50 epochs, batch 1024 [checked]. |
| CPU runtime | **About 1.5-2.5 h for BUDDY on all 3 datasets × 10 reps; about 40-80 min for Cora + Citeseer only [inferred].** <br>• Paper Table 3 (GPU) reports Pubmed preprocessing at 5 s and training at 1 s/epoch, and Cora at 0.4 s and 0.7 s/epoch [checked]. <br>• The README says the code was "tested on a Linux machine without GPU" [checked]. <br>• My CPU estimate scales those timings by FLOPs: Cora/Citeseer 2-4 min per rep, Pubmed 5-10 min per rep [inferred]. <br>• `run.py` prints the time of each epoch, so a 2-epoch smoke run will calibrate this. |
| Main risk | **Under-specified target.** <br>• The paper gives only tuning ranges, not the chosen values for each dataset. <br>• It does not state n, which the equivalence test needs (assume 10, the OGB convention, and flag it). <br>• The README calls the code a "reimplementation" whose defaults are "work in progress" [checked]. <br>**Install:** <br>• `torch_sparse` and `torch_scatter` are hard imports. Their wheels come from data.pyg.org, which this sandbox cannot reach, so build them from the PyPI sdist or allow the host. <br>• The PyG Planetoid downloader uses `github.com/.../raw` URLs, which return 403 here, while raw.githubusercontent.com works. Pre-seed `dataset/`. <br>• The code uses `distutils`, so you need Python 3.11 or older (the README uses 3.9). <br>**Contamination:** keep the pipeline away from the repo's issue tracker. |

---

## Backup 1: GNNInterpreter

| | |
|---|---|
| Paper | *GNNInterpreter: A Probabilistic Generative Model-Level Explanation for Graph Neural Networks*, Wang & Shen, **ICLR 2023** |
| Links | https://openreview.net/forum?id=rqq6Dh8t4d and arXiv https://arxiv.org/abs/2209.07924 (abstract matches) |
| Repo @ commit | https://github.com/yolandalalala/GNNInterpreter @ `4afe38cf1b4f6cb808d30ff39a133255f88cf37d` (2024-05-21). The core code lives in a separate package, `gnn-xai-common`; `requirements.txt` pins it at `9dfcb3b4aa1adac193d05d317b7404f2390389ed` [checked]. |
| Known answer | **SciCoQA rows 46-48.** Categories: Loss/Paper Omission ×2, Training/Paper Omission ×1. The origin is an MLRC 2023 report (https://openreview.net/pdf?id=8cYcR23WUo). The rows sit on the audited table's path [checked]. |
| Table to audit | **Table 2: 13 class-probability cells plus a training-time row** [checked]. **Caveat:** each ± is the sd across 1,000 sampled explanation graphs, not across seeds, and many cells are 1.000 ± 0.000. The equivalence test needs adapting. |
| Data / model | Four graph-classification datasets: MUTAG, plus Cyclicity, Motif and Shape, which are synthetic and generated from Rome graphs. Graphs average 18-57 nodes [checked]. The classifiers are GCN/NNConv with 3-5 layers and width 32-64; checkpoints are shipped in `ckpts/`, each under 90 KB [checked]. |
| CPU runtime | **About 5-20 min for the whole table [inferred].** The paper ran on a *single-core Intel i9 CPU* and reports 12-83 s per class, averaged over 100 trainings [checked]. |
| Main risk | <br>• The repo has only notebooks. <br>• The processed datasets come from a Google Drive link, which this sandbox cannot reach. <br>• The pinned commit is a 2024 refactor on torch 2.1.2 / PyG 2.5.3, while the paper used PyTorch 1.10 / PyG 2.0 [checked]. <br>• The sd is not over seeds. |

## Backup 2: Label-Free Explainability for Unsupervised Models

| | |
|---|---|
| Paper | *Label-Free Explainability for Unsupervised Models*, Crabbé & van der Schaar, **ICML 2022** |
| Links | https://proceedings.mlr.press/v162/crabbe22a/crabbe22a.pdf and arXiv https://arxiv.org/abs/2203.01928 (abstract matches) |
| Repo @ commit | https://github.com/JonathanCrabbe/Label-Free-XAI @ `3f6fd5e98ab2fe431d6c15abeb5896c3c7747c2b` (2022-09-21) [checked] |
| Known answer | **SciCoQA row 59**, category Training/Difference. The origin is an MLRC 2022 / ReScience C report (https://zenodo.org/record/8173656). The row is **not** on the audited table's path [checked], so only the paper-vs-code diff stage can score it. |
| Table to audit | **Tables 1-2, pretext-task sensitivity on MNIST: 12 Pearson-correlation cells**, each mean ± sd over 5 runs [checked]. Command: `cd experiments && python -m mnist --name pretext` [checked]. |
| Data / model | MNIST through the torchvision auto-download; its S3 mirror is reachable from this sandbox [checked]. The model is a conv autoencoder with 8/16/32 channels, latent size 4, well under 100k parameters [inferred from the architecture table]. Each run trains 3 pretext autoencoders and 1 classifier; there are 5 runs. Training uses ≤100 epochs, patience 10, batch 300. Example importance uses a 1,000-example subset [checked]. |
| CPU runtime | **About 1.5-4 h [inferred].** There are 20 trainings of a tiny model, which will be bound by data loading at about 5-10 s/epoch. Early stopping makes the epoch count uncertain. |
| Main risk | <br>• It may exceed the 2 h budget. <br>• It is the candidate most like MatchDG (PyTorch + MNIST), so it is a weaker test of generality. <br>• The known row is off the audited table's path. |

---

## Screened out (one line each)

- **GPU-scale or not CPU-runnable:** diffusion and GAN models, ImageNet/CIFAR ResNets, LLMs, MuJoCo, IR with BERT. This covers most of rows 1-45 and 49-58, 62, 66, 70-72 and 81-88.
- **Unofficial or third-party reimplementations:** rows 2, 6, 9, 11, 22.
- **No sd or single run:** GCN-Align (rows 89-91, TF1, DBP15K).
- **Results only in figures:** Shifty (row 60) and the fairness-attack paper (row 69).
- **Library with no experiment drivers:** CS-Shapley / valda (row 54).
- **Too close to MatchDG** (colored-MNIST invariance): CGN (row 63).
