#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-native-probe
#SBATCH --partition=batch
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$REPO_ROOT/runs/cwru-m15-native-probe-${SLURM_JOB_ID:-manual}}"
STATUS_FILE="$RUN_ROOT/run_status.json"

if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $REPO_ROOT" >&2
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
  printf '{"status":"%s","exit_code":%d,"slurm_job_id":"%s","git_commit":"%s"}\n' \
    "$state" \
    "$exit_code" \
    "${SLURM_JOB_ID:-unavailable}" \
    "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || printf unavailable)" \
    > "$STATUS_FILE"
  echo "M15 native-service probe artifacts: $RUN_ROOT"
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

if type module >/dev/null 2>&1; then
  module -t avail 2>&1 \
    | grep -Ei 'java|jdk|openjdk' \
    > "$RUN_ROOT/java_modules.txt" || true
else
  : > "$RUN_ROOT/java_modules.txt"
fi

JAVA_MODULE_LOADED=none
if ! command -v java >/dev/null 2>&1 && type module >/dev/null 2>&1; then
  : > "$RUN_ROOT/java_module_attempts.txt"
  for candidate in Java java OpenJDK; do
    if module load "$candidate" >> "$RUN_ROOT/java_module_attempts.txt" 2>&1; then
      if command -v java >/dev/null 2>&1; then
        JAVA_MODULE_LOADED="$candidate"
        break
      fi
    fi
  done
fi

command_available() {
  if command -v "$1" >/dev/null 2>&1; then
    printf 'true'
  else
    printf 'false'
  fi
}

BACKEND_RUNTIME=none
for candidate in podman docker apptainer singularity; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BACKEND_RUNTIME="$candidate"
    break
  fi
done

LOOPBACK_BIND="$($PYTHON_BIN - <<'PY'
import socket

try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        print("true")
except OSError:
    print("false")
PY
)"

JAVA_AVAILABLE="$(command_available java)"
CURL_AVAILABLE="$(command_available curl)"
WGET_AVAILABLE="$(command_available wget)"
TAR_AVAILABLE="$(command_available tar)"
SHA256SUM_AVAILABLE="$(command_available sha256sum)"
SHASUM_AVAILABLE="$(command_available shasum)"
SETSID_AVAILABLE="$(command_available setsid)"
TIMEOUT_AVAILABLE="$(command_available timeout)"
DOWNLOAD_TOOL_AVAILABLE=false
if [[ "$CURL_AVAILABLE" == true || "$WGET_AVAILABLE" == true ]]; then
  DOWNLOAD_TOOL_AVAILABLE=true
fi
HASH_TOOL_AVAILABLE=false
if [[ "$SHA256SUM_AVAILABLE" == true || "$SHASUM_AVAILABLE" == true ]]; then
  HASH_TOOL_AVAILABLE=true
fi
NATIVE_SERVICE_PREREQUISITES_READY=false
if [[ "$JAVA_AVAILABLE" == true \
  && "$DOWNLOAD_TOOL_AVAILABLE" == true \
  && "$TAR_AVAILABLE" == true \
  && "$HASH_TOOL_AVAILABLE" == true \
  && "$LOOPBACK_BIND" == true ]]; then
  NATIVE_SERVICE_PREREQUISITES_READY=true
fi

if [[ "$JAVA_AVAILABLE" == true ]]; then
  java -version > "$RUN_ROOT/java_version.txt" 2>&1
else
  : > "$RUN_ROOT/java_version.txt"
fi
df -Pk "$HOME" "$RUN_ROOT" > "$RUN_ROOT/filesystem.txt" 2>&1 || true

{
  printf 'probe_version=m15-b2-native-v1\n'
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID:-unavailable}"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'python_module=%s\n' "${PYTHON_MODULE:-none}"
  printf 'python_version=%s\n' "$($PYTHON_BIN --version 2>&1)"
  printf 'backend_runtime=%s\n' "$BACKEND_RUNTIME"
  printf 'java_available=%s\n' "$JAVA_AVAILABLE"
  printf 'java_module_loaded=%s\n' "$JAVA_MODULE_LOADED"
  printf 'curl_available=%s\n' "$CURL_AVAILABLE"
  printf 'wget_available=%s\n' "$WGET_AVAILABLE"
  printf 'tar_available=%s\n' "$TAR_AVAILABLE"
  printf 'sha256sum_available=%s\n' "$SHA256SUM_AVAILABLE"
  printf 'shasum_available=%s\n' "$SHASUM_AVAILABLE"
  printf 'setsid_available=%s\n' "$SETSID_AVAILABLE"
  printf 'timeout_available=%s\n' "$TIMEOUT_AVAILABLE"
  printf 'loopback_bind_available=%s\n' "$LOOPBACK_BIND"
  printf 'outbound_download_tested=false\n'
  printf 'native_service_prerequisites_ready=%s\n' \
    "$NATIVE_SERVICE_PREREQUISITES_READY"
} > "$RUN_ROOT/environment.txt"

echo "M15 native-service prerequisite probe completed."
