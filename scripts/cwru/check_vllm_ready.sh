#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ -x "$VLLM_ENV/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "$VLLM_ENV/bin/activate"
fi
cd "$XGAP_REPO_ROOT"

if PYTHONPATH=src python -m xgap.experiments.cwru_vllm check-ready \
  --base-url "$XGAP_LLM_BASE_URL" \
  --model "$XGAP_LLM_MODEL" \
  --api-key "$XGAP_LLM_API_KEY" \
  --timeout "${XGAP_VLLM_READY_TIMEOUT:-900}" \
  --interval "${XGAP_VLLM_READY_INTERVAL:-5}"; then
  exit 0
fi

echo "vLLM readiness failed. Last log lines:" >&2
tail -n 100 "$XGAP_VLLM_LOG" >&2 2>/dev/null || true
echo "GPU diagnostics:" >&2
nvidia-smi >&2 2>&1 || true
echo "Process diagnostics:" >&2
if [[ -f "$XGAP_VLLM_PID_FILE" ]]; then
  pid="$(tr -d '[:space:]' < "$XGAP_VLLM_PID_FILE")"
  ps -fp "$pid" >&2 2>&1 || true
else
  echo "No vLLM PID file: $XGAP_VLLM_PID_FILE" >&2
fi
exit 1
