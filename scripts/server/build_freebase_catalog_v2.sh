#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
FREEBASE_RDF="${XGAP_FREEBASE_RDF:-$RAW_DIR/freebase-rdf-latest.gz}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$RAW_DIR/source_manifest.json}"
CATALOG_DIR="${XGAP_FREEBASE_CATALOG_DIR:-${XGAP_GRAILQA_CATALOG_V2:-$HOME/xgap-data/freebase/catalog-v2}}"
ONTOLOGY="${XGAP_GRAILQA_ONTOLOGY:-$REPO_ROOT/datasets/grailqa_pilot_v1/ontology.yaml}"
REVERSE_PROPERTIES="${XGAP_GRAILQA_REVERSE_PROPERTIES:-$REPO_ROOT/datasets/grailqa_inference_catalog_v1/reverse_properties.json}"
PYTHON="${PYTHON:-python}"

FORCE=()
if [[ "${1:-}" == "--force" ]]; then
  FORCE=(--force)
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--force]" >&2
  exit 2
fi

cd "$REPO_ROOT"
export XGAP_GIT_COMMIT="$(git rev-parse HEAD)"

PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 build \
  --freebase-rdf "$FREEBASE_RDF" \
  --source-manifest "$SOURCE_MANIFEST" \
  --normalized-ontology "$ONTOLOGY" \
  --reverse-properties "$REVERSE_PROPERTIES" \
  --output "$CATALOG_DIR" \
  "${FORCE[@]}"

PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 verify \
  --catalog "$CATALOG_DIR" \
  --output "$CATALOG_DIR/integrity_report.json"
echo "Catalog v2 is complete and validated: $CATALOG_DIR"
