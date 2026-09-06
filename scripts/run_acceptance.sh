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

if [ -f examples/compiler_mvp_demo.py ]; then
  "$PYTHON" examples/compiler_mvp_demo.py
fi

if [ -f examples/llm_boundary_demo.py ]; then
  "$PYTHON" examples/llm_boundary_demo.py
fi

if [ -f examples/m11_physical_planner_demo.py ]; then
  "$PYTHON" examples/m11_physical_planner_demo.py
fi

if [ -f examples/m11_exhaustive_oracle_demo.py ]; then
  "$PYTHON" examples/m11_exhaustive_oracle_demo.py
fi

if [ -f examples/m12_experiment_contract_demo.py ]; then
  "$PYTHON" examples/m12_experiment_contract_demo.py
fi

if [ -f examples/m12c_calibration_demo.py ]; then
  "$PYTHON" examples/m12c_calibration_demo.py
fi

if [ -f examples/m12d_experiment_matrix_demo.py ]; then
  "$PYTHON" examples/m12d_experiment_matrix_demo.py
fi

if [ -f examples/m15_goal_loop_demo.py ]; then
  "$PYTHON" examples/m15_goal_loop_demo.py
fi

if [ -f examples/m15_federated_vertical_slice_demo.py ]; then
  "$PYTHON" examples/m15_federated_vertical_slice_demo.py
fi

if [ -f examples/m15_semantic_intake_demo.py ]; then
  "$PYTHON" examples/m15_semantic_intake_demo.py
fi
