"""Build an auditable Neo4j/Fuseki partition of a pinned FinBench snapshot.

The partition is a source-placement artifact, not an experiment result.  It
keeps graph structure and transactions in Neo4j, keeps semantic/control
attributes in Fuseki, and replicates only stable entity identity across the
two backends.  No backend, LLM, ontology service, or answer oracle is invoked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, TextIO

from xgap.experiments.m15_finbench_artifacts import (
    DEFAULT_LOCK_PATH,
    FinBenchArtifactLock,
    SnapshotTableSpec,
    load_finbench_artifact_lock,
    validate_finbench_tar_inventory,
    verify_finbench_archive,
)


LEGACY_PARTITION_SCHEMA_VERSION = "m15-finbench-source-partition-v1"
PARTITION_SCHEMA_VERSION = "m15-finbench-source-partition-v2"
SUPPORTED_PARTITION_SCHEMA_VERSIONS = frozenset(
    {LEGACY_PARTITION_SCHEMA_VERSION, PARTITION_SCHEMA_VERSION}
)
GENERATOR_VERSION = "m15-finbench-partition-generator-v2"
NEO4J_BATCH_SCHEMA_VERSION = "m15-finbench-neo4j-parameterized-batch-v1"
NEO4J_BATCH_FILENAME = "load_neo4j_batches.jsonl"
DEFAULT_BATCH_SIZE = 250
_DECIMAL = re.compile(
    r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
)
_SCHEMA_IRI = "https://xgap.dev/benchmark/finbench/v0.1.0/schema/"
_RESOURCE_IRI = "https://xgap.dev/benchmark/finbench/v0.1.0/resource/"


def validate_finbench_source_identity(
    workload_manifest: Mapping[str, Any],
    partition_manifest: Mapping[str, Any],
    *,
    source_identity_mode: str = "partition",
) -> str:
    """Bind a frozen workload to a separately validated source partition.

    Original confirmatory workpacks pin the source archive before placement.
    Explicit archive mode accepts that contract without rewriting the workpack;
    it never discards a partition pin the workload actually declares. This is
    metadata admission, not verification of the archive or partition bytes.
    """
    if source_identity_mode not in ("partition", "source_archive"):
        raise ValueError("unsupported FinBench source identity mode")

    def sha256(value: Any, label: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"FinBench {label} must be a lowercase SHA-256")
        return value

    actual_partition = sha256(partition_manifest.get("partition_sha256"), "partition identity")
    archive = partition_manifest.get("source_archive")
    actual_archive = sha256(
        archive.get("sha256") if isinstance(archive, Mapping) else None,
        "partition source archive identity",
    )
    expected_archive = sha256(workload_manifest.get("source_archive_sha256"), "workload source archive identity")
    if expected_archive != actual_archive:
        raise ValueError("FinBench workload and source archive identities differ")
    if "source_partition_sha256" in workload_manifest:
        expected_partition = sha256(
            workload_manifest["source_partition_sha256"], "workload partition identity"
        )
        if expected_partition != actual_partition:
            raise ValueError("FinBench workload and source partition identities differ")
    elif source_identity_mode == "partition":
        raise ValueError("FinBench partition mode requires a workload partition identity")
    return actual_archive


@dataclass(frozen=True)
class EntityPlacement:
    table_id: str
    id_column: str
    neo4j_label: str
    rdf_type: str
    neo4j_columns: tuple[str, ...]
    fuseki_columns: tuple[tuple[str, str], ...]
    numeric_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipPlacement:
    table_id: str
    from_column: str
    from_entity: str
    to_column: str
    to_entity: str
    neo4j_type: str
    property_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...] = ()


ENTITY_PLACEMENTS: tuple[EntityPlacement, ...] = (
    EntityPlacement(
        "person",
        "personId",
        "XGAPFinBenchPerson",
        "Person",
        ("personName", "createTime", "birthday"),
        (
            ("isBlocked", "isBlocked"),
            ("gender", "gender"),
            ("country", "country"),
            ("city", "city"),
        ),
    ),
    EntityPlacement(
        "account",
        "accountId",
        "XGAPFinBenchAccount",
        "Account",
        ("createTime", "nickname", "phonenum", "email", "lastLoginTime"),
        (
            ("isBlocked", "isBlocked"),
            ("accoutType", "accountType"),
            ("freqLoginType", "frequentLoginType"),
            ("accountLevel", "accountLevel"),
        ),
    ),
    EntityPlacement(
        "company",
        "companyId",
        "XGAPFinBenchCompany",
        "Company",
        ("companyName", "createTime", "description", "url"),
        (
            ("isBlocked", "isBlocked"),
            ("country", "country"),
            ("city", "city"),
            ("business", "business"),
        ),
    ),
    EntityPlacement(
        "medium",
        "mediumId",
        "XGAPFinBenchMedium",
        "Medium",
        ("createTime", "lastLoginTime"),
        (
            ("isBlocked", "isBlocked"),
            ("mediumType", "mediumType"),
            ("riskLevel", "riskLevel"),
        ),
    ),
    EntityPlacement(
        "loan",
        "loanId",
        "XGAPFinBenchLoan",
        "Loan",
        ("loanAmount", "balance", "createTime", "interestRate"),
        (("loanUsage", "loanUsage"),),
        ("loanAmount", "balance", "interestRate"),
    ),
)


RELATIONSHIP_PLACEMENTS: tuple[RelationshipPlacement, ...] = (
    RelationshipPlacement(
        "person_own_account",
        "personId",
        "person",
        "accountId",
        "account",
        "OWNS_ACCOUNT",
        ("createTime",),
    ),
    RelationshipPlacement(
        "company_own_account",
        "companyId",
        "company",
        "accountId",
        "account",
        "OWNS_ACCOUNT",
        ("createTime",),
    ),
    RelationshipPlacement(
        "account_transfer_account",
        "fromId",
        "account",
        "toId",
        "account",
        "TRANSFERRED_TO",
        ("amount", "createTime", "orderNum", "comment", "payType", "goodsType"),
        ("amount",),
    ),
    RelationshipPlacement(
        "medium_sign_in_account",
        "mediumId",
        "medium",
        "accountId",
        "account",
        "SIGNED_IN_TO",
        ("createTime", "location"),
    ),
    RelationshipPlacement(
        "person_guarantee_person",
        "fromId",
        "person",
        "toId",
        "person",
        "GUARANTEES",
        ("createTime", "relation"),
    ),
    RelationshipPlacement(
        "person_apply_loan",
        "personId",
        "person",
        "loanId",
        "loan",
        "APPLIED_FOR",
        ("createTime", "org"),
    ),
    RelationshipPlacement(
        "loan_deposit_account",
        "loanId",
        "loan",
        "accountId",
        "account",
        "DEPOSITED_TO",
        ("amount", "createTime"),
        ("amount",),
    ),
    RelationshipPlacement(
        "company_apply_loan",
        "companyId",
        "company",
        "loanId",
        "loan",
        "APPLIED_FOR",
        ("createTime", "org"),
    ),
    RelationshipPlacement(
        "account_withdraw_account",
        "fromId",
        "account",
        "toId",
        "account",
        "WITHDREW_TO",
        ("amount", "createTime"),
        ("amount",),
    ),
    RelationshipPlacement(
        "account_repay_loan",
        "accountId",
        "account",
        "loanId",
        "loan",
        "REPAID",
        ("amount", "createTime"),
        ("amount",),
    ),
    RelationshipPlacement(
        "company_invest_company",
        "investorId",
        "company",
        "companyId",
        "company",
        "INVESTED_IN",
        ("ratio", "createTime"),
        ("ratio",),
    ),
    RelationshipPlacement(
        "company_guarantee_company",
        "fromId",
        "company",
        "toId",
        "company",
        "GUARANTEES",
        ("createTime", "relation"),
    ),
    RelationshipPlacement(
        "person_invest_company",
        "investorId",
        "person",
        "companyId",
        "company",
        "INVESTED_IN",
        ("ratio", "createTime"),
        ("ratio",),
    ),
)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _numeric_value(value: str, *, table_id: str, column: str) -> int | float:
    if not value or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"Invalid FinBench numeric value: {table_id}.{column}")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid FinBench numeric value: {table_id}.{column}"
        ) from exc
    if not parsed.is_finite():
        raise ValueError(f"Non-finite FinBench numeric value: {table_id}.{column}")
    if "." not in value and "e" not in value.lower():
        return int(value)
    converted = float(parsed)
    if not converted == converted or converted in {float("inf"), float("-inf")}:
        raise ValueError(f"Non-finite FinBench numeric value: {table_id}.{column}")
    return converted


def _parameter_map(
    value: Mapping[str, str],
    *,
    table_id: str,
    numeric_columns: frozenset[str] = frozenset(),
) -> dict[str, str | int | float]:
    return {
        key: (
            _numeric_value(value[key], table_id=table_id, column=key)
            if key in numeric_columns
            else value[key]
        )
        for key in sorted(value)
    }


def _rdf_literal(value: str, *, boolean: bool = False) -> str:
    if boolean:
        if value not in {"true", "false"}:
            raise ValueError(f"Invalid FinBench boolean value: {value!r}")
        return value
    return json.dumps(value, ensure_ascii=False)


def _resource_iri(entity: str, identifier: str) -> str:
    if not identifier:
        raise ValueError(f"Empty FinBench identifier for {entity}")
    encoded = urllib.parse.quote(identifier, safe="")
    return f"<{_RESOURCE_IRI}{entity}/{encoded}>"


def _iter_rows(
    handle: tarfile.TarFile,
    inventory: Mapping[str, tarfile.TarInfo],
    table: SnapshotTableSpec,
) -> Iterator[tuple[int, dict[str, str]]]:
    member = inventory.get(table.member)
    if member is None or not member.isfile():
        raise ValueError(f"Required FinBench snapshot member is missing: {table.member}")
    stream = handle.extractfile(member)
    if stream is None:
        raise ValueError(f"Cannot read FinBench snapshot member: {table.member}")
    with io.TextIOWrapper(stream, encoding="utf-8", newline="") as text_stream:
        reader = csv.reader(text_stream, delimiter="|")
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise ValueError(f"FinBench snapshot member is empty: {table.member}") from exc
        if header != table.columns:
            raise ValueError(f"FinBench snapshot header drift: {table.member}")
        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise ValueError(
                    f"FinBench row width drift: {table.member}:{row_number}"
                )
            yield row_number, dict(zip(header, row, strict=True))


def _write_parameterized_batches(
    output: TextIO,
    rows: Iterator[Mapping[str, Any]],
    statement: str,
    *,
    kind: str,
    source_table: str,
    batch_size: int,
) -> tuple[int, int]:
    row_count = 0
    statement_count = 0
    batch: list[dict[str, Any]] = []

    def write_batch(items: Sequence[Mapping[str, Any]]) -> None:
        nonlocal statement_count
        statement_count += 1
        batch_id = f"{kind}-{source_table}-{statement_count:06d}"
        record: dict[str, Any] = {
            "schema_version": NEO4J_BATCH_SCHEMA_VERSION,
            "batch_id": batch_id,
            "kind": kind,
            "source_table": source_table,
            "statement": statement,
            "parameters": {"rows": [dict(item) for item in items]},
            "expected_affected_rows": len(items),
            "mutation_semantics": "create_into_empty_job_owned_database",
            "automatic_retries": 0,
        }
        record["batch_sha256"] = _canonical_sha256(record)
        output.write(
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )

    for row in rows:
        batch.append(dict(row))
        row_count += 1
        if len(batch) == batch_size:
            write_batch(batch)
            batch.clear()
    if batch:
        write_batch(batch)
    return row_count, statement_count


def _write_constraint_batch(
    output: TextIO, *, source_table: str, statement: str
) -> None:
    record: dict[str, Any] = {
        "schema_version": NEO4J_BATCH_SCHEMA_VERSION,
        "batch_id": f"constraint-{source_table}",
        "kind": "constraint",
        "source_table": source_table,
        "statement": statement,
        "parameters": {},
        "expected_affected_rows": None,
        "mutation_semantics": "create_into_empty_job_owned_database",
        "automatic_retries": 0,
    }
    record["batch_sha256"] = _canonical_sha256(record)
    output.write(
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _validate_complete_placement(lock: FinBenchArtifactLock) -> dict[str, SnapshotTableSpec]:
    tables = {item.table_id: item for item in lock.snapshot_tables}
    expected = {
        item.table_id for item in ENTITY_PLACEMENTS
    } | {item.table_id for item in RELATIONSHIP_PLACEMENTS}
    missing = sorted(expected - set(tables))
    extra = sorted(set(tables) - expected)
    if missing or extra:
        raise ValueError(
            f"FinBench partition table-set drift: missing={missing}, extra={extra}"
        )
    for entity in ENTITY_PLACEMENTS:
        columns = set(tables[entity.table_id].columns)
        required = {entity.id_column, *entity.neo4j_columns}
        required.update(source for source, _predicate in entity.fuseki_columns)
        if not required <= columns:
            raise ValueError(f"FinBench entity placement drift: {entity.table_id}")
    for edge in RELATIONSHIP_PLACEMENTS:
        columns = set(tables[edge.table_id].columns)
        required = {edge.from_column, edge.to_column, *edge.property_columns}
        if not required <= columns:
            raise ValueError(f"FinBench relationship placement drift: {edge.table_id}")
    return tables


def load_finbench_source_partition(root: str | Path) -> dict[str, Any]:
    """Load and verify the identity and two load files of one partition bundle."""

    bundle_root = Path(root).resolve()
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ValueError("FinBench partition root must be a regular directory")
    manifest_path = bundle_root / "source_partition_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("FinBench source partition manifest is missing or unsafe")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("FinBench source partition manifest must be an object")
    schema_version = manifest.get("schema_version")
    if schema_version not in SUPPORTED_PARTITION_SCHEMA_VERSIONS:
        raise ValueError("FinBench source partition schema is unsupported")
    if manifest.get("paper_result") is not False:
        raise ValueError("FinBench source partition must remain paper_result=false")
    claimed = manifest.get("partition_sha256")
    if not isinstance(claimed, str) or claimed != _canonical_sha256(
        {key: value for key, value in manifest.items() if key != "partition_sha256"}
    ):
        raise ValueError("FinBench source partition identity mismatch")
    output_files = manifest.get("output_files")
    expected_files = (
        {"load_neo4j.cypher", "load_fuseki.ttl"}
        if schema_version == LEGACY_PARTITION_SCHEMA_VERSION
        else {NEO4J_BATCH_FILENAME, "load_fuseki.ttl"}
    )
    if not isinstance(output_files, Mapping) or set(output_files) != expected_files:
        raise ValueError("FinBench source partition output file set is invalid")
    for name, raw in output_files.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"FinBench source partition file record is invalid: {name}")
        candidate = bundle_root / name
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"FinBench source partition file is missing or unsafe: {name}")
        if raw.get("size_bytes") != candidate.stat().st_size:
            raise ValueError(f"FinBench source partition file size mismatch: {name}")
        if raw.get("sha256") != _file_sha256(candidate):
            raise ValueError(f"FinBench source partition file digest mismatch: {name}")
    if schema_version == PARTITION_SCHEMA_VERSION:
        neo4j_load = manifest.get("neo4j_load")
        if not isinstance(neo4j_load, Mapping) or dict(neo4j_load) != {
            "format": "parameterized_jsonl_batches_v1",
            "filename": NEO4J_BATCH_FILENAME,
            "batch_schema_version": NEO4J_BATCH_SCHEMA_VERSION,
            "mutation_semantics": "create_into_empty_job_owned_database",
            "requires_empty_job_owned_database": True,
            "automatic_retries": 0,
        }:
            raise ValueError("FinBench source partition Neo4j load contract is invalid")
    return dict(manifest)


def build_finbench_source_partition(
    *,
    archive_path: str | Path,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    output_root: str | Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Create one immutable, directly loadable source partition bundle."""

    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("FinBench partition batch_size must be a positive integer")
    archive = Path(archive_path).resolve()
    lock_file = Path(lock_path).resolve()
    destination = Path(output_root).resolve()
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    lock = load_finbench_artifact_lock(lock_file)
    tables = _validate_complete_placement(lock)
    verification = verify_finbench_archive(archive, lock.artifact)
    if not verification.success:
        raise ValueError(f"FinBench archive verification failed: {verification.status}")

    staging = Path(
        tempfile.mkdtemp(prefix=destination.name + ".partial-", dir=destination.parent)
    )
    neo4j_path = staging / NEO4J_BATCH_FILENAME
    fuseki_path = staging / "load_fuseki.ttl"
    manifest_path = staging / "source_partition_manifest.json"
    source_counts: dict[str, int] = {}
    neo4j_statements: dict[str, int] = {}
    fuseki_triples: dict[str, int] = {}
    entity_ids: dict[str, set[str]] = {}
    orphan_counts: dict[str, int] = {}

    entity_by_id = {item.table_id: item for item in ENTITY_PLACEMENTS}
    try:
        with tarfile.open(archive, mode="r:gz") as handle, neo4j_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as neo4j, fuseki_path.open("w", encoding="utf-8", newline="\n") as fuseki:
            inventory = validate_finbench_tar_inventory(
                handle, lock.artifact.archive_root
            )
            fuseki.write(f"@prefix xgapfb: <{_SCHEMA_IRI}> .\n")
            fuseki.write("@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n\n")

            for entity in ENTITY_PLACEMENTS:
                constraint_name = f"xgap_finbench_{entity.table_id}_id"
                _write_constraint_batch(
                    neo4j,
                    source_table=entity.table_id,
                    statement=(
                        f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                        f"FOR (n:{entity.neo4j_label}) REQUIRE n.id IS UNIQUE"
                    ),
                )
                neo4j_statements[f"constraint:{entity.table_id}"] = 1

            for entity in ENTITY_PLACEMENTS:
                seen: set[str] = set()
                rdf_count = 0

                def encoded_nodes() -> Iterator[dict[str, Any]]:
                    nonlocal rdf_count
                    for _row_number, row in _iter_rows(
                        handle, inventory, tables[entity.table_id]
                    ):
                        identifier = row[entity.id_column]
                        if not identifier or identifier in seen:
                            raise ValueError(
                                f"Duplicate or empty FinBench entity ID: "
                                f"{entity.table_id}.{identifier!r}"
                            )
                        seen.add(identifier)
                        properties = {
                            column: row[column] for column in entity.neo4j_columns
                        }
                        subject = _resource_iri(entity.table_id, identifier)
                        fuseki.write(f"{subject} rdf:type xgapfb:{entity.rdf_type} .\n")
                        fuseki.write(
                            f"{subject} xgapfb:sourceId {_rdf_literal(identifier)} .\n"
                        )
                        rdf_count += 2
                        for source_column, predicate in entity.fuseki_columns:
                            raw = row[source_column]
                            if not raw:
                                continue
                            literal = _rdf_literal(
                                raw, boolean=source_column == "isBlocked"
                            )
                            fuseki.write(f"{subject} xgapfb:{predicate} {literal} .\n")
                            rdf_count += 1
                        fuseki.write("\n")
                        yield {
                            "id": identifier,
                            "props": _parameter_map(
                                properties,
                                table_id=entity.table_id,
                                numeric_columns=frozenset(entity.numeric_columns),
                            ),
                        }

                row_count, statement_count = _write_parameterized_batches(
                    neo4j,
                    encoded_nodes(),
                    (
                        "UNWIND $rows AS row "
                        f"CREATE (n:{entity.neo4j_label} {{id: row.id}}) "
                        "SET n += row.props RETURN count(*) AS loaded"
                    ),
                    kind="nodes",
                    source_table=entity.table_id,
                    batch_size=batch_size,
                )
                source_counts[entity.table_id] = row_count
                neo4j_statements[f"nodes:{entity.table_id}"] = statement_count
                fuseki_triples[entity.table_id] = rdf_count
                entity_ids[entity.table_id] = seen

            for edge in RELATIONSHIP_PLACEMENTS:
                missing_references = 0
                from_label = entity_by_id[edge.from_entity].neo4j_label
                to_label = entity_by_id[edge.to_entity].neo4j_label

                def encoded_edges() -> Iterator[dict[str, Any]]:
                    nonlocal missing_references
                    numeric = frozenset(edge.numeric_columns)
                    for row_number, row in _iter_rows(
                        handle, inventory, tables[edge.table_id]
                    ):
                        from_id = row[edge.from_column]
                        to_id = row[edge.to_column]
                        if (
                            from_id not in entity_ids[edge.from_entity]
                            or to_id not in entity_ids[edge.to_entity]
                        ):
                            missing_references += 1
                            continue
                        properties = {
                            column: row[column] for column in edge.property_columns
                        }
                        source_key = hashlib.sha256(
                            f"{edge.table_id}:{row_number}:".encode("utf-8")
                            + json.dumps(
                                row,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=False,
                            ).encode("utf-8")
                        ).hexdigest()
                        yield {
                            "fromId": from_id,
                            "toId": to_id,
                            "sourceKey": source_key,
                            "props": _parameter_map(
                                properties,
                                table_id=edge.table_id,
                                numeric_columns=numeric,
                            ),
                        }

                row_count, statement_count = _write_parameterized_batches(
                    neo4j,
                    encoded_edges(),
                    (
                        "UNWIND $rows AS row "
                        f"MATCH (a:{from_label} {{id: row.fromId}}) "
                        f"MATCH (b:{to_label} {{id: row.toId}}) "
                        f"CREATE (a)-[r:{edge.neo4j_type} "
                        "{sourceKey: row.sourceKey}]->(b) "
                        "SET r += row.props RETURN count(*) AS loaded"
                    ),
                    kind="relationships",
                    source_table=edge.table_id,
                    batch_size=batch_size,
                )
                source_counts[edge.table_id] = row_count + missing_references
                neo4j_statements[f"relationships:{edge.table_id}"] = statement_count
                orphan_counts[edge.table_id] = missing_references

        if any(orphan_counts.values()):
            failures = {key: value for key, value in orphan_counts.items() if value}
            raise ValueError(f"FinBench relationship endpoints are missing: {failures}")

        placement = {
            "identity_replication": {
                item.table_id: {
                    "source_column": item.id_column,
                    "neo4j_property": "id",
                    "fuseki_predicate": "sourceId",
                }
                for item in ENTITY_PLACEMENTS
            },
            "neo4j": {
                "authority": "structure_transactions_and_numeric_flow",
                "entities": {
                    item.table_id: {
                        "label": item.neo4j_label,
                        "columns": [item.id_column, *item.neo4j_columns],
                    }
                    for item in ENTITY_PLACEMENTS
                },
                "relationships": {
                    item.table_id: {
                        "type": item.neo4j_type,
                        "from_entity": item.from_entity,
                        "to_entity": item.to_entity,
                        "columns": [
                            item.from_column,
                            item.to_column,
                            *item.property_columns,
                        ],
                    }
                    for item in RELATIONSHIP_PLACEMENTS
                },
            },
            "fuseki": {
                "authority": "types_classification_and_control_attributes",
                "entities": {
                    item.table_id: {
                        "rdf_type": item.rdf_type,
                        "columns": [
                            item.id_column,
                            *[column for column, _predicate in item.fuseki_columns],
                        ],
                        "predicate_mapping": {
                            column: predicate
                            for column, predicate in item.fuseki_columns
                        },
                    }
                    for item in ENTITY_PLACEMENTS
                },
                "relationships": {},
            },
        }
        output_files = {
            NEO4J_BATCH_FILENAME: {
                "sha256": _file_sha256(neo4j_path),
                "size_bytes": neo4j_path.stat().st_size,
            },
            "load_fuseki.ttl": {
                "sha256": _file_sha256(fuseki_path),
                "size_bytes": fuseki_path.stat().st_size,
            },
        }
        manifest: dict[str, Any] = {
            "schema_version": PARTITION_SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "bundle_id": f"{lock.artifact.artifact_id}-xgap-heterogeneous-v2",
            "artifact_id": lock.artifact.artifact_id,
            "benchmark": lock.artifact.benchmark,
            "benchmark_version": lock.artifact.version,
            "scale_factor": lock.artifact.scale_factor,
            "source_archive": {
                "filename": lock.artifact.filename,
                "size_bytes": lock.artifact.size_bytes,
                "sha256": lock.artifact.digest_value,
            },
            "source_lock_sha256": _file_sha256(lock_file),
            "batch_size": batch_size,
            "source_table_count": len(source_counts),
            "source_row_counts": source_counts,
            "total_source_rows": sum(source_counts.values()),
            "placement": placement,
            "neo4j_statement_counts": neo4j_statements,
            "neo4j_statement_count": sum(neo4j_statements.values()),
            "neo4j_load": {
                "format": "parameterized_jsonl_batches_v1",
                "filename": NEO4J_BATCH_FILENAME,
                "batch_schema_version": NEO4J_BATCH_SCHEMA_VERSION,
                "mutation_semantics": "create_into_empty_job_owned_database",
                "requires_empty_job_owned_database": True,
                "automatic_retries": 0,
            },
            "fuseki_triple_counts": fuseki_triples,
            "fuseki_triple_count": sum(fuseki_triples.values()),
            "referential_integrity": {
                "passed": True,
                "orphan_counts": orphan_counts,
            },
            "output_files": output_files,
            "claim_boundary": lock.artifact.claim_boundary,
            "redistribution_terms_status": lock.artifact.redistribution_terms_status,
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
            "answer_oracle_accessed": False,
            "paper_result": False,
        }
        manifest["partition_sha256"] = _canonical_sha256(manifest)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, destination)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = build_finbench_source_partition(
            archive_path=args.archive,
            lock_path=args.lock,
            output_root=args.output_root,
            batch_size=args.batch_size,
        )
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
