#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-family-campaign
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:30:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
SERVICE_SCRIPT="$REPO_ROOT/scripts/slurm/run_m15_native_services.sbatch"
if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -f "$SERVICE_SCRIPT" ]]; then
  echo "XGAP_REPO_ROOT is not a complete XGAP checkout: $REPO_ROOT" >&2
  exit 2
fi

: "${XGAP_FINBENCH_CORRECTNESS_RUN:?XGAP_FINBENCH_CORRECTNESS_RUN is required}"
: "${XGAP_FINBENCH_CORRECTNESS_AUDIT:?XGAP_FINBENCH_CORRECTNESS_AUDIT is required}"

export XGAP_REPO_ROOT="$REPO_ROOT"
export XGAP_M15_WORKLOAD_MODE=finbench_family_campaign
export XGAP_FINBENCH_ARCHIVE="${XGAP_FINBENCH_ARCHIVE:-$HOME/.cache/xgap/finbench-v0.1.0/sf0.1.tar.gz}"
export XGAP_FINBENCH_LOCK="$REPO_ROOT/experiments/sources/m15_finbench_v010_sf0_1_sources.json"
export XGAP_FINBENCH_SPEC="$REPO_ROOT/experiments/configs/m15_finbench_sf0_1_primary_population_v1.json"
export XGAP_FINBENCH_BATCH_SIZE=2000
export XGAP_NEO4J_RESOURCE_PROFILE=finbench_sf0_1

source "$SERVICE_SCRIPT"
