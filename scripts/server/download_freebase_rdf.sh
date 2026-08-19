#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
FREEBASE_RDF="${XGAP_FREEBASE_RDF:-$RAW_DIR/freebase-rdf-latest.gz}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$RAW_DIR/source_manifest.json}"
HTTP_HEADERS="${XGAP_FREEBASE_HTTP_HEADERS:-$RAW_DIR/download_headers.txt}"
SOURCE_URL="https://storage.googleapis.com/freebase-public/rdf/freebase-rdf-latest.gz"
PYTHON="${PYTHON:-python}"

mkdir -p "$RAW_DIR"
cd "$REPO_ROOT"

if [[ -s "$FREEBASE_RDF" && -s "$SOURCE_MANIFEST" ]]; then
  if PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 verify-source \
    --freebase-rdf "$FREEBASE_RDF" --source-manifest "$SOURCE_MANIFEST"; then
    echo "Using verified Freebase source: $FREEBASE_RDF"
    exit 0
  fi
  echo "Existing Freebase source does not match its manifest; refusing overwrite." >&2
  exit 2
fi

if [[ -s "$FREEBASE_RDF" && ! -s "$SOURCE_MANIFEST" ]]; then
  echo "Existing Freebase dump has no source manifest; hashing it without redownloading."
  PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 source-manifest \
    --freebase-rdf "$FREEBASE_RDF" \
    --source-url "$SOURCE_URL" \
    --output "$SOURCE_MANIFEST"
  exit 0
fi

PART="${FREEBASE_RDF}.part"
echo "Downloading the official Google-hosted Freebase RDF dump."
echo "source=$SOURCE_URL"
echo "destination=$FREEBASE_RDF"
curl --fail --location --continue-at - --retry 8 --retry-delay 10 \
  --dump-header "$HTTP_HEADERS" --output "$PART" "$SOURCE_URL"
mv "$PART" "$FREEBASE_RDF"

PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog_v2 source-manifest \
  --freebase-rdf "$FREEBASE_RDF" \
  --source-url "$SOURCE_URL" \
  --http-headers "$HTTP_HEADERS" \
  --output "$SOURCE_MANIFEST"

echo "Freebase source and checksum manifest are ready."
echo "source_manifest=$SOURCE_MANIFEST"
