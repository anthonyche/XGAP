#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CATALOG_DIR="${XGAP_FREEBASE_CATALOG_DIR:-${XGAP_GRAILQA_CATALOG_V2:-$HOME/xgap-data/freebase/catalog-v2}}"
REACHABILITY_DIR="${XGAP_GRAILQA_REACHABILITY_V2:-$HOME/xgap-data/freebase/grailqa-reachability-v2}"
SUPPORTED_QUESTIONS="${XGAP_GRAILQA_SUPPORTED_QUESTIONS:-$REPO_ROOT/datasets/grailqa_audit_v2/supported_questions.jsonl}"
PILOT_ROOT="${XGAP_GRAILQA_PILOT_ROOT:-$REPO_ROOT/datasets/grailqa_pilot_v1}"
PYTHON="${PYTHON:-python}"

cd "$REPO_ROOT"
for required in \
  "$SUPPORTED_QUESTIONS" \
  "$PILOT_ROOT/inference_questions.jsonl" \
  "$PILOT_ROOT/reference_interpretations.jsonl" \
  "$PILOT_ROOT/workload_stats.jsonl"; do
  if [[ ! -s "$required" ]]; then
    echo "Required frozen GrailQA artifact is missing: $required" >&2
    echo "Install and verify the M13-D GrailQA artifacts before running M13-E3." >&2
    exit 2
  fi
done
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 verify \
  --catalog "$CATALOG_DIR" \
  --output "$CATALOG_DIR/integrity_report.json"

set +e
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_reachability m13e3-audit \
  --supported-questions "$SUPPORTED_QUESTIONS" \
  --pilot-root "$PILOT_ROOT" \
  --catalog-root "$CATALOG_DIR" \
  --output "$REACHABILITY_DIR"
STATUS=$?
set -e

PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_compatibility \
  --supported-questions "$SUPPORTED_QUESTIONS" \
  --pilot-references "$PILOT_ROOT/reference_interpretations.jsonl" \
  --catalog-root "$CATALOG_DIR" \
  --output "$REACHABILITY_DIR/archival_source_compatibility.json"

echo "Reachability report: $REACHABILITY_DIR/audit_summary.json"
echo "Archival compatibility: $REACHABILITY_DIR/archival_source_compatibility.json"
if [[ "$STATUS" -eq 2 ]]; then
  echo "Offline audit completed with live_preflight_allowed=false. No LLM was called."
fi
exit "$STATUS"
