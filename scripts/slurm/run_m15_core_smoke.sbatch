#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-core-smoke
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
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

if [[ -n "$PYTHON_MODULE" ]]; then
  if ! type module >/dev/null 2>&1; then
    echo "Environment Modules is unavailable; cannot load $PYTHON_MODULE." >&2
    exit 2
  fi
  module load "$PYTHON_MODULE"
fi

if [[ -n "$(git status --porcelain)" && "${XGAP_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Refusing a dirty experiment checkout." >&2
  exit 2
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command is unavailable: $PYTHON_BIN" >&2
  exit 2
fi

detect_runtime() {
  local candidate
  for candidate in podman docker apptainer singularity; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  printf 'none'
}

{
  printf 'probe_version=m15-b1-v1\n'
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID:-unavailable}"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'python_module=%s\n' "${PYTHON_MODULE:-none}"
  printf 'python_version=%s\n' "$($PYTHON_BIN --version 2>&1)"
  printf 'backend_runtime=%s\n' "$(detect_runtime)"
} > "$RUN_ROOT/environment.txt"

"$PYTHON_BIN" scripts/check_harness.py
"$PYTHON_BIN" -m pytest \
  tests/test_m15_semantic_program.py \
  tests/test_m15_tools.py \
  tests/test_m15_goal_loop.py \
  tests/test_m15_adaptive_runtime.py \
  tests/test_m15_fragment_compiler.py \
  tests/test_m15_federated_runtime.py \
  tests/test_m15_federated_planning.py \
  tests/test_m15_backend_observations.py \
  tests/test_m15_fixture_loader.py \
  tests/test_m15_native_artifacts.py \
  tests/test_m15_native_runtime.py \
  tests/test_m15_native_services.py \
  tests/test_m15_native_evidence.py \
  tests/test_m15_live_federated.py \
  tests/test_m15_live_adaptive.py \
  tests/test_m15_workload.py \
  tests/test_m15_scaled_federation.py \
  tests/test_m15_remote_executor.py \
  tests/test_m15_remote_control.py \
  | tee "$RUN_ROOT/pytest.txt"

"$PYTHON_BIN" examples/m15_federated_vertical_slice_demo.py \
  > "$RUN_ROOT/vertical_slice.json"

"$PYTHON_BIN" examples/m15_federated_plan_selection_demo.py \
  > "$RUN_ROOT/plan_selection.json"

"$PYTHON_BIN" examples/m15_adaptive_replanning_demo.py \
  > "$RUN_ROOT/adaptive_replanning.json"

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

"$PYTHON_BIN" - "$RUN_ROOT/plan_selection.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["evidence_class"] == "controlled_model_sanity_check"
assert payload["paper_result"] is False
assert payload["same_exact_answer"] is True
assert payload["selection_flipped"] is True
assert (
    payload["selections"]["transfer_sensitive"]["selected_plan_id"]
    == "m15-risk-first-bind"
)
assert payload["selections"]["slow_bind"]["selected_plan_id"] == "m15-parallel-hash"
PY

"$PYTHON_BIN" - "$RUN_ROOT/adaptive_replanning.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["evidence_class"] == "controlled_model_sanity_check"
assert payload["paper_result"] is False
assert payload["success"] is True
assert payload["initial_plan_id"] == "m15-parallel-hash"
assert payload["post_probe_plan_id"] == "m15-risk-first-bind"
assert payload["executed_plan_id"] == "m15-risk-first-bind"
assert payload["replan_count"] == 1
assert payload["no_duplicate_probe_call"] is True
assert payload["total_remote_calls"] == 2
assert payload["exact_answer"] is True
assert payload["persisted_snapshot_version_after_reopen"] == "task-1"
PY

echo "M15 core smoke passed."
