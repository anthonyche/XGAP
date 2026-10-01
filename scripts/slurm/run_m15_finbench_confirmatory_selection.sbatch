#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-confirmatory-selection
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
CAMPAIGN_ROOT="${XGAP_CONFIRMATORY_CAMPAIGN_ROOT:?XGAP_CONFIRMATORY_CAMPAIGN_ROOT is required}"

cd "$REPO_ROOT"
module load "$PYTHON_MODULE"
hash -r
PYTHONPATH=src "$PYTHON_BIN" \
  -m xgap.experiments.m15_finbench_confirmatory_campaign \
  assemble-selection \
  --campaign-root "$CAMPAIGN_ROOT"
