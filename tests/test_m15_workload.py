from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_workload import (
    BUNDLE_SCHEMA_VERSION,
    M15WorkloadSpec,
    generate_m15_workload_bundle,
    load_m15_workload_bundle,
    main,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTIVE_CONFIG = REPO_ROOT / "experiments/configs/m15_f0_selective.json"
BROAD_CONFIG = REPO_ROOT / "experiments/configs/m15_f0_broad_hot.json"


def _small_spec(**changes: object) -> M15WorkloadSpec:
    values: dict[str, object] = {
        "schema_version": "m15-f0-workload-spec-v1",
        "workload_id": "test-selective",
        "seed": "test-seed-v1",
        "company_count": 12,
        "transfer_count": 40,
        "high_risk_company_count": 3,
        "hot_company_count": 2,
        "hot_transfer_count": 32,
        "high_risk_placement": "cold_first",
        "max_bindings": 12,
    }
    values.update(changes)
    return M15WorkloadSpec.from_dict(values)


def test_workload_generation_is_byte_deterministic_and_hash_bound(
    tmp_path: Path,
) -> None:
    spec = _small_spec()
    first = generate_m15_workload_bundle(spec, tmp_path / "first")
    second = generate_m15_workload_bundle(spec, tmp_path / "second")

    assert first.manifest == second.manifest
    assert first.manifest["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert first.manifest["deterministic"] is True
    assert first.manifest["automatic_retries"] == 0
    assert first.manifest["paper_result"] is False
    for filename, digest in first.source_hashes.items():
        assert digest == second.source_hashes[filename]
        assert first.path(filename).read_bytes() == second.path(filename).read_bytes()
    assert len(first.expected_source_rows["neo4j"]) == spec.transfer_count
    assert len(first.expected_source_rows["fuseki"]) == spec.high_risk_company_count
    neo4j_load = first.path("load_neo4j.cypher").read_text("utf-8")
    assert "UNWIND" in neo4j_load
    assert "UNWIND [{account_id:" in neo4j_load
    assert '{"account_id"' not in neo4j_load
    assert '{"amount"' not in neo4j_load
    assert "$company_ids" in first.path(
        "query_recent_transfers_bound.cypher"
    ).read_text("utf-8")


def test_committed_development_configs_create_opposite_selectivity_regimes(
    tmp_path: Path,
) -> None:
    selective = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(SELECTIVE_CONFIG),
        tmp_path / "selective",
    )
    broad = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(BROAD_CONFIG),
        tmp_path / "broad",
    )

    assert selective.spec.transfer_count == broad.spec.transfer_count == 5000
    assert len(selective.expected_rows) < 250
    assert len(broad.expected_rows) > 4000
    assert len(selective.expected_rows) < len(broad.expected_rows)
    assert selective.manifest["counts"]["answer_rows"] == len(
        selective.expected_rows
    )
    assert broad.manifest["counts"]["answer_rows"] == len(broad.expected_rows)


def test_bundle_loader_rejects_tamper_extra_files_and_overwrite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    generate_m15_workload_bundle(_small_spec(), root)
    with pytest.raises(FileExistsError, match="already exists"):
        generate_m15_workload_bundle(_small_spec(), root)

    query = root / "query_high_risk.rq"
    query.write_text(query.read_text("utf-8") + "# tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_m15_workload_bundle(root)

    query.write_text(query.read_text("utf-8").removesuffix("# tampered\n"), encoding="utf-8")
    (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch"):
        load_m15_workload_bundle(root)


def test_bundle_loader_rejects_content_and_hash_changed_together(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    generate_m15_workload_bundle(_small_spec(), root)
    query = root / "query_high_risk.rq"
    query.write_text(query.read_text("utf-8") + "# changed with digest\n", encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files_sha256"]["query_high_risk.rq"] = hashlib.sha256(
        query.read_bytes()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not deterministic for its spec"):
        load_m15_workload_bundle(root)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"workload_id": "../escape"}, "workload_id"),
        ({"company_count": True}, "company_count must be an integer"),
        ({"hot_company_count": 12}, "hot_company_count"),
        ({"high_risk_placement": "random"}, "high_risk_placement"),
        (
            {"high_risk_company_count": 5, "max_bindings": 4},
            "max_bindings must cover",
        ),
    ],
)
def test_workload_spec_rejects_unbounded_or_ambiguous_configuration(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _small_spec(**changes)


def test_workload_generator_rejects_an_empty_federated_answer(
    tmp_path: Path,
) -> None:
    spec = _small_spec(
        hot_transfer_count=40,
        high_risk_placement="cold_first",
    )

    with pytest.raises(ValueError, match="empty federated answer"):
        generate_m15_workload_bundle(spec, tmp_path / "empty")
    assert not (tmp_path / "empty").exists()


def test_workload_cli_refuses_existing_destination(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "bundle"
    assert main(["--spec", str(SELECTIVE_CONFIG), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "success"

    assert main(["--spec", str(SELECTIVE_CONFIG), "--output", str(output)]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "configuration_error"
    assert "already exists" in failure["error"]
