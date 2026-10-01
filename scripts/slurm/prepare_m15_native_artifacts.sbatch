#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-native-artifacts
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:45:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
CACHE_ROOT="${XGAP_NATIVE_ARTIFACT_CACHE:-$HOME/xgap-data/m15-native/artifacts}"
RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$REPO_ROOT/runs/cwru-m15-native-artifacts-${SLURM_JOB_ID:-manual}}"
STATUS_FILE="$RUN_ROOT/run_status.json"
PREPARATION_ROOT="$RUN_ROOT/preparation"

if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $REPO_ROOT" >&2
  exit 2
fi
if [[ "$CACHE_ROOT" != /* ]]; then
  echo "XGAP_NATIVE_ARTIFACT_CACHE must be an absolute path." >&2
  exit 2
fi

mkdir -p "$RUN_ROOT"
exec > >(tee -a "$RUN_ROOT/job.log") 2>&1

finalize() {
  local exit_code=$?
  local state=failed
  if [[ "$exit_code" -eq 0 ]]; then
    state=success
  fi
  printf '{"status":"%s","exit_code":%d,"slurm_job_id":"%s","git_commit":"%s","preparation_manifest":"%s"}\n' \
    "$state" \
    "$exit_code" \
    "${SLURM_JOB_ID:-unavailable}" \
    "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || printf unavailable)" \
    "$PREPARATION_ROOT/run_manifest.json" \
    > "$STATUS_FILE"
  echo "M15 native-artifact preparation artifacts: $RUN_ROOT"
}
trap finalize EXIT

cd "$REPO_ROOT"
if [[ -n "$(git status --porcelain)" && "${XGAP_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Refusing a dirty experiment checkout." >&2
  exit 2
fi

if [[ -n "$PYTHON_MODULE" ]]; then
  if ! type module >/dev/null 2>&1; then
    echo "Environment Modules is unavailable; cannot load $PYTHON_MODULE." >&2
    exit 2
  fi
  module load "$PYTHON_MODULE"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command is unavailable: $PYTHON_BIN" >&2
  exit 2
fi

{
  printf 'preparation_version=m15-b2b-native-artifacts-v1\n'
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID:-unavailable}"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'python_module=%s\n' "${PYTHON_MODULE:-none}"
  printf 'python_version=%s\n' "$($PYTHON_BIN --version 2>&1)"
  printf 'cache_root=%s\n' "$CACHE_ROOT"
  printf 'automatic_retries=0\n'
  printf 'archives_extracted=false\n'
  printf 'services_started=false\n'
} > "$RUN_ROOT/environment.txt"

XGAP_PREPARE_M15_NATIVE_ARTIFACTS=1 \
PYTHONPATH="$REPO_ROOT/src" \
"$PYTHON_BIN" -m xgap.experiments.m15_native_artifacts \
  --lock "$REPO_ROOT/services/m15-native-runtime.lock.json" \
  --cache-root "$CACHE_ROOT" \
  --output-root "$RUN_ROOT" \
  --run-id preparation \
  --timeout-seconds 1800 \
  | tee "$RUN_ROOT/preparation_result.json"

echo "M15 native artifacts prepared and verified."
