#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

XGAP_FINBENCH_PYTHON="${XGAP_PYTHON:-python}"
XGAP_FINBENCH_LOCK="${XGAP_FINBENCH_LOCK:-$REPO_ROOT/experiments/sources/m15_finbench_v010_sources.json}"
XGAP_FINBENCH_SPEC="${XGAP_FINBENCH_SPEC:-$REPO_ROOT/experiments/configs/m15_finbench_primary_population_v1.json}"
XGAP_FINBENCH_CACHE="${XGAP_FINBENCH_CACHE:-$HOME/.cache/xgap/finbench-v0.1.0}"
XGAP_FINBENCH_ARCHIVE="${XGAP_FINBENCH_ARCHIVE:-$XGAP_FINBENCH_CACHE/sf0.01.tar.gz}"
XGAP_FINBENCH_PARTITION="${XGAP_FINBENCH_PARTITION:-$XGAP_FINBENCH_CACHE/sf0.01-xgap-heterogeneous-v1}"
XGAP_FINBENCH_WORKLOAD="${XGAP_FINBENCH_WORKLOAD:-$XGAP_FINBENCH_CACHE/sf0.01-primary-3family-v1}"

if ! command -v "$XGAP_FINBENCH_PYTHON" >/dev/null 2>&1; then
  echo "Python is unavailable: $XGAP_FINBENCH_PYTHON" >&2
  exit 1
fi

for input in "$XGAP_FINBENCH_LOCK" "$XGAP_FINBENCH_SPEC" "$XGAP_FINBENCH_ARCHIVE"; do
  if [[ ! -f "$input" || -L "$input" ]]; then
    echo "Required FinBench input is missing or unsafe: $input" >&2
    exit 1
  fi
done

if [[ ! -d "$XGAP_FINBENCH_PARTITION" || -L "$XGAP_FINBENCH_PARTITION" ]]; then
  echo "Verified FinBench partition is missing or unsafe: $XGAP_FINBENCH_PARTITION" >&2
  echo "Run scripts/server/build_m15_finbench_partition.sh first." >&2
  exit 1
fi

if [[ -e "$XGAP_FINBENCH_WORKLOAD" || -L "$XGAP_FINBENCH_WORKLOAD" ]]; then
  echo "Workload output already exists; refusing to overwrite: $XGAP_FINBENCH_WORKLOAD" >&2
  exit 1
fi

PYTHONPATH="$REPO_ROOT/src" "$XGAP_FINBENCH_PYTHON" \
  -m xgap.experiments.m15_finbench_workload \
  --archive "$XGAP_FINBENCH_ARCHIVE" \
  --partition-root "$XGAP_FINBENCH_PARTITION" \
  --lock "$XGAP_FINBENCH_LOCK" \
  --spec "$XGAP_FINBENCH_SPEC" \
  --output-root "$XGAP_FINBENCH_WORKLOAD"
