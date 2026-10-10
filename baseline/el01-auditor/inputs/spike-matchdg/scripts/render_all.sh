#!/usr/bin/env bash
# Re-derives every output from the raw logs, in order: grades, run counts, charts, regression check, the rendered
# report, concept note and spec, the patch files, the staged evidence (with sha256 manifest) and the blueprint page.
# Usage: render_all.sh <blueprint_out_dir> [deck_slides_dir]
set -eu
S=/home/claude/spike; PY=$S/.venv/bin/python; BP=$1
cd "$S"
$PY scripts/grade.py > /dev/null
$PY scripts/grade_lenet.py "$S/runs/matchdg_lenet" grades_lenet.json > /dev/null
if grep -qs ALL_DONE runs/matchdg_lenet_confirm/progress.txt; then
  $PY scripts/grade_lenet.py "$S/runs/matchdg_lenet_confirm" grades_lenet_confirm.json > /dev/null
fi
$PY scripts/count_runs.py > /dev/null
$PY scripts/wallclock.py > /dev/null
$PY scripts/check_selection_traces.py > /dev/null
if grep -qs ALL_DONE runs/h7_no_flip/progress.txt; then
  $PY scripts/parse_runs.py runs/h7_no_flip > /dev/null; $PY scripts/grade_f7.py > /dev/null
  if [ -d wt-h7-noflip/data/datasets ] && [ -d wt-lenet-confirm/data/datasets ]; then $PY scripts/check_f7_data.py > /dev/null; fi
fi
$PY scripts/charts.py > /dev/null
$PY scripts/regression.py
$PY scripts/report_tables.py evidence/report.template.md evidence/README.md
$PY scripts/report_tables.py docs/concept.template.md docs/concept.md
$PY scripts/report_tables.py docs/spec.template.md docs/spec.md
$PY scripts/report_tables.py docs/team-notes.template.md docs/team-notes.md
bash scripts/make_patches.sh > /dev/null
$PY scripts/stage_evidence.py "$BP"
$PY scripts/build_blueprint.py docs/blueprint.template.html "$BP/el01-blueprint.html"
$PY scripts/build_blueprint.py docs/onepage.template.html "$BP/el01-onepage.html"
# Optional second argument: the deck's slides folder; each slide is rendered from docs/deck/ with the same tokens.
if [ -n "${2:-}" ]; then
  for f in docs/deck/*.html; do
    n=$(basename "$f"); $PY scripts/build_blueprint.py "$f" "$BP/_slide_$n" > /dev/null; mv "$BP/_slide_$n" "$2/$n"
  done
fi
