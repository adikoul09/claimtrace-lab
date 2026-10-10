#!/usr/bin/env bash
# Runs the repo's own reproduce_slab.py commands (train then evaluate), logging each method separately.
# Usage: run_table1.sh <branch> <test_domain> <outdir>
set -u
BR=$1; TD=$2; OUT=$3
cd /home/claude/spike/robustdg
git checkout -q "$BR"
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/commit.txt"
COMMON="--dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains $TD --slab_data_dim 2 --slab_noise 0.1 --n_runs 10"
declare -A M
M[erm]="--method_name erm_match --match_case 0.0 --penalty_ws 0.0"
M[mmd]="--method_name mmd --gaussian 1 --conditional 0 --penalty_ws 0.1"
M[c-mmd]="--method_name mmd --gaussian 1 --conditional 1 --penalty_ws 0.1"
M[coral]="--method_name mmd --gaussian 0 --conditional 0 --penalty_ws 0.1"
M[c-coral]="--method_name mmd --gaussian 0 --conditional 1 --penalty_ws 0.1"
M[dann]="--method_name dann --conditional 0 --penalty_ws 0.01 --grad_penalty 0.1 --d_steps_per_g_step 4"
M[c-dann]="--method_name dann --conditional 1 --penalty_ws 0.01 --grad_penalty 1.0 --d_steps_per_g_step 2"
M[rand]="--method_name erm_match --match_case 0.0 --penalty_ws 1.0"
M[perf]="--method_name erm_match --match_case 1.0 --penalty_ws 1.0"
for m in erm rand perf mmd coral c-mmd c-coral dann c-dann; do
  s=$(date +%s)
  ../.venv/bin/python train.py $COMMON ${M[$m]} > "$OUT/train_$m.log" 2>&1
  ../.venv/bin/python test.py --test_metric per_domain_acc --acc_data_case train $COMMON ${M[$m]} > "$OUT/eval_$m.log" 2>&1
  echo "$m done in $(( $(date +%s) - s ))s" >> "$OUT/progress.txt"
done
echo ALL_DONE >> "$OUT/progress.txt"
