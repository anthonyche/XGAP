#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"
SPEC="experiments/specs/grailqa_semantic_pilot_v1.json"
OUTPUT="${XGAP_GRAILQA_READINESS_OUTPUT:-runs/grailqa-semantic-pilot-readiness}"

PYTHONPATH=src "$PYTHON" -m xgap.experiments.run_grailqa_semantic_pilot \
  --spec "$SPEC" \
  --output "$OUTPUT" \
  --check-ready

