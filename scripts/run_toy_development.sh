#!/usr/bin/env bash
# Fast everyday backbone checks; no model, catalog build or database daemon.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python}"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" -m pytest -q tests/test_toy_backbone.py tests/test_reified_directed_compiler.py tests/test_bounded_path_execution.py tests/test_semantic_dag_compiler.py tests/test_semantic_planning.py
"$PYTHON" examples/toy_backbone_demo.py
