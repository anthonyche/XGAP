#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ -z "${SLURM_JOB_ID:-}" && "${XGAP_ALLOW_NON_SLURM_VLLM:-0}" != "1" ]]; then
  echo "Qwen3-32B vLLM must run inside a Slurm allocation." >&2
  exit 2
fi
if [[ ! -x "$VLLM_ENV/bin/python" || ! -x "$VLLM_ENV/bin/vllm" ]]; then
  echo "Frozen vLLM environment is unavailable: $VLLM_ENV" >&2
  exit 2
fi

# shellcheck disable=SC1091
source "$VLLM_ENV/bin/activate"
mkdir -p "$XGAP_CWRU_RUN_ROOT"
cd "$XGAP_REPO_ROOT"

echo "Checking allocated GPU."
nvidia-smi
echo "Checking frozen Python, torch, CUDA, and vLLM versions."
PYTHONPATH=src python -m xgap.experiments.cwru_vllm verify-environment \
  --contract "$XGAP_CWRU_CONTRACT"

# An opt-in profile validates and exercises every CUDA device before loading the
# unchanged model. Legacy contracts emit no additional arguments.
XGAP_GPU_ARGUMENTS="$(PYTHONPATH=src python -m xgap.experiments.cwru_gpu_profile \
  --contract "$XGAP_CWRU_CONTRACT" --verify-allocation)"
XGAP_PARALLEL_ARGS=()
if [[ -n "$XGAP_GPU_ARGUMENTS" ]]; then
  while IFS= read -r XGAP_GPU_ARGUMENT; do
    XGAP_PARALLEL_ARGS+=("$XGAP_GPU_ARGUMENT")
  done <<< "$XGAP_GPU_ARGUMENTS"
fi

if [[ -f "$XGAP_VLLM_PID_FILE" ]]; then
  previous_pid="$(tr -d '[:space:]' < "$XGAP_VLLM_PID_FILE")"
  if [[ -n "$previous_pid" ]] && kill -0 "$previous_pid" 2>/dev/null; then
    echo "A recorded vLLM process is already running: PID $previous_pid" >&2
    exit 2
  fi
fi

revision_args=()
if [[ -n "${XGAP_MODEL_REVISION:-}" ]]; then
  revision_args=(--revision "$XGAP_MODEL_REVISION")
fi
XGAP_RESOLVED_MODEL_REVISION="$(
  PYTHONPATH=src python -m xgap.experiments.cwru_vllm resolve-revision \
    --model "$XGAP_LLM_MODEL" \
    --hf-home "$HF_HOME" \
    "${revision_args[@]}"
)"
export XGAP_RESOLVED_MODEL_REVISION
printf '%s\n' "$XGAP_RESOLVED_MODEL_REVISION" > "$XGAP_CWRU_RUN_ROOT/model_revision.txt"

echo "Starting $XGAP_LLM_MODEL revision $XGAP_RESOLVED_MODEL_REVISION on 127.0.0.1:8000."
"$VLLM_ENV/bin/vllm" serve "$XGAP_LLM_MODEL" \
  --revision "$XGAP_RESOLVED_MODEL_REVISION" \
  --host 127.0.0.1 \
  --port 8000 \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 12288 \
  --generation-config vllm \
  ${XGAP_PARALLEL_ARGS[@]+"${XGAP_PARALLEL_ARGS[@]}"} \
  >"$XGAP_VLLM_LOG" 2>&1 &
XGAP_VLLM_PID=$!
export XGAP_VLLM_PID
printf '%s\n' "$XGAP_VLLM_PID" > "$XGAP_VLLM_PID_FILE"

sleep 2
if ! kill -0 "$XGAP_VLLM_PID" 2>/dev/null; then
  echo "vLLM exited during startup." >&2
  tail -n 100 "$XGAP_VLLM_LOG" >&2 || true
  exit 1
fi
echo "vLLM startup process PID: $XGAP_VLLM_PID"
