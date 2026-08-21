#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${XGAP_REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
LOCAL_ROOT="${XGAP_GRAILQA_LOCAL_PREFLIGHT_ROOT:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1/preflight18}"
SPEC="$REPO_ROOT/experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json"
VLLM_ENV="${VLLM_ENV:-/home/hxc859/venvs/xgap-vllm}"
PYTHON="${PYTHON:-$VLLM_ENV/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "CWRU preflight Python is unavailable: $PYTHON" >&2
  exit 2
fi

export XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE="${XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE:-query_local_e3b4}"
export XGAP_GRAILQA_CATALOG_V2="${XGAP_GRAILQA_CATALOG_V2:-$LOCAL_ROOT}"
export XGAP_GRAILQA_REACHABILITY_V2="${XGAP_GRAILQA_REACHABILITY_V2:-$LOCAL_ROOT}"
export XGAP_GRAILQA_REACHABILITY_SUMMARY="${XGAP_GRAILQA_REACHABILITY_SUMMARY:-$LOCAL_ROOT/audit_summary.json}"
export XGAP_GRAILQA_REACHABILITY_ROWS="${XGAP_GRAILQA_REACHABILITY_ROWS:-$LOCAL_ROOT/reachability.jsonl}"
export XGAP_LLM_API_KEY="${XGAP_LLM_API_KEY:-local}"
export XGAP_LLM_MODEL="${XGAP_LLM_MODEL:-Qwen/Qwen3-32B}"

cd "$REPO_ROOT"
echo "M13-E3B.5 CWRU query-local preflight readiness"
echo "artifact_profile=$XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE"
echo "catalog_root=$XGAP_GRAILQA_CATALOG_V2"
echo "reachability_summary=$XGAP_GRAILQA_REACHABILITY_SUMMARY"
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_preflight check \
  --spec "$SPEC" \
  --repo-root "$REPO_ROOT" \
  --require-credentials
