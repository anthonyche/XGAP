#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"
SPEC="experiments/specs/grailqa_semantic_pilot_v1.json"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${XGAP_GRAILQA_SMOKE_OUTPUT:-runs/grailqa-semantic-pilot-smoke-$STAMP}"

echo "M13-D credentialed infrastructure smoke: fixed first 3 frozen pilot IDs"
echo "output=$OUTPUT"
PYTHONPATH=src "$PYTHON" -m xgap.experiments.run_grailqa_semantic_pilot \
  --spec "$SPEC" \
  --output "$OUTPUT" \
  --max-queries 3

