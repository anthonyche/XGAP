#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
PARQUET_ROOT="${XGAP_FREEBASE_PARQUET_ROOT:-$RAW_DIR/hf-archival-parquet}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$RAW_DIR/source_manifest.json}"
SOURCE_MODE="${XGAP_FREEBASE_SOURCE_MODE:-hf_archival_parquet}"
PYTHON="${PYTHON:-python}"

if [[ "$SOURCE_MODE" != "hf_archival_parquet" ]]; then
  echo "This script requires XGAP_FREEBASE_SOURCE_MODE=hf_archival_parquet." >&2
  exit 2
fi
cd "$REPO_ROOT"
PYTHONPATH=src "$PYTHON" -m xgap.experiments.freebase_sources verify \
  --parquet-root "$PARQUET_ROOT" \
  --source-manifest "$SOURCE_MANIFEST"
echo "Frozen archival Freebase Parquet source verification passed."
