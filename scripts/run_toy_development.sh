#!/usr/bin/env bash
# Fast everyday backbone checks; no model, catalog build or database daemon.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python}"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" -m pytest -q tests/test_toy_backbone.py tests/test_reified_directed_compiler.py tests/test_bounded_path_execution.py tests/test_semantic_dag_compiler.py tests/test_semantic_planning.py tests/test_semantic_binding_execution.py tests/test_path_orientation.py tests/test_candidate_assessment.py tests/test_semantic_capabilities.py tests/test_finite_regex_repetition.py tests/test_scoped_path_execution.py tests/test_native_boolean_conditions.py
"$PYTHON" examples/toy_backbone_demo.py
