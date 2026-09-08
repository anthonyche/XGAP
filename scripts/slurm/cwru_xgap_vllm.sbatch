#!/usr/bin/env bash
#SBATCH --job-name=xgap-vllm
#SBATCH --partition=gpu
#SBATCH -C gpu2h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: sbatch $0 <experiment-spec> <command> [args ...]" >&2
  exit 2
fi

EXPERIMENT_SPEC=$1
shift
EXPERIMENT_COMMAND=("$@")
# Prelaunch checks and failure cleanup must also work before vLLM activation.
CONTROL_PYTHON="${XGAP_PYTHON:-python}"
XGAP_REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
export XGAP_REPO_ROOT
if [[ ! -f "$XGAP_REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $XGAP_REPO_ROOT" >&2
  exit 2
fi

# shellcheck source=../cwru/common.sh
source "$XGAP_REPO_ROOT/scripts/cwru/common.sh"
mkdir -p "$XGAP_CWRU_RUN_ROOT"
exec > >(tee -a "$XGAP_CWRU_RUN_ROOT/job.log") 2>&1

cleanup() {
  local exit_code=$?
  set +e
  if [[ -f "$XGAP_VLLM_PID_FILE" ]]; then
    local pid
    pid="$(tr -d '[:space:]' < "$XGAP_VLLM_PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "Stopping vLLM PID $pid."
      kill "$pid" 2>/dev/null
      for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "vLLM did not stop after 30 seconds; sending SIGKILL."
        kill -9 "$pid" 2>/dev/null
      fi
      wait "$pid" 2>/dev/null || true
    fi
  fi
  cd "$XGAP_REPO_ROOT"
  PYTHONPATH=src "$CONTROL_PYTHON" -m xgap.experiments.cwru_vllm finalize-run \
    --root "$XGAP_CWRU_RUN_ROOT" \
    --exit-code "$exit_code" || true
  echo "CWRU run artifacts: $XGAP_CWRU_RUN_ROOT"
  return "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$XGAP_REPO_ROOT"
echo "Slurm job ID: ${SLURM_JOB_ID:-unavailable}"
echo "Hostname: $(hostname)"
echo "Git commit: $(git rev-parse HEAD)"
git_status="$(git status --porcelain)"
if [[ -n "$git_status" ]]; then
  echo "Git working tree status:"
  printf '%s\n' "$git_status"
  if [[ "${XGAP_ALLOW_DIRTY:-0}" != "1" ]]; then
    echo "Refusing a dirty experiment checkout. Set XGAP_ALLOW_DIRTY=1 only for diagnostics." >&2
    exit 2
  fi
else
  echo "Git working tree status: clean"
fi

echo "Checking frozen request token budget against the served context window."
PYTHONPATH=src "$CONTROL_PYTHON" -m xgap.experiments.cwru_vllm verify-token-budget \
  --repo-root "$XGAP_REPO_ROOT" \
  --spec "$EXPERIMENT_SPEC" \
  --contract "$XGAP_CWRU_CONTRACT"

# shellcheck source=../cwru/launch_vllm_qwen3_32b.sh
source "$XGAP_REPO_ROOT/scripts/cwru/launch_vllm_qwen3_32b.sh"
bash "$XGAP_REPO_ROOT/scripts/cwru/check_vllm_ready.sh"
if [[ "${XGAP_SKIP_VLLM_STRUCTURED_SMOKE:-0}" == "1" ]]; then
  echo "Skipping the generic structured-output smoke for an authority-bounded run."
else
  bash "$XGAP_REPO_ROOT/scripts/cwru/smoke_vllm_structured_output.sh"
fi

XGAP_RUN_ENVIRONMENT_FILE="$XGAP_CWRU_RUN_ROOT/cwru_environment.json"
export XGAP_RUN_ENVIRONMENT_FILE
PYTHONPATH=src python -m xgap.experiments.cwru_vllm capture-environment \
  --repo-root "$XGAP_REPO_ROOT" \
  --spec "$EXPERIMENT_SPEC" \
  --contract "$XGAP_CWRU_CONTRACT" \
  --output "$XGAP_RUN_ENVIRONMENT_FILE"

echo "Running experiment command: ${EXPERIMENT_COMMAND[*]}"
PYTHONPATH=src "${EXPERIMENT_COMMAND[@]}"
