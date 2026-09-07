from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from xgap.experiments.m15_finbench_artifacts import DEFAULT_LOCK_PATH
from xgap.experiments.m15_finbench_partition import (
    ENTITY_PLACEMENTS,
    RELATIONSHIP_PLACEMENTS,
    build_finbench_source_partition,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _source_rows(*, orphan: bool = False, invalid_amount: bool = False) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    lock = json.loads((REPO_ROOT / DEFAULT_LOCK_PATH).read_text(encoding="utf-8"))
    for table in lock["snapshot_tables"]:
        row = {column: f"{table['table_id']}-{column}" for column in table["columns"]}
        if "isBlocked" in row:
            row["isBlocked"] = "false"
        rows[table["table_id"]] = row

    entity_ids = {
        "person": "P1",
        "account": "A1",
        "company": "C1",
        "medium": "M1",
        "loan": "L1",
    }
    for entity in ENTITY_PLACEMENTS:
        rows[entity.table_id][entity.id_column] = entity_ids[entity.table_id]
        for column in entity.numeric_columns:
            rows[entity.table_id][column] = "1.25"
    for edge in RELATIONSHIP_PLACEMENTS:
        rows[edge.table_id][edge.from_column] = entity_ids[edge.from_entity]
        rows[edge.table_id][edge.to_column] = entity_ids[edge.to_entity]
        for column in edge.numeric_columns:
            rows[edge.table_id][column] = "1.25"
    if orphan:
        rows["account_transfer_account"]["toId"] = "A-missing"
    if invalid_amount:
        rows["account_transfer_account"]["amount"] = "1); MATCH (n) DETACH DELETE n"
    return rows


def _write_fixture(
    tmp_path: Path, *, orphan: bool = False, invalid_amount: bool = False
) -> tuple[Path, Path]:
    lock_value = json.loads(
        (REPO_ROOT / DEFAULT_LOCK_PATH).read_text(encoding="utf-8")
    )
    rows = _source_rows(orphan=orphan, invalid_amount=invalid_amount)
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as handle:
        root = tarfile.TarInfo("sf0.01")
        root.type = tarfile.DIRTYPE
        handle.addfile(root)
        snapshot = tarfile.TarInfo("sf0.01/snapshot")
        snapshot.type = tarfile.DIRTYPE
        handle.addfile(snapshot)
        for table in lock_value["snapshot_tables"]:
            row = rows[table["table_id"]]
            payload = (
                "|".join(table["columns"])
                + "\n"
                + "|".join(row[column] for column in table["columns"])
                + "\n"
            ).encode("utf-8")
            member = tarfile.TarInfo(table["member"])
            member.size = len(payload)
            handle.addfile(member, io.BytesIO(payload))
    archive_bytes = archive_buffer.getvalue()
    archive = tmp_path / "sf0.01.tar.gz"
    archive.write_bytes(archive_bytes)

    lock_value["artifact"]["size_bytes"] = len(archive_bytes)
    lock_value["artifact"]["digest"]["value"] = hashlib.sha256(
        archive_bytes
    ).hexdigest()
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(lock_value), encoding="utf-8")
    return archive, lock


def test_partition_is_complete_split_and_loadable(tmp_path: Path) -> None:
    archive, lock = _write_fixture(tmp_path)
    output = tmp_path / "bundle"

    manifest = build_finbench_source_partition(
        archive_path=archive,
        lock_path=lock,
        output_root=output,
        batch_size=2,
    )

    cypher = (output / "load_neo4j.cypher").read_text(encoding="utf-8")
    turtle = (output / "load_fuseki.ttl").read_text(encoding="utf-8")
    persisted = json.loads(
        (output / "source_partition_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == persisted
    assert manifest["source_table_count"] == 18
    assert manifest["total_source_rows"] == 18
    assert manifest["referential_integrity"]["passed"] is True
    assert manifest["backend_calls"] == 0
    assert manifest["answer_oracle_accessed"] is False
    assert manifest["paper_result"] is False
    assert "TRANSFERRED_TO" in cypher
    assert "WITHDREW_TO" in cypher
    assert "isBlocked" not in cypher
    assert "xgapfb:isBlocked false" in turtle
    assert "xgapfb:riskLevel" in turtle
    assert manifest["output_files"]["load_neo4j.cypher"]["sha256"] == hashlib.sha256(
        cypher.encode("utf-8")
    ).hexdigest()


def test_partition_is_byte_deterministic(tmp_path: Path) -> None:
    archive, lock = _write_fixture(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    one = build_finbench_source_partition(
        archive_path=archive, lock_path=lock, output_root=first
    )
    two = build_finbench_source_partition(
        archive_path=archive, lock_path=lock, output_root=second
    )

    assert one == two
    for name in ("load_neo4j.cypher", "load_fuseki.ttl", "source_partition_manifest.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_partition_rejects_orphan_relationship_without_partial_output(
    tmp_path: Path,
) -> None:
    archive, lock = _write_fixture(tmp_path, orphan=True)
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="endpoints are missing"):
        build_finbench_source_partition(
            archive_path=archive, lock_path=lock, output_root=output
        )

    assert not output.exists()
    assert list(tmp_path.glob("bundle.partial-*")) == []


def test_partition_rejects_numeric_injection(tmp_path: Path) -> None:
    archive, lock = _write_fixture(tmp_path, invalid_amount=True)

    with pytest.raises(ValueError, match="Invalid FinBench numeric value"):
        build_finbench_source_partition(
            archive_path=archive, lock_path=lock, output_root=tmp_path / "bundle"
        )


def test_partition_refuses_to_overwrite_bundle(tmp_path: Path) -> None:
    archive, lock = _write_fixture(tmp_path)
    output = tmp_path / "bundle"
    output.mkdir()

    with pytest.raises(ValueError, match="Output already exists"):
        build_finbench_source_partition(
            archive_path=archive, lock_path=lock, output_root=output
        )
