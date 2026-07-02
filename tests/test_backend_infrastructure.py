import json
from pathlib import Path

from xgap.backends import registry
from xgap.experiments.backend_smoke import run_backend_smoke
from xgap.experiments.results import normalize_smoke_rows
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import (
    BackendStatus,
    DatasetSpec,
    ExecutionReport,
    QueryArtifact,
    RunRecord,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_descriptor_yaml_files_load() -> None:
    descriptor_dir = REPO_ROOT / "descriptors" / "backends"

    descriptors = registry.load_descriptors(descriptor_dir)
    by_id = {descriptor.id: descriptor for descriptor in descriptors}

    assert {"reference_evaluator", "neo4j", "fuseki"} <= set(by_id)
    assert by_id["neo4j"].capabilities["graph_model"]["kind"] == "labeled_property_graph"
    assert by_id["fuseki"].capabilities["path_gpc_fragment"]["native_smoke_queries"] is True
    assert by_id["reference_evaluator"].runtime["live_service_required"] is False


def test_backend_registry_lists_and_filters_descriptors() -> None:
    registry.load_descriptors(REPO_ROOT / "descriptors" / "backends")

    assert registry.get("neo4j").language == "cypher"
    assert [descriptor.id for descriptor in registry.find_by_language("sparql")] == ["fuseki"]
    assert [descriptor.id for descriptor in registry.list_backends()] == [
        "fuseki",
        "neo4j",
        "reference_evaluator",
    ]


def test_runtime_objects_round_trip_to_json() -> None:
    artifact = QueryArtifact(
        artifact_id="toy-query",
        language="cypher",
        text="RETURN 1 AS ok",
        source_path="examples/financial_risk/smoke_neo4j.cypher",
    )
    report = ExecutionReport(
        backend_id="neo4j",
        artifact_id=artifact.artifact_id,
        language=artifact.language,
        success=True,
        rows=[{"company": "Redstone Analytics", "amount": 125000}],
        elapsed_ms=3.5,
    )
    record = RunRecord(
        run_id="run-1",
        backend_id="neo4j",
        dataset_id="financial_risk_toy",
        query_artifact=artifact,
        execution=report,
        normalized_result_path="runs/run-1/results/neo4j.json",
        log_path="runs/run-1/query_logs.jsonl",
    )

    decoded = json.loads(record.to_json())
    rebuilt = RunRecord.from_dict(decoded)

    assert rebuilt == record
    assert BackendStatus.from_dict(
        BackendStatus("neo4j", True, "ok", details={"port": 7474}).to_dict()
    ).ok


def test_dataset_spec_loads_backend_files() -> None:
    spec = DatasetSpec.from_yaml(REPO_ROOT / "examples" / "datasets" / "financial_risk_toy.yaml")

    assert spec.id == "financial_risk_toy"
    assert spec.backend_config("neo4j")["smoke_query_file"].endswith("smoke_neo4j.cypher")
    assert spec.backend_config("fuseki")["load_files"] == [
        "examples/financial_risk/load_fuseki.ttl"
    ]


def test_result_normalization_accepts_neo4j_and_sparql_shapes() -> None:
    rows = [
        {
            "company": "Redstone Analytics",
            "amount": 125000.0,
            "currency": "USD",
            "occurred_on": "2026-03-12",
        },
        {
            "company": "BlackPeak Trading",
            "amount": "87000.0",
            "currency": "USD",
            "occurredOn": "2026-04-02",
        },
    ]

    normalized = normalize_smoke_rows(rows)

    assert normalized == [
        {
            "company": "BlackPeak Trading",
            "amount": 87000,
            "currency": "USD",
            "occurred_on": "2026-04-02",
        },
        {
            "company": "Redstone Analytics",
            "amount": 125000.0,
            "currency": "USD",
            "occurred_on": "2026-03-12",
        },
    ]


class FakeBackendClient:
    def healthcheck(self) -> BackendStatus:
        return BackendStatus("neo4j", True, "ok")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        return ExecutionReport(
            backend_id="neo4j",
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[
                {
                    "company": "Redstone Analytics",
                    "amount": 125000.0,
                    "currency": "USD",
                    "occurred_on": "2026-03-12",
                }
            ],
        )


def test_backend_smoke_harness_writes_log_and_normalized_results(tmp_path: Path) -> None:
    record = run_backend_smoke(
        backend_id="neo4j",
        dataset_spec_path=REPO_ROOT / "examples" / "datasets" / "financial_risk_toy.yaml",
        descriptors_dir=REPO_ROOT / "descriptors" / "backends",
        runs_dir=tmp_path,
        run_id="unit-run",
        client=FakeBackendClient(),
    )

    log_path = Path(record.log_path)
    result_path = Path(record.normalized_result_path)

    assert log_path.exists()
    assert result_path.exists()
    assert json.loads(result_path.read_text(encoding="utf-8")) == [
        {
            "company": "Redstone Analytics",
            "amount": 125000.0,
            "currency": "USD",
            "occurred_on": "2026-03-12",
        }
    ]
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1


def test_backend_descriptor_is_plain_serializable_data() -> None:
    descriptor = BackendDescriptor.from_yaml(REPO_ROOT / "descriptors" / "backends" / "neo4j.yaml")

    payload = descriptor.to_dict()

    assert payload["id"] == "neo4j"
    json.dumps(payload, sort_keys=True)
