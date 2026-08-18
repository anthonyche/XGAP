#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"
SPEC="experiments/specs/grailqa_semantic_pilot_v1.json"
OUTPUT="${XGAP_GRAILQA_PILOT_OUTPUT:-runs/m13d-grailqa-semantic-pilot-v1}"

case "${1:-}" in
  "") RESUME=() ;;
  --resume) RESUME=(--resume) ;;
  *) echo "Usage: $0 [--resume]" >&2; exit 2 ;;
esac

PYTHONPATH=src "$PYTHON" -m xgap.experiments.run_grailqa_semantic_pilot \
  --spec "$SPEC" \
  --output "$OUTPUT" \
  "${RESUME[@]}"
