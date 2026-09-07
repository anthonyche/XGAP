from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from xgap.experiments import m15_finbench_workload as workload_module
from xgap.experiments.m15_finbench_artifacts import DEFAULT_LOCK_PATH
from xgap.experiments.m15_finbench_partition import (
    ENTITY_PLACEMENTS,
    RELATIONSHIP_PLACEMENTS,
    build_finbench_source_partition,
)
from xgap.experiments.m15_finbench_workload import (
    DEFAULT_SPEC_PATH,
    FinBenchQueryData,
    Transfer,
    _f1_instances,
    _f2_instances,
    _f3_instances,
    _templates,
    build_finbench_primary_workload,
    load_finbench_primary_workload,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _synthetic_query_data() -> FinBenchQueryData:
    people = {
        f"P{index:02d}": {"personId": f"P{index:02d}"} for index in range(12)
    }
    companies = {
        f"C{index:02d}": {"companyId": f"C{index:02d}"} for index in range(12)
    }
    media = {
        "MB": {"mediumId": "MB", "isBlocked": "true", "mediumType": "PHONE", "riskLevel": "Low risk"},
        "ML": {"mediumId": "ML", "isBlocked": "false", "mediumType": "NFC", "riskLevel": "Low risk"},
        "MH": {"mediumId": "MH", "isBlocked": "false", "mediumType": "NFC", "riskLevel": "High risk"},
        "MC": {"mediumId": "MC", "isBlocked": "false", "mediumType": "NFC", "riskLevel": "Critical risk"},
    }
    accounts: dict[str, dict[str, str]] = {}
    person_by_account: dict[str, str] = {}
    company_by_account: dict[str, str] = {}
    media_by_account: dict[str, tuple[str, ...]] = {}
    transfers: list[Transfer] = []
    outgoing: dict[str, list[Transfer]] = defaultdict(list)

    def add(source: str, target: str, amount: str, when: str, order: str) -> None:
        transfer = Transfer(source, target, Decimal(amount), when, order)
        transfers.append(transfer)
        outgoing[source].append(transfer)

    for index in range(12):
        source = f"S{index:02d}"
        destination = f"D{index:02d}"
        path_start = f"Q{index:02d}"
        accounts[source] = {"accountId": source, "isBlocked": "false"}
        accounts[destination] = {"accountId": destination, "isBlocked": "true"}
        accounts[path_start] = {"accountId": path_start, "isBlocked": "false"}
        person_by_account[source] = f"P{index:02d}"
        company_by_account[destination] = f"C{index:02d}"
        media_by_account[destination] = ("MB", "ML", "MH", "MC")
        for edge_index in range(index + 2):
            when = "2022-11-01 00:00:00.000"
            add(source, destination, "10.00", when, f"F{index}-{edge_index}")
        for edge_index in range(index + 2):
            target = f"T{index:02d}-{edge_index:02d}"
            accounts[target] = {"accountId": target, "isBlocked": "false"}
            if edge_index == 0:
                media_by_account[target] = ("MB",)
            add(
                path_start,
                target,
                "5.00",
                f"2022-10-{edge_index + 1:02d} 00:00:00.000",
                f"Q{index}-{edge_index}",
            )
    # Fix the temporal domain independently of candidate ordering and ensure
    # every suffix window has a nonempty risk-ranked result.
    add("S00", "D00", "1.00", "2020-01-01 00:00:00.000", "MIN")
    add("S00", "D00", "1.00", "2023-12-31 23:59:59.999", "MAX")
    return FinBenchQueryData(
        people=people,
        accounts=accounts,
        companies=companies,
        media=media,
        person_by_account=person_by_account,
        company_by_account=company_by_account,
        media_by_account=media_by_account,
        transfers=tuple(transfers),
        outgoing={
            key: tuple(sorted(value, key=lambda item: (item.create_time, item.to_id, item.order_num)))
            for key, value in outgoing.items()
        },
        minimum_transfer_time="2020-01-01 00:00:00.000",
        maximum_transfer_time="2023-12-31 23:59:59.999",
    )


def _write_minimal_verified_partition(tmp_path: Path) -> tuple[Path, Path, Path]:
    lock_value = json.loads(
        (REPO_ROOT / DEFAULT_LOCK_PATH).read_text(encoding="utf-8")
    )
    rows: dict[str, dict[str, str]] = {}
    for table in lock_value["snapshot_tables"]:
        row = {column: "value" for column in table["columns"]}
        if "isBlocked" in row:
            row["isBlocked"] = "false"
        rows[table["table_id"]] = row
    ids = {"person": "P", "account": "A", "company": "C", "medium": "M", "loan": "L"}
    for entity in ENTITY_PLACEMENTS:
        rows[entity.table_id][entity.id_column] = ids[entity.table_id]
        for column in entity.numeric_columns:
            rows[entity.table_id][column] = "1.0"
    for edge in RELATIONSHIP_PLACEMENTS:
        rows[edge.table_id][edge.from_column] = ids[edge.from_entity]
        rows[edge.table_id][edge.to_column] = ids[edge.to_entity]
        for column in edge.numeric_columns:
            rows[edge.table_id][column] = "1.0"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as handle:
        for directory in ("sf0.01", "sf0.01/snapshot"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            handle.addfile(info)
        for table in lock_value["snapshot_tables"]:
            row = rows[table["table_id"]]
            payload = (
                "|".join(table["columns"])
                + "\n"
                + "|".join(row[column] for column in table["columns"])
                + "\n"
            ).encode("utf-8")
            info = tarfile.TarInfo(table["member"])
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))
    archive_bytes = buffer.getvalue()
    archive = tmp_path / "sf0.01.tar.gz"
    archive.write_bytes(archive_bytes)
    lock_value["artifact"]["size_bytes"] = len(archive_bytes)
    lock_value["artifact"]["digest"]["value"] = hashlib.sha256(archive_bytes).hexdigest()
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(lock_value), encoding="utf-8")
    partition = tmp_path / "partition"
    build_finbench_source_partition(
        archive_path=archive, lock_path=lock, output_root=partition
    )
    return archive, lock, partition


def test_three_families_have_frozen_counts_splits_and_nonempty_oracles() -> None:
    data = _synthetic_query_data()

    f1, f1_oracles = _f1_instances(data)
    f2, f2_oracles = _f2_instances(data)
    f3, f3_oracles = _f3_instances(
        data, ("Low risk", "High risk", "Critical risk"), 10
    )

    assert [len(f1), len(f2), len(f3)] == [12, 12, 12]
    assert sum(item["split_role"] == "training" for item in [*f1, *f2]) == 16
    assert sum(item["split_role"] == "heldout_instance" for item in [*f1, *f2]) == 8
    assert {item["split_role"] for item in f3} == {"heldout_family"}
    for oracle in {**f1_oracles, **f2_oracles, **f3_oracles}.values():
        assert oracle["final_rows"]


def test_templates_expose_two_physical_routes_without_literal_ids() -> None:
    templates = _templates()

    assert len(templates) == 9
    assert "$control_ids" in templates["f1_neo4j_bound.cypher.tmpl"]
    assert "TRANSFERRED_TO*1..3" in templates["f2_neo4j_full.cypher.tmpl"]
    assert "strictly" not in templates["f2_neo4j_full.cypher.tmpl"]
    assert "$top_k" in templates["f3_neo4j_bound.cypher.tmpl"]
    assert "{{risk_level_literal}}" in templates["f3_fuseki_control.rq.tmpl"]
    assert not any("P00" in text or "D00" in text for text in templates.values())


def test_workload_bundle_is_deterministic_and_oracle_separated(
    tmp_path: Path, monkeypatch
) -> None:
    archive, lock, partition = _write_minimal_verified_partition(tmp_path)
    monkeypatch.setattr(
        workload_module,
        "load_finbench_query_data",
        lambda _archive, _lock: _synthetic_query_data(),
    )
    first = tmp_path / "workload-one"
    second = tmp_path / "workload-two"

    one = build_finbench_primary_workload(
        archive_path=archive,
        partition_root=partition,
        output_root=first,
        lock_path=lock,
        spec_path=REPO_ROOT / DEFAULT_SPEC_PATH,
    )
    two = build_finbench_primary_workload(
        archive_path=archive,
        partition_root=partition,
        output_root=second,
        lock_path=lock,
        spec_path=REPO_ROOT / DEFAULT_SPEC_PATH,
    )

    assert one == two
    assert one["instance_count"] == 36
    assert one["family_counts"] == {
        "f1_direct_transfer_control": 12,
        "f2_temporal_path_control": 12,
        "f3_aggregate_risk_ranking": 12,
    }
    assert one["split_counts"] == {
        "heldout_family": 12,
        "heldout_instance": 8,
        "training": 16,
    }
    public = json.loads((first / "public_instances.json").read_text())
    assert public["oracle_fields_present"] is False
    assert "final_rows" not in json.dumps(public)
    assert json.loads((first / "sealed_oracles.json").read_text())["queries"]
    assert load_finbench_primary_workload(first)["manifest"] == one
    for path in first.rglob("*"):
        if path.is_file():
            relative = path.relative_to(first)
            assert path.read_bytes() == (second / relative).read_bytes()


def test_workload_loader_detects_public_instance_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    archive, lock, partition = _write_minimal_verified_partition(tmp_path)
    monkeypatch.setattr(
        workload_module,
        "load_finbench_query_data",
        lambda _archive, _lock: _synthetic_query_data(),
    )
    output = tmp_path / "workload"
    build_finbench_primary_workload(
        archive_path=archive,
        partition_root=partition,
        output_root=output,
        lock_path=lock,
        spec_path=REPO_ROOT / DEFAULT_SPEC_PATH,
    )
    with (output / "public_instances.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")

    try:
        load_finbench_primary_workload(output)
    except ValueError as exc:
        assert "size mismatch" in str(exc)
    else:
        raise AssertionError("mutated public instance file was accepted")
