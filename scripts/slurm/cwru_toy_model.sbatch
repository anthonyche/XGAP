#!/usr/bin/env bash
#SBATCH --job-name=xgap-toy-model
#SBATCH --partition=gpu
#SBATCH --constraint=gpu2h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --exclude=gput069
#SBATCH --output=slurm-%x-%j.out

# Tiny connectivity only: no large data, catalog build or evaluation runner.
set -euo pipefail
[[ -n "${SLURM_JOB_ID:-}" ]] || { echo "A Slurm allocation is required." >&2; exit 2; }
[[ $# == 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "Pass the exact source commit." >&2; exit 2; }
export XGAP_REPO_ROOT="${SLURM_SUBMIT_DIR:?}"
cd "$XGAP_REPO_ROOT"
[[ "$(git rev-parse HEAD)" == "$1" && -z "$(git status --porcelain)" ]] || exit 2
export XGAP_MODEL_REVISION=9216db5781bf21249d130ec9da846c4624c16137
export XGAP_CWRU_CONTRACT="${XGAP_CWRU_CONTRACT:-$XGAP_REPO_ROOT/experiments/environments/cwru_pioneer_qwen3_32b_h100_single_v1.json}"
export XGAP_CWRU_RUN_ROOT="$XGAP_REPO_ROOT/runs/toy-model-${SLURM_JOB_ID}"
[[ ! -e "$XGAP_CWRU_RUN_ROOT" ]] || exit 2
unset XGAP_VLLM_PID XGAP_VLLM_PID_FILE XGAP_VLLM_LOG
export XGAP_LLM_BASE_URL=http://127.0.0.1:8000/v1 XGAP_LLM_MODEL=Qwen/Qwen3-32B
source scripts/cwru/common.sh
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export XGAP_VLLM_READY_TIMEOUT=1800
mkdir -p "$XGAP_CWRU_RUN_ROOT"
exec > >(tee -a "$XGAP_CWRU_RUN_ROOT/job.log") 2>&1

cleanup() {
  local code=$?
  set +e
  if [[ -n "${XGAP_VLLM_PID:-}" ]]; then
    kill "$XGAP_VLLM_PID" 2>/dev/null
    for _ in $(seq 1 30); do
      kill -0 "$XGAP_VLLM_PID" 2>/dev/null || break
      sleep 1
    done
    kill -0 "$XGAP_VLLM_PID" 2>/dev/null && kill -9 "$XGAP_VLLM_PID" 2>/dev/null
    wait "$XGAP_VLLM_PID" 2>/dev/null
  fi
  PYTHONPATH=src "$VLLM_ENV/bin/python" -m xgap.experiments.cwru_vllm finalize-run \
    --root "$XGAP_CWRU_RUN_ROOT" --exit-code "$code"
  return "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

date -Iseconds > "$XGAP_CWRU_RUN_ROOT/server_time.txt"
hostname > "$XGAP_CWRU_RUN_ROOT/hostname.txt"
git rev-parse HEAD > "$XGAP_CWRU_RUN_ROOT/source_commit.txt"
cp "$XGAP_CWRU_CONTRACT" "$XGAP_CWRU_RUN_ROOT/deployment_contract.json"
XGAP_TOY_SNAPSHOT="$HF_HOME/hub/models--Qwen--Qwen3-32B/snapshots/$XGAP_MODEL_REVISION"
"$VLLM_ENV/bin/python" scripts/run_toy_model.py --tokenizer-snapshot "$XGAP_TOY_SNAPSHOT" \
    --output "$XGAP_CWRU_RUN_ROOT/token_preflight.json"
source scripts/cwru/launch_vllm_qwen3_32b.sh
bash scripts/cwru/check_vllm_ready.sh
# The first of these five questions is also the structured-output connectivity check.
"$VLLM_ENV/bin/python" scripts/run_toy_model.py --tokenizer-snapshot "$XGAP_TOY_SNAPSHOT" \
    --output "$XGAP_CWRU_RUN_ROOT/model-recordings" --execute
