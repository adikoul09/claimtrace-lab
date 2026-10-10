#!/usr/bin/env bash
# MatchDG paper, Suppl. Table 11 (Rotated MNIST, LeNet, 1000 images per domain, leave-one-domain-out),
# run with the repo's own commands from reproduce_scripts/reproduce_rmnist_lenet.py (3 seeds = train.py default n_runs).
# CONFIRMATION on fresh MNIST subsets 3-5 and seeds 30-50 (branch audit/lenet-confirm adds --seed_offset; nothing else changes).
# One job per (test domain, method); MatchDG is its two phases (contrastive, then ERM with inferred matches) in order.
set -u
WT=/home/claude/spike/wt-lenet-confirm; OUT=/home/claude/spike/runs/matchdg_lenet_confirm
cd "$WT"; source ../.venv/bin/activate; export OMP_NUM_THREADS=1
mkdir -p "$OUT"; git rev-parse HEAD > "$OUT/commit.txt"
B="python train.py --dataset rot_mnist --mnist_case lenet --model_name lenet --img_h 32 --img_w 32 --seed_offset 3"
job() {
  m=$1; d=$2; tr=""; for x in 0 15 30 45 60 75; do [ "$x" != "$d" ] && tr="$tr $x"; done
  a="--train_domains$tr --test_domains $d"; t0=$(date +%s)
  case $m in
    erm)  $B --method_name erm_match --match_case 0.0 --penalty_ws 0.0 --epochs 100 $a > "$OUT/train_erm_$d.log" 2>&1 ;;
    rand) $B --method_name erm_match --match_case 0.0 --penalty_ws 1.0 --epochs 100 --total_matches_per_point 100 $a > "$OUT/train_rand_$d.log" 2>&1 ;;
    perf) $B --method_name erm_match --match_case 1.0 --penalty_ws 1.0 --epochs 100 $a > "$OUT/train_perf_$d.log" 2>&1 ;;
    matchdg)
      $B --method_name matchdg_ctr --match_case 0.0 --match_flag 1 --epochs 50 --batch_size 512 --pos_metric cos --match_func_aug_case 1 $a > "$OUT/train_matchdg_ctr_$d.log" 2>&1 &&
      $B --method_name matchdg_erm --match_case -1 --penalty_ws 1.0 --epochs 100 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name lenet --total_matches_per_point 100 $a > "$OUT/train_matchdg_$d.log" 2>&1 ;;
  esac
  echo "$m $d exit $? in $(( $(date +%s) - t0 ))s" >> "$OUT/progress.txt"
}
export -f job; export B OUT
for d in 0 75 15 30 45 60; do for m in matchdg erm rand perf; do echo "$m $d"; done; done | xargs -P 4 -L 1 bash -c 'job $0 $1'
echo ALL_DONE >> "$OUT/progress.txt"
