#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export XGAP_FINBENCH_LOCK="${XGAP_FINBENCH_LOCK:-$REPO_ROOT/experiments/sources/m15_finbench_v010_sf0_1_sources.json}"
export XGAP_FINBENCH_CACHE="${XGAP_FINBENCH_CACHE:-$HOME/.cache/xgap/finbench-v0.1.0}"
export XGAP_FINBENCH_OUTPUT="${XGAP_FINBENCH_OUTPUT:-$XGAP_FINBENCH_CACHE/sf0.1-inspection.json}"

exec "$SCRIPT_DIR/prepare_m15_finbench_sf001.sh"
