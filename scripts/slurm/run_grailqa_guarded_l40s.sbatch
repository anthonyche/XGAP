#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-l40s
#SBATCH --partition=gpu
#SBATCH -C gpul40s
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%j.out

# Explicit alternative deployment; never resubmit or retry here.
set -euo pipefail
: "${XGAP_REPO_ROOT:?Explicit XGAP_REPO_ROOT is required.}"
exec bash "$XGAP_REPO_ROOT/scripts/server/run_grailqa_guarded_preflight.sh" "$@"
