#!/usr/bin/env bash
# h5: re-tune the matching weight the way App. A.1 says (source validation), over the grid in reproduce_scripts/slab-tune.py.
# Usage: run_lambda_grid.sh <worktree> <outdir> <method> <lambda>
set -u
WT=$1; OUT=$2; M=$3; L=$4
cd "$WT"; mkdir -p "$OUT"; git rev-parse HEAD > "$OUT/commit.txt"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
COMMON="--dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10"
case $M in
  rand) X="--method_name erm_match --match_case 0.0" ;;
  perf) X="--method_name erm_match --match_case 1.0" ;;
esac
s=$(date +%s)
../.venv/bin/python train.py $COMMON $X --penalty_ws $L > "$OUT/train_${M}_lambda_${L}.log" 2>&1
echo "$M lambda $L done in $(( $(date +%s) - s ))s" >> "$OUT/progress.txt"
