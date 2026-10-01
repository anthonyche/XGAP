#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-live-resolution
#SBATCH --partition=gpu
#SBATCH -C gpu2h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:45:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

XGAP_REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
export XGAP_REPO_ROOT
if [[ ! -f "$XGAP_REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $XGAP_REPO_ROOT" >&2
  exit 2
fi

XGAP_CWRU_RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$XGAP_REPO_ROOT/runs/cwru-m15-live-resolution-${SLURM_JOB_ID:-manual}}"
export XGAP_CWRU_RUN_ROOT
# shellcheck source=../cwru/common.sh
source "$XGAP_REPO_ROOT/scripts/cwru/common.sh"

XGAP_E2B_SPEC="${XGAP_E2B_SPEC:-$XGAP_REPO_ROOT/experiments/configs/m15_e2b_live_resolution_gate.json}"
XGAP_E2B_PREFLIGHT="$XGAP_CWRU_RUN_ROOT/preflight_manifest.json"
XGAP_E2B_ENVIRONMENT="$XGAP_CWRU_RUN_ROOT/cwru_environment.json"
XGAP_E2B_OUTPUT="$XGAP_CWRU_RUN_ROOT/live-resolution-run"
XGAP_VLLM_PYTHON="${XGAP_VLLM_PYTHON:-$VLLM_ENV/bin/python}"
XGAP_CORE_PYTHON="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"

if [[ -e "$XGAP_CWRU_RUN_ROOT" ]]; then
  echo "Run root already exists; refusing to overwrite: $XGAP_CWRU_RUN_ROOT" >&2
  exit 2
fi
mkdir -p "$XGAP_CWRU_RUN_ROOT"
exec > >(tee -a "$XGAP_CWRU_RUN_ROOT/job.log") 2>&1

cleanup() {
  local exit_code=$?
  local stop_status="not_started"
  set +e
  if [[ -f "$XGAP_VLLM_PID_FILE" ]]; then
    local pid
    pid="$(tr -d '[:space:]' < "$XGAP_VLLM_PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      stop_status="sigterm"
      kill "$pid" 2>/dev/null
      for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null; then
        stop_status="sigkill"
        kill -9 "$pid" 2>/dev/null
      fi
      wait "$pid" 2>/dev/null || true
    else
      stop_status="already_stopped"
    fi
  fi
  printf '%s\n' "$stop_status" > "$XGAP_CWRU_RUN_ROOT/service_shutdown.txt"
  cd "$XGAP_REPO_ROOT" || true
  # Stop writing through tee before inventory hashes are computed; otherwise
  # finalize-run's own stdout would change job.log after it was hashed.
  exec >/dev/null 2>&1
  local finalize_python="$XGAP_CORE_PYTHON"
  if [[ ! -x "$finalize_python" ]]; then
    finalize_python="$XGAP_VLLM_PYTHON"
  fi
  PYTHONPATH=src "$finalize_python" -m xgap.experiments.cwru_vllm finalize-run \
    --root "$XGAP_CWRU_RUN_ROOT" \
    --exit-code "$exit_code" || true
  return "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$XGAP_REPO_ROOT"
if [[ ! -x "$XGAP_VLLM_PYTHON" ]]; then
  echo "Frozen vLLM Python is unavailable: $XGAP_VLLM_PYTHON" >&2
  exit 2
fi
if [[ ! -x "$XGAP_CORE_PYTHON" ]]; then
  echo "M15 core Python is unavailable: $XGAP_CORE_PYTHON" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing a dirty M15-E2B experiment checkout." >&2
  exit 2
fi
echo "Git commit: $(git rev-parse HEAD)"
echo "Slurm job ID: ${SLURM_JOB_ID:-unavailable}"
echo "Hostname: $(hostname)"

PYTHONPATH=src "$XGAP_CORE_PYTHON" -m pytest -q \
  tests/test_m15_llm_resolution_provider.py \
  tests/test_m15_live_resolution.py \
  > "$XGAP_CWRU_RUN_ROOT/pytest.txt"

PYTHONPATH=src "$XGAP_CORE_PYTHON" -m xgap.experiments.m15_live_resolution \
  preflight \
  --repo-root "$XGAP_REPO_ROOT" \
  --spec "$XGAP_E2B_SPEC" \
  --output "$XGAP_E2B_PREFLIGHT" \
  > "$XGAP_CWRU_RUN_ROOT/preflight_stdout.json"

PYTHONPATH=src "$XGAP_CORE_PYTHON" -m xgap.experiments.cwru_vllm \
  verify-token-budget \
  --repo-root "$XGAP_REPO_ROOT" \
  --spec "$XGAP_E2B_SPEC" \
  --contract "$XGAP_CWRU_CONTRACT" \
  > "$XGAP_CWRU_RUN_ROOT/token_budget.json"

date -u +%Y-%m-%dT%H:%M:%SZ > "$XGAP_CWRU_RUN_ROOT/service_launch_requested_at.txt"
# shellcheck source=../cwru/launch_vllm_qwen3_32b.sh
source "$XGAP_REPO_ROOT/scripts/cwru/launch_vllm_qwen3_32b.sh"
bash "$XGAP_REPO_ROOT/scripts/cwru/check_vllm_ready.sh"

XGAP_RUN_ENVIRONMENT_FILE="$XGAP_E2B_ENVIRONMENT"
export XGAP_RUN_ENVIRONMENT_FILE
PYTHONPATH=src python -m xgap.experiments.cwru_vllm capture-environment \
  --repo-root "$XGAP_REPO_ROOT" \
  --spec "$XGAP_E2B_SPEC" \
  --contract "$XGAP_CWRU_CONTRACT" \
  --output "$XGAP_E2B_ENVIRONMENT"

# There is intentionally no generic structured-output smoke here: this is the
# only inference request in the E2B job.
PYTHONPATH=src "$XGAP_CORE_PYTHON" -m xgap.experiments.m15_live_resolution run \
  --repo-root "$XGAP_REPO_ROOT" \
  --spec "$XGAP_E2B_SPEC" \
  --preflight "$XGAP_E2B_PREFLIGHT" \
  --environment "$XGAP_E2B_ENVIRONMENT" \
  --output-root "$XGAP_E2B_OUTPUT" \
  > "$XGAP_CWRU_RUN_ROOT/live_resolution_stdout.json"
