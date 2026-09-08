#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-confirmatory-audit
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
# The auditor reconstructs all 1,888 measurements and the delayed-oracle
# analysis in one read-only process.  This is deliberately larger than a
# measurement block; command-line --mem remains an explicit scheduler
# override for recovery of an already-frozen runner.
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
CAMPAIGN_ROOT="${XGAP_CONFIRMATORY_CAMPAIGN_ROOT:?XGAP_CONFIRMATORY_CAMPAIGN_ROOT is required}"
RUNNER_COMMIT="${XGAP_CONFIRMATORY_RUNNER_COMMIT:?XGAP_CONFIRMATORY_RUNNER_COMMIT is required}"
CAMPAIGN_ID="${XGAP_CONFIRMATORY_CAMPAIGN_ID:?XGAP_CONFIRMATORY_CAMPAIGN_ID is required}"
AUDIT_OUTPUT="${XGAP_CONFIRMATORY_AUDIT_OUTPUT:-$REPO_ROOT/runs/audits/$CAMPAIGN_ID-audit.json}"

cd "$REPO_ROOT"
module load "$PYTHON_MODULE"
hash -r
PYTHONPATH=src "$PYTHON_BIN" \
  -m xgap.experiments.m15_finbench_confirmatory_campaign_evidence \
  --campaign-root "$CAMPAIGN_ROOT" \
  --repo-root "$REPO_ROOT" \
  --expected-commit "$RUNNER_COMMIT" \
  --output "$AUDIT_OUTPUT"
