#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-freeze
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

XGAP_REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
XGAP_PYTHON="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
XGAP_FINBENCH_ARCHIVE="${XGAP_FINBENCH_ARCHIVE:-$HOME/.cache/xgap/finbench-v0.1.0/sf0.1.tar.gz}"
XGAP_POPULATION_JOB_ID="${XGAP_POPULATION_JOB_ID:-3793727}"
XGAP_POPULATION_COMMIT="${XGAP_POPULATION_COMMIT:-10b560053f5cd5e9a49337875dc8a747c9a28336}"
XGAP_POPULATION_RUN="${XGAP_POPULATION_RUN:-$XGAP_REPO_ROOT/runs/cwru-m15-finbench-confirmatory-population-$XGAP_POPULATION_JOB_ID}"
XGAP_POPULATION_AUDIT="${XGAP_POPULATION_AUDIT:-$XGAP_REPO_ROOT/runs/audits/cwru-m15-finbench-confirmatory-population-$XGAP_POPULATION_JOB_ID-audit.json}"
XGAP_RUN_ROOT="${XGAP_RUN_ROOT:-$XGAP_REPO_ROOT/runs/cwru-m15-finbench-confirmatory-freeze-${SLURM_JOB_ID:-manual}}"

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
  -m xgap.experiments.m15_finbench_confirmatory_freeze_job \
  --repo-root "$XGAP_REPO_ROOT" \
  --archive "$XGAP_FINBENCH_ARCHIVE" \
  --population-run-root "$XGAP_POPULATION_RUN" \
  --population-audit "$XGAP_POPULATION_AUDIT" \
  --population-expected-commit "$XGAP_POPULATION_COMMIT" \
  --lock experiments/sources/m15_finbench_v010_sf0_1_sources.json \
  --protocol experiments/configs/m15_finbench_paper_protocol_draft_v1.json \
  --author-selection experiments/artifacts/m15_finbench_paper_protocol_author_selection_a_v1.json \
  --family-contract experiments/configs/m15_finbench_confirmatory_family_contract_v1.json \
  --output-root "$XGAP_RUN_ROOT" \
  --slurm-job-id "${SLURM_JOB_ID:-manual}"
