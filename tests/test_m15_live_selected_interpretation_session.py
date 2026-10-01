from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
import xgap.experiments.m15_live_selected_interpretation_session as live_selected

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    build_m15_controlled_training_observations,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_selected_interpretation_session import (
    LIVE_SELECTED_SESSION_SCHEMA_VERSION,
    SELECTED_SESSION_PREFLIGHT_SCHEMA_VERSION,
    M15LiveSelectedInterpretationSessionError,
    build_m15_selected_session_preflight,
    prepare_m15_selected_interpretation_session,
    run_m15_live_selected_interpretation_session,
)
from xgap.experiments.m15_selected_interpretation_session_evidence import (
    SELECTED_INTERPRETATION_SESSION_AUDIT_SCHEMA_VERSION,
    audit_m15_selected_interpretation_session_run,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
SPECS = REPO_ROOT / "experiments/specs"
WORKLOAD_SPEC = CONFIGS / "m15_f2c_parameterized_workload_dev.json"
QUERY_TEMPLATE = CONFIGS / "m15_f2c_parameterized_financial_risk_v2.json"
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
SEMANTIC_CATALOG = CONFIGS / "m15_f2c6_semantic_relaxation_dev.json"
PREDICATE_MAPPING = CONFIGS / "m15_f2c8_predicate_mapping_dev.json"
CARDINALITY_POLICY = CONFIGS / "m15_f2c10_direct_semantic_workload_dev.json"
PREDICTOR_POLICY = CONFIGS / "m15_f2c10_family_memory_predictor_dev.json"
INTERPRETATION_POLICY = CONFIGS / "m15_e5_hierarchical_interpretation_policy_dev.json"
RELAXATION_POLICY = CONFIGS / "m15_e5b_anchored_predicate_relaxation_dev.json"
TRANSPORT_POLICY = CONFIGS / "m15_e5c_clarification_transport_dev.json"
LIVE_POLICY = CONFIGS / "m15_e5d_live_selected_session_dev.json"
RESOLUTION_ONTOLOGY = SPECS / "m15_e3_financial_risk_ontology_dev.json"
BRIDGE_SPEC = CONFIGS / "m15_e4_resolution_execution_bridge_dev.json"
RUNTIME_HASH = content_hash(
    {
        "runtime": "e5d-local-controlled-runtime",
        "neo4j": "controlled",
        "fuseki": "controlled",
    }
)


@pytest.fixture
def prepared_e5d(tmp_path: Path):
    source_base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "source-base",
    )
    source_workload = generate_m15_direct_semantic_workload_bundle(
        base_bundle=source_base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        policy=CARDINALITY_POLICY,
        destination=tmp_path / "source-direct",
    )
    controlled = build_m15_controlled_training_observations(source_workload)
    memory = build_m15_direct_training_memory_view(
        workload=source_workload,
        raw_observations=controlled["observations"],
        runtime_compatibility_sha256=RUNTIME_HASH,
        policy=PREDICTOR_POLICY,
        measurement_source_kind="controlled_local_nonmeasurement_fixture",
    )
    memory_path = tmp_path / "historical-training-memory.json"
    memory_path.write_text(json.dumps(memory.to_dict()), encoding="utf-8")
    resolution = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=CONFIGS / "m15_e3_financial_risk_intake_dev.json",
        catalog_path=SPECS / "m15_e3_financial_risk_catalog_dev.json",
        ontology_path=RESOLUTION_ONTOLOGY,
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-e5d-test-entity-selection",
    )
    resolution_path = tmp_path / "resolution-run.json"
    resolution_path.write_text(json.dumps(resolution), encoding="utf-8")
    prepared = prepare_m15_selected_interpretation_session(
        resolution_run_path=resolution_path,
        bridge_spec_path=BRIDGE_SPEC,
        workload_destination=tmp_path / "prepared-workload",
        training_memory_path=memory_path,
        expected_training_memory_sha256=memory.memory_view_hash,
        predictor_policy_path=PREDICTOR_POLICY,
        interpretation_policy_path=INTERPRETATION_POLICY,
        ontology_path=RESOLUTION_ONTOLOGY,
        relaxation_policy_path=RELAXATION_POLICY,
        transport_policy_path=TRANSPORT_POLICY,
        live_policy_path=LIVE_POLICY,
        session_id="m15-e5d-test-session",
        structural_candidate_id="constraint:single-transfer-at-least-50000",
        predicate_candidate_id="predicate:transferred_to",
        authority_source_id="explicit-e5d-test-user-input",
        repo_root=REPO_ROOT,
    )
    return prepared, resolution_path, memory_path


@dataclass
class _ControlledClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    fail_artifact_id: str | None = None
    calls: int = 0

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "controlled fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.calls += 1
        if artifact.artifact_id == self.fail_artifact_id:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                rows=[],
                elapsed_ms=1.0,
                error="controlled failure",
            )
        rows = [dict(item) for item in self.rows_by_artifact[artifact.artifact_id]]
        upper = artifact.parameters.get("occurred_on_lt")
        if self.backend_id == "neo4j" and isinstance(upper, str):
            rows = [item for item in rows if str(item["occurred_on"]) < upper]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                item
                for item in rows
                if str(item["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
        )


def _clients(prepared, *, fail_first: bool = False):
    handoff = prepared.clarification_session.execution_handoff
    assert handoff is not None
    descriptor_by_plan = {
        item["plan_id"]: item
        for item in handoff.to_dict()["selected_plans"]
    }
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    first_neo4j = None
    for plan_id, plan in handoff.plans.items():
        instance = load_m15_parameterized_instance(
            prepared.resolution_bridge.workload.workload_bundle,
            descriptor_by_plan[plan_id]["query_id"],
        )
        source = instance["source_oracles"]
        for node in plan.nodes:
            backend_id = node.parameters.get("backend_id")
            if backend_id not in rows:
                continue
            artifact = QueryArtifact.from_dict(node.parameters["artifact"])
            if backend_id == "fuseki":
                role = "fuseki_risk"
            elif "company_ids" in artifact.parameters:
                role = "neo4j_bound"
            else:
                role = "neo4j_full"
            rows[backend_id][artifact.artifact_id] = source[role]
            if first_neo4j is None and backend_id == "neo4j":
                first_neo4j = artifact.artifact_id
    return {
        "neo4j": _ControlledClient(
            "neo4j",
            rows["neo4j"],
            first_neo4j if fail_first else None,
        ),
        "fuseki": _ControlledClient("fuseki", rows["fuseki"]),
    }


def test_e5d_preflight_binds_memory_authority_and_selected_handoff(
    prepared_e5d,
) -> None:
    prepared, _, _ = prepared_e5d
    preflight = build_m15_selected_session_preflight(prepared)
    session = prepared.clarification_session.to_dict()

    assert preflight["schema_version"] == SELECTED_SESSION_PREFLIGHT_SCHEMA_VERSION
    assert preflight["sealed_before_service_start"] is True
    assert preflight["backend_calls_before_seal"] == 0
    assert preflight["current_query_profile_calls"] == 0
    assert preflight["session_sha256"] == session["session_sha256"]
    assert preflight["selected_plan_ids"] == session["execution_handoff"][
        "selected_plan_ids"
    ]
    assert content_hash(
        {key: value for key, value in preflight.items() if key != "preflight_sha256"}
    ) == preflight["preflight_sha256"]


def test_e5d_live_goal_executes_all_and_only_selected_plans(
    prepared_e5d,
    tmp_path: Path,
) -> None:
    prepared, _, _ = prepared_e5d
    clients = _clients(prepared)
    record = run_m15_live_selected_interpretation_session(
        prepared=prepared,
        clients=clients,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    results = json.loads(record.result_path.read_text(encoding="utf-8"))[
        "results"
    ]
    handoff = prepared.clarification_session.execution_handoff
    assert handoff is not None
    selected_ids = handoff.to_dict()["selected_plan_ids"]
    assert manifest["schema_version"] == LIVE_SELECTED_SESSION_SCHEMA_VERSION
    assert manifest["selected_plan_ids"] == selected_ids
    assert [item["plan_id"] for item in results] == selected_ids
    assert manifest["summary"]["goal_tool_calls"] == len(selected_ids)
    assert manifest["summary"]["total_remote_calls"] == 2 * len(selected_ids)
    assert manifest["validation"]["passed"] is True
    assert all(item["exact_oracle_answer"] is True for item in results)
    assert sum(client.calls for client in clients.values()) == 2 * len(selected_ids)
    goal = json.loads((record.run_root / "goal_spec.json").read_text())
    assert goal["allowed_tools"] == ["runtime.execute_plan"]
    assert goal["max_tool_calls"] == len(selected_ids)
    memory = json.loads((record.run_root / "execution_memory.json").read_text())
    assert len(memory) == len(selected_ids)


def test_e5d_control_plane_contains_no_native_query_text(prepared_e5d) -> None:
    prepared, _, _ = prepared_e5d
    portable = json.dumps(
        {
            "session": prepared.clarification_session.to_dict(),
            "preflight": build_m15_selected_session_preflight(prepared),
        },
        sort_keys=True,
    )
    assert " MATCH " not in portable
    assert "SELECT " not in portable


def test_e5d_stops_after_first_failed_plan_without_retry(
    prepared_e5d,
    tmp_path: Path,
) -> None:
    prepared, _, _ = prepared_e5d
    clients = _clients(prepared, fail_first=True)
    record = run_m15_live_selected_interpretation_session(
        prepared=prepared,
        clients=clients,
        output_root=tmp_path / "failed-runs",
        repo_root=REPO_ROOT,
    )

    assert not record.success
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    results = json.loads(record.result_path.read_text(encoding="utf-8"))[
        "results"
    ]
    assert status["status"] == "failed"
    assert len(results) == 1
    assert invocations["automatic_retries"] == 0
    assert invocations["total_tool_invocations"] == 2
    assert sum(client.calls for client in clients.values()) == 2


def test_e5d_rejects_wrong_memory_identity_before_execution(
    prepared_e5d,
) -> None:
    prepared, resolution_path, memory_path = prepared_e5d
    with pytest.raises(
        M15LiveSelectedInterpretationSessionError,
        match="expected training memory",
    ):
        prepare_m15_selected_interpretation_session(
            resolution_run_path=resolution_path,
            bridge_spec_path=BRIDGE_SPEC,
            workload_destination=memory_path.parent / "wrong-memory-workload",
            training_memory_path=memory_path,
            expected_training_memory_sha256="not-a-hash",
            predictor_policy_path=PREDICTOR_POLICY,
            interpretation_policy_path=INTERPRETATION_POLICY,
            ontology_path=RESOLUTION_ONTOLOGY,
            relaxation_policy_path=RELAXATION_POLICY,
            transport_policy_path=TRANSPORT_POLICY,
            live_policy_path=LIVE_POLICY,
            session_id="m15-e5d-wrong-memory-session",
            structural_candidate_id=(
                "constraint:single-transfer-at-least-50000"
            ),
            predicate_candidate_id="predicate:transferred_to",
            authority_source_id="explicit-e5d-test-user-input",
            repo_root=REPO_ROOT,
        )


def test_e5d_rejects_unexecutable_structural_choice_before_service_start(
    prepared_e5d,
) -> None:
    _, resolution_path, memory_path = prepared_e5d
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    with pytest.raises(
        M15LiveSelectedInterpretationSessionError,
        match="executable R1",
    ):
        prepare_m15_selected_interpretation_session(
            resolution_run_path=resolution_path,
            bridge_spec_path=BRIDGE_SPEC,
            workload_destination=memory_path.parent / "unsupported-workload",
            training_memory_path=memory_path,
            expected_training_memory_sha256=memory[
                "training_memory_view_sha256"
            ],
            predictor_policy_path=PREDICTOR_POLICY,
            interpretation_policy_path=INTERPRETATION_POLICY,
            ontology_path=RESOLUTION_ONTOLOGY,
            relaxation_policy_path=RELAXATION_POLICY,
            transport_policy_path=TRANSPORT_POLICY,
            live_policy_path=LIVE_POLICY,
            session_id="m15-e5d-unavailable-session",
            structural_candidate_id="constraint:amount-at-least-50000",
            predicate_candidate_id="predicate:transferred_to",
            authority_source_id="explicit-e5d-test-user-input",
            repo_root=REPO_ROOT,
        )


def test_e5d_independent_audit_reconstructs_native_run_read_only(
    prepared_e5d,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_prepared, source_resolution, _ = prepared_e5d
    commit = "a" * 40
    outer = tmp_path / "cwru-m15-e5d-controlled"
    service = outer / "native-service-run"
    preflight_root = service / "selected-interpretation-session-preflight"
    input_root = outer / "selected-session-inputs"
    input_root.mkdir(parents=True)
    service.mkdir(parents=True)
    shutil.copyfile(source_resolution, outer / "resolution_run.json")
    shutil.copyfile(BRIDGE_SPEC, outer / "resolution_bridge_spec.json")
    filenames = {
        "training_memory": "training_memory_view.json",
        "predictor_policy": "predictor_policy.json",
        "interpretation_policy": "interpretation_policy.json",
        "ontology": "ontology.json",
        "relaxation_policy": "relaxation_policy.json",
        "transport_policy": "transport_policy.json",
        "live_policy": "live_policy.json",
    }
    copied: dict[str, Path] = {}
    for key, filename in filenames.items():
        copied[key] = input_root / filename
        shutil.copyfile(source_prepared.source_paths[key], copied[key])

    prepared = prepare_m15_selected_interpretation_session(
        resolution_run_path=outer / "resolution_run.json",
        bridge_spec_path=outer / "resolution_bridge_spec.json",
        workload_destination=preflight_root / "workload",
        training_memory_path=copied["training_memory"],
        expected_training_memory_sha256=(
            source_prepared.memory.memory_view_hash
        ),
        predictor_policy_path=copied["predictor_policy"],
        interpretation_policy_path=copied["interpretation_policy"],
        ontology_path=copied["ontology"],
        relaxation_policy_path=copied["relaxation_policy"],
        transport_policy_path=copied["transport_policy"],
        live_policy_path=copied["live_policy"],
        session_id="m15-e5d-auditable-session",
        structural_candidate_id="constraint:single-transfer-at-least-50000",
        predicate_candidate_id="predicate:transferred_to",
        authority_source_id="explicit-e5d-auditable-user-input",
        repo_root=REPO_ROOT,
    )
    preflight = build_m15_selected_session_preflight(prepared)
    session = prepared.clarification_session.to_dict()

    def write(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    write(preflight_root / "preflight_manifest.json", preflight)
    write(preflight_root / "clarification_session.json", session)
    write(preflight_root / "authority_events.json", session["authority_events"])
    write(preflight_root / "execution_handoff.json", session["execution_handoff"])

    monkeypatch.setattr(
        live_selected,
        "_git_state",
        lambda _root: {"commit": commit, "clean": True},
    )
    record = run_m15_live_selected_interpretation_session(
        prepared=prepared,
        clients=_clients(prepared),
        output_root=service,
        repo_root=REPO_ROOT,
    )
    assert record.success

    fixture = service / "resolution-execution-fixture-load"
    write(fixture / "run_status.json", {"status": "success"})
    write(
        fixture / "run_manifest.json",
        {
            "schema_version": "m15-f2c4-parameterized-fixture-v1",
            "status": "success",
            "error": None,
            "automatic_retries": 0,
            "git": {"commit": commit, "clean": True},
        },
    )
    write(
        fixture / "load_reports.json",
        {"neo4j": {"success": True}, "fuseki": {"success": True}},
    )
    write(
        fixture / "verification.json",
        {"validation": {"passed": True, "checks": {"exact": True}}},
    )
    write(
        outer / "run_status.json",
        {
            "status": "success",
            "exit_code": 0,
            "git_commit": commit,
            "workload_mode": "selected_interpretation_session",
            "runtime_removed": True,
            "cleanup_error": None,
        },
    )
    (outer / "environment.txt").write_text(
        "\n".join(
            (
                "run_version=m15-e5d-native-live-selected-interpretation-session-services-v1",
                f"git_commit={commit}",
                "loopback_only=true",
                "automatic_retries=0",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    write(service / "run_status.json", {"status": "success"})
    write(
        service / "run_manifest.json",
        {
            "schema_version": (
                "m15-e5d-native-live-selected-interpretation-session-service-run-v1"
            ),
            "status": "success",
            "error": None,
            "runtime_root": str(tmp_path / "removed-runtime"),
            "automatic_retries": 0,
            "service_restarts": 0,
            "public_ports": False,
            "credentials_persisted": False,
            "selected_interpretation_session_preflight": preflight,
        },
    )
    write(
        service / "service_plan.json",
        {
            "public_ports": False,
            "neo4j_http_url": "http://127.0.0.1:17474",
            "fuseki_url": "http://127.0.0.1:13030",
            "services": [
                {
                    "service_id": "neo4j",
                    "health_url": "http://127.0.0.1:17474",
                    "command": ["neo4j", "console"],
                },
                {
                    "service_id": "fuseki",
                    "health_url": "http://127.0.0.1:13030/$/ping",
                    "command": ["fuseki-server", "--localhost"],
                },
            ],
        },
    )
    (service / "neo4j.conf").write_text(
        "\n".join(
            (
                "server.default_listen_address=127.0.0.1",
                "server.default_advertised_address=127.0.0.1",
                "server.bolt.listen_address=127.0.0.1:17687",
                "server.bolt.advertised_address=127.0.0.1:17687",
                "server.http.listen_address=127.0.0.1:17474",
                "server.http.advertised_address=127.0.0.1:17474",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    write(
        service / "service_health.json",
        [{"success": True}, {"success": True}],
    )
    write(
        service / "service_shutdown.json",
        [{"success": True}, {"success": True}],
    )

    before = tuple(
        (path.relative_to(outer).as_posix(), path.stat().st_size)
        for path in sorted(outer.rglob("*"))
        if path.is_file()
    )
    audit = audit_m15_selected_interpretation_session_run(
        run_root=outer,
        expected_commit=commit,
        repo_root=REPO_ROOT,
    )
    after = tuple(
        (path.relative_to(outer).as_posix(), path.stat().st_size)
        for path in sorted(outer.rglob("*"))
        if path.is_file()
    )

    assert audit.to_dict()["schema_version"] == (
        SELECTED_INTERPRETATION_SESSION_AUDIT_SCHEMA_VERSION
    )
    assert audit.success is True, audit.failed_check_ids
    assert audit.failed_check_ids == ()
    assert audit.run_tree_mutated is False
    assert before == after
