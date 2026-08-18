#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python}"
RUN_ID="grailqa-semantic-preflight-v2-$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${XGAP_GRAILQA_PREFLIGHT_OUTPUT:-$REPO_ROOT/runs/$RUN_ID}"

cd "$REPO_ROOT"
bash scripts/check_grailqa_semantic_preflight_v2_ready.sh
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_preflight run \
  --spec experiments/specs/grailqa_semantic_preflight_v2.json \
  --repo-root "$REPO_ROOT" \
  --output "$OUTPUT"
