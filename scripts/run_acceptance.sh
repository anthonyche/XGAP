#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"

"$PYTHON" scripts/check_harness.py
"$PYTHON" -m pytest

if [ -f examples/core_algebra_demo.py ]; then
  "$PYTHON" examples/core_algebra_demo.py
fi

if [ -f examples/plan_print_demo.py ]; then
  "$PYTHON" examples/plan_print_demo.py
fi

if [ -f examples/recursive_demo.py ]; then
  "$PYTHON" examples/recursive_demo.py
fi

if [ -f examples/solution_space_demo.py ]; then
  "$PYTHON" examples/solution_space_demo.py
fi

if [ -f examples/semantic_audit_demo.py ]; then
  "$PYTHON" examples/semantic_audit_demo.py
fi

if [ -f examples/lowering_demo.py ]; then
  "$PYTHON" examples/lowering_demo.py
fi

if [ -f examples/pattern_lowering_audit_demo.py ]; then
  "$PYTHON" examples/pattern_lowering_audit_demo.py
fi

if [ -f examples/quantified_pattern_demo.py ]; then
  "$PYTHON" examples/quantified_pattern_demo.py
fi
