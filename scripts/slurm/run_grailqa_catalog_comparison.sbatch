#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-catalog-compare
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail
module load Miniconda3
: "${XGAP_REPO_ROOT:?Explicit XGAP_REPO_ROOT is required.}"
exec bash "$XGAP_REPO_ROOT/scripts/server/run_grailqa_catalog_comparison.sh" "$@"
