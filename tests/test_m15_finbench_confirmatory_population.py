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
from xgap.experiments.m15_finbench_confirmatory_population import (
    DEFAULT_DESIGN_PATH,
    FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION,
    FinBenchConfirmatoryPopulationError,
    compile_finbench_confirmatory_population_registry,
    write_finbench_confirmatory_population_registry,
)
from xgap.experiments.m15_finbench_workload import (
    FinBenchQueryData,
    Transfer,
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
