#!/usr/bin/env bash

# Submit the exact staged FinBench campaign after explicit author authority.
set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-$PWD}"
PYTHON_BIN="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
FREEZE_RUN="${XGAP_FINBENCH_CONFIRMATORY_FREEZE_RUN:?XGAP_FINBENCH_CONFIRMATORY_FREEZE_RUN is required}"
FREEZE_AUDIT="${XGAP_FINBENCH_CONFIRMATORY_FREEZE_AUDIT:?XGAP_FINBENCH_CONFIRMATORY_FREEZE_AUDIT is required}"
SELECTION_ADMISSION="${XGAP_FINBENCH_CONFIRMATORY_SELECTION_ADMISSION:?XGAP_FINBENCH_CONFIRMATORY_SELECTION_ADMISSION is required}"
EXECUTION_REQUEST="${XGAP_FINBENCH_CONFIRMATORY_EXECUTION_REQUEST:?XGAP_FINBENCH_CONFIRMATORY_EXECUTION_REQUEST is required}"
EXECUTION_AUTHORITY="${XGAP_FINBENCH_CONFIRMATORY_EXECUTION_AUTHORITY:?XGAP_FINBENCH_CONFIRMATORY_EXECUTION_AUTHORITY is required}"
CAMPAIGN_ROOT="${XGAP_CONFIRMATORY_CAMPAIGN_ROOT:?XGAP_CONFIRMATORY_CAMPAIGN_ROOT is required}"

if [[ ! -f "$REPO_ROOT/pyproject.toml" || ! -x "$PYTHON_BIN" ]]; then
  echo "Repository or Python runtime is unavailable." >&2
  exit 2
fi
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]]; then
  echo "Refusing to submit from a dirty checkout." >&2
  exit 2
fi
RUNNER_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"

cd "$REPO_ROOT"
PYTHONPATH=src "$PYTHON_BIN" \
  -m xgap.experiments.m15_finbench_confirmatory_campaign \
  initialize \
  --campaign-root "$CAMPAIGN_ROOT" \
  --freeze-run-root "$FREEZE_RUN" \
  --freeze-audit "$FREEZE_AUDIT" \
  --selection-admission "$SELECTION_ADMISSION" \
  --execution-request "$EXECUTION_REQUEST" \
  --execution-authority "$EXECUTION_AUTHORITY" \
  --repo-root "$REPO_ROOT"

CAMPAIGN_ID="$($PYTHON_BIN -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["campaign_id"])' \
  "$CAMPAIGN_ROOT/campaign_manifest.json")"
export XGAP_REPO_ROOT="$REPO_ROOT"
export XGAP_PYTHON="$PYTHON_BIN"
export XGAP_FINBENCH_CONFIRMATORY_FREEZE_RUN="$FREEZE_RUN"
export XGAP_CONFIRMATORY_CAMPAIGN_ROOT="$CAMPAIGN_ROOT"
export XGAP_CONFIRMATORY_CAMPAIGN_ID="$CAMPAIGN_ID"
export XGAP_CONFIRMATORY_RUNNER_COMMIT="$RUNNER_COMMIT"

submit_job() {
  local raw
  local job_id
  raw="$(sbatch --parsable "$@")"
  job_id="${raw%%;*}"
  if [[ ! "$job_id" =~ ^[1-9][0-9]*$ ]]; then
    echo "Unexpected sbatch identity: $raw" >&2
    exit 2
  fi
  printf '%s\n' "$job_id"
}

TRAINING_JOB="$(submit_job \
  --array=1-7%1 \
  --export=ALL,XGAP_CONFIRMATORY_PHASE=crossfit_training_measurement \
  scripts/slurm/run_m15_finbench_confirmatory_campaign_block.sbatch)"
PROFILE_JOB="$(submit_job \
  --array=1 \
  --export=ALL,XGAP_CONFIRMATORY_PHASE=current_query_profile_acquisition \
  scripts/slurm/run_m15_finbench_confirmatory_campaign_block.sbatch)"
SELECTION_JOB="$(submit_job \
  --dependency=afterok:"$TRAINING_JOB":"$PROFILE_JOB" \
  --export=ALL \
  scripts/slurm/run_m15_finbench_confirmatory_selection.sbatch)"
SERVING_JOB="$(submit_job \
  --dependency=afterok:"$SELECTION_JOB" \
  --array=1-7%1 \
  --export=ALL,XGAP_CONFIRMATORY_PHASE=paired_selected_serving \
  scripts/slurm/run_m15_finbench_confirmatory_campaign_block.sbatch)"
SHADOW_JOB="$(submit_job \
  --dependency=afterok:"$SELECTION_JOB" \
  --array=1-7%1 \
  --export=ALL,XGAP_CONFIRMATORY_PHASE=postselection_shadow_evaluation \
  scripts/slurm/run_m15_finbench_confirmatory_campaign_block.sbatch)"
FINALIZE_JOB="$(submit_job \
  --dependency=afterok:"$SERVING_JOB":"$SHADOW_JOB" \
  --export=ALL \
  scripts/slurm/run_m15_finbench_confirmatory_finalize.sbatch)"
AUDIT_JOB="$(submit_job \
  --dependency=afterany:"$FINALIZE_JOB" \
  --begin=now+2minutes \
  --export=ALL \
  scripts/slurm/run_m15_finbench_confirmatory_campaign_audit.sbatch)"

PYTHONPATH=src "$PYTHON_BIN" \
  -m xgap.experiments.m15_finbench_confirmatory_campaign \
  record-submission \
  --campaign-root "$CAMPAIGN_ROOT" \
  --training-job-id "$TRAINING_JOB" \
  --profile-job-id "$PROFILE_JOB" \
  --selection-job-id "$SELECTION_JOB" \
  --serving-job-id "$SERVING_JOB" \
  --shadow-job-id "$SHADOW_JOB" \
  --finalize-job-id "$FINALIZE_JOB" \
  --audit-job-id "$AUDIT_JOB"

"$PYTHON_BIN" -c '
import json, sys
print(json.dumps({
    "status": "submitted",
    "campaign_id": sys.argv[1],
    "campaign_root": sys.argv[2],
    "runner_commit": sys.argv[3],
    "training_array_job_id": sys.argv[4],
    "profile_job_id": sys.argv[5],
    "selection_job_id": sys.argv[6],
    "serving_array_job_id": sys.argv[7],
    "shadow_array_job_id": sys.argv[8],
    "finalize_job_id": sys.argv[9],
    "audit_job_id": sys.argv[10],
    "automatic_retries": 0,
    "paper_result": False,
}, indent=2, sort_keys=True))
' "$CAMPAIGN_ID" "$CAMPAIGN_ROOT" "$RUNNER_COMMIT" \
  "$TRAINING_JOB" "$PROFILE_JOB" "$SELECTION_JOB" "$SERVING_JOB" \
  "$SHADOW_JOB" "$FINALIZE_JOB" "$AUDIT_JOB"
