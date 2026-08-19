#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
FREEBASE_RDF="${XGAP_FREEBASE_RDF:-$RAW_DIR/freebase-rdf-latest.gz}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$RAW_DIR/source_manifest.json}"
PYTHON="${PYTHON:-python}"

cd "$REPO_ROOT"
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 verify-source \
  --freebase-rdf "$FREEBASE_RDF" --source-manifest "$SOURCE_MANIFEST"

if [[ "${XGAP_SKIP_GZIP_TEST:-0}" != "1" ]]; then
  echo "Running streaming gzip integrity test (no decompressed copy is written)..."
  gzip --test "$FREEBASE_RDF"
fi
echo "Freebase raw artifact verification passed."
