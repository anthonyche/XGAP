"""Compile FinBench-derived public instances into federated runtime plans.

The compiler reads only the public workload contract and hash-verified native
templates.  Answer oracles are deliberately outside this module so physical
selection and online execution cannot inspect them before a plan is sealed.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
)
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedPlanCandidate,
    RuntimeNode,
    RuntimeNodeKind,
)


FEDERATION_SCHEMA_VERSION = "m15-finbench-federation-v1"
MAX_CONTROL_BINDINGS = 250_000
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_F1 = "f1_direct_transfer_control"
_F2 = "f2_temporal_path_control"
_F3 = "f3_aggregate_risk_ranking"
_STRATEGIES = {
    _F1: ("graph_first_hash", "control_first_bind"),
    _F2: ("path_first_hash", "control_first_bound_path"),
    _F3: ("aggregate_first_hash", "control_first_bound_aggregate"),
}
_RESULT_FIELDS = {
    _F1: ("company_id", "account_id", "total_amount"),
    _F2: ("other_id", "account_distance", "medium_id", "medium_type"),
    _F3: ("company_id", "total_amount"),
}


def _instance(public: Mapping[str, Any], query_id: str) -> dict[str, Any]:
    if not _SAFE_ID.fullmatch(query_id):
        raise ValueError("FinBench query_id is unsafe")
    raw = public.get("instances")
    if not isinstance(raw, list):
        raise ValueError("FinBench public instance list is invalid")
    matches = [item for item in raw if isinstance(item, Mapping) and item.get("query_id") == query_id]
    if len(matches) != 1:
        raise ValueError(f"unknown FinBench query instance '{query_id}'")
    selected = dict(matches[0])
    family_id = selected.get("family_id")
    if family_id not in _STRATEGIES:
        raise ValueError("FinBench query family is unsupported")
    parameters = selected.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("FinBench query parameters are invalid")
    selected["parameters"] = dict(parameters)
    return selected


def _template(root: Path, name: str) -> str:
    path = root / "templates" / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"FinBench query template is missing or unsafe: {name}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"FinBench query template is empty: {name}")
    return text


def _rdf_string_literal(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("FinBench RDF literal must be a short nonempty string")
    if any(ord(character) < 0x20 for character in value):
        raise ValueError("FinBench RDF literal contains a control character")
    return json.dumps(value, ensure_ascii=True)


def _artifact(
    *,
    root: Path,
    query_id: str,
    role: str,
    language: str,
    parameters: Mapping[str, Any],
    template_name: str,
    risk_level: object | None = None,
) -> QueryArtifact:
    text = _template(root, template_name)
    if risk_level is None:
        if "{{" in text or "}}" in text:
            raise ValueError("unbound placeholder remains in FinBench template")
    else:
        placeholder = "{{risk_level_literal}}"
        if text.count(placeholder) != 1:
            raise ValueError("FinBench risk template placeholder contract drifted")
        text = text.replace(placeholder, _rdf_string_literal(risk_level))
        if "{{" in text or "}}" in text:
            raise ValueError("unbound placeholder remains in FinBench risk query")
    return QueryArtifact(
        artifact_id=f"m15-finbench-{query_id}-{role.replace('_', '-')}",
        language=language,
        text=text,
        kind="compiled",
        source_path=f"workload:templates/{template_name}",
        parameters=dict(parameters),
    )


def build_finbench_query_artifacts(
    workload_root: str | Path, *, query_id: str
) -> dict[str, QueryArtifact]:
    """Bind one public instance to native artifacts without reading its oracle."""

    workload = load_finbench_primary_public_workload(workload_root)
    instance = _instance(workload["public_instances"], query_id)
    family_id = str(instance["family_id"])
    parameters = instance["parameters"]
    root = Path(workload["root"])
    if family_id == _F1:
        required = {"person_id", "start_time", "end_time"}
        if set(parameters) != required:
            raise ValueError("FinBench F1 parameter contract drifted")
        native_parameters = {key: parameters[key] for key in sorted(required)}
        return {
            "neo4j_full": _artifact(
                root=root,
                query_id=query_id,
                role="neo4j_full",
                language="cypher",
                parameters=native_parameters,
                template_name="f1_neo4j_full.cypher.tmpl",
            ),
            "neo4j_bound": _artifact(
                root=root,
                query_id=query_id,
                role="neo4j_bound",
                language="cypher",
                parameters=native_parameters,
                template_name="f1_neo4j_bound.cypher.tmpl",
            ),
            "fuseki_control": _artifact(
                root=root,
                query_id=query_id,
                role="fuseki_control",
                language="sparql",
                parameters={},
                template_name="f1_fuseki_control.rq.tmpl",
            ),
        }
    if family_id == _F2:
        required = {"start_account_id", "start_time", "end_time", "max_hops"}
        if set(parameters) != required or parameters.get("max_hops") != 3:
            raise ValueError("FinBench F2 parameter contract drifted")
        native_parameters = {
            key: parameters[key]
            for key in ("start_account_id", "start_time", "end_time")
        }
        return {
            "neo4j_full": _artifact(
                root=root,
                query_id=query_id,
                role="neo4j_full",
                language="cypher",
                parameters=native_parameters,
                template_name="f2_neo4j_full.cypher.tmpl",
            ),
            "neo4j_bound": _artifact(
                root=root,
                query_id=query_id,
                role="neo4j_bound",
                language="cypher",
                parameters=native_parameters,
                template_name="f2_neo4j_bound.cypher.tmpl",
            ),
            "fuseki_control": _artifact(
                root=root,
                query_id=query_id,
                role="fuseki_control",
                language="sparql",
                parameters={},
                template_name="f2_fuseki_control.rq.tmpl",
            ),
        }
    required = {"start_time", "end_time", "risk_level", "top_k"}
    if set(parameters) != required:
        raise ValueError("FinBench F3 parameter contract drifted")
    top_k = parameters.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("FinBench F3 top_k must be a positive integer")
    native_parameters = {
        "start_time": parameters["start_time"],
        "end_time": parameters["end_time"],
        "top_k": top_k,
    }
    return {
        "neo4j_full": _artifact(
            root=root,
            query_id=query_id,
            role="neo4j_full",
            language="cypher",
            parameters={key: native_parameters[key] for key in ("start_time", "end_time")},
            template_name="f3_neo4j_full.cypher.tmpl",
        ),
        "neo4j_bound": _artifact(
            root=root,
            query_id=query_id,
            role="neo4j_bound",
            language="cypher",
            parameters=native_parameters,
            template_name="f3_neo4j_bound.cypher.tmpl",
        ),
        "fuseki_control": _artifact(
            root=root,
            query_id=query_id,
            role="fuseki_control",
            language="sparql",
            parameters={},
            template_name="f3_fuseki_control.rq.tmpl",
            risk_level=parameters["risk_level"],
        ),
    }


def _remote(
    node_id: str,
    backend_id: str,
    artifact: QueryArtifact,
    observation_key: str,
    semantic_operator_ids: Sequence[str],
) -> RuntimeNode:
    return RuntimeNode(
        node_id,
        RuntimeNodeKind.REMOTE_QUERY,
        parameters={
            "backend_id": backend_id,
            "artifact": artifact.to_dict(),
            "observation_key": observation_key,
        },
        semantic_operator_ids=tuple(semantic_operator_ids),
    )


def _exchange(node_id: str, input_id: str, semantic_id: str) -> RuntimeNode:
    return RuntimeNode(
        node_id,
        RuntimeNodeKind.EXCHANGE,
        inputs=(input_id,),
        semantic_operator_ids=(semantic_id,),
    )


def _bound_remote(
    *,
    artifact: QueryArtifact,
    input_id: str,
    bind_field: str,
    observation_key: str,
) -> RuntimeNode:
    return RuntimeNode(
        "neo4j-bound",
        RuntimeNodeKind.REMOTE_BIND_QUERY,
        inputs=(input_id,),
        parameters={
            "backend_id": "neo4j",
            "artifact": artifact.to_dict(),
            "observation_key": observation_key,
            "bind_field": bind_field,
            "parameter": "control_ids",
            "max_bindings": MAX_CONTROL_BINDINGS,
        },
        semantic_operator_ids=("bind-control-domain", "execute-graph-fragment"),
    )


def _project(input_id: str, family_id: str) -> RuntimeNode:
    return RuntimeNode(
        "project-answer",
        RuntimeNodeKind.PROJECT,
        inputs=(input_id,),
        parameters={"fields": list(_RESULT_FIELDS[family_id])},
        semantic_operator_ids=("answer-projection",),
    )


def _plan(
    *,
    workload: Mapping[str, Any],
    instance: Mapping[str, Any],
    strategy: str,
    artifacts: Mapping[str, QueryArtifact],
) -> FederatedExecutionPlan:
    family_id = str(instance["family_id"])
    query_id = str(instance["query_id"])
    workload_sha = str(workload["manifest"]["workload_sha256"])
    prefix = f"m15-finbench:{workload_sha}:{query_id}"
    control = _remote(
        "fuseki-control",
        "fuseki",
        artifacts["fuseki_control"],
        f"{prefix}:fuseki-control",
        ("resolve-control-predicate", "scan-control-domain"),
    )
    exchange_control = _exchange(
        "exchange-control", "fuseki-control", "federated-control-exchange"
    )
    metadata = {
        "schema_version": FEDERATION_SCHEMA_VERSION,
        "population_id": workload["manifest"]["population_id"],
        "workload_sha256": workload_sha,
        "query_id": query_id,
        "family_id": family_id,
        "split_role": instance["split_role"],
        "physical_strategy": strategy,
        "semantic_deviation": 0,
        "current_query_profile_calls": 0,
        "paper_result": False,
    }
    graph_full = _remote(
        "neo4j-full",
        "neo4j",
        artifacts["neo4j_full"],
        f"{prefix}:neo4j-full",
        ("execute-graph-fragment",),
    )
    exchange_full = _exchange(
        "exchange-graph", "neo4j-full", "federated-graph-exchange"
    )

    if strategy in {_F1: "graph_first_hash", _F2: "path_first_hash", _F3: "aggregate_first_hash"}.values():
        nodes: list[RuntimeNode] = [graph_full, control, exchange_full, exchange_control]
        if family_id == _F1:
            nodes.extend(
                (
                    RuntimeNode(
                        "join-control",
                        RuntimeNodeKind.COORDINATOR_SEMI_JOIN,
                        inputs=("exchange-graph", "exchange-control"),
                        parameters={"left_on": "account_id", "right_on": "account_id"},
                        semantic_operator_ids=("federated-control-semi-join",),
                    ),
                    _project("join-control", family_id),
                )
            )
            root = "project-answer"
        elif family_id == _F2:
            nodes.extend(
                (
                    RuntimeNode(
                        "join-control",
                        RuntimeNodeKind.COORDINATOR_JOIN,
                        inputs=("exchange-graph", "exchange-control"),
                        parameters={"left_on": "medium_id", "right_on": "medium_id"},
                        semantic_operator_ids=("federated-control-join",),
                    ),
                    _project("join-control", family_id),
                )
            )
            root = "project-answer"
        else:
            top_k = int(instance["parameters"]["top_k"])
            nodes.extend(
                (
                    RuntimeNode(
                        "join-control",
                        RuntimeNodeKind.COORDINATOR_SEMI_JOIN,
                        inputs=("exchange-graph", "exchange-control"),
                        parameters={
                            "left_on": "medium_ids",
                            "right_on": "medium_id",
                            "left_value_mode": "collection",
                        },
                        semantic_operator_ids=("federated-control-semi-join",),
                    ),
                    RuntimeNode(
                        "aggregate-company",
                        RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE,
                        inputs=("join-control",),
                        parameters={
                            "group_by": ["company_id"],
                            "aggregations": {
                                "total_amount": {"op": "sum", "field": "account_amount"}
                            },
                            "group_reduction_fraction": 0.5,
                        },
                        semantic_operator_ids=("aggregate-company-transfer-amount",),
                    ),
                    _project("aggregate-company", family_id),
                    RuntimeNode(
                        "top-k-answer",
                        RuntimeNodeKind.COORDINATOR_SORT_LIMIT,
                        inputs=("project-answer",),
                        parameters={
                            "order_by": [
                                {"field": "total_amount", "direction": "desc"},
                                {"field": "company_id", "direction": "asc"},
                            ],
                            "limit": top_k,
                        },
                        semantic_operator_ids=("rank-and-limit",),
                    ),
                )
            )
            root = "top-k-answer"
        return FederatedExecutionPlan(
            plan_id=f"m15-finbench-{query_id}-{strategy}",
            nodes=tuple(nodes),
            roots=(root,),
            max_remote_calls=2,
            max_parallelism=2,
            metadata=metadata,
        )

    bind_field = "account_id" if family_id == _F1 else "medium_id"
    bound = _bound_remote(
        artifact=artifacts["neo4j_bound"],
        input_id="exchange-control",
        bind_field=bind_field,
        observation_key=f"{prefix}:neo4j-bound",
    )
    exchange_bound = _exchange(
        "exchange-graph", "neo4j-bound", "federated-graph-exchange"
    )
    nodes = [control, exchange_control, bound, exchange_bound]
    if family_id == _F2:
        nodes.append(
            RuntimeNode(
                "join-control",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("exchange-graph", "exchange-control"),
                parameters={"left_on": "medium_id", "right_on": "medium_id"},
                semantic_operator_ids=("federated-control-join",),
            )
        )
        project_input = "join-control"
    else:
        project_input = "exchange-graph"
    nodes.append(_project(project_input, family_id))
    root = "project-answer"
    if family_id == _F3:
        nodes.append(
            RuntimeNode(
                "top-k-answer",
                RuntimeNodeKind.COORDINATOR_SORT_LIMIT,
                inputs=("project-answer",),
                parameters={
                    "order_by": [
                        {"field": "total_amount", "direction": "desc"},
                        {"field": "company_id", "direction": "asc"},
                    ],
                    "limit": int(instance["parameters"]["top_k"]),
                },
                semantic_operator_ids=("rank-and-limit",),
            )
        )
        root = "top-k-answer"
    return FederatedExecutionPlan(
        plan_id=f"m15-finbench-{query_id}-{strategy}",
        nodes=tuple(nodes),
        roots=(root,),
        max_remote_calls=2,
        max_parallelism=1,
        metadata=metadata,
    )


def build_finbench_plan_candidates(
    workload_root: str | Path, *, query_id: str
) -> tuple[FederatedPlanCandidate, ...]:
    """Build two exact, semantically equivalent physical plans for one query."""

    workload = load_finbench_primary_public_workload(workload_root)
    instance = _instance(workload["public_instances"], query_id)
    artifacts = build_finbench_query_artifacts(workload_root, query_id=query_id)
    family_id = str(instance["family_id"])
    semantic_key = (
        f"{workload['manifest']['workload_sha256']}:{query_id}:exact"
    )
    return tuple(
        FederatedPlanCandidate(
            _plan(
                workload=workload,
                instance=instance,
                strategy=strategy,
                artifacts=artifacts,
            ),
            semantic_key,
        )
        for strategy in _STRATEGIES[family_id]
    )


def _amount(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("FinBench amount must be numeric")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("FinBench amount must be numeric") from exc
    if not decimal.is_finite():
        raise ValueError("FinBench amount must be finite")
    return format(decimal.quantize(Decimal("0.001")), "f")


def canonicalize_finbench_rows(
    family_id: str, rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize native scalar types and deterministic answer order for comparison."""

    if family_id not in _RESULT_FIELDS:
        raise ValueError("FinBench query family is unsupported")
    expected = set(_RESULT_FIELDS[family_id])
    result: list[dict[str, Any]] = []
    for row in rows:
        if set(row) != expected:
            raise ValueError("FinBench result row schema does not match its family")
        normalized = dict(row)
        if "total_amount" in normalized:
            normalized["total_amount"] = _amount(normalized["total_amount"])
        if "account_distance" in normalized:
            distance = normalized["account_distance"]
            if isinstance(distance, bool):
                raise ValueError("FinBench account distance must be an integer")
            try:
                integer = int(distance)
            except (TypeError, ValueError) as exc:
                raise ValueError("FinBench account distance must be an integer") from exc
            if integer < 1 or integer > 3 or float(distance) != integer:
                raise ValueError("FinBench account distance is outside 1..3")
            normalized["account_distance"] = integer
        result.append(normalized)
    if family_id == _F1:
        return sorted(result, key=lambda row: (str(row["company_id"]), str(row["account_id"])))
    if family_id == _F2:
        return sorted(
            result,
            key=lambda row: (
                int(row["account_distance"]),
                str(row["other_id"]),
                str(row["medium_id"]),
            ),
        )
    return sorted(
        result,
        key=lambda row: (-Decimal(str(row["total_amount"])), str(row["company_id"])),
    )


def compare_finbench_result_to_oracle(
    workload_root: str | Path,
    *,
    query_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Open the sealed oracle only after execution and compare exact final rows."""

    from xgap.experiments.m15_finbench_workload import load_finbench_primary_workload

    workload = load_finbench_primary_workload(workload_root)
    instance = _instance(workload["public_instances"], query_id)
    oracle = workload["sealed_oracles"]["queries"].get(query_id)
    if not isinstance(oracle, Mapping) or not isinstance(oracle.get("final_rows"), list):
        raise ValueError("FinBench final oracle is invalid")
    actual = canonicalize_finbench_rows(str(instance["family_id"]), rows)
    expected = canonicalize_finbench_rows(
        str(instance["family_id"]), oracle["final_rows"]
    )
    return {
        "query_id": query_id,
        "family_id": instance["family_id"],
        "exact": actual == expected,
        "actual_row_count": len(actual),
        "expected_row_count": len(expected),
        "actual_rows": actual,
        "expected_rows": expected,
    }
