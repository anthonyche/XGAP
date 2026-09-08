#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-confirmatory-later-audit
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

AUDITOR_ROOT="${XGAP_AUDITOR_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
EVIDENCE_ROOT="${XGAP_EVIDENCE_REPO_ROOT:?XGAP_EVIDENCE_REPO_ROOT is required}"
AUDITOR_COMMIT="${XGAP_CONFIRMATORY_AUDITOR_COMMIT:?XGAP_CONFIRMATORY_AUDITOR_COMMIT is required}"
RUNNER_COMMIT="${XGAP_CONFIRMATORY_RUNNER_COMMIT:?XGAP_CONFIRMATORY_RUNNER_COMMIT is required}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
CAMPAIGN_ROOT="${XGAP_CONFIRMATORY_CAMPAIGN_ROOT:?XGAP_CONFIRMATORY_CAMPAIGN_ROOT is required}"
AUDIT_OUTPUT="${XGAP_CONFIRMATORY_AUDIT_OUTPUT:?XGAP_CONFIRMATORY_AUDIT_OUTPUT is required}"

test -d "$AUDITOR_ROOT"
test -d "$EVIDENCE_ROOT"
test ! -L "$AUDITOR_ROOT"
test ! -L "$EVIDENCE_ROOT"
test "$(git -C "$AUDITOR_ROOT" rev-parse HEAD)" = "$AUDITOR_COMMIT"
test -z "$(git -C "$AUDITOR_ROOT" status --porcelain --untracked-files=all)"
test "$(git -C "$EVIDENCE_ROOT" rev-parse HEAD)" = "$RUNNER_COMMIT"
test -z "$(git -C "$EVIDENCE_ROOT" status --porcelain --untracked-files=all)"
test ! -e "$AUDIT_OUTPUT"
test ! -L "$AUDIT_OUTPUT"

cd "$AUDITOR_ROOT"
module load "$PYTHON_MODULE"
hash -r
PYTHONPATH="$AUDITOR_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.m15_finbench_confirmatory_campaign_evidence \
  --campaign-root "$CAMPAIGN_ROOT" \
  --repo-root "$EVIDENCE_ROOT" \
  --expected-commit "$RUNNER_COMMIT" \
  --output "$AUDIT_OUTPUT"
