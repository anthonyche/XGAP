#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-finbench-confirmatory-campaign-block
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%A_%a.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
CAMPAIGN_ROOT="${XGAP_CONFIRMATORY_CAMPAIGN_ROOT:?XGAP_CONFIRMATORY_CAMPAIGN_ROOT is required}"
PHASE="${XGAP_CONFIRMATORY_PHASE:?XGAP_CONFIRMATORY_PHASE is required}"
ATTEMPT_INDEX="${XGAP_CONFIRMATORY_ATTEMPT_INDEX:-1}"
TASK_ID="${SLURM_ARRAY_TASK_ID:?this entry point requires a Slurm array task}"
BLOCK_RUNNER="$REPO_ROOT/scripts/slurm/run_m15_native_finbench_confirmatory_block.sbatch"

if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -f "$BLOCK_RUNNER" ]]; then
  echo "XGAP_REPO_ROOT is not a complete XGAP checkout: $REPO_ROOT" >&2
  exit 2
fi
if [[ "$CAMPAIGN_ROOT" != /* || ! -d "$CAMPAIGN_ROOT" || -L "$CAMPAIGN_ROOT" ]]; then
  echo "Campaign root is missing or unsafe: $CAMPAIGN_ROOT" >&2
  exit 2
fi
if [[ ! "$TASK_ID" =~ ^[1-7]$ ]]; then
  echo "Invalid confirmatory array task: $TASK_ID" >&2
  exit 2
fi
if [[ "$ATTEMPT_INDEX" != 1 && "$ATTEMPT_INDEX" != 2 ]]; then
  echo "Confirmatory attempt index must be 1 or 2." >&2
  exit 2
fi

case "$PHASE" in
  crossfit_training_measurement|paired_selected_serving|postselection_shadow_evaluation)
    BLOCK_INDEX="$TASK_ID"
    ;;
  current_query_profile_acquisition)
    if [[ "$TASK_ID" != 1 ]]; then
      echo "The profile phase has exactly one block." >&2
      exit 2
    fi
    BLOCK_INDEX=1
    ;;
  *)
    echo "Unsupported confirmatory phase: $PHASE" >&2
    exit 2
    ;;
esac

printf -v BLOCK_ID '%s-block-%02d' "$PHASE" "$BLOCK_INDEX"
CONTEXT_SUFFIX=""
if [[ "$ATTEMPT_INDEX" == 2 ]]; then
  CONTEXT_SUFFIX="-attempt-2"
fi
CONTEXT="$CAMPAIGN_ROOT/contexts/$BLOCK_ID$CONTEXT_SUFFIX.json"
if [[ ! -f "$CONTEXT" || -L "$CONTEXT" ]]; then
  echo "Sealed execution context is missing or unsafe: $CONTEXT" >&2
  exit 2
fi

export XGAP_REPO_ROOT="$REPO_ROOT"
export XGAP_FINBENCH_CONFIRMATORY_EXECUTION_CONTEXT="$CONTEXT"
export XGAP_CWRU_RUN_ROOT="$CAMPAIGN_ROOT/block-runs/$BLOCK_ID/attempt-$ATTEMPT_INDEX"

source "$BLOCK_RUNNER"
