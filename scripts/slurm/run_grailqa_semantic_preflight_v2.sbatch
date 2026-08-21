#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-preflight
#SBATCH --partition=gpu
#SBATCH -C gpu2h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

XGAP_REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
export XGAP_REPO_ROOT
SPEC="$XGAP_REPO_ROOT/experiments/specs/grailqa_semantic_preflight_v2_cwru_qwen3_32b.json"
XGAP_CWRU_RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$XGAP_REPO_ROOT/runs/cwru-grailqa-preflight-v2-${SLURM_JOB_ID:-manual}}"
export XGAP_CWRU_RUN_ROOT
RESULT_ROOT="$XGAP_CWRU_RUN_ROOT/results/grailqa-semantic-preflight-v2"
LOCAL_ROOT="${XGAP_GRAILQA_LOCAL_PREFLIGHT_ROOT:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1/preflight18}"

export XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE="${XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE:-query_local_e3b4}"
export XGAP_GRAILQA_CATALOG_V2="${XGAP_GRAILQA_CATALOG_V2:-$LOCAL_ROOT}"
export XGAP_GRAILQA_REACHABILITY_V2="${XGAP_GRAILQA_REACHABILITY_V2:-$LOCAL_ROOT}"
export XGAP_GRAILQA_REACHABILITY_SUMMARY="${XGAP_GRAILQA_REACHABILITY_SUMMARY:-$LOCAL_ROOT/audit_summary.json}"
export XGAP_GRAILQA_REACHABILITY_ROWS="${XGAP_GRAILQA_REACHABILITY_ROWS:-$LOCAL_ROOT/reachability.jsonl}"

export XGAP_LLM_BASE_URL="${XGAP_LLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export XGAP_LLM_API_KEY="${XGAP_LLM_API_KEY:-local}"
export XGAP_LLM_MODEL="${XGAP_LLM_MODEL:-Qwen/Qwen3-32B}"

cd "$XGAP_REPO_ROOT"
VLLM_ENV="${VLLM_ENV:-/home/hxc859/venvs/xgap-vllm}"
if [[ ! -f "$VLLM_ENV/bin/activate" ]]; then
  echo "Frozen vLLM environment is unavailable: $VLLM_ENV" >&2
  exit 2
fi
# shellcheck disable=SC1091
source "$VLLM_ENV/bin/activate"
mkdir -p "$XGAP_CWRU_RUN_ROOT"
echo "Checking the M13-E3B.5 query-local catalog/reachability gate before loading Qwen3-32B."
echo "artifact_profile=$XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE"
echo "catalog_root=$XGAP_GRAILQA_CATALOG_V2"
echo "reachability_summary=$XGAP_GRAILQA_REACHABILITY_SUMMARY"
set +e
PYTHONPATH=src python -m xgap.experiments.grailqa_preflight check \
  --spec "$SPEC" \
  --repo-root "$XGAP_REPO_ROOT" \
  --require-credentials \
  > "$XGAP_CWRU_RUN_ROOT/preflight_readiness.json"
gate_status=$?
set -e
cat "$XGAP_CWRU_RUN_ROOT/preflight_readiness.json"
if [[ "$gate_status" -ne 0 ]]; then
  PYTHONPATH=src python -m xgap.experiments.cwru_vllm finalize-run \
    --root "$XGAP_CWRU_RUN_ROOT" \
    --exit-code "$gate_status"
  echo "Offline preflight gate failed; Qwen3-32B was not loaded." >&2
  exit "$gate_status"
fi

exec bash "$XGAP_REPO_ROOT/scripts/slurm/cwru_xgap_vllm.sbatch" \
  "$SPEC" \
  python -m xgap.experiments.grailqa_preflight run \
  --spec "$SPEC" \
  --repo-root "$XGAP_REPO_ROOT" \
  --output "$RESULT_ROOT"
