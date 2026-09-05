"""Executable M15 plans backed by a verified deterministic workload bundle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Mapping

from xgap.experiments.m15_live_federated import build_m15_semantic_program
from xgap.experiments.m15_method_policy import (
    M15PlanMemoryContext,
    build_m15_plan_memory_context,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedPlanCandidate,
    PlanObservationRequest,
    RuntimeNode,
    RuntimeNodeKind,
)
from xgap.semantic import SemanticGraphProgram
from xgap.tools import BackendObservationCatalog, BackendOperation


def _bundle(value: M15WorkloadBundle | str | Path) -> M15WorkloadBundle:
    root = value.root if isinstance(value, M15WorkloadBundle) else value
    return load_m15_workload_bundle(root)


def _artifact(
    bundle: M15WorkloadBundle,
    filename: str,
    *,
    artifact_id: str,
    language: str,
    parameters: Mapping[str, object] | None = None,
) -> QueryArtifact:
    return QueryArtifact(
        artifact_id=artifact_id,
        language=language,
        text=bundle.path(filename).read_text(encoding="utf-8"),
        kind="native",
        source_path=f"bundle:{bundle.spec.workload_id}/{filename}",
        parameters=dict(parameters or {}),
    )


def _alignment_mapping(
    rows: list[dict[str, object]],
    *,
    prefix: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows:
        value = row.get("company_id")
        if not isinstance(value, str) or not value.startswith(prefix):
            raise ValueError(f"source oracle has invalid company_id for prefix '{prefix}'")
        canonical = value.removeprefix(prefix)
        if not canonical:
            raise ValueError("source oracle company_id has an empty canonical suffix")
        mapping[value] = canonical
    return mapping


def _risk_company_ids(bundle: M15WorkloadBundle) -> list[str]:
    prefix = f"rdf:{bundle.spec.workload_id}:"
    mapping = _alignment_mapping(
        bundle.expected_source_rows["fuseki"],
        prefix=prefix,
    )
    return sorted(set(mapping.values()))


def _observation_keys(bundle: M15WorkloadBundle) -> dict[str, str]:
    prefix = f"m15-f0:{bundle.spec.workload_id}"
    return {
        "neo4j_full": f"{prefix}:neo4j-full",
        "neo4j_bound": f"{prefix}:neo4j-bound",
        "fuseki_risk": f"{prefix}:fuseki-risk",
    }


def build_m15_scaled_semantic_program(
    workload: M15WorkloadBundle | str | Path,
) -> SemanticGraphProgram:
    bundle = _bundle(workload)
    base = build_m15_semantic_program()
    return replace(
        base,
        program_id=f"m15-f0-{bundle.spec.workload_id}-exact",
        metadata={
            **dict(base.metadata),
            "dataset_id": f"m15_f0:{bundle.spec.workload_id}",
            "workload_spec_sha256": bundle.manifest["spec_sha256"],
            "workload_generator": bundle.manifest["generator_version"],
            "evidence_class": "deterministic_scaled_development_workload",
            "paper_result": False,
        },
    )


def build_m15_scaled_plan_candidates(
    workload: M15WorkloadBundle | str | Path,
) -> tuple[FederatedPlanCandidate, ...]:
    """Build parallel-hash and risk-first-bind plans for one exact workload."""

    bundle = _bundle(workload)
    workload_id = bundle.spec.workload_id
    ids = _observation_keys(bundle)
    neo4j_full = _artifact(
        bundle,
        "query_recent_transfers.cypher",
        artifact_id=f"m15-f0-{workload_id}-neo4j-full",
        language="cypher",
    )
    neo4j_bound = _artifact(
        bundle,
        "query_recent_transfers_bound.cypher",
        artifact_id=f"m15-f0-{workload_id}-neo4j-bound",
        language="cypher",
    )
    fuseki_risk = _artifact(
        bundle,
        "query_high_risk.rq",
        artifact_id=f"m15-f0-{workload_id}-fuseki-risk",
        language="sparql",
    )
    neo4j_mapping = _alignment_mapping(
        bundle.expected_source_rows["neo4j"],
        prefix=f"neo:{workload_id}:",
    )
    fuseki_mapping = _alignment_mapping(
        bundle.expected_source_rows["fuseki"],
        prefix=f"rdf:{workload_id}:",
    )
    semantic_key = (
        f"m15-f0:{workload_id}:exact:{bundle.manifest['spec_sha256']}"
    )
    parallel = FederatedExecutionPlan(
        plan_id=f"m15-f0-{workload_id}-parallel-hash",
        nodes=(
            RuntimeNode(
                "recent-transfers",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "neo4j",
                    "artifact": neo4j_full.to_dict(),
                    "observation_key": ids["neo4j_full"],
                },
                semantic_operator_ids=("resolved-person", "recent-large-transfers"),
            ),
            RuntimeNode(
                "high-risk",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "fuseki",
                    "artifact": fuseki_risk.to_dict(),
                    "observation_key": ids["fuseki_risk"],
                },
                semantic_operator_ids=("high-risk-companies",),
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
                inputs=("high-risk",),
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
                "answer",
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
                inputs=("answer",),
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
            "dataset_id": f"m15_f0:{workload_id}",
            "physical_strategy": "parallel_hash_join",
            "workload_spec_sha256": bundle.manifest["spec_sha256"],
            "paper_result": False,
        },
    )
    by_id = {node.node_id: node for node in parallel.nodes}
    bind = FederatedExecutionPlan(
        plan_id=f"m15-f0-{workload_id}-risk-first-bind",
        nodes=(
            by_id["high-risk"],
            by_id["align-risk"],
            by_id["exchange-risk"],
            RuntimeNode(
                "bound-recent-transfers",
                RuntimeNodeKind.REMOTE_BIND_QUERY,
                inputs=("exchange-risk",),
                parameters={
                    "backend_id": "neo4j",
                    "artifact": neo4j_bound.to_dict(),
                    "observation_key": ids["neo4j_bound"],
                    "bind_field": "canonical_company_id",
                    "parameter": "company_ids",
                    "max_bindings": bundle.spec.max_bindings,
                },
                semantic_operator_ids=(
                    "resolved-person",
                    "recent-large-transfers",
                    "federated-company-join",
                ),
            ),
            replace(
                by_id["align-transfers"],
                node_id="align-bound-transfers",
                inputs=("bound-recent-transfers",),
            ),
            replace(
                by_id["exchange-transfers"],
                node_id="exchange-bound-transfers",
                inputs=("align-bound-transfers",),
            ),
            replace(
                by_id["answer"],
                inputs=("exchange-bound-transfers", "exchange-risk"),
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


def build_m15_scaled_observation_catalogs(
    workload: M15WorkloadBundle | str | Path,
) -> dict[str, BackendObservationCatalog]:
    bundle = _bundle(workload)
    workload_id = bundle.spec.workload_id
    token = workload_id.replace("-", "_").upper()
    risk_ids = _risk_company_ids(bundle)
    version = str(bundle.manifest["spec_sha256"])[:16]
    return {
        "neo4j": BackendObservationCatalog(
            catalog_id=f"m15-f0-{workload_id}-neo4j-observations",
            version=version,
            schema_artifact=QueryArtifact(
                f"m15-f0-{workload_id}-neo4j-labels",
                "cypher",
                "CALL db.labels() YIELD label RETURN label ORDER BY label",
            ),
            query_artifacts={
                "recent-transfers-full": _artifact(
                    bundle,
                    "query_recent_transfers.cypher",
                    artifact_id=f"m15-f0-{workload_id}-neo4j-full",
                    language="cypher",
                ),
                "recent-transfers-bound": _artifact(
                    bundle,
                    "query_recent_transfers_bound.cypher",
                    artifact_id=f"m15-f0-{workload_id}-neo4j-bound",
                    language="cypher",
                    parameters={"company_ids": risk_ids},
                ),
            },
            sample_artifacts={
                "company-refs": QueryArtifact(
                    f"m15-f0-{workload_id}-company-ref-sample",
                    "cypher",
                    (
                        f"MATCH (c:M15F0_{token}_CompanyRef) "
                        "RETURN c.id AS company_id ORDER BY company_id LIMIT 10"
                    ),
                )
            },
        ),
        "fuseki": BackendObservationCatalog(
            catalog_id=f"m15-f0-{workload_id}-fuseki-observations",
            version=version,
            schema_artifact=QueryArtifact(
                f"m15-f0-{workload_id}-fuseki-predicates",
                "sparql",
                (
                    "SELECT DISTINCT ?predicate WHERE { ?subject ?predicate ?object } "
                    "ORDER BY ?predicate LIMIT 100"
                ),
            ),
            query_artifacts={
                "high-risk": _artifact(
                    bundle,
                    "query_high_risk.rq",
                    artifact_id=f"m15-f0-{workload_id}-fuseki-risk",
                    language="sparql",
                )
            },
            sample_artifacts={
                "companies": QueryArtifact(
                    f"m15-f0-{workload_id}-fuseki-company-sample",
                    "sparql",
                    (
                        f"PREFIX data: <http://xgap.example.org/m15-f0/{workload_id}/> "
                        "SELECT ?company_id WHERE { ?company a data:Company ; "
                        "data:companyId ?company_id } ORDER BY ?company_id LIMIT 10"
                    ),
                )
            },
        ),
    }


def build_m15_scaled_observation_requests(
    workload: M15WorkloadBundle | str | Path,
) -> tuple[PlanObservationRequest, ...]:
    bundle = _bundle(workload)
    ids = _observation_keys(bundle)
    return (
        PlanObservationRequest(
            "profile-neo4j-full",
            ids["neo4j_full"],
            "neo4j",
            BackendOperation.PROFILE,
            {"query_id": "recent-transfers-full"},
        ),
        PlanObservationRequest(
            "profile-neo4j-bound",
            ids["neo4j_bound"],
            "neo4j",
            BackendOperation.PROFILE,
            {"query_id": "recent-transfers-bound"},
        ),
        PlanObservationRequest(
            "profile-fuseki-risk",
            ids["fuseki_risk"],
            "fuseki",
            BackendOperation.PROFILE,
            {"query_id": "high-risk"},
        ),
    )


def build_m15_scaled_probe_plan(
    workload: M15WorkloadBundle | str | Path,
) -> FederatedExecutionPlan:
    bundle = _bundle(workload)
    candidates = build_m15_scaled_plan_candidates(bundle)
    nodes = {node.node_id: node for node in candidates[0].plan.nodes}
    return FederatedExecutionPlan(
        plan_id=f"m15-f0-{bundle.spec.workload_id}-risk-probe-prefix",
        nodes=(nodes["high-risk"], nodes["align-risk"], nodes["exchange-risk"]),
        roots=("exchange-risk",),
        max_remote_calls=1,
        max_parallelism=1,
        metadata={
            "execution_phase": "adaptive_probe",
            "evidence_class": "deterministic_scaled_development_workload",
            "workload_spec_sha256": bundle.manifest["spec_sha256"],
            "paper_result": False,
        },
    )


def build_m15_scaled_plan_memory_context(
    workload: M15WorkloadBundle | str | Path,
    *,
    bandwidth_bytes_per_ms: float,
    exchange_fixed_ms: float,
    coordinator_row_ms: float,
) -> M15PlanMemoryContext:
    """Bind reusable task memory to the complete scaled-workload contract."""

    bundle = _bundle(workload)
    candidates = build_m15_scaled_plan_candidates(bundle)
    requests = build_m15_scaled_observation_requests(bundle)
    catalogs = build_m15_scaled_observation_catalogs(bundle)
    catalog_binding = {
        backend_id: {
            "catalog_id": catalog.catalog_id,
            "version": catalog.version,
            "schema_artifact": (
                catalog.schema_artifact.to_dict()
                if catalog.schema_artifact is not None
                else None
            ),
            "query_artifacts": {
                key: artifact.to_dict()
                for key, artifact in sorted(catalog.query_artifacts.items())
            },
            "sample_artifacts": {
                key: artifact.to_dict()
                for key, artifact in sorted(catalog.sample_artifacts.items())
            },
        }
        for backend_id, catalog in sorted(catalogs.items())
    }
    return build_m15_plan_memory_context(
        context_id=f"m15-f1-{bundle.spec.workload_id}",
        candidates=candidates,
        requests=requests,
        bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
        exchange_fixed_ms=exchange_fixed_ms,
        coordinator_row_ms=coordinator_row_ms,
        binding={
            "workload_manifest": dict(bundle.manifest),
            "observation_catalogs": catalog_binding,
        },
    )
