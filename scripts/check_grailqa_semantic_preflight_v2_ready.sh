#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python}"

cd "$REPO_ROOT"
echo "M13-E1 GrailQA semantic preflight v2 readiness"
echo "The offline catalog/retrieval/prompt gate runs before credential validation."
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_preflight check \
  --spec experiments/specs/grailqa_semantic_preflight_v2.json \
  --repo-root "$REPO_ROOT" \
  --require-credentials
