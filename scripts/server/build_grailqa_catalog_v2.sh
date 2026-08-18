#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_LINK="${XGAP_DATA_LINK:-$HOME/xgap-data}"
SOURCE_ROOT="${XGAP_FREEBASE_SOURCE_ROOT:-$DATA_LINK/freebase-m13e1-v2}"
FREEBASE_RDF="${XGAP_FREEBASE_RDF:-$SOURCE_ROOT/freebase-rdf-latest.gz}"
CATALOG_ROOT="${XGAP_GRAILQA_CATALOG_V2:-$DATA_LINK/grailqa-inference-catalog-v2}"
REACHABILITY_ROOT="${XGAP_GRAILQA_REACHABILITY_V2:-$DATA_LINK/grailqa-reachability-v2}"
SOURCE_URL="https://storage.googleapis.com/freebase-public/rdf/freebase-rdf-latest.gz"
PYTHON="${PYTHON:-python}"

mkdir -p "$SOURCE_ROOT" "$DATA_LINK"

if [[ "${1:-}" == "--download" ]]; then
  echo "Downloading the official Freebase dump (approximately 22 GB compressed)."
  echo "destination=$FREEBASE_RDF"
  curl --fail --location --continue-at - --retry 5 --retry-delay 5 \
    "$SOURCE_URL" --output "$FREEBASE_RDF"
fi

if [[ ! -s "$FREEBASE_RDF" ]]; then
  cat >&2 <<EOF
Freebase RDF dump is missing: $FREEBASE_RDF

Download it explicitly with:
  bash scripts/server/build_grailqa_catalog_v2.sh --download

The script does not substitute GrailQA gold annotations for missing public data.
EOF
  exit 2
fi

cd "$REPO_ROOT"
echo "Hashing and building query-independent catalog v2..."
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 build \
  --freebase-rdf "$FREEBASE_RDF" \
  --normalized-ontology datasets/grailqa_pilot_v1/ontology.yaml \
  --reverse-properties datasets/grailqa_inference_catalog_v1/reverse_properties.json \
  --source-url "$SOURCE_URL" \
  --output "$CATALOG_ROOT"

echo "Auditing catalog coverage over all supported train/dev questions..."
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_reachability catalog-coverage \
  --supported-questions datasets/grailqa_audit_v2/supported_questions.jsonl \
  --catalog-root "$CATALOG_ROOT" \
  --output "$CATALOG_ROOT/catalog_coverage_all_supported.json"

echo "Building the frozen 150-query reachability v2 bundle..."
set +e
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_reachability v2-pilot \
  --pilot-root datasets/grailqa_pilot_v1 \
  --catalog-root "$CATALOG_ROOT" \
  --output "$REACHABILITY_ROOT"
AUDIT_STATUS=$?
set -e

echo "catalog_root=$CATALOG_ROOT"
echo "reachability_root=$REACHABILITY_ROOT"
if [[ "$AUDIT_STATUS" -eq 2 ]]; then
  echo "Catalog build completed, but the frozen prompt-reachability gate failed."
  exit 2
fi
exit "$AUDIT_STATUS"
