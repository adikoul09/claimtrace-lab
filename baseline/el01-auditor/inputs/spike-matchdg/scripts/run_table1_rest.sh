#!/usr/bin/env bash
# Runs the remaining Table 1 methods with the repo's own reproduce_slab.py arguments, train then evaluate,
# in its own worktree (mmd and coral share a results path, so they must not share a checkout).
# Usage: run_table1_rest.sh <worktree> <outdir> methods...
set -u
WT=$1; OUT=$2; shift 2
cd "$WT"
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/commit.txt"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
../.venv/bin/python data_gen_syn.py > "$OUT/datagen_$(basename $WT).log" 2>&1
COMMON="--dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10"
declare -A M
M[mmd]="--method_name mmd --gaussian 1 --conditional 0 --penalty_ws 0.1"
M[c-mmd]="--method_name mmd --gaussian 1 --conditional 1 --penalty_ws 0.1"
M[coral]="--method_name mmd --gaussian 0 --conditional 0 --penalty_ws 0.1"
M[c-coral]="--method_name mmd --gaussian 0 --conditional 1 --penalty_ws 0.1"
M[dann]="--method_name dann --conditional 0 --penalty_ws 0.01 --grad_penalty 0.1 --d_steps_per_g_step 4"
M[c-dann]="--method_name dann --conditional 1 --penalty_ws 0.01 --grad_penalty 1.0 --d_steps_per_g_step 2"
for m in "$@"; do
  s=$(date +%s)
  ../.venv/bin/python train.py $COMMON ${M[$m]} > "$OUT/train_$m.log" 2>&1
  t=$(( $(date +%s) - s ))
  ../.venv/bin/python test.py --test_metric per_domain_acc --acc_data_case train $COMMON ${M[$m]} > "$OUT/eval_$m.log" 2>&1
  echo "$m train ${t}s (one thread, 4 jobs in parallel on 4 vCPU)" >> "$OUT/progress.txt"
done
echo "DONE $*" >> "$OUT/progress.txt"
