# ClaimTrace

Claim-level reproducibility audits for ML papers: every claim traced to its code, its run and the exact log line.

Built by team Axiom 3 for ELEVATE 1.0 (DJSCE), problem statement EL-01.

Build plan: `MASTER_PROMPT.md`. Status: `PROGRESS.md`.

## Commands (so far)

```
uv sync --extra api                                 # installs the el01 command (editable)
uv run el01 regress --spike inputs/spike-matchdg    # MatchDG regression gate: must report 0 mismatches
uv run el01 grade-spike                             # re-derive the MatchDG grades into audits/matchdg/
uv run el01 env build matchdg                       # date-pinned uv env for the repo at its commit (workspace/envs/matchdg)
uv run el01 env compare matchdg inputs/spike-matchdg/requirements-pinned.txt   # differences from another pinned list
uv run el01 run-shipped matchdg                     # run the smoke command as shipped; classify the first failure
uv run el01 repair matchdg [--llm live]             # repair loop: REPAIR(env|compat) commits, hypothesis branches
uv run el01 repair-compare matchdg --ours 9b4a263 --ours 3f08ff7 --ours 45e7771 --hypothesis 7dde854 --test-domain 0.9
uv run el01 claims matchdg [--llm live]             # claim cards from the paper's text; code checks every number
uv run el01 link matchdg [--llm live] [--no-dry-run]  # claim-to-command links, checked and dry-run by code
uv run el01 link-check matchdg                      # Phase 4 acceptance: cards, commands, parsers vs the spike
uv run pytest -q                                    # fast tests (needs workspace/spike/logs, see PROGRESS.md Phase 0)
```

LLM calls default to `--llm replay`: answers come only from the recorded calls in `.cache/llm/`, at zero quota.
`--llm live` spends quota (Claude Code CLI with your login, or the API if `ANTHROPIC_API_KEY` is set) and records each
call; every call is logged to `audits/<id>/llm_usage.jsonl`.
