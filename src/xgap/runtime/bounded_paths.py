"""Compile one bounded semantic Traverse into native work plus path selection."""

from xgap.compilers.bounded_paths import compile_bounded_paths
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind


def compile_bounded_path_plan(query, *, backend_id, plan_id="bounded-path-plan", **options):
    try:
        artifact = compile_bounded_paths(query, backend_id=backend_id, **options)
    except UnsupportedCompilationError:
        from xgap.runtime.scoped_paths import compile_scoped_path_plan
        return compile_scoped_path_plan(query, backend_id=backend_id, plan_id=plan_id, **options)
    return FederatedExecutionPlan(plan_id, (
        RuntimeNode("candidates", RuntimeNodeKind.REMOTE_QUERY,
                    parameters={"backend_id": backend_id, "artifact": artifact.to_dict()}),
        RuntimeNode("paths", RuntimeNodeKind.COORDINATOR_PATH_SELECT, ("candidates",),
                    parameters=artifact.parameters["path_selection"]),
    ), ("paths",), max_remote_calls=1, metadata={
        "compiler": "bounded_native_paths_v1", "branch_count": artifact.parameters["branch_count"],
        "selector_placement": "coordinator", "candidate_placement": backend_id})
