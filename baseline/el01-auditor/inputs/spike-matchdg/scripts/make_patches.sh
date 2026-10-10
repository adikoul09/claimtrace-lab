#!/usr/bin/env bash
# Writes evidence/branches.txt (every run directory -> commit, branch, and what differs), repairs.patch and hypotheses.patch.
set -eu
S=/home/claude/spike; G="git -C $S/robustdg"; E=$S/evidence; mkdir -p "$E"
{
  echo "# Experiment tree. Every run directory in logs/ ran on the commit below (logs/<run>/commit.txt)."
  echo "# REPAIR = allowed change to make the code run; HYPOTHESIS = changes what is measured; AUDIT(harness) = seed plumbing only."
  echo
  printf "%-30s %-8s %-36s %s\n" "run directory" "commit" "branch" "what differs from the baseline (paper_target_1.0)"
  while read -r run what; do
    c=$(cut -c1-7 "$S/runs/$run/commit.txt")
    b=$($G branch --points-at "$c" --format='%(refname:short)' | grep -v matchdg-lenet | head -1)
    [ -z "$b" ] && b="$($G branch --contains "$c" --format='%(refname:short)' | grep -v -e matchdg-lenet -e combined | head -1) (tip~1)"
    printf "%-30s %-8s %-36s %s\n" "$run" "$c" "$b" "$what"
  done <<'T'
paper_target_1.0 baseline: three repairs + h0 (paper's target domain p = 1.0); all nine Table 1 methods
h_select_valloss h1: epoch chosen by lowest validation cross-entropy (code: highest validation accuracy)
h_select_valloss_total h1b: epoch chosen by lowest validation total objective (cross-entropy + λ x matching penalty)
h_omission_plain_sgd h2: plain SGD, no momentum or Nesterov
h_plain_sgd_1000ep h2 check: same commit as h2, run with --epochs 1000
h_combined h1 + h2 in one branch (interaction check)
naive_target_0.9_3m h3: no code change; evaluated with --test_domains 0.9 (the nearest domain the shipped generator builds)
h_omission_constant_penalty h4: matching weight constant at λ (code ramps it from about 0 to λ)
h5_lambda_grid h5: no code change; --penalty_ws 0.1 and 10.0 (the grid in reproduce_scripts/slab-tune.py), RandMatch and PerfMatch
h_dann_lr h6: DANN/CDANN learning rate from args (0.1, as the paper states) instead of hard-coded 0.01
confirm_base confirmation baseline: fresh seeds 10-19 (seed plumbing only)
confirm_select_valloss confirmation of h1 on fresh seeds 10-19
matchdg_lenet MatchDG Suppl. Table 11 (Rotated MNIST, LeNet): repairs only, no hypothesis changes; commands from reproduce_scripts/reproduce_rmnist_lenet.py
matchdg_lenet_confirm Table 11 confirmation on fresh MNIST subsets 3-5, seeds 30-50: repairs + seed plumbing only (--seed_offset, --train_seeds); rule pre-registered in audit/PREREGISTERED_table11_confirm.txt
h7_no_flip h7 (F7, SciCoQA row 67): MatchDG only, on the Table 11 confirmation's subsets and seeds; augmented Rotated MNIST copy without horizontal flips (same random draws); rule pre-registered in audit/PREREGISTERED_f7.txt
T
  echo
  for b in $($G for-each-ref --format='%(refname:short)' refs/heads/audit | grep -v matchdg-lenet); do
    echo "### branch $b"; $G log --format='%h %s' 3eee173..$b | cat; echo
  done
} > "$E/branches.txt"
$G diff 3eee173 audit/repair-env > "$E/repairs.patch"
{
  for pair in "h0: paper's target domain (baseline)|audit/repair-env|audit/h-paper-target-1.0" \
              "h1: select by validation cross-entropy|be16a6f~1|be16a6f" \
              "harness: --seed_offset for fresh-seed confirmation (no effect on seeds 0-9)|be16a6f|12460e5" \
              "h1b: select by validation total objective|audit/h-paper-target-1.0|audit/h-select-valloss-total" \
              "h2: plain SGD|audit/h-paper-target-1.0|audit/h-omission-plain-sgd" \
              "h1 + h2|audit/h-select-valloss|audit/h-combined" \
              "h4: constant matching weight|audit/h-paper-target-1.0|audit/h-omission-constant-penalty" \
              "h6: DANN/CDANN learning rate from args|audit/h-paper-target-1.0|audit/h-dann-lr" \
              "harness: --seed_offset and --train_seeds for the Table 11 confirmation (no effect on subsets 0-2)|audit/repair-env|audit/lenet-confirm~1" \
              "h7 (F7): no horizontal flip in the augmented Rotated MNIST copy, same random draws|audit/h7-no-flip~2|audit/h7-no-flip~1"; do
    IFS='|' read -r t a b <<<"$pair"; echo "### $t   ($($G rev-parse --short $a)..$($G rev-parse --short $b))"; $G diff "$a" "$b"; echo
  done
} > "$E/hypotheses.patch"
cp /mnt/project-files/analysis/spike-matchdg/requirements-pinned.txt "$E/" 2>/dev/null || true
wc -l "$E"/branches.txt "$E"/*.patch
