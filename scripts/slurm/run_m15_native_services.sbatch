#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-native-services
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
JAVA_MODULE="${XGAP_JAVA_MODULE:-Java/17.0.6}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
CACHE_ROOT="${XGAP_NATIVE_ARTIFACT_CACHE:-$HOME/xgap-data/m15-native/artifacts}"
RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$REPO_ROOT/runs/cwru-m15-native-services-${SLURM_JOB_ID:-manual}}"
STATUS_FILE="$RUN_ROOT/run_status.json"
STAGING_MANIFEST="$RUN_ROOT/runtime_staging.json"
RUNTIME_ROOT=""
LOCAL_BASE=""
RUNTIME_REMOVED=false
CLEANUP_ERROR=""

if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $REPO_ROOT" >&2
  exit 2
fi
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "This entry point requires a real Slurm allocation." >&2
  exit 2
fi
if [[ "$CACHE_ROOT" != /* ]]; then
  echo "XGAP_NATIVE_ARTIFACT_CACHE must be an absolute path." >&2
  exit 2
fi

mkdir -p "$RUN_ROOT"
exec > >(tee -a "$RUN_ROOT/job.log") 2>&1

cleanup_runtime() {
  if [[ -z "$RUNTIME_ROOT" ]]; then
    RUNTIME_REMOVED=true
    return 0
  fi
  case "$RUNTIME_ROOT" in
    "$LOCAL_BASE"/xgap-m15-"$SLURM_JOB_ID".*) ;;
    *)
      CLEANUP_ERROR="runtime path failed the job-owned prefix check"
      return 1
      ;;
  esac
  if [[ -L "$RUNTIME_ROOT" || ! -d "$RUNTIME_ROOT" ]]; then
    CLEANUP_ERROR="runtime path is not the expected real directory"
    return 1
  fi
  if [[ "$(stat -c %u "$RUNTIME_ROOT")" != "$(id -u)" ]]; then
    CLEANUP_ERROR="runtime path is not owned by the job user"
    return 1
  fi
  if ! rm -rf -- "$RUNTIME_ROOT"; then
    CLEANUP_ERROR="failed to remove the validated runtime path"
    return 1
  fi
  if [[ -e "$RUNTIME_ROOT" || -L "$RUNTIME_ROOT" ]]; then
    CLEANUP_ERROR="validated runtime path still exists after cleanup"
    return 1
  fi
  RUNTIME_REMOVED=true
}

finalize() {
  local exit_code=$?
  local state=failed
  trap - EXIT
  set +e
  if ! cleanup_runtime; then
    exit_code=1
  fi
  if [[ "$exit_code" -eq 0 && "$RUNTIME_REMOVED" == true ]]; then
    state=success
  fi
  local cleanup_json=null
  if [[ -n "$CLEANUP_ERROR" ]]; then
    cleanup_json="\"$CLEANUP_ERROR\""
  fi
  printf '{"status":"%s","exit_code":%d,"slurm_job_id":"%s","git_commit":"%s","runtime_removed":%s,"cleanup_error":%s}\n' \
    "$state" \
    "$exit_code" \
    "$SLURM_JOB_ID" \
    "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || printf unavailable)" \
    "$RUNTIME_REMOVED" \
    "$cleanup_json" \
    > "$STATUS_FILE"
  echo "M15 native-service artifacts: $RUN_ROOT"
  exit "$exit_code"
}
trap finalize EXIT

cd "$REPO_ROOT"
if [[ -n "$(git status --porcelain)" && "${XGAP_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Refusing a dirty experiment checkout." >&2
  exit 2
fi
if ! type module >/dev/null 2>&1; then
  echo "Environment Modules is unavailable." >&2
  exit 2
fi
module load "$PYTHON_MODULE"
module load "$JAVA_MODULE"
hash -r
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command is unavailable: $PYTHON_BIN" >&2
  exit 2
fi
if ! command -v java >/dev/null 2>&1; then
  echo "Java is unavailable after loading $JAVA_MODULE." >&2
  exit 2
fi
JAVA_BIN="$(command -v java)"

LOCAL_BASE="${SLURM_TMPDIR:-/tmp}"
if [[ "$LOCAL_BASE" != /* || ! -d "$LOCAL_BASE" || -L "$LOCAL_BASE" ]]; then
  echo "Allocation-local base must be an absolute real directory: $LOCAL_BASE" >&2
  exit 2
fi
LOCAL_BASE="$(cd "$LOCAL_BASE" && pwd -P)"
FILESYSTEM_TYPE="$(stat -f -c %T "$LOCAL_BASE")"
case "${FILESYSTEM_TYPE,,}" in
  tmpfs|xfs|ext2/ext3|ext4|btrfs|zfs|overlay|overlayfs) ;;
  *)
    echo "Allocation runtime filesystem is not allowlisted: $FILESYSTEM_TYPE" >&2
    exit 2
    ;;
esac
RUNTIME_ROOT="$(mktemp -d "$LOCAL_BASE/xgap-m15-${SLURM_JOB_ID}.XXXXXX")"

{
  printf 'run_version=m15-b2d-native-services-v1\n'
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'python_module=%s\n' "$PYTHON_MODULE"
  printf 'python_version=%s\n' "$($PYTHON_BIN --version 2>&1)"
  printf 'java_module=%s\n' "$JAVA_MODULE"
  printf 'java_command=%s\n' "$JAVA_BIN"
  printf 'runtime_base=%s\n' "$LOCAL_BASE"
  printf 'runtime_root=%s\n' "$RUNTIME_ROOT"
  printf 'runtime_filesystem_type=%s\n' "$FILESYSTEM_TYPE"
  printf 'cache_root=%s\n' "$CACHE_ROOT"
  printf 'loopback_only=true\n'
  printf 'automatic_retries=0\n'
} > "$RUN_ROOT/environment.txt"
if command -v findmnt >/dev/null 2>&1; then
  findmnt -T "$LOCAL_BASE" -o TARGET,SOURCE,FSTYPE,OPTIONS \
    > "$RUN_ROOT/runtime_mount.txt"
else
  printf 'findmnt_unavailable=true\n' > "$RUN_ROOT/runtime_mount.txt"
fi
java -version > "$RUN_ROOT/java_version.txt" 2>&1
cp -- "$REPO_ROOT/services/m15-native-runtime.lock.json" \
  "$RUN_ROOT/runtime_lock.json"

XGAP_STAGE_M15_NATIVE_RUNTIME=1 \
PYTHONPATH="$REPO_ROOT/src" \
"$PYTHON_BIN" -m xgap.experiments.m15_native_runtime \
  --lock "$REPO_ROOT/services/m15-native-runtime.lock.json" \
  --cache-root "$CACHE_ROOT" \
  --runtime-root "$RUNTIME_ROOT" \
  --manifest "$STAGING_MANIFEST" \
  | tee "$RUN_ROOT/runtime_staging_result.json"

XGAP_RUN_M15_NATIVE_SERVICES=1 \
PYTHONPATH="$REPO_ROOT/src" \
"$PYTHON_BIN" -m xgap.experiments.m15_native_services \
  --runtime-root "$RUNTIME_ROOT" \
  --staging-manifest "$STAGING_MANIFEST" \
  --output-root "$RUN_ROOT" \
  --run-id native-service-run \
  --filesystem-type "$FILESYSTEM_TYPE" \
  --allocation-id "$SLURM_JOB_ID" \
  --java-command "$JAVA_BIN" \
  --repo-root "$REPO_ROOT" \
  | tee "$RUN_ROOT/native_service_result.json"

echo "M15 native services and federated vertical slice passed."
