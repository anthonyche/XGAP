#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-native-semantic-direct-frontier
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
SERVICE_SCRIPT="$REPO_ROOT/scripts/slurm/run_m15_native_services.sbatch"
if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -f "$SERVICE_SCRIPT" ]]; then
  echo "XGAP_REPO_ROOT is not a complete XGAP checkout: $REPO_ROOT" >&2
  exit 2
fi
export XGAP_REPO_ROOT="$REPO_ROOT"
export XGAP_M15_WORKLOAD_MODE=semantic_direct_frontier
source "$SERVICE_SCRIPT"
