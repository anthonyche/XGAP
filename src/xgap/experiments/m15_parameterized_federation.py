"""Compile one F2C3 query instance into exact federated runtime plans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedPlanCandidate,
    RuntimeNode,
    RuntimeNodeKind,
)


def _bundle(
    value: M15ParameterizedWorkloadBundle | str | Path,
) -> M15ParameterizedWorkloadBundle:
    if isinstance(value, M15ParameterizedWorkloadBundle):
        return value
    return load_m15_parameterized_workload_bundle(value)


def _json_file(bundle: M15ParameterizedWorkloadBundle, path: str) -> Any:
    return json.loads(bundle.path(path).read_text(encoding="utf-8"))


def _instance_record(
    bundle: M15ParameterizedWorkloadBundle,
    query_id: str,
) -> Mapping[str, Any]:
    matches = [
        item for item in bundle.manifest["instances"] if item["query_id"] == query_id
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown parameterized query instance '{query_id}'")
    return matches[0]


def load_m15_parameterized_contract(
    workload: M15ParameterizedWorkloadBundle | str | Path,
    query_id: str,
) -> dict[str, Any]:
    """Load one contract and binding without opening any answer oracle."""

    bundle = _bundle(workload)
    record = dict(_instance_record(bundle, query_id))
    root = f"instances/{query_id}"
    contract = _json_file(bundle, f"{root}/parameterized_contract.json")
    bindings = _json_file(bundle, f"{root}/bindings.json")
    if contract["query_instance_sha256"] != record["query_instance_sha256"]:
        raise ValueError("query instance contract disagrees with bundle manifest")
    if bindings["query_instance_sha256"] != record["query_instance_sha256"]:
        raise ValueError("query binding artifact disagrees with bundle manifest")
    return {
        "record": record,
        "contract": contract,
        "bindings": bindings,
    }


def load_m15_parameterized_instance(
    workload: M15ParameterizedWorkloadBundle | str | Path,
    query_id: str,
) -> dict[str, Any]:
    """Load one hash-verified instance and its exact expected artifacts."""

    bundle = _bundle(workload)
    identity = load_m15_parameterized_contract(bundle, query_id)
    record = identity["record"]
    root = f"instances/{query_id}"
    source_oracles = _json_file(bundle, f"{root}/expected_source_results.json")
    final_oracle = _json_file(bundle, f"{root}/expected_result.json")
    expected_counts = {
        role: len(rows) for role, rows in source_oracles.items()
    } | {"final": len(final_oracle)}
    if expected_counts != record["oracle_counts"]:
        raise ValueError("query oracle counts disagree with bundle manifest")
    return {
        **identity,
        "source_oracles": source_oracles,
        "final_oracle": final_oracle,
    }


def _alignment_mapping(
    *,
    company_count: int,
    prefix: str,
) -> dict[str, str]:
    """Build namespace alignment from the workload ID domain, never an oracle."""

    width = max(4, len(str(company_count)))
    company_ids = (
        f"C{index:0{width}d}" for index in range(1, company_count + 1)
    )
    return {f"{prefix}{company_id}": company_id for company_id in company_ids}


def _artifact(
    bundle: M15ParameterizedWorkloadBundle,
    query_id: str,
    role: str,
    *,
    language: str,
    parameters: Mapping[str, Any],
) -> QueryArtifact:
    extension = "rq" if language == "sparql" else "cypher"
    path = f"instances/{query_id}/{role}.{extension}"
    return QueryArtifact(
        artifact_id=f"m15-f2c-{query_id}-{role.replace('_', '-')}",
        language=language,
        text=bundle.path(path).read_text(encoding="utf-8"),
        kind="compiled",
        source_path=f"bundle:{bundle.spec.workload_id}/{path}",
        parameters=dict(parameters),
    )


def build_m15_parameterized_query_artifacts(
    workload: M15ParameterizedWorkloadBundle | str | Path,
    *,
    query_id: str,
) -> dict[str, QueryArtifact]:
    """Load the three hash-verified native artifacts for one query instance."""

    bundle = _bundle(workload)
    instance = load_m15_parameterized_contract(bundle, query_id)
    runtime = instance["bindings"]["runtime_parameters"]
    return {
        "neo4j_full": _artifact(
            bundle,
            query_id,
            "neo4j_full",
            language="cypher",
            parameters=runtime["neo4j_full"],
        ),
        "neo4j_bound": _artifact(
            bundle,
            query_id,
            "neo4j_bound",
            language="cypher",
            parameters=runtime["neo4j_bound"],
        ),
        "fuseki_risk": _artifact(
            bundle,
            query_id,
            "fuseki_risk",
            language="sparql",
            parameters=runtime["fuseki_risk"],
        ),
    }


def build_m15_parameterized_plan_candidates(
    workload: M15ParameterizedWorkloadBundle | str | Path,
    *,
    query_id: str,
) -> tuple[FederatedPlanCandidate, ...]:
    """Build parallel-hash and risk-first-bind plans for one exact instance."""

    bundle = _bundle(workload)
    instance = load_m15_parameterized_contract(bundle, query_id)
    record = instance["record"]
    workload_id = bundle.spec.workload_id
    neo4j_prefix = f"neo:{workload_id}:"
    fuseki_prefix = f"rdf:{workload_id}:"
    neo4j_mapping = _alignment_mapping(
        company_count=bundle.spec.company_count,
        prefix=neo4j_prefix,
    )
    fuseki_mapping = _alignment_mapping(
        company_count=bundle.spec.company_count,
        prefix=fuseki_prefix,
    )
    artifacts = build_m15_parameterized_query_artifacts(
        bundle,
        query_id=query_id,
    )
    full = artifacts["neo4j_full"]
    bound = artifacts["neo4j_bound"]
    risk = artifacts["fuseki_risk"]
    observation_prefix = f"m15-f2c:{workload_id}:{query_id}"
    semantic_key = (
        f"{bundle.manifest['family_compatibility_sha256']}:"
        f"{record['query_instance_sha256']}:exact"
    )
    parallel = FederatedExecutionPlan(
        plan_id=f"m15-f2c-{query_id}-parallel-hash",
        nodes=(
            RuntimeNode(
                "recent-transfers",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "neo4j",
                    "artifact": full.to_dict(),
                    "observation_key": f"{observation_prefix}:neo4j-full",
                },
                semantic_operator_ids=(
                    "resolved-person",
                    "recent-large-transfers",
                ),
            ),
            RuntimeNode(
                "risk-matched-companies",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "fuseki",
                    "artifact": risk.to_dict(),
                    "observation_key": f"{observation_prefix}:fuseki-risk",
                },
                semantic_operator_ids=("risk-matched-companies",),
            ),
            RuntimeNode(
                "align-transfers",
                RuntimeNodeKind.ALIGN,
                inputs=("recent-transfers",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": neo4j_mapping,
                },
                semantic_operator_ids=("align-transfer-company",),
            ),
            RuntimeNode(
                "align-risk",
                RuntimeNodeKind.ALIGN,
                inputs=("risk-matched-companies",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": fuseki_mapping,
                },
                semantic_operator_ids=("align-risk-company",),
            ),
            RuntimeNode(
                "exchange-transfers",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-transfers",),
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "exchange-risk",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-risk",),
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "join-answer",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("exchange-transfers", "exchange-risk"),
                parameters={
                    "left_on": "canonical_company_id",
                    "right_on": "canonical_company_id",
                },
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "project-answer",
                RuntimeNodeKind.PROJECT,
                inputs=("join-answer",),
                parameters={
                    "fields": [
                        "person",
                        "company",
                        "amount",
                        "currency",
                        "occurred_on",
                        "risk",
                    ]
                },
                semantic_operator_ids=("answer-projection",),
            ),
        ),
        roots=("project-answer",),
        max_remote_calls=2,
        max_parallelism=2,
        metadata={
            "physical_strategy": "parallel_hash_join",
            "workload_id": workload_id,
            "bundle_content_sha256": bundle.manifest["bundle_content_sha256"],
            "family_compatibility_sha256": bundle.manifest[
                "family_compatibility_sha256"
            ],
            "query_instance_sha256": record["query_instance_sha256"],
            "semantic_deviation": 0,
            "paper_result": False,
        },
    )
    by_id = {node.node_id: node for node in parallel.nodes}
    bind = FederatedExecutionPlan(
        plan_id=f"m15-f2c-{query_id}-risk-first-bind",
        nodes=(
            by_id["risk-matched-companies"],
            by_id["align-risk"],
            by_id["exchange-risk"],
            RuntimeNode(
                "bound-recent-transfers",
                RuntimeNodeKind.REMOTE_BIND_QUERY,
                inputs=("exchange-risk",),
                parameters={
                    "backend_id": "neo4j",
                    "artifact": bound.to_dict(),
                    "observation_key": f"{observation_prefix}:neo4j-bound",
                    "bind_field": "canonical_company_id",
                    "parameter": "company_ids",
                    "max_bindings": bundle.spec.company_count,
                },
                semantic_operator_ids=(
                    "resolved-person",
                    "recent-large-transfers",
                    "federated-company-join",
                ),
            ),
            RuntimeNode(
                "align-bound-transfers",
                RuntimeNodeKind.ALIGN,
                inputs=("bound-recent-transfers",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": neo4j_mapping,
                },
                semantic_operator_ids=("align-transfer-company",),
            ),
            RuntimeNode(
                "exchange-bound-transfers",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-bound-transfers",),
                semantic_operator_ids=("federated-company-join",),
            ),
            RuntimeNode(
                "join-answer",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("exchange-bound-transfers", "exchange-risk"),
                parameters={
                    "left_on": "canonical_company_id",
                    "right_on": "canonical_company_id",
                },
                semantic_operator_ids=("federated-company-join",),
            ),
            by_id["project-answer"],
        ),
        roots=("project-answer",),
        max_remote_calls=2,
        max_parallelism=1,
        metadata={
            **dict(parallel.metadata),
            "physical_strategy": "risk_first_bind_join",
        },
    )
    return (
        FederatedPlanCandidate(parallel, semantic_key),
        FederatedPlanCandidate(bind, semantic_key),
    )
