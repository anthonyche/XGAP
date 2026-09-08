#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-paper
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
SPEC="$XGAP_REPO_ROOT/experiments/specs/grailqa_semantic_paper_run_cwru_qwen3_32b.json"
PROTOCOL="${XGAP_GRAILQA_SEMANTIC_PROTOCOL:-$XGAP_REPO_ROOT/experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json}"
CORE_PYTHON="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
CATALOG_ROOT="${XGAP_GRAILQA_PILOT150_CATALOG:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150}"
REACHABILITY_SUMMARY="${XGAP_GRAILQA_PILOT150_REACHABILITY_SUMMARY:-$CATALOG_ROOT/audit_summary.json}"
REACHABILITY_ROWS="${XGAP_GRAILQA_PILOT150_REACHABILITY_ROWS:-$CATALOG_ROOT/reachability.jsonl}"
AUTHOR_SELECTION="${XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION:?set XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION}"
PREEXECUTION_ADMISSION="${XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION:?set XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION}"
EXECUTION_REQUEST="${XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST:?set XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST}"
EXECUTION_AUTHORITY="${XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY:?set XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY}"

if [[ ! -f "$XGAP_REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $XGAP_REPO_ROOT" >&2
  exit 2
fi
if [[ ! -x "$CORE_PYTHON" ]]; then
  echo "Core Python is unavailable: $CORE_PYTHON" >&2
  exit 2
fi
if [[ -n "$(git -C "$XGAP_REPO_ROOT" status --porcelain)" ]]; then
  echo "Refusing a dirty M13-E4 semantic-paper checkout." >&2
  exit 2
fi

RUN_ID="$("$CORE_PYTHON" - "$EXECUTION_REQUEST" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1]))
print(value["run_id"])
PY
)"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$ ]]; then
  echo "Authority-bound run_id is unsafe: $RUN_ID" >&2
  exit 2
fi

XGAP_CWRU_RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$XGAP_REPO_ROOT/runs/cwru-grailqa-semantic-paper-${SLURM_JOB_ID:-manual}}"
export XGAP_CWRU_RUN_ROOT
RESULT_ROOT="$XGAP_CWRU_RUN_ROOT/results/$RUN_ID"
mkdir -p "$XGAP_CWRU_RUN_ROOT"

echo "Checking the exact request and independent authority before loading Qwen3-32B."
PYTHONPATH="$XGAP_REPO_ROOT/src" "$CORE_PYTHON" \
  -m xgap.experiments.grailqa_semantic_paper_run check \
  --request "$EXECUTION_REQUEST" \
  --admission "$PREEXECUTION_ADMISSION" \
  --authority "$EXECUTION_AUTHORITY" \
  --protocol "$PROTOCOL" \
  --author-selection "$AUTHOR_SELECTION" \
  --repo-root "$XGAP_REPO_ROOT" \
  --catalog-root "$CATALOG_ROOT" \
  --reachability-summary "$REACHABILITY_SUMMARY" \
  --reachability-rows "$REACHABILITY_ROWS" \
  > "$XGAP_CWRU_RUN_ROOT/paper_run_readiness.json"

export XGAP_SKIP_VLLM_STRUCTURED_SMOKE=1
export XGAP_PYTHON="$CORE_PYTHON"
exec bash "$XGAP_REPO_ROOT/scripts/slurm/cwru_xgap_vllm.sbatch" \
  "$SPEC" \
  "$CORE_PYTHON" -m xgap.experiments.grailqa_semantic_paper_run run \
  --request "$EXECUTION_REQUEST" \
  --admission "$PREEXECUTION_ADMISSION" \
  --authority "$EXECUTION_AUTHORITY" \
  --protocol "$PROTOCOL" \
  --author-selection "$AUTHOR_SELECTION" \
  --repo-root "$XGAP_REPO_ROOT" \
  --catalog-root "$CATALOG_ROOT" \
  --reachability-summary "$REACHABILITY_SUMMARY" \
  --reachability-rows "$REACHABILITY_ROWS" \
  --output "$RESULT_ROOT"
