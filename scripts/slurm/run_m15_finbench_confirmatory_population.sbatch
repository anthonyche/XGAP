#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-population
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

XGAP_REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
XGAP_PYTHON="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
XGAP_FINBENCH_ARCHIVE="${XGAP_FINBENCH_ARCHIVE:-$HOME/.cache/xgap/finbench-v0.1.0/sf0.1.tar.gz}"
XGAP_RUN_ROOT="${XGAP_RUN_ROOT:-$XGAP_REPO_ROOT/runs/cwru-m15-finbench-confirmatory-population-${SLURM_JOB_ID:-manual}}"

if [[ ! -f "$XGAP_REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $XGAP_REPO_ROOT" >&2
  exit 2
fi
if [[ ! -x "$XGAP_PYTHON" ]]; then
  echo "XGAP Python is unavailable: $XGAP_PYTHON" >&2
  exit 2
fi

cd "$XGAP_REPO_ROOT"
PYTHONPATH=src "$XGAP_PYTHON" \
  -m xgap.experiments.m15_finbench_confirmatory_population_job \
  --repo-root "$XGAP_REPO_ROOT" \
  --archive "$XGAP_FINBENCH_ARCHIVE" \
  --lock experiments/sources/m15_finbench_v010_sf0_1_sources.json \
  --design experiments/configs/m15_finbench_confirmatory_population_design_v1.json \
  --output-root "$XGAP_RUN_ROOT" \
  --slurm-job-id "${SLURM_JOB_ID:-manual}"
