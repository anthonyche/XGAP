#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKLOAD="${XGAP_LOCAL_CATALOG_WORKLOAD:-preflight18}"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
PARQUET_ROOT="${XGAP_FREEBASE_PARQUET_ROOT:-$RAW_DIR/hf-archival-parquet}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$RAW_DIR/source_manifest.json}"
LOCAL_ROOT="${XGAP_GRAILQA_LOCAL_CATALOG_ROOT:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1}"
STAGING_ROOT="${XGAP_LOCAL_CATALOG_STAGING_ROOT:-${TMPDIR:-/tmp}}"
CONFIG="${XGAP_LOCAL_CATALOG_CONFIG:-$REPO_ROOT/experiments/specs/grailqa_local_catalog_v1.json}"
PYTHON="${PYTHON:-python}"

case "$WORKLOAD" in
  preflight18|pilot150) ;;
  *)
    echo "XGAP_LOCAL_CATALOG_WORKLOAD must be preflight18 or pilot150." >&2
    exit 2
    ;;
esac

COMMAND="run"
FORCE=()
if [[ "${1:-}" == "--audit-only" ]]; then
  COMMAND="audit"
elif [[ "${1:-}" == "--force" ]]; then
  FORCE=(--force)
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--force|--audit-only]" >&2
  exit 2
fi

cd "$REPO_ROOT"
export XGAP_GIT_COMMIT="$(git rev-parse HEAD)"
export XGAP_FREEBASE_PARQUET_ROOT="$PARQUET_ROOT"
export XGAP_FREEBASE_SOURCE_MANIFEST="$SOURCE_MANIFEST"

if [[ "$COMMAND" == "audit" ]]; then
  echo "Auditing the existing query-local workload without reading the Parquet source: $WORKLOAD"
else
  echo "Building and auditing query-local workload: $WORKLOAD"
  echo "The builder first validates the complete frozen M13-E3A source exactly once."
fi
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_local_catalog "$COMMAND" \
  --config "$CONFIG" \
  --workload "$WORKLOAD" \
  --parquet-root "$PARQUET_ROOT" \
  --source-manifest "$SOURCE_MANIFEST" \
  --local-root "$LOCAL_ROOT" \
  --staging-root "$STAGING_ROOT" \
  "${FORCE[@]}"

OUTPUT="$LOCAL_ROOT/$WORKLOAD"
echo "M13-E3B local catalog and offline audit are ready: $OUTPUT"
echo "GO/NO-GO: $OUTPUT/prompt_reachability.json"
echo "Entity before/after: $OUTPUT/entity_retrieval_before_after.json"
echo "Schema before/after: $OUTPUT/schema_ranking_before_after.json"
echo "Relation ranking audit: $OUTPUT/relation_ranking_audit.jsonl"
echo "Type ranking audit: $OUTPUT/type_ranking_audit.jsonl"
echo "Relation diagnostics v2: $OUTPUT/relation_diagnostics_v2.jsonl"
echo "Type diagnostics v2: $OUTPUT/type_diagnostics_v2.jsonl"
