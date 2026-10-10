#!/usr/bin/env bash
# Usage: run_dann.sh <worktree> <outdir> methods...   (dann, c-dann with the repo's reproduce_slab.py arguments)
set -u
WT=$1; OUT=$2; shift 2
cd "$WT"; mkdir -p "$OUT"; git rev-parse HEAD > "$OUT/commit.txt"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
../.venv/bin/python data_gen_syn.py > "$OUT/datagen.log" 2>&1
COMMON="--dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10"
declare -A M
M[dann]="--method_name dann --conditional 0 --penalty_ws 0.01 --grad_penalty 0.1 --d_steps_per_g_step 4"
M[c-dann]="--method_name dann --conditional 1 --penalty_ws 0.01 --grad_penalty 1.0 --d_steps_per_g_step 2"
for m in "$@"; do
  s=$(date +%s)
  ../.venv/bin/python train.py $COMMON ${M[$m]} > "$OUT/train_$m.log" 2>&1
  echo "$m done in $(( $(date +%s) - s ))s" >> "$OUT/progress.txt"
done
echo ALL_DONE >> "$OUT/progress.txt"
