# EL-01 auditor: progress

State carried between sessions. Plan: `MASTER_PROMPT.md` section 7. Choices: `DECISIONS.md`.

## Phases

- [x] Phase 0: setup and inventory ✓ (2026-10-03)
- [x] Phase 1: port the grader and pass the MatchDG regression ✓ (2026-10-04)
- [x] Phase 2: audit workspace, environment builder, runner ✓ (2026-10-04)
- [x] Phase 3: repair agent ✓ (2026-10-04)
- [x] Phase 4: claim cards and the claim-to-command linker ✓ (2026-10-04)
- [x] Phase 5: settings extraction (schema v2), the diff, and the data-pipeline test ✓ (2026-10-04)
- [ ] Phase 6: branch-patch writer and ablation runs
- [ ] Phase 7: end-to-end pipeline and the report
- [ ] Phase 8: second paper, blind
- [ ] Phase 9: the UI (three screens) and demo mode

## Machine facts (recorded 2026-10-03)

| Fact | Value |
|---|---|
| OS | macOS 27.0.1 (build 26A434), arm64 |
| CPU | Apple M4, 10 cores: 4 performance + 6 efficiency (10 logical) |
| RAM | 16 GiB |
| Free disk | 47 GiB free of 228 GiB (data volume) |
| Default parallel jobs | max(1, 10 − 2) = 8 |
| Project path | `/Users/dev/el01-auditor` (not iCloud-synced, no spaces) |
| Tools | git 2.54.0 (Apple Git-157), uv 0.12.23, tool Python 3.10.22 (uv-managed); system `python3` 3.9.6 is not used |
| Claude Code CLI | 2.1.288, at `~/.local/bin/claude` |

The spike ran on 4 x86 vCPUs; this laptop is Apple Silicon, so expect small numeric differences on fresh runs (section 5). Grading the spike's own logs must still match `golden/` exactly.

## Claude Code CLI check (2.1.288)

| Flag (section 5) | Status |
|---|---|
| `-p` / `--print`, prompt on stdin | present; stdin accepted ("Input must be provided either through stdin or as a prompt argument") |
| `--output-format json` | present (choices: text, json, stream-json) |
| `--json-schema <schema>` | present |
| `--model <model>` | present; aliases include `sonnet`, `opus`, `fable` |
| `--max-turns <turns>` | **hidden from `--help`, but accepted**: `--max-turns notanumber` fails with "must be a number"; an unknown flag fails with "unknown option" (parse-only probes, no API call) |
| `--no-session-persistence` | present (print mode only) |
| `--tools <tools...>` | present; `""` disables all built-in tools |
| `--allowedTools` / `--allowed-tools` | present |
| `--add-dir <directories...>` | present |
| `--bare` | present; not used (needs an API key) |
| Also available | `--strict-mcp-config`, `--mcp-config`, `--setting-sources`, `--max-budget-usd` |

Verified in Phase 3 with two live probe calls: the JSON result carries `structured_output`; with `--safe-mode --restricted --strict-mcp-config` the agent has no MCP servers, no user plugins, only the tools named in `--tools` (plus StructuredOutput), and cannot read outside its working directory (DECISIONS.md).

## Inventory (section 3)

All 13 inputs are present. Nothing missing.
- Spec, team notes and concept note are in `inputs/`; all of `spike-matchdg/` is there: scripts (including `scripts/v1/` and `scripts/preregistered/`), `golden/` (4 files), `extraction/` (prompts, schema, score, 4 outputs), `metrics/` (23 files + `v1/`), `logs.tar.gz`, the bundle, the patches, `branches.txt`, `templates/` (5 files) and `second-paper-candidates.md`.
- `inputs/spike-matchdg/scripts/verdicts.py` sha256 = `7721a4727c1636d8f8e3f9610897eee7ffc00d3c7d44d2542f99f0d66974a83d`, the frozen hash (rule 2).

Workspace (git-ignored):
- `workspace/spike/logs/`: 15 run directories and 178 files from `logs.tar.gz`, including 3 `PREREGISTERED.txt` files (matchdg_lenet, matchdg_lenet_confirm, h7_no_flip).
- `workspace/repos/robustdg/`: clone of microsoft/robustdg, detached at `3eee173` (2022-03-20). The bundle is fetched as 12 `audit/*` remote branches plus tag `round0-submission` (refspec note in `DECISIONS.md`).
- `workspace/papers/matchdg/`: `mahajan21b.pdf` (12 pages), `mahajan21b-supp.pdf` (19 pages).
- Disk so far: workspace 111 MB, `.venv` 180 MB.

## Phase 0: setup and inventory ✓

Plan: check the inputs → git init, `.gitignore`, `pyproject.toml`, uv venv (3.10) with the dependencies → record machine facts and the CLI check → extract the logs → clone robustdg, verify and fetch the bundle → download both PDFs → write `CLAUDE.md`, `PROGRESS.md` and `DECISIONS.md` → acceptance check → commit.

Acceptance output (trimmed):
```
$ git bundle verify inputs/spike-matchdg/matchdg-audit.bundle (in the clone)
../../../inputs/spike-matchdg/matchdg-audit.bundle is okay
$ git -C workspace/repos/robustdg branch -r | grep audit/
  audit/audit-evidence  audit/confirm-base  audit/h-combined  audit/h-dann-lr
  audit/h-omission-constant-penalty  audit/h-omission-plain-sgd  audit/h-paper-target-1.0
  audit/h-select-valloss  audit/h-select-valloss-total  audit/h7-no-flip
  audit/lenet-confirm  audit/repair-env
  -> 12 audit/* branches
$ git -C workspace/repos/robustdg tag
  round0-submission
$ required commits
  9b4a263 -> 9b4a26399773f52e9729aa960182bd04412f846f
  3f08ff7 -> 3f08ff76eba6b47367c3071a9e91f03f748b278f
  45e7771 -> 45e77711e42338dc4a170482c39ee7393e6f7bb1
  7dde854 -> 7dde854f830e12891e15208e3d3b2a67ede98cc9
  2a57284 -> 2a57284cbdf813f08ae3066201ef5ecad2199893
$ PDFs
  mahajan21b-supp.pdf  2356975 bytes  sha256 2726d78e4d55150c7c208bb37195545ccc32338edff04e9919f1325b94530e67
  mahajan21b.pdf       2032058 bytes  sha256 c9d9f8a4fc7fabd12534630f3268a3dff52eae611eefbebd501f78718ca07c21
```
PROGRESS.md holds the machine facts and the CLI flags (above).

## Phase 1: port the grader and pass the MatchDG regression ✓

Plan:
- `el01/config.py` `Paths`; `el01/grade/legacy/verdicts_v2.py` (byte copy) and `rules.py` (2.1, `setup_flag` takes findings/branch map/short names).
- `grade/parse.py` (parse_runs + parse_epochs + F7 contrastive epochs) and `grade/effects.py`. The MatchDG graders go in `grade/spike/{table1,table11,f7}.py` and take an injected rules namespace (default: legacy v2, the rules the run sets pre-registered). `diff/settings_diff.py` is the port of extraction_diff.
- `grade/spike/regress.py`: parse every log, grade, flatten, compare with `golden/`, then the 6 extraction checks. It also checks that the regenerated files equal the spike's copies after path normalisation (cited logs become `logs/<run>/<file>`).
- CLI `el01 regress`, `el01 grade-spike` (writes `audits/matchdg/`). Tests: verdicts hash, legacy vs 2.1 equivalence, regression and traceability.
- Acceptance → PROGRESS.md → commit.

Built: `el01/config.py`, `el01/grade/{legacy/verdicts_v2.py, rules.py, parse.py, effects.py}`, `el01/grade/spike/{matchdg, rules_adapter, table1, table11, f7, compare, regress}.py`, `el01/diff/settings_diff.py`, `el01/cli.py`; tests `test_verdicts_hash.py`, `test_rules_equivalence.py`, `test_regression.py` (28 tests, about 7 s). `el01 grade-spike` wrote `audits/matchdg/` (15 per-run metrics + epochs.json, 4 grades files; byte-identical on rerun).

Acceptance output (trimmed):
```
$ uv run el01 regress --spike inputs/spike-matchdg
126 graded items (73 verdicts) + 6 extraction checks: 0 mismatches
20 regenerated files vs the spike's copies (cited logs normalised to logs/<run>/<file>): 0 mismatches
exit=0
$ (normalised comparison of audits/matchdg/ with inputs/spike-matchdg/metrics/)
grades.json: equal   grades_lenet_confirm.json: equal   grades_f7.json: equal   grades_lenet.json: equal
$ uv run el01 grade-spike   (headlines, all as in Appendix B)
table11_confirm: cells + averages {Inconclusive: 15, Reproduced: 13}; matchdg_vs_erm Reproduced
Table 1 h1 (select by val. loss) moves PerfMatch by -25.82 [-34.4, -17.24], Holm p 0.00141, survives
F7 six-domain average effect -0.04 (95% CI -0.41 to 0.34), excludes 0: False
$ uv run pytest -q
28 passed in 6.80s
$ git status --short inputs   -> (empty)
```
Checks that the regression is not vacuous: a +0.01 change to one per-seed value flips 3 golden items; a wrong cited run and an int/float swap are both reported by the file check.

## Phase 2: audit workspace, environment builder, runner ✓

Plan (approved 2026-10-04, defaults on h5py / Python choice / resume):
- `audits/matchdg/audit.yaml` (Appendix C + `env:` entry points and `smoke:` command from `run_table1.sh`); `AuditConfig` in `el01/config.py`; `Paths` gains workspace dirs.
- `el01/run/worktrees.py` (one detached worktree per ref under `workspace/worktrees/<audit>/`), `el01/run/runner.py` (parallel jobs up to the budget, `OMP_NUM_THREADS=1`, `commit.txt`, `progress.txt` + `ALL_DONE`, per-job status with start/end UTC, resume skips exit-0 jobs). Test: dummy command, 3 jobs.
- `el01/env/imports.py` (AST import scan from the entry points; tiers core / lazy / guarded) and `el01/env/builder.py` (ladder: shipped results → Dockerfile (report only) → uv env; Python from core-framework pin or commit date − 6 months; `UV_EXCLUDE_NEWER` = commit + 24 h; lazy packages kept only if they leave core versions unchanged; wheel-gap bump logged, e.g. h5py 3.6.0 → 3.7.0; wheels only). CLI `el01 env build`, `el01 env compare`.
- `el01/run/classify.py` (last traceback → missing path / no GPU / missing attribute or API / missing data / other, with the line of the path literal) and `el01/run/shipped.py`. CLI `el01 run-shipped`.
- Acceptance → DECISIONS.md (env differences vs `requirements-pinned.txt`) → PROGRESS.md → commit `phase 2: env builder and runner`.

Built: `audits/matchdg/audit.yaml`, `AuditConfig` + workspace paths in `el01/config.py`, `el01/ingest/repo.py`, `el01/run/{worktrees, runner, classify, shipped}.py`, `el01/env/{imports, builder}.py`; CLI `el01 env build <id> [--rebuild]`, `el01 env compare <id> <file>`, `el01 run-shipped <id>`; tests `test_runner.py` (5), `test_env.py` (20), `test_classify.py` (12). Committed evidence: `audits/matchdg/env.json`, `audits/matchdg/run_as_shipped.json`. Env build: about 1.5 min from cold, 548 MB in `workspace/envs/matchdg/`.

Acceptance output (trimmed):
```
$ uv run el01 env build matchdg
python 3.9.25 (newest CPython minor released by 2021-09-20 (commit date 2022-03-20 - 6 months): 3.9.0 on 2020-10-05)
commit 3eee173 (2022-03-20T15:15:32-04:00), UV_EXCLUDE_NEWER=2022-03-21T19:15:32Z
added (imported, not in requirements): pillow, absl-py, matplotlib, more-itertools, opacus, scipy, seaborn
listed but not imported (not installed): advertorch
guarded imports (not installed): cifar10_models, pycuda
lazy dropped: mia: mia==0.1.2 has no wheel for CPython 3.9.25 on Darwin arm64, and no later release has one either
lazy dropped: tensorflow-gpu==1.15.2: ... has no wheels with a matching Python ABI tag (e.g., `cp39`) ...
wheel gap: h5py==3.6.0 has no wheel for CPython 3.9.25 on Darwin arm64; 3.7.0 is the earliest release with one (released 2022-05-24)
key versions: torch 1.11.0, numpy 1.22.3, scipy 1.8.0, opacus 1.1.0
$ workspace/envs/matchdg/bin/python -c "import sys,torch,numpy; ..."
3.9.25 1.11.0 1.22.3
$ uv run el01 env compare matchdg inputs/spike-matchdg/requirements-pinned.txt
same version: 26; different version: 2; only ours: 8; only theirs: 0
  changed  h5py: ours 3.7.0, theirs 3.6.0
  changed  opacus: ours 1.1.0, theirs 0.15.0
  ours     absl-py, imageio, networkx, pywavelets, scikit-image, tifffile, torchxrayvision, tqdm   (listed in DECISIONS.md)
$ uv run el01 run-shipped matchdg
data step: python data_gen_syn.py: done (exit 0) in 5s -> runs/shipped_data/datagen.log
run as shipped: python train.py --dataset slab ... --n_runs 1 --method_name erm_match --match_case 0.0 --penalty_ws 0.0
  failed (exit 1) in 1s -> runs/shipped/train_erm.log
first failure: missing path (FileNotFoundError on an absolute path outside the worktree and the workspace)
  raised at utils/slab_data.py:78 (runs/shipped/train_erm.log:15)
  path literal at utils/slab_data.py:75: '/home/t-dimaha/RobustDG/robustdg/data/datasets/slab/'
  a file with that name exists in the worktree: data/datasets/slab/total_slabs_7_slab_noise_0.1_spur_corr_0.0_case_train_seed_0.pickle
  location: utils/slab_data.py:75  (exception at runs/shipped/train_erm.log:17)
$ uv run pytest -q          (includes the runner test: dummy command, 3 jobs in parallel)
65 passed in 11.36s
$ uv run el01 regress
126 graded items (73 verdicts) + 6 extraction checks: 0 mismatches
20 regenerated files vs the spike's copies (cited logs normalised to logs/<run>/<file>): 0 mismatches
$ git status --short inputs   -> (empty)
```
The spike's own shipped-run log (`logs/01_train_erm_shipped.log`) classifies the same way (`test_classify.py`). The first fresh run took 17 s (cold start of the new env), the rerun 1 s.

## Phase 3: repair agent ✓

Plan (approved 2026-10-04, with live calls and the `test.py` eval line added to the smoke command):
- `audit.yaml` `smoke.eval` (the `test.py --test_metric per_domain_acc --acc_data_case train` line of `run_table1.sh`), so `test.py:183` is exercised.
- `el01/llm/{backend,cache}.py`: replay (default) / claude_cli / anthropic_api; cache key = sha256(agent, prompt, schema, model, input hashes); every call logged to `audits/<id>/llm_usage.jsonl`. `.cache/llm/` is tracked so replay works from a clean checkout. One probe call checks `structured_output`, MCP tools and user plugins.
- `el01/repair/policy.py`: code decides the class from the changed lines only (numbers, data-generation files and words, model/loss/optimizer/metric/selection words → hypothesis; otherwise env/compat from the failure class). The LLM's class is advisory.
- `el01/run/trace.py` + `el01/repair/inertness.py` (port of `trace_opacus.py`): calls into the libraries the patch names, and hits on statements the patch put under a new condition, during a 5-epoch run; with/without comparison when the code runs without the patch.
- `el01/repair/agent.py`, CLI `el01 repair <id> [--llm live]`: run → classify → (missing data domain → `HYPOTHESIS(F1)` on `el01/h-F1`) or (agent edits → unified diff → `git apply --check` → policy → `REPAIR(env|compat)` on `el01/repair` → inertness) → re-run; stop at success or 5 repair attempts (Not runnable).
- `el01/repair/compare.py`, CLI `el01 repair-compare <id> --ours … --hypothesis …`: equivalence of each commit with ours, and smoke accuracy on both branches on this laptop.
- Tests: policy over every REPAIR/HYPOTHESIS commit in the bundle, backend (fake `claude` script), loop (synthetic repo + scripted agent), trace (toy library).
- Acceptance (live, then replay at zero quota) → DECISIONS.md → PROGRESS.md → commit `phase 3: repair agent`.

Built: `el01/llm/{backend,cache}.py`, `el01/llm/prompts/{repair,missing_domain}.md`, `el01/llm/schemas/repair.json`, `el01/repair/{policy,agent,inertness,compare}.py`, `el01/run/trace.py` (port of `trace_opacus.py`), `el01/run/shims/fork/sitecustomize.py`, `ingest/repo.py` (`snapshot`, `tree_id`), `Smoke.eval`; CLI `el01 repair <id> [--llm live] [--restart] [--max-attempts N]`, `el01 repair-compare <id> --ours … --hypothesis … --test-domain …`; tests `test_policy.py` (9), `test_llm_backend.py` (5), `test_repair_loop.py` (8, synthetic repo + scripted agent), `test_trace.py` (4). Committed evidence: `audits/matchdg/repair.json` (the replayed run), `audits/matchdg/repair/` (patches, prompts, answers, `inertness_<sha>.json`, `compare.json`, `live_run.json` = the live run it replays), `audits/matchdg/llm_usage.jsonl`, `.cache/llm/repair/` (14 recorded calls).

Three live runs (16 live calls including 2 CLI probes, $0.65 in total; one clean pass costs about $0.20):
1. Repairs 1–3 and h0 as in the spike (path fix byte-identical to 9b4a263), then the new eval step failed on macOS: DataLoader worker under `spawn` re-imports `test.py`, which has no `__main__` guard (`runs/repair/attempt_05/eval_erm.log`). The agent proposed `num_workers=0` twice; the policy rejected both (numeric literal) → *Not runnable* after 5 attempts. Fixed in the environment, not the code: the runner uses Linux's `fork` on macOS (DECISIONS.md). Also fixed: prompts carried commit shas and pids, so replay could never hit the cache.
2. Ran to the end, but the CPU-fallback repair also patched `misc_scripts/logit_plot_slab.py` and `test_slab.py` (the prompt said "other entry points or modules"). Fixed: code rejects any repair outside the run path (entry points + the modules they import); the prompt says the same.
3. Passed (below). The replay re-creates the same four patches byte for byte with 0 cache misses.

Acceptance output (trimmed):
```
$ uv run el01 repair matchdg --llm live --restart
run 1 at 3eee173: missing path at utils/slab_data.py:75 (runs/repair/attempt_01/train_erm.log:17) -> REPAIR(env)
run 2: missing data at utils/slab_data.py:75 (attempt_02/train_erm.log:41)
  missing data domain: spur_corr = 1.0 (generated: 0, 0.1, 0.2, 0.9) -> hypothesis branch, not a repair -> el01/h-F1
run 3: no GPU at algorithms/algo.py:170 (attempt_03/train_erm.log:60) -> REPAIR(env) (test.py:183, train.py:169)
run 4: missing attribute or API at algorithms/algo.py:276 (attempt_04/train_erm.log:59) -> REPAIR(compat) (algorithms/algo.py:276)
run 5: runs: every smoke step exited 0 (datagen, train_erm, eval_erm)
  inertness: 0 calls into opacus and 0 executions of algorithms/algo.py:277 during a 5-epoch run (runs/repair/inertness_<sha>/trace/trace.log:85)
verdict: runs; agent calls 4 (cache hits 1, misses 3), repair attempts 3
$ uv run el01 repair matchdg --restart          (replay, the default)
verdict: runs; runs 5, agent calls 4 (cache hits 4, misses 0); llm_usage.jsonl: 4 lines "replay hit"
01-repair-env.patch, 02-repair-env.patch, 03-repair-compat.patch, F1-hypothesis.patch: byte-identical to the live run's
$ git log --format=%s el01/repair          -> REPAIR(compat), REPAIR(env), REPAIR(env), then 3eee173's history (exactly 3)
$ uv run el01 repair-compare matchdg --ours 9b4a263 --ours 3f08ff7 --ours 45e7771 --hypothesis 7dde854 --test-domain 0.9
repair commits: agent 3, ours 3 (equal)
  9b4a263 ~ agent REPAIR(env)     identical:  utils/slab_data.py:75
  3f08ff7 ~ agent REPAIR(env)     same lines: test.py:183, train.py:169  (agent writes the fallback inside torch.device(...))
  45e7771 ~ agent REPAIR(compat)  identical:  algorithms/algo.py:276
  7dde854 ~ agent HYPOTHESIS(F1)  identical:  data_gen_syn.py:42
smoke final (el01/h-F1 vs 7dde854, test domain 1.0): both ran; metric lines identical (503 vs 503)
  Final Test Accuracy (Source Validation) 60.1 / (Target Validation) 64.1 (train_erm.log:651-652); Per Domain Acc 100.0 / 96.6 (eval_erm.log:17), both
smoke repairs_test_0.9 (el01/repair vs 45e7771): both ran; metric lines identical (503 vs 503); 64.1 / 65.8; 100.0 / 95.8
pass
$ uv run pytest -q        -> 90 passed in 29.23s
$ uv run el01 regress     -> 126 graded items (73 verdicts) + 6 extraction checks: 0 mismatches; 20 regenerated files: 0 mismatches
$ git status --short inputs   -> (empty)
```
The smoke accuracies on this laptop (60.1 / 64.1) equal the spike's own `logs/04_train_erm_1seed.log:651-652`, run on Linux.


## Phase 4: claim cards and the claim-to-command linker ✓

Plan (approved 2026-10-04, dry runs on `el01/h-F1`, network for the MNIST data step only):
- `el01/ingest/pdf_text.py` (pypdf → text with `[page N]` markers, verbatim quote lookup).
- `el01/extract/claims.py`: `paper_extractor` agent (tool-less, both documents' text in the prompt, one call per target table). Code verifies every number: the verbatim header and row lines must be on the cited page, and code's own parse of the row line (column count, value at the column) must equal the agent's value; role and provenance need a verbatim quote. → `audits/<id>/claims.json`.
- `el01/link/argspec.py`: the scripts' real argparse actions, captured in the audited env (`parse_args` patched to dump and exit); flag validation and normalised argument dicts.
- `el01/link/parser_spec.py`: generic line-numbered parser (per-run blocks keeping the last match, or whole log with a key filter; expected count per run).
- `el01/link/linker.py`: `linker` agent (claim cards, README, `reproduce_scripts/`, `--help` of the scripts they run; read-only tools on a snapshot of the commit). Code validates flags, then dry runs (`--epochs 1 --n_runs 1`) on `el01/h-F1`, then the parser spec on the 1-epoch logs. → `audits/<id>/links.json`.
- `el01/link/spike.py`, CLI `el01 link-check <id>`: cards vs `golden/claims.json`; commands vs `run_table1.sh` / `run_matchdg_lenet.sh` as normalised argument dicts; parser specs vs `parse_train` / `parse_eval` on all spike logs.
- CLI `el01 claims`, `el01 link`, `el01 link-check`; tests for pdf text, card validation, argspec, parser spec, replay.
- Acceptance (live, then replay at zero quota) → DECISIONS.md → PROGRESS.md → commit `phase 4: claim cards and linker`.

Built: `el01/ingest/pdf_text.py` (page text, quote lookup with optional line-end hyphens, `table_span`), `el01/extract/claims.py`, `el01/link/{argspec,parser_spec,linker,spike}.py`, prompts `paper_extractor.md`, `linker.md`, `linker_feedback.md`, schemas `claims.json`, `links.json`; `LinkSpec` (audit.yaml `link:`), runner `Job.network`; CLI `el01 claims <id>`, `el01 link <id> [--no-dry-run]`, `el01 link-check <id>` (all `[--llm live]` where they call agents); tests `test_pdf_text.py` (6), `test_claims.py` (9), `test_argspec.py` (3), `test_parser_spec.py` (3), `test_link.py` (5, a toy two-phase repo through the real probe, dry runs, ladder and feedback), `test_link_replay.py` (2). Committed evidence: `audits/matchdg/{claims,links,link_check}.json`, `audits/matchdg/claims/`, `audits/matchdg/link/` (prompts and answers), `.cache/llm/{paper_extractor,linker}/`.

Added during the build (each in DECISIONS.md): rows must lie between the table's caption and the next caption (Table 11 and 12 share page 12, header and an ERM row); supporting quotes count on the page code finds them; commands judged by the scripts' own argparse (robustdg's `--help` crashes; `--dataset` is an abbreviation of `--dataset_name`); the linker also reads the paper pages that mention the table and prefers per-run values; a rejected table gets a second linker call with code's findings; dry runs start clean and run one chain at a time.

Live calls: 7, $2.76 (above the ≤ $2 estimate in the plan: two prompt revisions). Extractor: 2 calls ($0.60), cards right first time; code first verified 72/97 because of its own quote matching (fixed), then 97/97 from the same recorded answers. Linker: (1) 2 calls ($0.78): commands right, but parsers read train.py's summary line and the MNIST data step took the README's ResNet `--subset_size 2000` → prompt revised (per-run values; paper pages); (2) 2 calls ($0.92): Table 11 valid (1000 from the paper, per-run parsers); Table 1 had no data step ("generated in memory"), caught by the clean dry run (FileNotFoundError, `utils/slab_data.py:78`); (3) 1 call ($0.46) answering code's findings added `python data_gen_syn.py` → all valid. The first run's 2 answers stay in the cache, unused.

Acceptance output (trimmed):
```
$ uv run el01 claims matchdg            (replay)
  Table 1 (main p.4): 9 rows x 3 columns, 27/27 cells verified; 1 relative/trend claims (1 verified); call: cache hit
  Table 11 (supplement p.12): 10 rows x 7 columns, 70/70 cells verified; 1 relative/trend claims (1 verified); call: cache hit
97/97 cells verified, 2 relative/trend claims; agent calls 2 (cache hits 2), recorded cost $0.5959
  Table 1: baseline: ERM, DANN, MMD, CORAL, RandMatch, CDANN, C-MMD, C-CORAL; oracle: PerfMatch
  Suppl. Table 11: baseline: ERM, CCSA (cited), D-MTAE (cited), LabelGrad (cited), DAN (cited), CrossGrad (cited), DIV A (cited), RandMatch; method: MatchDG; oracle: PerfMatch
$ uv run el01 link matchdg              (replay; dry runs from a clean worktree at el01/h-F1, about 7 min)
  data step python data/data_gen_mnist.py --dataset rot_mnist --model lenet --img_h 32 --img_w 32 --subset_size 1000: done (exit 0) in 15s
  round 1, Table 1: linked 27, derived 0, unlinked entries 0; valid 0; REJECTED by code   (FileNotFoundError: data/datasets/slab/…pickle)
  round 1, Suppl. Table 11: linked 24, derived 4, unlinked entries 42; valid 28
Table 1: linker, call 2 (replay)
  data step python data_gen_syn.py: done (exit 0) in 1s
  round 2, Table 1: linked 27, derived 0, unlinked entries 0; valid 27
  round 2, Suppl. Table 11: linked 24, derived 4, unlinked entries 42; valid 28
agent calls 3 (cache hits 3), recorded cost $1.3853; every linked cell valid: True
  (commands, validity and the dry runs' parsed values and line numbers equal the live run's)
$ uv run el01 link-check matchdg
Table 1: 9/9 target cells = golden; PerfMatch role: oracle
Table 11: 24/24 cells + 4/4 averages = golden; PerfMatch role: oracle
commands: Table 1 9/9 rows (train + eval), Table 11 24/24 cells equal as normalised argument dicts (ignored: mnist_seed, n_runs; 0 steps differ only there)
parser specs: 682 values in 106 spike logs; 0 mismatches with parse_runs
   (Table 1 Target 340 values in 34 logs and Table 11 162 in 54: parse_train run, value and line; Table 1 Source 180 per-run values in 18 logs: mean = parse_eval's)
data step Table 1: python data_gen_syn.py (spike: python data_gen_syn.py, scripts/run_table1_rest.sh:11): equal
data step Suppl. Table 11: python data/data_gen_mnist.py … --subset_size 1000; 54 split shapes vs the spike's 54 (logs/matchdg_lenet/datagen.log): equal
dry runs: Table 1: 27/27 linked cells ran and parsed; Suppl. Table 11: 24/24 linked cells ran and parsed, 4/4 derived cells valid
blind extraction runs (Table 1 cells equal): paper_run1 27/27, paper_run2 27/27
pass
$ uv run pytest -q        -> 118 passed in 27.79s
$ uv run el01 regress     -> 126 graded items (73 verdicts) + 6 extraction checks: 0 mismatches; 20 regenerated files: 0 mismatches
$ git status --short inputs   -> (empty)
```
Checks that the acceptance is not vacuous (in-memory mutations): `--penalty_ws 0.5` on PerfMatch → Table 1 8/9; `--ctr_match_interrupt 10` on MatchDG/45 → Table 11 23/24; a run-start regex that skips odd runs → 9 parser mismatches; golden MatchDG/30 mean 99.8 → 1 card mismatch; `--n_runs 10` alone → reported, not failed.

## Phase 5: settings extraction (schema v2), the diff, and the data-pipeline test ✓

Plan (approved 2026-10-04: F1–F3 must be found in all 4 paper × code pairings; live spend capped at about $10; plus Builder's two additions below):
- `el01/extract/schema_v2.json`: the spike's 20 keys (free-form values, `{method: value}`) plus 5 data-pipeline keys as lists of entries with enumerated fields (`data.preprocessing.resize`, `.normalization`, `data.augmentation`, `data.domain_transform`, `train.model_selection_data`). Evidence is structured: paper `{doc, page, quote}`, code `{file, lines, code}`.
- `el01/extract/settings.py`: `paper_extractor` (tool-less, the PDFs' text) and `code_extractor` (Read/Grep/Glob on a `git archive` snapshot of the audited commit; told only the table's name, caption, columns and the paper's own row labels, never `links.json`). Two runs per side per table (replicate number in the cache inputs, same prompt). Code checks every quote and every `file:lines` citation; agreement between runs per key → `audits/<id>/settings.json`.
- `el01/diff/settings_diff.py`: `diff_v2` = the unchanged v1 `diff` + v2 rules (paper omission / difference on the 5 new keys, `optim.name`, `eval.aggregation`); an augmentation omission carries `reaches` (the selection steps that read the augmented copy) → `audits/<id>/settings_diff.json`. v1 behaviour is untouched, so `el01 regress` stays at 0.
- `el01/diff/spike.py`, CLI `el01 settings <id> [--llm live]`, `el01 settings-check <id>`: Table 1 vs `golden/findings.json` (F1–F3 required in 4/4 pairings, F4/F5 should, F6 bonus); Table 11: the F7 code path (augmentation lines and MatchDG's first-phase selection data, verified citations) and an F7 paper omission in every pairing → `audits/matchdg/extraction_score.json`.
- Addition 1: `test_settings_prompts.py` fails if either extractor prompt (templates, schema text, rendered and recorded prompts, minus the paper's own text) mentions `flip`, `data_gen_mnist`, `match_eval` or an F-number. Only the acceptance checker names them. F7 is found *after* schema v2 added the data-pipeline keys: not blind.
- Addition 2: `settings-check` lists every finding beyond F1–F7 as "new, unverified", including the Phase 4 leads (test.py:399 standard errors; Rotated MNIST data size).
- Live run (8 calls), replay (0 misses, same outputs), pytest, regress → DECISIONS.md → PROGRESS.md → commit `phase 5: settings diff v2`.

Built: `el01/extract/{schema_v2.json, settings.py}`, `el01/diff/settings_diff.py` (`diff_v2` added; v1 untouched), `el01/diff/spike.py` (checker), prompts `paper_extractor_settings.md`, `code_extractor.md`; CLI `el01 settings <id> [--llm live] [--runs 2] [--jobs 4]`, `el01 settings-check <id>`; tests `test_settings_diff_v2.py` (5), `test_settings_extract.py` (4), `test_settings_prompts.py` (3), `test_settings_check.py` (4), `test_settings_replay.py` (1). Committed evidence: `audits/matchdg/{settings,settings_diff,extraction_score}.json`, `audits/matchdg/settings/<table>/{paper,code}_run{1,2}.{prompt.md,answer.json}`, `.cache/llm/{paper_extractor,code_extractor}/` (16 settings calls).

Live calls: 16, $6.23 (cap $10). Paper ≈ $0.32 each (2–4 turns), code ≈ $0.46 each (15–30 turns, 95–123 s). (1) 8 calls, $3.15: F2–F7 in 4/4, **F1 in 2/4**: `code_run2` put a note inside a value (`{"code": [0.0, 0.10, 0.20, 0.90], "note": "target 1.0 is not generated …"}`) because the shared key description read "code: …; paper: …"; the spike's rule reads every number in a value, so "1.0" counted as available. Fixed in the schema and prompts (one description per side; `value` holds the value only), not in the diff (DECISIONS.md). (2) 8 calls, $3.09: pass. The first run's answers stay in the cache, unused.

**F7 is not a blind result.** It was found after schema v2 added the data-pipeline keys (augmentation, its uses, the data each selection step reads), which exist because SciCoQA row 67 showed the v1 schema could not express it. The prompts never name the file, the transform or any finding (`test_settings_prompts.py`); the result is that, given those keys, both code runs trace the path the hand audit traced. F1–F6 are scored against the spike's hand audit; the spike's blind v1 run had already found F1–F5 (F6 in 1 of 2 code runs).

Acceptance output (trimmed):
```
$ uv run el01 settings matchdg --llm live          (second live run)
  Table 1 code_run1: evidence items 48/49 verified ... Suppl. Table 11 code_run1: 57/57 ... (8 runs; paper runs 92/92, code runs 206/209)
Table 1: agreement between runs (25 keys): paper runs: same 15, differ 4, both null 6; code runs: same 14, differ 11
  findings per pairing: 23, 23, 23, 23; in every pairing 15, in some 16
Suppl. Table 11: agreement between runs (25 keys): paper runs: same 17, differ 1, one null 1, both null 6; code runs: same 16, differ 9
  findings per pairing: 17, 12, 17, 12; in every pairing 11, in some 7
agent calls 8 (cache hits 0), recorded cost $3.0874
$ uv run el01 settings matchdg                     (replay: 8 hits, 0 misses; settings_diff.json and settings/ byte-identical to the live run, settings.json differs only in cache/backend fields)
$ uv run el01 settings-check matchdg               (-> audits/matchdg/extraction_score.json)
Table 1:
  F1 [must]   target domain p = 1.0 never generated (code omission): found in 4/4 pairings, with verified evidence in 4/4
  F2 [must]   model selection: validation loss (paper) vs accuracy (code) (difference): 4/4, verified 4/4
  F3 [must]   optimizer: plain SGD vs momentum 0.9 + Nesterov (paper omission): 4/4, verified 4/4
  F4 [should] matching weight ramps from about 0 (paper omission): 4/4, verified 4/4
  F5 [should] DANN/CDANN learning rate 0.1 vs 0.01 (difference): 4/4, verified 4/4
  F6 [bonus]  hyperparameters ranked by target accuracy (difference): 4/4, verified 4/4
  pass: True
Suppl. Table 11:
  F3 4/4, F4 4/4 (both apply here too, spec section 3)
  F7 [must] flip after rotation in the augmented copy, reaching only MatchDG's first-phase checkpoint choice (paper omission): 4/4, verified 4/4; its selection step listed in 4/4
  code_run1: augmented copy (crop then flip, after rotation): yes [random_resized_crop, random_horizontal_flip]; MatchDG first-phase selection on it: yes (MatchDG, "phase 1 (matchdg_ctr)"); other methods selecting on it: 0
    citations verified: data/data_gen_mnist.py:34-35, 85 ok, data/mnist_loader_match_eval.py:38 ok, algorithms/match_dg.py:263-266 ok
  code_run2: same, citations verified: all 3 ok
  pass: True
new, unverified (14 beyond F1-F7; hypotheses for branches, not results):
  Table 1: data.domain_transform.kind (difference, wording: "label-dependent noise on linear feature" vs "noisy_linear_component"), 4 pairings
  Table 1: eval.aggregation (difference): Source columns mean_se_over_seeds (np.std/sqrt(n)) vs paper mean_sd_over_seeds, 2 + 2 pairings (method key spelt differently by the two code runs)
  Suppl. Table 11: data.preprocessing.normalization (paper omission): mean_std 0.1307 / 0.3081, 4 pairings
  Suppl. Table 11: data.preprocessing.resize (paper omission): 32 x 32 from 28 x 28, 4 pairings
  Suppl. Table 11: train.batch_size, train.epochs (difference): MatchDG phase 1 batch 512 / 50 epochs vs paper 16 / 100, 4 pairings
  Suppl. Table 11: optim.lr_schedule (paper omission): step halving every 25 epochs (lr = 0.01 / 2^(epoch // 25), optimizer rebuilt), 2 pairings per method spelling
  Suppl. Table 11: eval.aggregation (difference): the Average column is not computed by the repository, 2 pairings
  Suppl. Table 11: train.model_selection (difference): code_run1 gives it per method (MatchDG phase 1: highest TopK Perfect Match Score), 2 pairings
  new, unverified (lead from Phase 4): Table 1 Source spreads are standard errors (test.py:399): the diff lists it in 4/4 pairings; code citations verified: test.py:399, train.py:314
  new, unverified (lead from Phase 4): Rotated MNIST data size: the diff lists it in 0/4 pairings: paper and code both 1000; code citations verified include docs/notebooks/reproduce_results.ipynb:273
note: F7 found after schema v2 added the data-pipeline keys (spec section 3), so not a blind result
pass
$ uv run pytest -q        -> 135 passed in 28.26s
$ uv run el01 regress     -> 126 graded items (73 verdicts) + 6 extraction checks: 0 mismatches; 20 regenerated files: 0 mismatches
$ git status --short inputs   -> (empty)
```
Checks that the acceptance is not vacuous (`test_settings_check.py`, in-memory mutations of the recorded answers, re-diffed): the augmented selection entry removed from the code runs → F7 0/4, Table 11 fails; the paper's selection rule copied into the code runs → F2 missed, Table 1 fails; the `mnist_loader_match_eval.py` citations marked unverified → Table 11 fails. Three of 209 code citations failed verification in the second run (off by one line, or the code is on other lines); the values keep them with status `partly`/`unverified`.

Reading the new findings (none is a result; each is a branch candidate for Phase 6):
- **The test.py:399 lead, confirmed by the extractor** with verified citations: Table 1's Source columns are printed as standard errors, the Target column as a population sd (train.py:314). Both code runs found it; the prompt asks what spread is printed but names no file.
- MatchDG phase-1 batch 512 / 50 epochs: spec section 3 says the paper's Table 9 gives these (contrastive phase 50 epochs, batch 512), so these two are probably paper-side extraction gaps (both paper runs gave 16 / 100 for every method), not differences. Check before writing a branch.
- The lr schedule (halving every 25 epochs) and the 32 × 32 resize / mean-std normalisation of Rotated MNIST are omissions the paper's text does not cover (per both paper runs); the Table 1 domain-transform "difference" is wording only (`kind` compared as text).
- Table 11 `train.model_selection`: the spike's v1 rule compares the value as one string, so a per-method answer (code_run1) always differs from a single paper value; the content behind it is real (MatchDG's phase 1 selects by match score), and the same fact is F7's selection step. Kept as the spike's rule (regression).
- The first live run's code runs also listed train.py's "Target Validation" oracle print (selection on target test data) as a checkpoint entry; the second run's did not. Agreement between runs is a measurement, not a given.

## Phase 6: branch-patch writer and ablation runs (plan, approved 2026-10-04)

### Context
Phases 3–5 produced repairs (`el01/repair`), h0 (`el01/h-F1`) and a settings diff with numbered findings (`audits/matchdg/extraction_score.json`: F1–F6, F8 on Table 1; F3, F4, F7 on Suppl. Table 11). Phase 6 turns each numbered finding into one HYPOTHESIS branch, checks in code that the branch changes exactly that one setting, and measures each branch against the baseline with the spike's paired-by-seed effect + Holm logic. Pre-registration (rule 5) comes first. Step 0 after approval: copy this plan under a "Phase 6" heading in PROGRESS.md.

Measured while planning: on Phase 5's recorded answers, `diff_v2(code_run1, code_run2)` at the **same commit** lists 2 distinct settings for Table 1 (target domains; the target-validation print) and 3 for Table 11; `canon` differs on 8 and 7 of 25 keys. A literal "any difference = a changed setting" self-check would therefore reject most correct branches on extractor noise alone (question 2).

### Builder's answers (2026-10-04)
- **Baseline = h0 as is** (`el01/h-F1`, equivalent to 7dde854). The stream coupling stays recorded as a known second change: the training data differs from the shipped code's. The data-step check reports it for F1 and does not fail other branches on it. The writer writes no F1 branch.
- **Self-check is patch-attributed.** A diff_v2/canon difference counts as a changed setting only if either run's evidence for that key cites a line the patch touched (baseline lines mapped through the diff). The rest is listed as "extractor disagreement", not counted.
- **Live cap: $12.** Code stops before a call that would exceed it (running total from llm_usage.jsonl for Phase 6) and asks.
- **Interaction: report only.** The combined branch's paired effect + CI (in the Holm family, as the spike's h_combined), next to the sum of the two single effects. No "interact" wording and no new test; Lead decides on a rule later (noted in PROGRESS).

### Decisions taken from the code / rules (no question needed)
- **Branch set** = numbered findings only (no number → no branch; #6/#7 excluded by instruction): F2 → h1 + h1b (readings), F3 → h2, F4 → h4, F5 → h6, F6 (tuning criterion), F8 (Source spread sd vs se), F7 (Table 11, no flip). F1 is h0 itself (the baseline).
- **Setting identity** = the finding's key set from `extraction_score.json` (F3 = `optim.momentum` + `optim.nesterov` is one setting). Pass needs the changed keys ⊆ the finding's keys, and at least one of them.
- **Comments**: the writer may add no comments in the added lines. Code rejects them, so a `# AUDIT` comment cannot lead the self-check extractor. Bundle equivalence ignores comments.
- **Methods per branch** = the finding's methods ∩ the methods whose 1-epoch dry run executes a changed line (existing tracer `el01/run/trace.py --line`). This keeps out methods the patch never reaches. Those would have identical per-seed values, se = 0, and `effects.effect()` (the spike's code) returns p = 0.0 for them. That would make a false Holm survivor. The grader also refuses any se = 0 effect with a clear message rather than report it (a guard, not a statistics change; flagged for Lead).
- **F7 / Table 11**: written and self-checked now. Its run is its own pre-registered test (as in the spike's `grade_f7`), deferred to Phase 7 full mode. The exploratory Holm family here is Table 1.
- **F8** changes no Target number, so it is outside the effect family. Its branch is written and self-checked only.
- **Fresh seeds** (confirmation): `data_gen_syn.py` makes data seeds 0–9 only. An `AUDIT(harness)` commit from the writer in harness mode (seeds 0–19). Code verifies that the data files for seeds 0–9 stay byte-identical. Confirmation runs `--n_runs 20` and keeps runs 10–19, so train.py needs no change. Runs 0–9 must equal the exploratory runs (a determinism check).

### Build (small commits, pytest + `el01 regress` before each)
1. **`el01/grade/prereg.py`** (rule 5): `write(run_set)` → `audits/<id>/prereg/<run_set>.txt` + `.json` (tracked) and a copy in the run dir. It holds the sha256 of `legacy/verdicts_v2.py`, `rules.py`, `effects.py`, `ablation.py`, `parse.py`, `prereg.py`; the run plan (claims × seeds × branch → commit sha); the floor per metric from audit.yaml; and UTC time. `check(run_dir)` refuses: missing prereg, any hash mismatch, a run whose `commit.txt` is not in the plan. Commit before the runs start. Tests: missing / edited file / foreign commit / ok.
2. **branch_writer agent**: `el01/llm/prompts/branch_writer.md` (+ `_feedback.md`), `el01/llm/schemas/branch.json`, `el01/branch/writer.py`. Reuses `repair/agent.py` (`apply_edits`, `render_diff`, `_scratch`, `_commit_patch`, `outside_run_path`) and `backend.Request` with `AGENT_TOOLS` on a snapshot of the baseline (`ingest/repo.snapshot`). Input: the finding's key, paper value, code value, verified citations and paper quote. It is never told the F-number's spike branch. Output: `readings: [{label, paper_value, edits[]}]`; code writes one branch per reading, `el01/h-F<n>` or `el01/h-F<n>-<k>`. Commit `HYPOTHESIS(Fn): <key>: <paper value> instead of <code value>` (code value from the extraction; paper value per reading). The prompt is generic: "change only that setting; everything else, including random-number streams, stays as in the baseline". Prompt test as in Phase 5 (no F-numbers, no bundle names).
3. **Self-check**, `el01/branch/selfcheck.py`: `repo_and_snapshot(ref=branch)` + `code_request(..., run=1)` on the branch. The same call at the baseline branch (replicate 1), cached once per table. Changed settings = `diff_v2` both directions + `canon` per key, grouped by `setting_id`; attribution per question 2. Data-step check for branches that touch a data step (`links.json` data_steps): run it on baseline and branch; existing output files must be byte-identical. On fail: reject, re-ask the writer with code's findings, at most 2 retries, then "branch not written".
4. **Bundle equivalence** (read-only), `el01/branch/compare.py` on `repair/compare.diff_signature`: our `baseline..branch` diff vs the bundle's HYPOTHESIS commits squashed relative to 7dde854 (AUDIT(harness) excluded). Levels: identical / same lines / different. Behaviour: the bundle diff applied to our baseline in a scratch worktree vs our branch, 1-seed smoke on a reached method; metric lines identical or not. If the baseline is h0 as-is, it also reports per-seed agreement with the spike's own logs (reported only, never tuned).
5. **Ablation**: `el01/branch/ablate.py`, grader `el01/grade/ablation.py`. The grader ports `effect`/`holm`/ALPHA/`detectable`/selection summary from `grade/spike/table1.py` unchanged, but is driven by the prereg plan instead of constants. Commands come from `links.json` (train step; `--n_runs` = audit.yaml seeds). Runner: one worktree per branch, data step per worktree; a new `Job.group` (method_name + train domains) is serialised within a worktree, and other groups/branches run in parallel up to 8. Logs: `runs/ablation/<branch>/train_<method>.log`; `parse_run_dir` / `parse_epochs_all` keep (log, line) on every number.
6. **Order of run sets**, each pre-registered and committed first: (a) exploratory: baseline + all Table 1 branches, seeds 0–9 → grade → Holm over the family. (b) Confirmation: the largest Holm-surviving |effect| (code picks it, the combined branch excluded) on seeds 10–19, that branch and method vs baseline. (c) Interaction: the top two branches cherry-picked into one (code, no LLM), on seeds 0–9; reported only (combined effect + CI next to the sum), no verdict.
7. **CLI**: `el01 branches <id> [--llm live] [--restart]`, `el01 ablate <id> --set {exploratory,confirm,interaction}`, `el01 branch-check <id>` (acceptance). Evidence: `audits/matchdg/branches.json`, `branches/` (prompts, answers, patches, selfcheck), `ablation/grades*.json`, `prereg/`.
8. Tests: writer loop on a synthetic repo with a scripted agent; self-check attribution (noise filtered, a two-setting patch rejected); prereg; ablation grader on the spike's own logs (it reproduces `grades.json` effects for the shared branches); replay test.

### LLM budget (estimate; cap asked before any live call)
- Writer ≈ 7 calls × ~$0.25 = $1.75 (F2–F8 + harness).
- Self-check extractor ≈ 10–11 × $0.43 = $4.5 (2 baselines + 8–9 branches).
- Retries ≈ 2–3 × $0.7 = $2.
- Expected **≈ $8**; worst case (every branch retried twice) ≈ $20. **Cap $12 (approved).** Every call is logged to `audits/matchdg/llm_usage.jsonl`.

### Verification (acceptance; trimmed output goes into PROGRESS.md)
- `el01 branch-check matchdg`: branches equivalent to h1, h1b, h2, h4, h6, each self-check pass.
- `el01 ablate matchdg --set exploratory`: h1 PerfMatch over 10 seeds: effect < 0, CI excludes 0, survives Holm (no expected value in code).
- Replay of `el01 branches` + self-check: 0 misses, $0; patches byte-identical.
- `uv run pytest -q`; `uv run el01 regress --spike inputs/spike-matchdg` 0 mismatches; `git status --short inputs` empty.
- Close: Phase 6 ✓, DECISIONS.md, commit `phase 6: branch writer and ablation`, 5-line summary.

## Notes for later phases

- **Product name (2026-10-04, Lead, team Axiom 3): ClaimTrace.** Phases 7 and 9 must use it: report title "ClaimTrace audit: <paper>", UI header "ClaimTrace". The package and the `el01` command stay; `claimtrace` is an alias for the same CLI.
- **Before the Phase 8 blind run (to-do, from Phase 5):** the paper extractor must get each supplement table as its own block, labelled with its caption. Build this in code (from `pdf_text`: the span from a `Table N.` caption to the next caption, as `table_span` does), not through prompt wording. Add an offline test that MatchDG's supplement Table 8 (p.9) and Table 9 (p.10) come out as separate blocks with their captions. Reason: in Phase 5 all four Table 11 paper runs took batch 16 / 100 epochs from Table 8 and ignored Table 9 (MatchDG Phase 1: 50 epochs, batch 512), giving false differences #6/#7, and a prompt-level table index did not help. Do not re-run MatchDG live for it; the Phase 8 paper's run is its first live use.
- Phase 6 (self-check): `el01/extract/settings.py` `repo_and_snapshot(paths, cfg, ref)` + `code_request(...)` re-run the code extractor on a branch snapshot; diff the branch's answer against a baseline code run with `diff_v2` (code vs code) and require exactly one changed key. Code runs disagree on wording for 9–11 of 25 keys even at the same commit (`agreement` in settings.json), so the self-check should compare canonical values (`settings.canon`) and run the baseline extractor at the baseline branch with the same replicate number, not compare raw text.
- Phase 6: F-numbers for branches come from `extraction_score.json` (the checker's mapping); new findings carry no number yet. Table 11's MatchDG batch/epochs "differences" need a look at the paper's Table 9 before a branch (above).
- Phase 7/8: a linker should read `docs/` notebooks as well as the README and `reproduce_scripts/` (robustdg's LeNet data command is only in `docs/notebooks/reproduce_results.ipynb:273`).
- Phase 8: settings extraction for a new paper is `el01 settings <id> --llm live` after `el01 claims`; about $0.8 per table per run pair at MatchDG's size (one paper call + one code call). The checker (`el01/diff/spike.py`) is MatchDG-only.

- Phase 5 (settings diff), from Phase 4: **Table 1's Source spreads are standard errors in the code.** `test.py:399` prints `np.std(x)/np.sqrt(n)` for `--test_metric per_domain_acc`, while the Table 1 caption says "Mean and standard deviation over 10 different seed values". The linker noticed it in its notes; I read the line. The Target column comes from train.py's per-run lines, where code computes the sd itself. A lead for the diff, not a finding yet.
- ~~Phase 5: no repository command makes LeNet-size Rotated MNIST~~ **Corrected in Phase 5:** the repository does give it, in the `# Table 11` cell of `docs/notebooks/reproduce_results.ipynb:273` (`python data/data_gen_mnist.py --dataset rot_mnist --model lenet --img_h 32 --img_w 32 --subset_size 1000`); both Phase 5 code-extractor runs cited that line (verified by code, and read by hand). The Phase 4 linker reads the README and `reproduce_scripts/` only, not `docs/notebooks/`, so it took 1000 from the paper: the same value, so `links.json` needs no change, but a later linker should read the notebooks too. Paper and repository agree on 1000; not a difference.
- Phase 6/7: **parallel runs in one robustdg worktree are unsafe.** mmd, coral, c-mmd and c-coral share one result directory and model file (the names ignore `gaussian`/`conditional`), and `train.py:202-203` creates that directory with an exists-then-makedirs race (Phase 4 replay: CORAL failed with FileExistsError when run beside its siblings). erm/rand/perf on Rotated MNIST share `results/rot_mnist/erm_match/…/train_[…]` per test domain too. Give each parallel job its own worktree, or serialise jobs that share `method_name` and train domains; the spike ran Table 1 methods one after another.
- Phase 7: `audits/<id>/links.json` holds, per claim cell, the commands (data steps per table), the parser spec and `values: per_run | aggregate`; all MatchDG cells are per_run. Real runs set `--n_runs` from audit.yaml `seeds` (the acceptance ignores `n_runs`). Derived cells (Table 11 Average) are the mean of the linked cells.
- Phase 8: probing a script's parser runs its module code up to `parse_args` (timeout 300 s); a script doing work before parsing would do it. A `--help` that crashes (robustdg's unescaped `%`) is handled.

- Phase 6 (and the report): **h0 (7dde854) changes more than the target domain.** `data_gen_syn.py` seeds numpy once per data seed and loops noise 0.0 before noise 0.1, so appending 1.0 to `spur_corr_list` shifts the random stream: all 120 `slab_noise 0.1` pickles (train/val/test, every spur value and seed; Table 1 uses noise 0.1) get different X/Y draws, while the 120 noise-0.0 files are unchanged; the shipped generator is otherwise deterministic (two runs: X and Y equal in 240/240). Same distribution, different samples. The branch self-check (spec section 6, "exactly one changed setting") should catch this kind of coupling; the live agent's first h0 answer tried to keep the stream (appending the 1.0 draws after all others) but its `old` text did not match the file. Builder/Lead to decide whether it matters for the spike's Table 1 baseline.
- Phase 6/7: the policy's number rule also fires on environment numbers such as DataLoader `num_workers` (first live run). With the fork shim the MatchDG commands no longer need such a change; if a later paper does, consider an explicit allowlist of process settings (`num_workers`, `pin_memory`) rather than loosening the number rule.
- Phase 7/9: `el01 repair` writes the job-screen material: `audits/<id>/repair.json` is rewritten after every run and agent call (runs, failures with log lines, calls, outcomes).
- Phase 3 used `audit.yaml` `smoke` (train + eval). The inertness trace runs in the audited env (opacus 1.1.0, not the spike's 0.15.0); the 5 opacus import names in `algo.py` that 1.1.0 lacks are listed as not pre-imported in `inertness_<sha>.json`.
- Phase 8: uv has no CPython 3.7 (see DECISIONS.md); `audit.yaml` `env.python` overrides the Python choice, `env.extra` adds packages.
- Phase 2+: `uv sync --extra api` installs `el01` (editable); run commands as `uv run el01 …`. Logs must be extracted to `workspace/spike/logs/` or the tests fail with that reason.
- Phase 6/7: rule 5's pre-registration check (`el01/grade/prereg.py`) is not built yet. The imported spike run sets are graded with the rules their own `PREREGISTERED.txt` hashed (legacy v2); Table 1's exploratory run sets have no pre-registration, as in the spike.
- Phase 7: the generic grader goes in `el01/grade/grade.py` on `rules.py` 2.1; reuse `el01/grade/parse.py`, `effects.py` and `spike/compare.py`, and the regression in `spike/regress.py` stays the gate.
- Phase 2: default jobs = 8, but 6 of the 10 cores are efficiency cores, so per-job times will not compare one-to-one with the spike's 4-vCPU numbers.

## Phase 5 precision pass (2026-10-04)

Builder asked for four changes, then a re-run of `el01 settings-check matchdg`, a check that #1, #6, #7 and #14 (the numbering of the 14 "new, unverified" lines at commit 1fa014d) are gone while the known findings remain, and a precision log. The four changes:
1. compare the domain-transform `kind` semantically;
2. de-duplicate findings across runs;
3. drop v1's `train.model_selection` string compare;
4. make the paper extractor read the supplement's hyperparameter tables.

Then the team added **F8** (DECISIONS.md: team-verified, outside golden/, found after the spike, not blind): Table 1's Source columns are printed by `test.py:399` as standard errors, while the caption says standard deviation. Target is graded from `train.py:314-315`'s sd, so no verdict changes, and `golden/verdicts.json` is untouched.

Built:
- `kind` is now a vocabulary of mechanisms in `schema_v2.json`. The agents choose the value; code compares it.
- `diff_v2` uses per-method rule 3 and per-method enumerated heads, and skips `other:`.
- `setting_id` grouping and `precision()` are in `el01/diff/spike.py`; F8 has its own matcher.
- The paper prompt lists every `Table N.` line code finds and asks for per-method and per-phase values from those tables.
- Tests: 141 pass. Regress: 0 mismatches.

Live: one 8-call run ($3.31). An earlier attempt was stopped by the session limit after one call; that call was cached and reused.

**Phase 5 total: 24 settings calls, $9.54** (cap about $10).

Results, from `el01 settings-check matchdg`:

| Item | Before (1fa014d) | Now | How |
|---|---|---|---|
| #1 domain-transform kind (wording) | listed | **gone** | all 4 runs chose `feature_noise` (Table 1) and `rotation` (Table 11), so the kinds are compared and agree |
| #14 Table 11 `train.model_selection` (string compare) | listed | **gone** | per method; MatchDG's `other: phase 1 …` is skipped, and its substance is F7's selection step |
| #2/#3, #9–#13 (same setting, two spellings) | 2 + 5 lines | 1 + 1 | grouped by setting |
| #6 / #7 MatchDG phase-1 batch 512 / 50 epochs | listed | **still listed** | both new paper runs again quoted supp. Table 8 ("Batch Size 16 [16]", "Total Epochs - 100") and not Table 9 (p.10), despite the table index. **Change (4) did not work.** These two remain false differences from paper-side misses. |
| F1–F5 (Table 1) | 4/4 | 4/4 verified | |
| F6 (bonus) | 4/4 | **2/4** | Table 1 `code_run2` did not trace the tuning script |
| F7 (Table 11) | 4/4 | 4/4, both code runs trace the path | **only after two checker changes, made after seeing a failure** (below) |
| F8 (team-verified) | (lead) | 2/4 | the same `code_run2` did not trace `test.py`'s per-domain print; `code_run1` cites `test.py:399` |
| New: `train.model_selection_data` checkpoint on target test data | not listed | listed (Tables 1 and 11, 2/4) | `train.py:303-304` prints a "Target Validation" oracle max; real code, new to this run's code extractors |

**The two checker changes made after seeing the failure** (both in DECISIONS.md):
- With the checker as it stood, Table 11 failed: `code_run1` showed 26/39 evidence items verified and 2 of 3 F7 citations missing.
- (a) Citations like `"lines": "11, 30-35"` were rejected on format alone. Code now accepts a list of ranges and still requires the quoted pieces, in order, on exactly those lines. Result: 38/39 verified.
- (b) `code_run1` cited `match_dg.py:263-266`, verified, under `train.model_selection` (how the checkpoint is chosen) rather than `train.model_selection_data`. The F7 citation search now covers both keys plus `data.augmentation`.
- Builder may prefer to count Table 11 as failing on the original checker.

**Precision (lower bound):** distinct settings (key, kind, field, use) over the 4 pairings of each table. "Known" means it matches a known finding of that table. Every new, unverified setting counts as false.

| Stage | Known = F1–F7 | Known = F1–F8 |
|---|---|---|
| Before (1fa014d: v1 rule 3, old answers) | 12/21 (0.571) | 13/21 (0.619) |
| New rules, old answers (no LLM) | 12/19 (0.632) | 13/19 (0.684) |
| New rules, new answers (now) | Table 1 7/9, Table 11 5/12: **12/21 (0.571)** | Table 1 8/9, Table 11 5/12: **13/21 (0.619)** |

- The rules removed #1 and #14.
- The new answers added one setting the old answers did not have: the target-validation checkpoint entry, in both tables. #6 and #7 remain.
- Read by hand (not scored), the 8 remaining new settings are:
  - #6 and #7: paper-extractor misses, so false;
  - the target-validation oracle print: real code, but no single setting the paper describes;
  - Table 11 normalization, resize, lr schedule: real code facts the paper text does not mention; searching the paper text for "schedul", "resiz" and "normaliz" finds nothing;
  - Table 11 "Average" not computed by the repository: true, and probably harmless.

Open:
- (4) needs another approach. Either a paper prompt that tells the agent to prefer a per-method or per-phase table over a general one, or code that passes the caption-matched tables' text as a separate block. Both need a paper-side re-run (4 calls, about $1.3), which goes over the $10 cap: ask Builder first.
- Agreement between runs dropped on recall: one code run found neither F6 nor F8.

Follow-up (Builder, 2026-10-04): #6/#7 stay as recorded paper-extractor misses, and Phase 5 makes no more live calls. The "checkpoint reads target test data" item is a **false alarm** (team-verified; DECISIONS.md): `train.py:303/315` only print a target-validation max, while the checkpoint and the reported numbers use source validation. The checker labels it so and counts it as false. Precision is unchanged: **12/21 (F1–F7), 13/21 (F1–F8)**. Of the remaining distinct settings, 2 are false alarms and 7 (F1–F7) or 6 (F1–F8) are new and unverified.

LLM spend so far, from `audits/matchdg/llm_usage.jsonl`:
- It covers live (cache-miss) calls only. Replays cost nothing.
- MatchDG is the only audit so far, so this is all of it. Phases 0–2 made no LLM calls.
- Calls stopped by the session limit returned no answer and are not logged.
- `total_cost_usd` is the CLI's reported cost; on the Pro plan it is a quota measure, not a bill.
- My own build sessions are not in this log.
```
Phase 3 (repair agent + 2 CLI probes)    16 calls  $ 0.6535  input   375,784  output   8,656
Phase 4 (claim cards + linker)            7 calls  $ 2.7628  input 1,548,193  output  80,527
Phase 5 (settings extraction)            24 calls  $ 9.5445  input 6,068,517  output 255,624
Total, Phases 0-5 (0-2 made no LLM calls) 47 calls  $12.9608  input 7,992,494  output 344,807
```
