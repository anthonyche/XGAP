#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
PARQUET_ROOT="${XGAP_FREEBASE_PARQUET_ROOT:-$RAW_DIR/hf-archival-parquet}"
FROZEN_SPEC="${XGAP_FREEBASE_PARQUET_SPEC:-$REPO_ROOT/experiments/sources/freebase_hf_archival_parquet_v1.json}"
PYTHON="${PYTHON:-python}"

cd "$REPO_ROOT"
bash scripts/server/download_freebase_archival_parquet.sh --smoke-only
PYTHONPATH=src "$PYTHON" -m xgap.experiments.freebase_sources smoke \
  --parquet-root "$PARQUET_ROOT" \
  --frozen-spec "$FROZEN_SPEC" \
  --shard default/data/0000.parquet \
  --max-row-groups 1
echo "Frozen archival Freebase Parquet smoke passed."
