from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from xgap.experiments import (
    m15_finbench_confirmatory_population_evidence as evidence,
)
from xgap.experiments import m15_finbench_confirmatory_population_job as job
from xgap.experiments import m15_finbench_confirmatory_freeze_job as freeze_job
from xgap.experiments import (
    m15_finbench_confirmatory_freeze_evidence as freeze_evidence,
)
from xgap.experiments.m15_finbench_confirmatory_population import (
    DEFAULT_DESIGN_PATH,
    FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION,
    FinBenchConfirmatoryPopulationError,
    compile_finbench_confirmatory_population_registry,
    write_finbench_confirmatory_population_registry,
)
from xgap.experiments import m15_finbench_confirmatory_workload as workload
from xgap.experiments.m15_finbench_confirmatory_workload import (
    DEFAULT_FAMILY_CONTRACT_PATH,
    FinBenchConfirmatoryWorkloadError,
    build_finbench_confirmatory_population_approval,
    build_finbench_confirmatory_workload,
)
from xgap.experiments.m15_finbench_confirmatory_crossfit import (
    FinBenchConfirmatoryCrossfitError,
    build_finbench_confirmatory_crossfit_predictions,
)
from xgap.experiments.m15_finbench_confirmatory_schedule import (
    FinBenchConfirmatoryScheduleError,
    build_finbench_confirmatory_schedule,
)
from xgap.experiments.m15_finbench_paper_protocol import (
    DEFAULT_AUTHOR_SELECTION_PATH,
    DEFAULT_PROTOCOL_PATH,
)
from xgap.experiments.m15_finbench_federation import (
    build_finbench_plan_candidates,
)
from xgap.experiments.m15_finbench_workload import (
    FinBenchQueryData,
    Transfer,
    load_finbench_primary_workload,
)


ROOT = Path(__file__).resolve().parents[1]
F1 = "f1_direct_transfer_control"
F2 = "f2_temporal_path_control"
F3 = "f3_aggregate_risk_ranking"


def _data() -> FinBenchQueryData:
    people = {
        f"P{index:02d}": {"personId": f"P{index:02d}"}
        for index in range(40)
    }
    accounts = {
        **{
            f"S{index:02d}": {
                "accountId": f"S{index:02d}",
                "isBlocked": "false",
            }
            for index in range(40)
        },
        **{
            f"D{index:02d}": {
                "accountId": f"D{index:02d}",
                "isBlocked": "true" if index % 2 else "false",
            }
            for index in range(40)
        },
    }
    companies = {
        f"C{index:02d}": {"companyId": f"C{index:02d}"}
        for index in range(40)
    }
    risk_levels = ("Critical risk", "High risk", "Low risk", "Watch risk")
    media = {
        f"M{index}": {
            "mediumId": f"M{index}",
            "riskLevel": risk,
            "isBlocked": "true" if index % 2 else "false",
            "mediumType": f"type-{index}",
        }
        for index, risk in enumerate(risk_levels)
    }
    person_by_account = {
        f"S{index:02d}": f"P{index:02d}" for index in range(40)
    }
    company_by_account = {
        f"D{index:02d}": f"C{index:02d}" for index in range(40)
    }
    transfers: list[Transfer] = []
    outgoing: dict[str, tuple[Transfer, ...]] = {}
    for index in range(40):
        source = f"S{index:02d}"
        f1_rows = [
            Transfer(
                source,
                f"D{index:02d}",
                Decimal(index + repetition + 1),
                f"2026-08-{repetition + 1:02d} 00:00:00.000",
                f"f1-{index}-{repetition}",
            )
            for repetition in range(index % 8 + 1)
        ]
        transfers.extend(f1_rows)
        outgoing[source] = tuple(
            Transfer(
                source,
                f"D{(index + repetition) % 40:02d}",
                Decimal(100 + repetition),
                f"2026-08-{repetition + 1:02d} 01:00:00.000",
                f"f2-{index}-{repetition}",
            )
            for repetition in range(index % 5 + 2)
        )
    return FinBenchQueryData(
        people=people,
        accounts=accounts,
        companies=companies,
        media=media,
        person_by_account=person_by_account,
        company_by_account=company_by_account,
        media_by_account={
            f"D{index:02d}": (f"M{index % len(media)}",)
            for index in range(40)
        },
        transfers=tuple(transfers),
        outgoing=outgoing,
        minimum_transfer_time="2026-08-01 00:00:00.000",
        maximum_transfer_time="2026-08-31 23:59:59.999",
    )


def _compile(data: FinBenchQueryData | None = None) -> dict[str, object]:
    return compile_finbench_confirmatory_population_registry(
        data or _data(),
        source_artifact_id="ldbc-finbench-v0.1.0-sf0.1",
        source_archive_sha256="a" * 64,
        design=ROOT / DEFAULT_DESIGN_PATH,
    ).to_dict()


def test_compiles_all_author_options_with_balanced_crossfit() -> None:
    registry = _compile()

    assert (
        registry["schema_version"]
        == FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION
    )
    assert registry["author_selected_population_option_id"] is None
    assert registry["sampling_frame_counts"] == {F1: 40, F2: 40, F3: 40}
    assert [
        option["total_instance_count"]
        for option in registry["population_options"]
    ] == [36, 48, 60]
    for option in registry["population_options"]:
        per_family = option["per_family_instance_count"]
        assert option["family_counts"] == {
            F1: per_family,
            F2: per_family,
            F3: per_family,
        }
        instances = option["instances"]
        assert len(instances) == option["total_instance_count"]
        assert len({item["query_id"] for item in instances}) == len(instances)
        for family_id in (F1, F2):
            family = [item for item in instances if item["family_id"] == family_id]
            assert {
                fold: sum(item["evaluation_fold_id"] == fold for item in family)
                for fold in range(1, 5)
            } == {fold: per_family // 4 for fold in range(1, 5)}
            assert all(len(item["training_fold_ids"]) == 3 for item in family)
        assert all(
            item["split_role"] == "heldout_family"
            and item["evaluation_fold_id"] is None
            and item["training_fold_ids"] == []
            for item in instances
            if item["family_id"] == F3
        )


def test_size_options_are_nested_before_author_choice() -> None:
    options = _compile()["population_options"]
    by_size = {
        option["total_instance_count"]: option for option in options
    }
    for family_id in (F1, F2, F3):
        sets = {
            size: {
                item["candidate_id"]
                for item in by_size[size]["instances"]
                if item["family_id"] == family_id
            }
            for size in (36, 48, 60)
        }
        assert sets[36] < sets[48] < sets[60]
        if family_id in (F1, F2):
            folds = {
                size: {
                    item["candidate_id"]: item["evaluation_fold_id"]
                    for item in by_size[size]["instances"]
                    if item["family_id"] == family_id
                }
                for size in (36, 48, 60)
            }
            assert all(
                folds[36][candidate_id] == folds[48][candidate_id]
                == folds[60][candidate_id]
                for candidate_id in sets[36]
            )


def test_blocked_labels_and_transfer_amounts_cannot_change_selection() -> None:
    original = _data()
    changed_accounts = copy.deepcopy(dict(original.accounts))
    for row in changed_accounts.values():
        row["isBlocked"] = "false" if row.get("isBlocked") == "true" else "true"
    changed_media = copy.deepcopy(dict(original.media))
    for row in changed_media.values():
        row["isBlocked"] = "false" if row.get("isBlocked") == "true" else "true"
    changed = replace(
        original,
        accounts=changed_accounts,
        media=changed_media,
        transfers=tuple(
            replace(transfer, amount=transfer.amount + Decimal("999999"))
            for transfer in original.transfers
        ),
    )

    assert _compile(original) == _compile(changed)


def test_registry_is_zero_call_result_blind_and_deterministic() -> None:
    first = _compile()
    second = _compile()
    assert first == second
    assert first["sampling_provenance"] == {
        "source_fields_used_for_sampling": [
            "person.personId",
            "account.accountId",
            "person_own_account.personId",
            "person_own_account.accountId",
            "company_own_account.accountId",
            "account_transfer_account.fromId",
            "account_transfer_account.toId",
            "account_transfer_account.createTime",
            "medium.riskLevel",
        ],
        "forbidden_fields_used_for_sampling": [],
        "answer_oracle_reads": 0,
        "observed_cost_reads": 0,
        "current_query_profile_calls": 0,
        "backend_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
    }
    assert first["claim_boundary"] == {
        "artifact_class": "result_blind_population_option_registry",
        "contains_answer_rows": False,
        "contains_execution_measurements": False,
        "author_decision_inferred": False,
        "confirmatory_run_authorized": False,
        "paper_result": False,
    }
    assert first["automatic_retries"] == 0
    assert first["paper_result"] is False
    assert len(first["registry_sha256"]) == 64


def test_explicit_approval_materializes_confirmatory_workload_without_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _data()
    registry = _compile(data)
    option = registry["population_options"][0]
    approval = build_finbench_confirmatory_population_approval(
        registry,
        selected_population_option_id=option["population_option_id"],
        approval_id="author-selection-test-v1",
        authority_source_id="author:test:explicit-choice",
    )
    archive = tmp_path / "sf0.1.tar.gz"
    archive.write_bytes(b"verified-test-archive")
    lock = SimpleNamespace(
        artifact=SimpleNamespace(
            artifact_id=registry["source_artifact_id"],
            digest_value=registry["source_archive_sha256"],
        )
    )
    monkeypatch.setattr(workload, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(workload, "load_finbench_query_data", lambda *_args: data)
    output = tmp_path / "confirmatory-workload"

    manifest = build_finbench_confirmatory_workload(
        archive_path=archive,
        population_registry=registry,
        population_approval=approval,
        output_root=output,
        lock_path=tmp_path / "unused-lock.json",
        family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
    )
    loaded = load_finbench_primary_workload(output)

    assert manifest["instance_count"] == 36
    assert manifest["population_registry_sha256"] == registry["registry_sha256"]
    assert manifest["population_approval_sha256"] == approval["approval_sha256"]
    assert manifest["confirmatory_execution_authorized"] is False
    assert manifest["backend_calls"] == 0
    assert manifest["current_query_profile_calls"] == 0
    assert manifest["llm_calls"] == 0
    assert manifest["ontology_service_calls"] == 0
    assert manifest["paper_result"] is False
    assert len(loaded["public_instances"]["instances"]) == 36
    assert set(loaded["sealed_oracles"]["queries"]) == {
        item["query_id"] for item in loaded["public_instances"]["instances"]
    }
    for family_id in (F1, F2, F3):
        query_id = next(
            item["query_id"]
            for item in loaded["public_instances"]["instances"]
            if item["family_id"] == family_id
        )
        candidates = build_finbench_plan_candidates(output, query_id=query_id)
        assert len(candidates) == 2
        assert all(candidate.plan.max_remote_calls == 2 for candidate in candidates)


def test_confirmatory_workload_keeps_empty_answers_and_rejects_unbound_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _data()
    data = replace(
        original,
        accounts={
            key: {**value, "isBlocked": "false"}
            for key, value in original.accounts.items()
        },
        media={
            key: {**value, "isBlocked": "false"}
            for key, value in original.media.items()
        },
    )
    registry = _compile(data)
    option = registry["population_options"][1]
    approval = build_finbench_confirmatory_population_approval(
        registry,
        selected_population_option_id=option["population_option_id"],
        approval_id="author-selection-empty-v1",
        authority_source_id="author:test:explicit-choice",
    )
    archive = tmp_path / "sf0.1.tar.gz"
    archive.write_bytes(b"verified-test-archive")
    lock = SimpleNamespace(
        artifact=SimpleNamespace(
            artifact_id=registry["source_artifact_id"],
            digest_value=registry["source_archive_sha256"],
        )
    )
    monkeypatch.setattr(workload, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(workload, "load_finbench_query_data", lambda *_args: data)
    output = tmp_path / "empty-answer-workload"

    manifest = build_finbench_confirmatory_workload(
        archive_path=archive,
        population_registry=registry,
        population_approval=approval,
        output_root=output,
        lock_path=tmp_path / "unused-lock.json",
        family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
    )
    loaded = load_finbench_primary_workload(output)
    queries = loaded["sealed_oracles"]["queries"]
    assert manifest["instance_count"] == 48
    assert any(not value["final_rows"] for value in queries.values())
    assert manifest["oracle_isolation"]["empty_answers_retained"] is True

    tampered = copy.deepcopy(approval)
    tampered["selected_population_option_id"] = "m15-finbench-confirmatory-60-v1"
    with pytest.raises(FinBenchConfirmatoryWorkloadError, match="approval hash"):
        build_finbench_confirmatory_workload(
            archive_path=archive,
            population_registry=registry,
            population_approval=tampered,
            output_root=tmp_path / "must-not-exist",
            lock_path=tmp_path / "unused-lock.json",
            family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
        )


def test_option_a_freezes_complete_result_blind_confirmatory_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _data()
    registry = _compile(data)
    option = registry["population_options"][1]
    assert option["population_option_id"] == "m15-finbench-confirmatory-48-v1"
    approval = build_finbench_confirmatory_population_approval(
        registry,
        selected_population_option_id=option["population_option_id"],
        approval_id="author-selection-option-a-v1",
        authority_source_id="author:anthonyche:explicit-option-a-2026-09-07",
    )
    archive = tmp_path / "sf0.1.tar.gz"
    archive.write_bytes(b"verified-test-archive")
    lock = SimpleNamespace(
        artifact=SimpleNamespace(
            artifact_id=registry["source_artifact_id"],
            digest_value=registry["source_archive_sha256"],
        )
    )
    monkeypatch.setattr(workload, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(workload, "load_finbench_query_data", lambda *_args: data)
    output = tmp_path / "option-a-workload"
    build_finbench_confirmatory_workload(
        archive_path=archive,
        population_registry=registry,
        population_approval=approval,
        output_root=output,
        lock_path=tmp_path / "unused-lock.json",
        family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
    )

    schedule = build_finbench_confirmatory_schedule(
        workload_root=output,
        protocol=ROOT / DEFAULT_PROTOCOL_PATH,
        author_selection=ROOT / DEFAULT_AUTHOR_SELECTION_PATH,
    ).to_dict()

    assert schedule["population_id"] == "m15-finbench-confirmatory-48-v1"
    assert schedule["expected_counts"] == {
        "seen_family_query_count": 32,
        "cold_family_query_count": 16,
        "inferential_query_count": 32,
        "training_plan_runs": 448,
        "profile_acquisition_plan_runs": 96,
        "selected_serving_plan_runs": 672,
        "evaluation_shadow_plan_runs": 672,
        "total_plan_runs": 1888,
        "total_backend_calls": 3776,
    }
    assert schedule["measurement_block_count"] == 22
    assert schedule["current_query_profile_calls_for_family_memory"] == 0
    assert schedule["oracle_inputs"] == []
    assert schedule["confirmatory_execution_authorized"] is False
    assert schedule["paper_result"] is False
    assert all(
        record["oracle_inputs"] == []
        for records in (
            schedule["crossfit_training_runs"],
            schedule["profile_acquisition_runs"],
            schedule["selected_serving_slots"],
            schedule["evaluation_shadow_runs"],
        )
        for record in records
    )
    method_counts = {
        method: sum(
            item["method_id"] == method
            for item in schedule["selected_serving_slots"]
        )
        for method in (
            "family_memory_zero_profile",
            "predeclared_family_fallback",
            "current_query_dual_profile",
        )
    }
    assert method_counts == {
        "family_memory_zero_profile": 224,
        "predeclared_family_fallback": 112,
        "current_query_dual_profile": 336,
    }
    assert len({item["run_id"] for item in schedule["crossfit_training_runs"]}) == 448
    assert len({item["slot_id"] for item in schedule["selected_serving_slots"]}) == 672

    changed = json.loads(
        (ROOT / DEFAULT_AUTHOR_SELECTION_PATH).read_text(encoding="utf-8")
    )
    changed["decisions"]["selected_serving_repetitions"] = "5"
    with pytest.raises(FinBenchConfirmatoryScheduleError, match="hash mismatch"):
        build_finbench_confirmatory_schedule(
            workload_root=output,
            protocol=ROOT / DEFAULT_PROTOCOL_PATH,
            author_selection=changed,
        )


def test_confirmatory_crossfit_excludes_own_fold_and_keeps_cold_family_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _data()
    registry = _compile(data)
    option = registry["population_options"][0]
    approval = build_finbench_confirmatory_population_approval(
        registry,
        selected_population_option_id=option["population_option_id"],
        approval_id="author-selection-crossfit-v1",
        authority_source_id="author:test:explicit-choice",
    )
    archive = tmp_path / "sf0.1.tar.gz"
    archive.write_bytes(b"verified-test-archive")
    lock = SimpleNamespace(
        artifact=SimpleNamespace(
            artifact_id=registry["source_artifact_id"],
            digest_value=registry["source_archive_sha256"],
        )
    )
    monkeypatch.setattr(workload, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(workload, "load_finbench_query_data", lambda *_args: data)
    output = tmp_path / "crossfit-workload"
    build_finbench_confirmatory_workload(
        archive_path=archive,
        population_registry=registry,
        population_approval=approval,
        output_root=output,
        lock_path=tmp_path / "unused-lock.json",
        family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
    )
    loaded = load_finbench_primary_workload(output)
    families = {
        item["family_id"]: item
        for item in loaded["family_contracts"]["families"]
    }
    raw_observations = []
    for instance in loaded["public_instances"]["instances"]:
        family_id = instance["family_id"]
        if family_id == F3:
            continue
        feature = next(iter(instance["selection_feature"].values()))
        for strategy_position, strategy in enumerate(
            families[family_id]["physical_strategies"], start=1
        ):
            repetitions = []
            for block in range(1, 5):
                order_position = (
                    strategy_position if block % 2 else 3 - strategy_position
                )
                repetitions.append(
                    {
                        "repetition_id": (
                            f"r-{instance['query_id']}-{strategy}-{block}"
                        ),
                        "block_index": block,
                        "order_position": order_position,
                        "elapsed_ms": float(feature + strategy_position * 10 + block),
                        "total_bytes_moved": int(
                            feature * 100 + strategy_position * 1000 + block
                        ),
                        "total_remote_calls": 2,
                        "execution_success": True,
                        "exact_answer": True,
                    }
                )
            raw_observations.append(
                {
                    "query_id": instance["query_id"],
                    "family_id": family_id,
                    "physical_strategy": strategy,
                    "repetitions": repetitions,
                }
            )

    suite = build_finbench_confirmatory_crossfit_predictions(
        workload_root=output,
        raw_observations=raw_observations,
        measurement_source_id="test-crossfit-observations-v1",
        policy=ROOT / "experiments/configs/m15_finbench_family_memory_policy_v1.json",
    ).to_dict()

    assert suite["prediction_count"] == 36
    assert suite["seen_family_prediction_count"] == 24
    assert suite["cold_family_prediction_count"] == 12
    assert suite["current_query_profile_calls"] == 0
    assert suite["historical_training_measurements_used"] is True
    assert suite["current_query_measurements_used_for_own_prediction"] is False
    assert suite["oracle_inputs"] == []
    assert suite["crossfit_exclusion_enforced"] is True
    assert all(memory["training_query_count"] == 18 for memory in suite["fold_memories"])
    assert all(memory["evaluation_query_count"] == 6 for memory in suite["fold_memories"])
    assert all(
        not set(memory["training_query_ids"]).intersection(
            memory["evaluation_query_ids"]
        )
        and memory["evaluation_query_observations_in_memory"] == []
        for memory in suite["fold_memories"]
    )
    for prediction in suite["predictions"]:
        assert prediction["own_query_observation_used"] is False
        assert prediction["current_query_measurements_used"] is False
        assert prediction["current_query_profile_calls"] == 0
        if prediction["family_id"] in (F1, F2):
            neighbors = {
                query_id
                for item in prediction["strategy_predictions"]
                for query_id in item["neighbor_query_ids"]
            }
            assert prediction["query_id"] not in neighbors
            assert all(
                next(
                    instance["evaluation_fold_id"]
                    for instance in loaded["public_instances"]["instances"]
                    if instance["query_id"] == query_id
                )
                != prediction["evaluation_fold_id"]
                for query_id in neighbors
            )
        else:
            assert prediction["selection_source"] == (
                "predeclared_cold_start_fallback"
            )
            assert prediction["strategy_predictions"] == []

    with pytest.raises(FinBenchConfirmatoryCrossfitError, match="cover every"):
        build_finbench_confirmatory_crossfit_predictions(
            workload_root=output,
            raw_observations=raw_observations[:-1],
            measurement_source_id="test-crossfit-observations-v1",
            policy=(
                ROOT
                / "experiments/configs/m15_finbench_family_memory_policy_v1.json"
            ),
        )


def test_design_drift_and_insufficient_frame_fail_closed() -> None:
    design = json.loads(
        (ROOT / DEFAULT_DESIGN_PATH).read_text(encoding="utf-8")
    )
    design["selection_uses_answer_content"] = True
    with pytest.raises(FinBenchConfirmatoryPopulationError, match="leakage"):
        compile_finbench_confirmatory_population_registry(
            _data(),
            source_artifact_id="ldbc-finbench-v0.1.0-sf0.1",
            source_archive_sha256="a" * 64,
            design=design,
        )

    small = replace(
        _data(),
        person_by_account={"S00": "P00"},
    )
    with pytest.raises(FinBenchConfirmatoryPopulationError, match="needs 3"):
        compile_finbench_confirmatory_population_registry(
            small,
            source_artifact_id="ldbc-finbench-v0.1.0-sf0.1",
            source_archive_sha256="a" * 64,
            design=ROOT / DEFAULT_DESIGN_PATH,
        )


def test_writer_is_atomic_and_refuses_overwrite(tmp_path: Path) -> None:
    registry = compile_finbench_confirmatory_population_registry(
        _data(),
        source_artifact_id="ldbc-finbench-v0.1.0-sf0.1",
        source_archive_sha256="a" * 64,
        design=ROOT / DEFAULT_DESIGN_PATH,
    )
    output = tmp_path / "population-options.json"
    write_finbench_confirmatory_population_registry(registry, output)
    assert json.loads(output.read_text(encoding="utf-8")) == registry.to_dict()
    with pytest.raises(FileExistsError):
        write_finbench_confirmatory_population_registry(registry, output)


def test_sealed_job_and_independent_auditor_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("", encoding="utf-8")
    archive = tmp_path / "sf0.1.tar.gz"
    archive.write_bytes(b"verified-test-archive")
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(
        json.dumps({"schema_version": "test-lock"}), encoding="utf-8"
    )
    design_path = tmp_path / "design.json"
    design_path.write_text(
        (ROOT / DEFAULT_DESIGN_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    lock = SimpleNamespace(
        artifact=SimpleNamespace(
            artifact_id="ldbc-finbench-v0.1.0-sf0.1",
            digest_value=archive_sha256,
        )
    )
    commit = "b" * 40
    monkeypatch.setattr(
        job,
        "_git_state",
        lambda _root: {"commit": commit, "clean": True},
    )
    monkeypatch.setattr(job, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(job, "load_finbench_query_data", lambda *_args: _data())
    monkeypatch.setattr(evidence, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(evidence, "load_finbench_query_data", lambda *_args: _data())
    run_root = tmp_path / "run"

    manifest = job.run_finbench_confirmatory_population_job(
        repo_root=repo,
        archive=archive,
        lock_path=lock_path,
        design_path=design_path,
        output_root=run_root,
        slurm_job_id="123",
    )
    before = {
        path.relative_to(run_root): path.read_bytes()
        for path in run_root.rglob("*")
        if path.is_file()
    }
    audit = evidence.audit_finbench_confirmatory_population(
        run_root=run_root,
        archive=archive,
        expected_commit=commit,
        lock_path=lock_path,
        design_path=design_path,
    )

    assert manifest["external_call_counts"] == {
        "backend_calls": 0,
        "current_query_profile_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
    }
    assert audit.success, audit.failed_check_ids
    assert audit.run_tree_mutated is False
    assert before == {
        path.relative_to(run_root): path.read_bytes()
        for path in run_root.rglob("*")
        if path.is_file()
    }


def test_population_auditor_refuses_in_tree_and_existing_output(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    archive = tmp_path / "archive.tar.gz"
    archive.write_bytes(b"archive")
    in_tree = run_root / "audit.json"
    assert evidence.main(
        [
            "--run-root",
            str(run_root),
            "--archive",
            str(archive),
            "--expected-commit",
            "a" * 40,
            "--output",
            str(in_tree),
        ]
    ) == 2
    assert not in_tree.exists()

    existing = tmp_path / "existing.json"
    existing.write_text("preserve", encoding="utf-8")
    assert evidence.main(
        [
            "--run-root",
            str(run_root),
            "--archive",
            str(archive),
            "--expected-commit",
            "a" * 40,
            "--output",
            str(existing),
        ]
    ) == 2
    assert existing.read_text(encoding="utf-8") == "preserve"


def test_population_job_and_auditor_reject_archive_symlinks(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "archive.tar.gz"
    archive.write_bytes(b"archive")
    link = tmp_path / "archive-link.tar.gz"
    link.symlink_to(archive)

    with pytest.raises(ValueError, match="symbolic link"):
        job.run_finbench_confirmatory_population_job(
            repo_root=tmp_path,
            archive=link,
            lock_path=tmp_path / "lock.json",
            design_path=ROOT / DEFAULT_DESIGN_PATH,
            output_root=tmp_path / "run",
            slurm_job_id="123",
        )
    with pytest.raises(ValueError, match="symbolic link"):
        evidence.audit_finbench_confirmatory_population(
            run_root=tmp_path,
            archive=link,
            expected_commit="a" * 40,
        )


def test_option_a_freeze_job_and_independent_auditor_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("", encoding="utf-8")
    archive = tmp_path / "sf0.1.tar.gz"
    archive.write_bytes(b"verified-test-archive")
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    lock_path = tmp_path / "lock.json"
    lock_path.write_text('{"schema_version":"test-lock"}\n', encoding="utf-8")
    design_path = tmp_path / "design.json"
    design_path.write_text(
        (ROOT / DEFAULT_DESIGN_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    lock = SimpleNamespace(
        artifact=SimpleNamespace(
            artifact_id="ldbc-finbench-v0.1.0-sf0.1",
            digest_value=archive_sha256,
        )
    )
    population_commit = "b" * 40
    freeze_commit = "c" * 40
    monkeypatch.setattr(job, "_git_state", lambda _root: {
        "commit": population_commit,
        "clean": True,
    })
    monkeypatch.setattr(job, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(job, "load_finbench_query_data", lambda *_args: _data())
    monkeypatch.setattr(evidence, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(evidence, "load_finbench_query_data", lambda *_args: _data())
    monkeypatch.setattr(workload, "load_finbench_artifact_lock", lambda _path: lock)
    monkeypatch.setattr(workload, "load_finbench_query_data", lambda *_args: _data())
    population_run = tmp_path / "population-run"
    job.run_finbench_confirmatory_population_job(
        repo_root=repo,
        archive=archive,
        lock_path=lock_path,
        design_path=design_path,
        output_root=population_run,
        slurm_job_id="population-test",
    )
    population_audit = evidence.audit_finbench_confirmatory_population(
        run_root=population_run,
        archive=archive,
        expected_commit=population_commit,
        lock_path=lock_path,
        design_path=design_path,
    ).to_dict()
    population_audit_path = tmp_path / "population-audit.json"
    population_audit_path.write_text(
        json.dumps(population_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(freeze_job, "_git_state", lambda _root: {
        "commit": freeze_commit,
        "clean": True,
    })
    freeze_run = tmp_path / "freeze-run"
    manifest = freeze_job.run_finbench_confirmatory_freeze_job(
        repo_root=repo,
        archive=archive,
        population_run_root=population_run,
        population_audit=population_audit_path,
        population_expected_commit=population_commit,
        output_root=freeze_run,
        slurm_job_id="freeze-test",
        lock_path=lock_path,
        protocol=ROOT / DEFAULT_PROTOCOL_PATH,
        author_selection=ROOT / DEFAULT_AUTHOR_SELECTION_PATH,
        family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
    )
    before = {
        path.relative_to(freeze_run): path.read_bytes()
        for path in freeze_run.rglob("*")
        if path.is_file()
    }
    audit = freeze_evidence.audit_finbench_confirmatory_freeze(
        run_root=freeze_run,
        archive=archive,
        population_run_root=population_run,
        population_audit=population_audit_path,
        population_expected_commit=population_commit,
        expected_commit=freeze_commit,
        lock_path=lock_path,
        protocol=ROOT / DEFAULT_PROTOCOL_PATH,
        author_selection=ROOT / DEFAULT_AUTHOR_SELECTION_PATH,
        family_contract=ROOT / DEFAULT_FAMILY_CONTRACT_PATH,
    )

    assert manifest["expected_counts"]["total_plan_runs"] == 1888
    assert manifest["expected_counts"]["total_backend_calls"] == 3776
    assert manifest["external_call_counts"] == {
        "backend_calls": 0,
        "current_query_profile_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
    }
    assert manifest["confirmatory_execution_authorized"] is False
    assert audit.success, audit.failed_check_ids
    assert audit.run_tree_mutated is False
    assert before == {
        path.relative_to(freeze_run): path.read_bytes()
        for path in freeze_run.rglob("*")
        if path.is_file()
    }


def test_confirmatory_freeze_slurm_entry_is_cpu_only_and_no_execution() -> None:
    wrapper = (
        ROOT / "scripts/slurm/run_m15_finbench_confirmatory_freeze.sbatch"
    ).read_text(encoding="utf-8")

    assert "#SBATCH --partition=batch" in wrapper
    assert "#SBATCH --time=00:30:00" in wrapper
    assert "m15_finbench_confirmatory_freeze_job" in wrapper
    assert "m15_finbench_paper_protocol_author_selection_a_v1.json" in wrapper
    assert "native_services" not in wrapper
    assert "vllm" not in wrapper.lower()
    assert "--gres=gpu" not in wrapper


def test_population_slurm_entry_is_cpu_only_and_result_blind() -> None:
    wrapper = (
        ROOT / "scripts/slurm/run_m15_finbench_confirmatory_population.sbatch"
    ).read_text(encoding="utf-8")

    assert "#SBATCH --partition=batch" in wrapper
    assert "#SBATCH --time=00:30:00" in wrapper
    assert "m15_finbench_confirmatory_population_job" in wrapper
    assert "m15_finbench_v010_sf0_1_sources.json" in wrapper
    assert "m15_finbench_confirmatory_population_design_v1.json" in wrapper
    assert "native_services" not in wrapper
    assert "vllm" not in wrapper.lower()
    assert "--gres=gpu" not in wrapper
