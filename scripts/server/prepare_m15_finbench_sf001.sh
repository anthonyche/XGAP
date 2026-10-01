#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

XGAP_FINBENCH_PYTHON="${XGAP_PYTHON:-python}"
XGAP_FINBENCH_LOCK="${XGAP_FINBENCH_LOCK:-$REPO_ROOT/experiments/sources/m15_finbench_v010_sources.json}"
XGAP_FINBENCH_CACHE="${XGAP_FINBENCH_CACHE:-$HOME/.cache/xgap/finbench-v0.1.0}"
XGAP_FINBENCH_OUTPUT="${XGAP_FINBENCH_OUTPUT:-$XGAP_FINBENCH_CACHE/sf0.01-inspection.json}"

if ! command -v "$XGAP_FINBENCH_PYTHON" >/dev/null 2>&1; then
  echo "Python is unavailable: $XGAP_FINBENCH_PYTHON" >&2
  exit 1
fi

if [[ ! -f "$XGAP_FINBENCH_LOCK" || -L "$XGAP_FINBENCH_LOCK" ]]; then
  echo "Pinned FinBench artifact lock is missing or unsafe: $XGAP_FINBENCH_LOCK" >&2
  exit 1
fi

if [[ -e "$XGAP_FINBENCH_OUTPUT" || -L "$XGAP_FINBENCH_OUTPUT" ]]; then
  echo "Inspection output already exists; refusing to overwrite: $XGAP_FINBENCH_OUTPUT" >&2
  exit 1
fi

PYTHONPATH="$REPO_ROOT/src" "$XGAP_FINBENCH_PYTHON" \
  -m xgap.experiments.m15_finbench_artifacts prepare \
  --lock "$XGAP_FINBENCH_LOCK" \
  --cache-root "$XGAP_FINBENCH_CACHE" \
  --output "$XGAP_FINBENCH_OUTPUT"
