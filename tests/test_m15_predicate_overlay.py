from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pytest

from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_fixture import (
    load_m15_parameterized_fixture,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    PREDICATE_OVERLAY_SCHEMA_VERSION,
    PREDICATE_WORKLOAD_BUNDLE_SCHEMA_VERSION,
    M15PredicateMappingSpec,
    M15PredicateOverlayError,
    generate_m15_predicate_overlay_bundle,
    load_m15_predicate_overlay_workload_bundle,
    load_m15_predicate_overlay_bundle,
    main,
)
from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = (
    REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
)
QUERY_TEMPLATE = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
SEMANTIC_CATALOG = (
    REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
)
PREDICATE_MAPPING = (
    REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
)
BASE_QUERY_ID = "financial-risk-alice-aug-high-v2"
BASE_BUNDLE_SHA256 = (
    "b06b1c4b4e630e37cbea8d4cf5d81bbc31c4a2280b97a64f5a4a9efed0d434e7"
)


def _base_bundle(tmp_path: Path, name: str = "base"):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / name,
    )


def _overlay(tmp_path: Path, name: str = "predicate-overlay"):
    base = _base_bundle(tmp_path)
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        destination=tmp_path / name,
    )
    return base, overlay


def _bindings(bundle, query_id: str) -> dict[str, object]:
    contract = load_m15_parameterized_instance(bundle, query_id)["contract"]
    return {item["slot_id"]: item["value"] for item in contract["bindings"]}


@dataclass
class PredicateOracleClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "predicate fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        rows = [dict(row) for row in self.rows_by_artifact[artifact.artifact_id]]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
        )


def _clients(bundle) -> dict[str, PredicateOracleClient]:
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    for query_id in bundle.instance_ids():
        sources = load_m15_parameterized_instance(bundle, query_id)[
            "source_oracles"
        ]
        prefix = f"m15-f2c-{query_id}"
        rows["neo4j"][f"{prefix}-neo4j-full"] = sources["neo4j_full"]
        rows["neo4j"][f"{prefix}-neo4j-bound"] = sources["neo4j_full"]
        rows["fuseki"][f"{prefix}-fuseki-risk"] = sources["fuseki_risk"]
    return {
        backend_id: PredicateOracleClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


def _scheduler(bundle) -> FederatedScheduler:
    plugins = BackendPluginRegistry()
    for backend_id, client in _clients(bundle).items():
        plugins.register(
            NativeBackendPlugin(
                backend_id,
                client,
            )
        )
    return FederatedScheduler(BackendInvokeTool(plugins))


@dataclass
class PredicateFixtureLoader:
    backend_id: str
    loaded_paths: list[Path]

    def load(self, path: Path) -> BackendLoadReport:
        self.loaded_paths.append(path)
        return BackendLoadReport(
            backend_id=self.backend_id,
            success=True,
            operations_attempted=1,
            bytes_sent=path.stat().st_size,
            elapsed_ms=1.0,
        )


def test_predicate_overlay_binds_all_direct_classes_only(tmp_path: Path) -> None:
    base, overlay = _overlay(tmp_path)
    manifest = overlay.to_dict()

    assert manifest["schema_version"] == PREDICATE_OVERLAY_SCHEMA_VERSION
    assert overlay.workload_bundle.manifest["schema_version"] == (
        PREDICATE_WORKLOAD_BUNDLE_SCHEMA_VERSION
    )
    assert manifest["counts"] == {
        "semantic_classes": 12,
        "direct_supported_classes": 4,
        "overlay_instances": 3,
        "predicate_enabled_instances": 2,
        "path_blocked_classes": 8,
        "base_query_instances": 6,
        "total_query_instances": 9,
        "payment_edges": 720,
    }
    assert {
        tuple(item["changed_slot_ids"])
        for item in manifest["overlay_instances"]
    } == {
        ("risk-level",),
        ("transfer-predicate",),
        ("risk-level", "transfer-predicate"),
    }
    assert manifest["remaining_blockers"] == [
        "path_semantics_unbound",
        "path_backend_template_missing",
        "path_data_missing",
        "path_oracle_support_missing",
    ]
    assert manifest["base_workload_bundle_content_sha256"] == (
        base.manifest["bundle_content_sha256"]
    )
    assert len(manifest["overlay_sha256"]) == 64
    assert manifest["paper_result"] is False


def test_mapping_is_catalog_bound_and_explicitly_development_only(
    tmp_path: Path,
) -> None:
    _, overlay = _overlay(tmp_path)

    assert overlay.mapping.to_dict() == json.loads(
        PREDICATE_MAPPING.read_text(encoding="utf-8")
    )
    assert overlay.manifest["predicate_mapping"] == {
        "mapping_id": "financial-relation-siblings-development-v1",
        "mapping_sha256": overlay.workload_bundle.manifest[
            "predicate_mapping_sha256"
        ],
        "transition_id": "transfer-to-payment-sibling",
        "source_predicate": "transfer_to_company",
        "target_predicate": "payment_to_company",
        "transformation": "ontology_sibling",
        "evidence": {
            "kind": "development_mapping_fixture",
            "reference": "financial-relation-siblings-v1",
        },
        "backend_relationship_type": "PAYMENT_TO_COMPANY",
    }
    assert overlay.manifest["claim_boundary"] == {
        "artifact_class": "unexecuted_predicate_relaxation_overlay",
        "development_mapping_fixture": True,
        "all_direct_semantic_classes_bound": True,
        "multihop_classes_materialized": False,
        "base_bundle_mutated": False,
        "relaxed_backend_artifacts_bound": True,
        "relaxed_oracles_bound": True,
        "semantic_user_utility_validated": False,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "contains_measurements": False,
        "paper_result": False,
    }


def test_predicate_instances_preserve_hard_bindings_and_have_exact_oracles(
    tmp_path: Path,
) -> None:
    _, overlay = _overlay(tmp_path)
    records = overlay.manifest["overlay_instances"]

    assert [item["oracle_counts"]["final"] for item in records] == [11, 6, 9]
    for record in records:
        query_id = record["query_id"]
        bindings = _bindings(overlay.workload_bundle, query_id)
        assert bindings["person-identity"] == "person-alice-smith"
        assert bindings["time-lower-bound"] == "2026-08-01"
        assert bindings["amount-lower-bound"] == 50000
        assert bindings["path-shape"] == "direct"
        assert record["query_instance_sha256"] == load_m15_parameterized_instance(
            overlay.workload_bundle, query_id
        )["contract"]["query_instance_sha256"]
        instance = load_m15_parameterized_instance(
            overlay.workload_bundle, query_id
        )
        assert instance["final_oracle"]
        assert {row["risk"] for row in instance["final_oracle"]} == {
            bindings["risk-level"]
        }
        source_ids = {
            row["transfer_id"]
            for row in instance["source_oracles"]["neo4j_full"]
        }
        if bindings["transfer-predicate"] == "payment_to_company":
            assert all(value.startswith("P") for value in source_ids)
        else:
            assert all(value.startswith("T") for value in source_ids)


def test_payment_queries_compile_to_closed_backend_mapping(tmp_path: Path) -> None:
    _, overlay = _overlay(tmp_path)
    payment_records = [
        item
        for item in overlay.manifest["overlay_instances"]
        if "transfer-predicate" in item["changed_slot_ids"]
    ]

    assert len(payment_records) == 2
    for record in payment_records:
        query_id = record["query_id"]
        text = overlay.workload_bundle.path(
            f"instances/{query_id}/neo4j_full.cypher"
        ).read_text(encoding="utf-8")
        assert "_PAYMENT_TO_COMPANY]" in text
        assert "{{compile:" not in text
        candidates = build_m15_parameterized_plan_candidates(
            overlay.workload_bundle,
            query_id=query_id,
        )
        assert len(candidates) == 2
        assert all(item.plan.max_remote_calls == 2 for item in candidates)


def test_every_added_direct_class_has_two_exact_executable_plans(
    tmp_path: Path,
) -> None:
    _, overlay = _overlay(tmp_path)
    scheduler = _scheduler(overlay.workload_bundle)

    for record in overlay.manifest["overlay_instances"]:
        query_id = record["query_id"]
        oracle = load_m15_parameterized_instance(
            overlay.workload_bundle, query_id
        )["final_oracle"]
        candidates = build_m15_parameterized_plan_candidates(
            overlay.workload_bundle,
            query_id=query_id,
        )
        assert len({item.semantic_equivalence_key for item in candidates}) == 1
        for candidate in candidates:
            result = scheduler.execute(candidate.plan, goal_id=query_id)
            assert result.success
            assert result.total_remote_calls == 2
            assert list(result.final_rows) == oracle


def test_predicate_bundle_reuses_ordinary_fixture_boundary(tmp_path: Path) -> None:
    base, overlay = _overlay(tmp_path)
    loaded_paths: list[Path] = []
    loaders = {
        backend_id: PredicateFixtureLoader(backend_id, loaded_paths)
        for backend_id in ("neo4j", "fuseki")
    }

    record = load_m15_parameterized_fixture(
        workload_bundle=overlay.workload_bundle,
        clients=_clients(overlay.workload_bundle),
        loaders=loaders,
        output_root=tmp_path / "fixture",
        repo_root=REPO_ROOT,
        bundle_loader=partial(
            load_m15_predicate_overlay_workload_bundle,
            overlay_root=overlay.root,
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
            mapping=PREDICATE_MAPPING,
        ),
    )
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))

    assert record.success
    assert manifest["verification"]["query_instance_count"] == 9
    assert manifest["verification"]["backend_query_count"] == 18
    assert manifest["verification"]["passed"] is True
    assert loaded_paths == [
        overlay.workload_bundle.path("load_neo4j.cypher"),
        overlay.workload_bundle.path("load_fuseki.ttl"),
    ]


def test_base_bundle_and_existing_instance_artifacts_remain_exact(
    tmp_path: Path,
) -> None:
    base, overlay = _overlay(tmp_path)
    composed = overlay.workload_bundle

    assert base.manifest["bundle_content_sha256"] == BASE_BUNDLE_SHA256
    assert overlay.manifest["base_artifact_preservation"][
        "base_bundle_mutated"
    ] is False
    for path in overlay.manifest["base_artifact_preservation"][
        "unchanged_files"
    ]:
        assert base.path(path).read_bytes() == composed.path(path).read_bytes()
    base_load = base.path("load_neo4j.cypher").read_text(encoding="utf-8")
    composed_load = composed.path("load_neo4j.cypher").read_text(
        encoding="utf-8"
    )
    assert composed_load.startswith(base_load + "\n")
    assert "_PAYMENT_TO_COMPANY" not in base_load
    assert "_PAYMENT_TO_COMPANY" in composed_load
    assert base.path("load_fuseki.ttl").read_bytes() == composed.path(
        "load_fuseki.ttl"
    ).read_bytes()
    assert composed.manifest["load_protocol"] == {
        "neo4j_order": "frozen_base_then_payment_augmentation",
        "neo4j_base_statement_count": 13,
        "neo4j_payment_batch_size": 100,
        "neo4j_payment_statement_count": 8,
        "neo4j_combined_statement_count": 21,
        "fuseki_base_artifact_reused": True,
    }


def test_overlay_is_deterministic_and_reloadable(tmp_path: Path) -> None:
    base = _base_bundle(tmp_path)
    first = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        destination=tmp_path / "first",
    )
    second = generate_m15_predicate_overlay_bundle(
        base_bundle=base.root,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        mapping=M15PredicateMappingSpec.from_json(PREDICATE_MAPPING),
        destination=tmp_path / "second",
    )
    loaded = load_m15_predicate_overlay_bundle(
        first.root,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )

    assert first.manifest == second.manifest == loaded.manifest
    assert first.workload_bundle.manifest == second.workload_bundle.manifest
    assert first.workload_bundle.manifest == loaded.workload_bundle.manifest


def test_loader_rejects_nested_tamper(tmp_path: Path) -> None:
    base, overlay = _overlay(tmp_path)
    payment = next(
        item
        for item in overlay.manifest["overlay_instances"]
        if item["changed_slot_ids"] == ["transfer-predicate"]
    )
    target = overlay.workload_bundle.path(
        f"instances/{payment['query_id']}/neo4j_full.cypher"
    )
    target.write_text(target.read_text(encoding="utf-8") + "// tamper\n")

    with pytest.raises(M15PredicateOverlayError, match="SHA-256 mismatch"):
        load_m15_predicate_overlay_bundle(
            overlay.root,
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
            mapping=PREDICATE_MAPPING,
        )


def test_mapping_catalog_mismatch_fails_closed(tmp_path: Path) -> None:
    base = _base_bundle(tmp_path)
    changed = json.loads(PREDICATE_MAPPING.read_text(encoding="utf-8"))
    changed["evidence"]["reference"] = "unregistered-reference"
    changed_path = tmp_path / "changed-mapping.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(M15PredicateOverlayError, match="disagrees"):
        generate_m15_predicate_overlay_bundle(
            base_bundle=base,
            base_query_id=BASE_QUERY_ID,
            catalog=SEMANTIC_CATALOG,
            mapping=changed_path,
            destination=tmp_path / "rejected",
        )
    assert not (tmp_path / "rejected").exists()


def test_existing_destination_and_cli_are_fail_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = _base_bundle(tmp_path)
    output = tmp_path / "cli-overlay"
    arguments = [
        "--base-bundle-root",
        str(base.root),
        "--base-query-id",
        BASE_QUERY_ID,
        "--catalog",
        str(SEMANTIC_CATALOG),
        "--mapping",
        str(PREDICATE_MAPPING),
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "success"
    assert success["counts"]["predicate_enabled_instances"] == 2

    assert main(arguments) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "configuration_error"
    assert "destination exists" in failure["error"]
