#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-guarded
#SBATCH --partition=gpu
#SBATCH -C gpu2h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%j.out

# Explicit development entrypoint only. This file never submits another job.
set -euo pipefail
: "${XGAP_REPO_ROOT:?Explicit XGAP_REPO_ROOT is required.}"
exec bash "$XGAP_REPO_ROOT/scripts/server/run_grailqa_guarded_preflight.sh" "$@"
