#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ -x "$VLLM_ENV/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "$VLLM_ENV/bin/activate"
fi
mkdir -p "$XGAP_CWRU_RUN_ROOT"
cd "$XGAP_REPO_ROOT"
PYTHONPATH=src python -m xgap.experiments.cwru_vllm smoke \
  --base-url "$XGAP_LLM_BASE_URL" \
  --model "$XGAP_LLM_MODEL" \
  --api-key "$XGAP_LLM_API_KEY" \
  --timeout "${XGAP_VLLM_SMOKE_TIMEOUT:-60}" \
  --output "$XGAP_CWRU_RUN_ROOT/vllm_structured_smoke.json"
