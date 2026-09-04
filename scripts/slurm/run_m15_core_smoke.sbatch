#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-core-smoke
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$REPO_ROOT/runs/cwru-m15-core-smoke-${SLURM_JOB_ID:-manual}}"
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
  echo "M15 core smoke artifacts: $RUN_ROOT"
}
trap finalize EXIT

cd "$REPO_ROOT"
echo "Slurm job ID: ${SLURM_JOB_ID:-unavailable}"
echo "Hostname: $(hostname)"
echo "Git commit: $(git rev-parse HEAD)"

if [[ -n "$(git status --porcelain)" && "${XGAP_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Refusing a dirty experiment checkout." >&2
  exit 2
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command is unavailable: $PYTHON_BIN" >&2
  exit 2
fi

{
  printf 'probe_version=m15-b1-v1\n'
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID:-unavailable}"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'python_version=%s\n' "$($PYTHON_BIN --version 2>&1)"
} > "$RUN_ROOT/environment.txt"

"$PYTHON_BIN" scripts/check_harness.py
"$PYTHON_BIN" -m pytest \
  tests/test_m15_semantic_program.py \
  tests/test_m15_tools.py \
  tests/test_m15_goal_loop.py \
  tests/test_m15_fragment_compiler.py \
  tests/test_m15_federated_runtime.py \
  | tee "$RUN_ROOT/pytest.txt"

"$PYTHON_BIN" examples/m15_federated_vertical_slice_demo.py \
  > "$RUN_ROOT/vertical_slice.json"

"$PYTHON_BIN" - "$RUN_ROOT/vertical_slice.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["success"] is True
assert payload["total_remote_calls"] == 2
assert payload["total_bytes_moved"] > 0
assert len(payload["final_rows"]) == 1
PY

echo "M15 core smoke passed."
