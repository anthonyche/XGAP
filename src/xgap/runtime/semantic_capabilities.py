"""Admit semantic requirements using the operator's compiled execution nodes."""

from xgap.compilers.features import default_profile
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.semantic.program import SemanticProgramError


_COORDINATOR = {
    R.COORDINATOR_JOIN: ("coordinator.join", "equality_join"),
    R.COORDINATOR_SEMI_JOIN: ("coordinator.semi_join",),
    R.COORDINATOR_GROUP_AGGREGATE: ("coordinator.aggregate",),
    R.COORDINATOR_SORT_LIMIT: ("coordinator.order_limit",),
    R.COORDINATOR_PATH_SELECT: ("coordinator.path_select",),
    R.COORDINATOR_FILTER: ("coordinator.filter",),
    R.COORDINATOR_ROW_PROJECT: ("coordinator.project",),
    R.PROJECT: ("coordinator.project",),
    R.ALIGN: ("coordinator.align",),
    R.MERGE: ("coordinator.union",),
}


def admit_semantic_capabilities(program, nodes, backends):
    """Pure compile-time admission, never an assertion of live availability.

    Native compilers have already checked their actual input/profile/encoding.
    An advertised backend feature alone cannot witness successful compilation.
    Only nodes owned by the requesting semantic operator can fulfill its demand.
    """
    admitted = {}
    for op in program.operators:
        if not op.required_capabilities:
            continue
        witnesses = {}
        for node in nodes:
            if op.operator_id not in node.semantic_operator_ids:
                continue
            capabilities = _COORDINATOR.get(node.kind, ())
            if node.kind is R.REMOTE_QUERY:
                artifact = node.parameters["artifact"]
                backend = backends[node.parameters["backend_id"]]
                profile = backend.profile or default_profile(backend.backend_id)
                language = artifact["language"].lower()
                if profile.backend_id != backend.backend_id or profile.language.lower() != language:
                    raise SemanticProgramError("Native capability witness disagrees with its backend profile")
                capabilities = ("native." + language,)
                if language == "cypher" and profile.data_model == "labeled_property_graph":
                    capabilities += ("property_graph.read",)
                elif language == "sparql" and profile.data_model == "rdf_graph":
                    capabilities += ("rdf_graph.read",)
            for capability in capabilities:
                witnesses.setdefault(capability, []).append(node.node_id)
        missing = sorted(set(op.required_capabilities) - witnesses.keys())
        if missing:
            raise SemanticProgramError(
                f"Operator '{op.operator_id}' has unsatisfied capabilities {missing}; "
                f"compiled operator provides {sorted(witnesses)}")
        admitted[op.operator_id] = {
            "required": list(op.required_capabilities),
            "witnesses": {name: witnesses[name] for name in sorted(op.required_capabilities)},
        }
    return {"version": 1, "operators": admitted} if admitted else None
