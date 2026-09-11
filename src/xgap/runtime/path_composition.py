"""Physical placement of existing concatenation/Recursive over native PathSets."""

from xgap.algebra.evaluator import join_paths, recursive_paths
from xgap.algebra.ops import RecursiveMode
from xgap.runtime.path_selection import normalized_pathset


def compose_paths(inputs, parameters):
    paths = [normalized_pathset(rows) for rows in inputs]
    operation = parameters.get("operation")
    if operation == "join" and len(paths) in (1, 2):
        # One input explicitly means self-concatenation; shared work is not duplicated.
        result = join_paths(paths[0], paths[-1])
    elif operation == "recursive" and len(paths) == 1:
        depth = parameters.get("max_depth")
        if type(depth) is not int or depth <= 0:
            raise ValueError("Scoped native Recursive requires a finite positive depth")
        result = recursive_paths(paths[0], RecursiveMode(parameters["mode"]), depth)
    else:
        raise ValueError("Path composition requires join (one/two inputs) or recursive (one)")
    maximum = parameters["max_edges"]
    if type(maximum) is not int or maximum < 0 or any(len(p) > maximum for p in result):
        raise ValueError("Composed path exceeds its compiled finite edge bound")
    return tuple({"path": list(p.sequence)} for p in result)
