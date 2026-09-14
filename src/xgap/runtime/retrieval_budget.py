"""Explicit bounded relationship observations, not complete-query answers.

Keep node identities/properties complete. Limit each compiled edge Match in the
native query; one extra row detects actual omission without a second request.
The original coordinator operators then run on these observed leaf relations.
"""
from dataclasses import replace
import hashlib

from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.semantic.program import SemanticOperatorKind as S

PROFILE = "bounded-edge-relations-v1"
REMOTE = {R.REMOTE_QUERY, R.REMOTE_BIND_QUERY}
MAX_ROWS = 1_000_000


def budget_from_artifact(artifact):
    spec = artifact.get("parameters", {}).get("retrieval_budget")
    if spec is None:
        return None
    rows = spec.get("rows") if isinstance(spec, dict) else None
    if (not isinstance(spec, dict) or set(spec) != {"profile", "rows", "fetch_rows", "template_sha256"}
            or spec["profile"] != PROFILE or type(rows) is not int or not 1 <= rows <= MAX_ROWS
            or type(spec["fetch_rows"]) is not int or spec["fetch_rows"] != rows + 1
            or artifact.get("parameters", {}).get("compiler") != "semantic_edge_match_v1"
            or artifact.get("language") not in ("cypher", "sparql")
            or not artifact.get("text", "").endswith(f"\nLIMIT {rows + 1}")
            or hashlib.sha256(artifact["text"].encode()).hexdigest() != spec["template_sha256"]):
        raise ValueError("Invalid compiled relationship retrieval budget")
    return spec


def observe_budget(spec, received):
    return {"profile": PROFILE, "row_budget": spec["rows"], "source_rows_received": received,
        "rows_kept": min(received, spec["rows"]), "source_rows_omitted": received > spec["rows"],
        "selection": "backend_return_order_prefix; not a random sample"}


def apply_retrieval_budget(plan, program, rows):
    if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise ValueError("Relationship row budget must be in 1..1000000")
    if any(op.kind is S.TRAVERSE for op in program.operators):
        raise ValueError("Budgeted mode requires expanded Match relations, not native Traverse selectors")
    nodes, bounded = [], []
    for node in plan.nodes:
        artifact = node.parameters.get("artifact", {})
        params = artifact.get("parameters", {})
        if node.kind in REMOTE and params.get("compiler") == "semantic_edge_match_v1":
            if "retrieval_budget" in params or artifact.get("language") not in ("cypher", "sparql"):
                raise ValueError("Unsupported or already budgeted native relationship query")
            text = artifact["text"] + f"\nLIMIT {rows + 1}"
            spec = {"profile": PROFILE, "rows": rows, "fetch_rows": rows + 1,
                    "template_sha256": hashlib.sha256(text.encode()).hexdigest()}
            artifact = {**artifact, "text": text, "parameters": {**params, "retrieval_budget": spec}}
            budget_from_artifact(artifact)
            node = replace(node, parameters={**node.parameters, "artifact": artifact})
            bounded.append(node.node_id)
        nodes.append(node)
    return replace(plan, nodes=tuple(nodes), metadata={**plan.metadata, "retrieval_budget": {
        "profile": PROFILE, "rows_per_relationship_query": rows, "bounded_nodes": bounded,
        "relationship_wire_row_upper_bound": len(bounded) * (rows + 1),
        "relationship_coordinator_row_upper_bound": len(bounded) * rows,
        "node_identity_and_property_reads": "complete; excluded from relationship row bound",
        "operator_semantics": "original operators evaluated on budgeted leaf relations",
        "coverage_is_strategy_dependent": True,
        "aggregate_values_may_change": any(op.kind is S.AGGREGATE for op in program.operators),
        "ranking_may_change": any(op.kind is S.ORDER_LIMIT for op in program.operators),
        "full_source_quality_bound": None, "backend_internal_scan_bound": None}})


def retrieval_observation(plan, execution_value):
    spec = plan.metadata.get("retrieval_budget")
    if spec is None:
        return None
    observations = {n["node_id"]: n.get("metadata", {}).get("retrieval_budget")
                    for n in execution_value.get("node_results", [])}
    values = [observations.get(n) for n in spec["bounded_nodes"]]
    known = all(v is not None for v in values)
    omitted = any(v and v["source_rows_omitted"] for v in values)
    return {**spec, "coverage_observed": known, "source_rows_omitted": omitted if known else None,
        "complete_for_selected_interpretation": known and not omitted,
        "observations": {n: observations.get(n) for n in spec["bounded_nodes"]},
        "aggregate_values_full_source_exact": known and not omitted,
        "ranking_full_source_exact": known and not omitted,
        "unbiased_estimation_or_confidence_interval": False}
