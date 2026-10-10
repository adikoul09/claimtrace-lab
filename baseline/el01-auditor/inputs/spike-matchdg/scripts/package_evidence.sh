#!/usr/bin/env bash
# Builds the public evidence repo: the robustdg audit branches plus an orphan branch `audit-evidence` holding the
# report, raw logs, parsed metrics, grades, patches, scripts and the extraction test (the same files published with
# the blueprint page). Output: a git bundle that applies on top of a fork of microsoft/robustdg (prerequisite 3eee173).
set -eu
S=/home/claude/spike; OUT=$S/evidence-repo; STAGE=$(mktemp -d)
"$S/.venv/bin/python" "$S/scripts/stage_evidence.py" "$STAGE"
rm -rf "$OUT"; git init -q "$OUT"; cd "$OUT"
git fetch -q --update-shallow "$S/robustdg" 'refs/heads/audit/*:refs/heads/audit/*'
git branch -D audit/matchdg-lenet >/dev/null 2>&1 || true   # same commit as audit/repair-env
git checkout -q --orphan audit-evidence
cp -r "$STAGE/evidence/." .
git add -A
git -c user.name="EL-01 audit" -c user.email="audit@example.invalid" commit -q -m "Audit evidence for MatchDG (ICML 2021), Table 1 and Suppl. Table 11: report, raw logs, parsed metrics with log line numbers, grades, patches, scripts, extraction test"
# The tag freezes what judges see: push it with the branches (see team notes).
git -c user.name="EL-01 audit" -c user.email="audit@example.invalid" tag -a round0-submission -m "EL-01 Round 0 submission: evidence as submitted (manifest sha256 $(sha256sum manifest.json | cut -c1-64))"
git bundle create "$S/matchdg-audit.bundle" --branches --tags --not 3eee173 2>/dev/null || git bundle create "$S/matchdg-audit.bundle" --branches --tags
git bundle list-heads "$S/matchdg-audit.bundle"
du -h "$S/matchdg-audit.bundle"; rm -rf "$STAGE"
