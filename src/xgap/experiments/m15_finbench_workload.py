"""Compile the three-family FinBench-derived XGAP development population.

This compiler binds a verified FinBench archive and verified heterogeneous
partition to public query instances, literal-free backend templates, and a
separate exact-oracle file.  It performs no backend or model call and keeps the
result explicitly outside the paper-result boundary.
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
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from xgap.experiments.m15_finbench_artifacts import (
    DEFAULT_LOCK_PATH,
    FinBenchArtifactLock,
    SnapshotTableSpec,
    load_finbench_artifact_lock,
    validate_finbench_tar_inventory,
    verify_finbench_archive,
)
from xgap.experiments.m15_finbench_partition import (
    PARTITION_SCHEMA_VERSION,
    load_finbench_source_partition,
)


POPULATION_SPEC_SCHEMA_VERSION = "m15-finbench-primary-population-spec-v1"
WORKLOAD_SCHEMA_VERSION = "m15-finbench-primary-workload-v1"
GENERATOR_VERSION = "m15-finbench-primary-workload-generator-v1"
DEFAULT_SPEC_PATH = Path(
    "experiments/configs/m15_finbench_primary_population_v1.json"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_FAMILY_IDS = (
    "f1_direct_transfer_control",
    "f2_temporal_path_control",
    "f3_aggregate_risk_ranking",
)
_HELDOUT_POSITIONS = frozenset({3, 6, 9, 12})


@dataclass(frozen=True)
class Transfer:
    from_id: str
    to_id: str
    amount: Decimal
    create_time: str
    order_num: str


@dataclass(frozen=True)
class FinBenchQueryData:
    people: Mapping[str, Mapping[str, str]]
    accounts: Mapping[str, Mapping[str, str]]
    companies: Mapping[str, Mapping[str, str]]
    media: Mapping[str, Mapping[str, str]]
    person_by_account: Mapping[str, str]
    company_by_account: Mapping[str, str]
    media_by_account: Mapping[str, tuple[str, ...]]
    transfers: tuple[Transfer, ...]
    outgoing: Mapping[str, tuple[Transfer, ...]]
    minimum_transfer_time: str
    maximum_transfer_time: str


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"


def _read_json_object(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} must be a regular non-symbolic-link file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return dict(value)


def _validate_population_spec(path: Path) -> dict[str, Any]:
    spec = _read_json_object(path, name="FinBench population spec")
    if spec.get("schema_version") != POPULATION_SPEC_SCHEMA_VERSION:
        raise ValueError("FinBench population spec schema is unsupported")
    if spec.get("partition_schema_version") != PARTITION_SCHEMA_VERSION:
        raise ValueError("FinBench population partition schema is unsupported")
    if spec.get("paper_result") is not False or spec.get("automatic_retries") != 0:
        raise ValueError("FinBench development population must disable retry and paper result")
    if any(spec.get(field) != 0 for field in ("backend_calls", "llm_calls", "ontology_service_calls")):
        raise ValueError("FinBench population spec must make zero external calls")
    families = spec.get("families")
    if not isinstance(families, list) or [item.get("family_id") for item in families if isinstance(item, Mapping)] != list(_FAMILY_IDS):
        raise ValueError("FinBench population must contain the exact ordered F1--F3 families")
    for family in families:
        if not isinstance(family, Mapping) or family.get("instance_count") != 12:
            raise ValueError("Each FinBench primary family must declare 12 instances")
        strategies = family.get("physical_strategies")
        if not isinstance(strategies, list) or len(strategies) != 2 or len(set(strategies)) != 2:
            raise ValueError("Each FinBench family must declare two physical strategies")
        if not isinstance(family.get("hard_constraints"), list) or not family["hard_constraints"]:
            raise ValueError("Each FinBench family must declare hard constraints")
    return spec


def _iter_rows(
    handle: tarfile.TarFile,
    inventory: Mapping[str, tarfile.TarInfo],
    table: SnapshotTableSpec,
) -> Iterator[dict[str, str]]:
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
            yield dict(zip(header, row, strict=True))


def _unique_map(
    rows: Iterator[Mapping[str, str]], key: str, *, table_id: str
) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        identifier = row[key]
        if not identifier or identifier in result:
            raise ValueError(f"Duplicate or empty FinBench ID in {table_id}: {identifier!r}")
        result[identifier] = dict(row)
    return result


def load_finbench_query_data(
    archive_path: str | Path, lock: FinBenchArtifactLock
) -> FinBenchQueryData:
    verification = verify_finbench_archive(archive_path, lock.artifact)
    if not verification.success:
        raise ValueError(f"FinBench archive verification failed: {verification.status}")
    table_by_id = {table.table_id: table for table in lock.snapshot_tables}
    required = {
        "person",
        "account",
        "company",
        "medium",
        "person_own_account",
        "company_own_account",
        "account_transfer_account",
        "medium_sign_in_account",
    }
    if not required <= set(table_by_id):
        raise ValueError("FinBench query population source tables are incomplete")
    with tarfile.open(Path(archive_path), mode="r:gz") as handle:
        inventory = validate_finbench_tar_inventory(handle, lock.artifact.archive_root)
        people = _unique_map(
            _iter_rows(handle, inventory, table_by_id["person"]),
            "personId",
            table_id="person",
        )
        accounts = _unique_map(
            _iter_rows(handle, inventory, table_by_id["account"]),
            "accountId",
            table_id="account",
        )
        companies = _unique_map(
            _iter_rows(handle, inventory, table_by_id["company"]),
            "companyId",
            table_id="company",
        )
        media = _unique_map(
            _iter_rows(handle, inventory, table_by_id["medium"]),
            "mediumId",
            table_id="medium",
        )
        person_by_account: dict[str, str] = {}
        for row in _iter_rows(handle, inventory, table_by_id["person_own_account"]):
            if row["personId"] not in people or row["accountId"] not in accounts:
                raise ValueError("FinBench person ownership contains an orphan endpoint")
            if row["accountId"] in person_by_account:
                raise ValueError("FinBench account has multiple person owners")
            person_by_account[row["accountId"]] = row["personId"]
        company_by_account: dict[str, str] = {}
        for row in _iter_rows(handle, inventory, table_by_id["company_own_account"]):
            if row["companyId"] not in companies or row["accountId"] not in accounts:
                raise ValueError("FinBench company ownership contains an orphan endpoint")
            if row["accountId"] in company_by_account:
                raise ValueError("FinBench account has multiple company owners")
            company_by_account[row["accountId"]] = row["companyId"]
        media_sets: dict[str, set[str]] = defaultdict(set)
        for row in _iter_rows(handle, inventory, table_by_id["medium_sign_in_account"]):
            if row["mediumId"] not in media or row["accountId"] not in accounts:
                raise ValueError("FinBench medium sign-in contains an orphan endpoint")
            media_sets[row["accountId"]].add(row["mediumId"])
        transfers: list[Transfer] = []
        outgoing_lists: dict[str, list[Transfer]] = defaultdict(list)
        for row in _iter_rows(
            handle, inventory, table_by_id["account_transfer_account"]
        ):
            if row["fromId"] not in accounts or row["toId"] not in accounts:
                raise ValueError("FinBench transfer contains an orphan endpoint")
            transfer = Transfer(
                row["fromId"],
                row["toId"],
                Decimal(row["amount"]),
                row["createTime"],
                row["orderNum"],
            )
            transfers.append(transfer)
            outgoing_lists[transfer.from_id].append(transfer)
    if not transfers:
        raise ValueError("FinBench transfer table is empty")
    outgoing = {
        key: tuple(
            sorted(value, key=lambda item: (item.create_time, item.to_id, item.order_num))
        )
        for key, value in outgoing_lists.items()
    }
    return FinBenchQueryData(
        people=people,
        accounts=accounts,
        companies=companies,
        media=media,
        person_by_account=person_by_account,
        company_by_account=company_by_account,
        media_by_account={key: tuple(sorted(value)) for key, value in media_sets.items()},
        transfers=tuple(transfers),
        outgoing=outgoing,
        minimum_transfer_time=min(item.create_time for item in transfers),
        maximum_transfer_time=max(item.create_time for item in transfers),
    )


def _quantile_select(
    values: Sequence[tuple[str, int]], count: int
) -> tuple[tuple[str, int], ...]:
    if len(values) < count:
        raise ValueError(f"FinBench query selection needs {count} candidates, found {len(values)}")
    ordered = sorted(values, key=lambda item: (item[1], item[0]))
    if count == 1:
        return (ordered[len(ordered) // 2],)
    positions = [round(index * (len(ordered) - 1) / (count - 1)) for index in range(count)]
    if len(set(positions)) != count:
        raise ValueError("FinBench quantile selection produced duplicate positions")
    return tuple(ordered[index] for index in positions)


def _amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001')):.3f}"


def _split_role(position: int) -> str:
    return "heldout_instance" if position in _HELDOUT_POSITIONS else "training"


def _f1_instances(data: FinBenchQueryData) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocked_accounts = {
        identifier
        for identifier, row in data.accounts.items()
        if row["isBlocked"] == "true"
    }
    structural = Counter()
    eligible: set[str] = set()
    for transfer in data.transfers:
        person_id = data.person_by_account.get(transfer.from_id)
        if person_id is None or transfer.to_id not in data.company_by_account:
            continue
        structural[person_id] += 1
        if transfer.to_id in blocked_accounts:
            eligible.add(person_id)
    selected = _quantile_select(
        [(person_id, structural[person_id]) for person_id in eligible], 12
    )
    instances: list[dict[str, Any]] = []
    oracle_queries: dict[str, Any] = {}
    blocked_rows = [{"account_id": identifier} for identifier in sorted(blocked_accounts)]
    for position, (person_id, degree) in enumerate(selected, start=1):
        query_id = f"finbench-f1-{position:02d}"
        full_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for transfer in data.transfers:
            if data.person_by_account.get(transfer.from_id) != person_id:
                continue
            company_id = data.company_by_account.get(transfer.to_id)
            if company_id is not None:
                full_totals[(company_id, transfer.to_id)] += transfer.amount
        full_rows = [
            {
                "company_id": company_id,
                "account_id": account_id,
                "total_amount": _amount(total),
            }
            for (company_id, account_id), total in sorted(full_totals.items())
        ]
        final_rows = [row for row in full_rows if row["account_id"] in blocked_accounts]
        if not final_rows:
            raise ValueError(f"FinBench F1 selected an empty exact query: {query_id}")
        instances.append(
            {
                "query_id": query_id,
                "family_id": _FAMILY_IDS[0],
                "split_role": _split_role(position),
                "selection_position": position,
                "selection_feature": {"structural_degree": degree},
                "natural_language": (
                    "Within the inclusive benchmark time window, which blocked "
                    f"company-owned accounts received transfers from person {person_id}, "
                    "and what total amount did each company/account receive?"
                ),
                "parameters": {
                    "person_id": person_id,
                    "start_time": data.minimum_transfer_time,
                    "end_time": data.maximum_transfer_time,
                },
            }
        )
        oracle_queries[query_id] = {
            "neo4j_full": full_rows,
            "fuseki_control": blocked_rows,
            "neo4j_bound": final_rows,
            "final_rows": final_rows,
        }
    return instances, oracle_queries


def _path_rows(
    data: FinBenchQueryData,
    start_id: str,
    *,
    blocked_media: set[str] | None,
) -> list[dict[str, Any]]:
    rows: set[tuple[str, int, str]] = set()

    def visit(node: str, depth: int, last_time: str | None, visited: frozenset[str]) -> None:
        if depth == 3:
            return
        for transfer in data.outgoing.get(node, ()):
            if transfer.to_id in visited:
                continue
            if not (
                data.minimum_transfer_time <= transfer.create_time <= data.maximum_transfer_time
            ):
                continue
            if last_time is not None and transfer.create_time <= last_time:
                continue
            next_depth = depth + 1
            for medium_id in data.media_by_account.get(transfer.to_id, ()):
                if blocked_media is None or medium_id in blocked_media:
                    rows.add((transfer.to_id, next_depth, medium_id))
            visit(
                transfer.to_id,
                next_depth,
                transfer.create_time,
                visited | {transfer.to_id},
            )

    visit(start_id, 0, None, frozenset({start_id}))
    return [
        {"other_id": other_id, "account_distance": distance, "medium_id": medium_id}
        for other_id, distance, medium_id in sorted(rows, key=lambda item: (item[1], item[0], item[2]))
    ]


def _f2_instances(data: FinBenchQueryData) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blocked_media = {
        identifier
        for identifier, row in data.media.items()
        if row["isBlocked"] == "true"
    }
    eligible: list[tuple[str, int]] = []
    for account_id, outgoing in data.outgoing.items():
        degree = len(outgoing)
        if not 2 <= degree <= 32:
            continue
        direct_answer = any(
            blocked_media.intersection(data.media_by_account.get(edge.to_id, ()))
            for edge in outgoing
        )
        if direct_answer:
            eligible.append((account_id, degree))
    selected = _quantile_select(eligible, 12)
    control_rows = [
        {
            "medium_id": identifier,
            "medium_type": data.media[identifier]["mediumType"],
        }
        for identifier in sorted(blocked_media)
    ]
    medium_type = {row["medium_id"]: row["medium_type"] for row in control_rows}
    instances: list[dict[str, Any]] = []
    oracle_queries: dict[str, Any] = {}
    for position, (account_id, degree) in enumerate(selected, start=1):
        query_id = f"finbench-f2-{position:02d}"
        full_rows = _path_rows(data, account_id, blocked_media=None)
        bound_rows = _path_rows(data, account_id, blocked_media=blocked_media)
        final_rows = [
            {**row, "medium_type": medium_type[row["medium_id"]]}
            for row in bound_rows
        ]
        if not final_rows:
            raise ValueError(f"FinBench F2 selected an empty exact query: {query_id}")
        instances.append(
            {
                "query_id": query_id,
                "family_id": _FAMILY_IDS[1],
                "split_role": _split_role(position),
                "selection_position": position,
                "selection_feature": {"out_degree": degree},
                "natural_language": (
                    f"From account {account_id}, find accounts reachable in one to three "
                    "cycle-free outward transfers with strictly increasing timestamps "
                    "inside the inclusive benchmark window and signed into by a blocked medium."
                ),
                "parameters": {
                    "start_account_id": account_id,
                    "start_time": data.minimum_transfer_time,
                    "end_time": data.maximum_transfer_time,
                    "max_hops": 3,
                },
            }
        )
        oracle_queries[query_id] = {
            "neo4j_full": full_rows,
            "fuseki_control": control_rows,
            "neo4j_bound": bound_rows,
            "final_rows": final_rows,
        }
    return instances, oracle_queries


def _format_time(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds")


def _four_windows(data: FinBenchQueryData) -> tuple[tuple[str, str], ...]:
    start = datetime.fromisoformat(data.minimum_transfer_time)
    finish = datetime.fromisoformat(data.maximum_transfer_time) + timedelta(milliseconds=1)
    span = finish - start
    boundaries = [start + span * index / 4 for index in range(5)]
    final = _format_time(boundaries[4])
    return tuple((_format_time(boundaries[index]), final) for index in range(4))


def _f3_instances(
    data: FinBenchQueryData, risk_levels: Sequence[str], top_k: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    available = {row["riskLevel"] for row in data.media.values()}
    if not set(risk_levels) <= available:
        raise ValueError("FinBench F3 risk level is absent from the source data")
    windows = _four_windows(data)
    instances: list[dict[str, Any]] = []
    oracle_queries: dict[str, Any] = {}
    position = 0
    for window_position, (start_time, end_time) in enumerate(windows, start=1):
        for risk_position, risk_level in enumerate(risk_levels, start=1):
            position += 1
            query_id = f"finbench-f3-w{window_position}-r{risk_position}"
            control_ids = {
                identifier
                for identifier, row in data.media.items()
                if row["riskLevel"] == risk_level
            }
            eligible_accounts = {
                account_id
                for account_id, medium_ids in data.media_by_account.items()
                if control_ids.intersection(medium_ids)
                and account_id in data.company_by_account
            }
            account_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
            company_totals: dict[str, Decimal] = defaultdict(Decimal)
            for transfer in data.transfers:
                if not start_time <= transfer.create_time < end_time:
                    continue
                company_id = data.company_by_account.get(transfer.to_id)
                if company_id is None or transfer.to_id not in data.media_by_account:
                    continue
                account_totals[(company_id, transfer.to_id)] += transfer.amount
                if transfer.to_id in eligible_accounts:
                    company_totals[company_id] += transfer.amount
            full_rows = [
                {
                    "company_id": company_id,
                    "account_id": account_id,
                    "medium_ids": list(data.media_by_account[account_id]),
                    "account_amount": _amount(total),
                }
                for (company_id, account_id), total in sorted(account_totals.items())
            ]
            final_rows = [
                {
                    "company_id": company_id,
                    "total_amount": _amount(total),
                }
                for company_id, total in sorted(
                    company_totals.items(), key=lambda item: (-item[1], item[0])
                )[:top_k]
            ]
            if not final_rows:
                raise ValueError(f"FinBench F3 selected an empty exact query: {query_id}")
            instances.append(
                {
                    "query_id": query_id,
                    "family_id": _FAMILY_IDS[2],
                    "split_role": "heldout_family",
                    "selection_position": position,
                    "selection_feature": {
                        "window_position": window_position,
                        "risk_position": risk_position,
                    },
                    "natural_language": (
                        f"Between {start_time} inclusive and {end_time} exclusive, rank "
                        f"the top {top_k} companies by total transfers into company-owned "
                        f"accounts signed into by a medium whose exact category is {risk_level}."
                    ),
                    "parameters": {
                        "start_time": start_time,
                        "end_time": end_time,
                        "risk_level": risk_level,
                        "top_k": top_k,
                    },
                }
            )
            oracle_queries[query_id] = {
                "fuseki_control": [
                    {"medium_id": identifier} for identifier in sorted(control_ids)
                ],
                "neo4j_full": full_rows,
                "neo4j_bound": final_rows,
                "final_rows": final_rows,
            }
    return instances, oracle_queries


def _templates() -> dict[str, str]:
    path_predicates = """WHERE all(r IN transfers WHERE r.createTime >= $start_time AND r.createTime <= $end_time)
  AND (size(transfers) = 1 OR all(i IN range(0, size(transfers) - 2) WHERE transfers[i].createTime < transfers[i + 1].createTime))
  AND all(n IN nodes(path) WHERE single(m IN nodes(path) WHERE m = n))"""
    return {
        "f1_neo4j_full.cypher.tmpl": """MATCH (person:XGAPFinBenchPerson {id: $person_id})-[:OWNS_ACCOUNT]->(source:XGAPFinBenchAccount)
MATCH (source)-[transfer:TRANSFERRED_TO]->(destination:XGAPFinBenchAccount)<-[:OWNS_ACCOUNT]-(company:XGAPFinBenchCompany)
WHERE transfer.createTime >= $start_time AND transfer.createTime <= $end_time
RETURN company.id AS company_id, destination.id AS account_id,
       round(sum(transfer.amount) * 1000) / 1000 AS total_amount
ORDER BY company_id, account_id""",
        "f1_neo4j_bound.cypher.tmpl": """MATCH (person:XGAPFinBenchPerson {id: $person_id})-[:OWNS_ACCOUNT]->(source:XGAPFinBenchAccount)
MATCH (source)-[transfer:TRANSFERRED_TO]->(destination:XGAPFinBenchAccount)<-[:OWNS_ACCOUNT]-(company:XGAPFinBenchCompany)
WHERE transfer.createTime >= $start_time AND transfer.createTime <= $end_time
  AND destination.id IN $control_ids
RETURN company.id AS company_id, destination.id AS account_id,
       round(sum(transfer.amount) * 1000) / 1000 AS total_amount
ORDER BY company_id, account_id""",
        "f1_fuseki_control.rq.tmpl": """PREFIX xgapfb: <https://xgap.dev/benchmark/finbench/v0.1.0/schema/>
SELECT ?account_id WHERE {
  ?account a xgapfb:Account ; xgapfb:sourceId ?account_id ; xgapfb:isBlocked true .
}
ORDER BY ?account_id""",
        "f2_neo4j_full.cypher.tmpl": f"""MATCH path=(start:XGAPFinBenchAccount {{id: $start_account_id}})-[transfers:TRANSFERRED_TO*1..3]->(other:XGAPFinBenchAccount)
{path_predicates}
MATCH (medium:XGAPFinBenchMedium)-[:SIGNED_IN_TO]->(other)
RETURN DISTINCT other.id AS other_id, length(path) AS account_distance, medium.id AS medium_id
ORDER BY account_distance, other_id, medium_id""",
        "f2_neo4j_bound.cypher.tmpl": f"""MATCH path=(start:XGAPFinBenchAccount {{id: $start_account_id}})-[transfers:TRANSFERRED_TO*1..3]->(other:XGAPFinBenchAccount)
{path_predicates}
MATCH (medium:XGAPFinBenchMedium)-[:SIGNED_IN_TO]->(other)
WHERE medium.id IN $control_ids
RETURN DISTINCT other.id AS other_id, length(path) AS account_distance, medium.id AS medium_id
ORDER BY account_distance, other_id, medium_id""",
        "f2_fuseki_control.rq.tmpl": """PREFIX xgapfb: <https://xgap.dev/benchmark/finbench/v0.1.0/schema/>
SELECT ?medium_id ?medium_type WHERE {
  ?medium a xgapfb:Medium ; xgapfb:sourceId ?medium_id ;
          xgapfb:isBlocked true ; xgapfb:mediumType ?medium_type .
}
ORDER BY ?medium_id""",
        "f3_neo4j_full.cypher.tmpl": """MATCH (company:XGAPFinBenchCompany)-[:OWNS_ACCOUNT]->(account:XGAPFinBenchAccount)
MATCH (medium:XGAPFinBenchMedium)-[:SIGNED_IN_TO]->(account)
WITH DISTINCT company, account, medium
ORDER BY medium.id
WITH company, account, collect(medium.id) AS medium_ids
MATCH ()-[transfer:TRANSFERRED_TO]->(account)
WHERE transfer.createTime >= $start_time AND transfer.createTime < $end_time
RETURN company.id AS company_id, account.id AS account_id, medium_ids,
       round(sum(transfer.amount) * 1000) / 1000 AS account_amount
ORDER BY company_id, account_id""",
        "f3_neo4j_bound.cypher.tmpl": """MATCH (medium:XGAPFinBenchMedium)-[:SIGNED_IN_TO]->(account:XGAPFinBenchAccount)<-[:OWNS_ACCOUNT]-(company:XGAPFinBenchCompany)
WHERE medium.id IN $control_ids
WITH DISTINCT company, account
MATCH ()-[transfer:TRANSFERRED_TO]->(account)
WHERE transfer.createTime >= $start_time AND transfer.createTime < $end_time
WITH company, round(sum(transfer.amount) * 1000) / 1000 AS total_amount
RETURN company.id AS company_id, total_amount
ORDER BY total_amount DESC, company_id
LIMIT $top_k""",
        "f3_fuseki_control.rq.tmpl": """PREFIX xgapfb: <https://xgap.dev/benchmark/finbench/v0.1.0/schema/>
SELECT ?medium_id WHERE {
  VALUES ?risk_level { {{risk_level_literal}} }
  ?medium a xgapfb:Medium ; xgapfb:sourceId ?medium_id ; xgapfb:riskLevel ?risk_level .
}
ORDER BY ?medium_id""",
    }


def load_finbench_primary_public_workload(root: str | Path) -> dict[str, Any]:
    """Load the public workload contract without opening answer-oracle content."""

    bundle_root = Path(root).resolve()
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ValueError("FinBench workload root must be a regular directory")
    manifest = _read_json_object(
        bundle_root / "workload_manifest.json", name="FinBench workload manifest"
    )
    if manifest.get("schema_version") != WORKLOAD_SCHEMA_VERSION:
        raise ValueError("FinBench workload schema is unsupported")
    if manifest.get("paper_result") is not False:
        raise ValueError("FinBench workload must remain paper_result=false")
    claimed = manifest.get("workload_sha256")
    if not isinstance(claimed, str) or claimed != _canonical_sha256(
        {key: value for key, value in manifest.items() if key != "workload_sha256"}
    ):
        raise ValueError("FinBench workload identity mismatch")
    output_files = manifest.get("output_files")
    template_files = manifest.get("template_files")
    if not isinstance(output_files, Mapping) or set(output_files) != {
        "public_instances.json",
        "sealed_oracles.json",
        "family_contracts.json",
    }:
        raise ValueError("FinBench workload output file set is invalid")
    if not isinstance(template_files, Mapping) or set(template_files) != set(_templates()):
        raise ValueError("FinBench workload template file set is invalid")
    for relative, raw in {
        **{name: value for name, value in output_files.items()},
        **{f"templates/{name}": value for name, value in template_files.items()},
    }.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"FinBench workload file record is invalid: {relative}")
        candidate = bundle_root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"FinBench workload file is missing or unsafe: {relative}")
        if raw.get("size_bytes") != candidate.stat().st_size:
            raise ValueError(f"FinBench workload file size mismatch: {relative}")
        if raw.get("sha256") != _file_sha256(candidate):
            raise ValueError(f"FinBench workload file digest mismatch: {relative}")
    public = _read_json_object(
        bundle_root / "public_instances.json", name="FinBench public instances"
    )
    contracts = _read_json_object(
        bundle_root / "family_contracts.json", name="FinBench family contracts"
    )
    instances = public.get("instances")
    families = contracts.get("families")
    if not isinstance(instances, list) or len(instances) != manifest.get("instance_count"):
        raise ValueError("FinBench public instance count mismatch")
    if not isinstance(families, list) or [
        item.get("family_id") for item in families if isinstance(item, Mapping)
    ] != list(_FAMILY_IDS):
        raise ValueError("FinBench family contract set mismatch")
    forbidden = {"oracle", "final_rows", "neo4j_full", "neo4j_bound", "fuseki_control"}
    if any(forbidden.intersection(item) for item in instances if isinstance(item, Mapping)):
        raise ValueError("FinBench public instances expose oracle fields")
    return {
        "root": bundle_root,
        "manifest": manifest,
        "public_instances": public,
        "family_contracts": contracts,
    }


def load_finbench_primary_workload(root: str | Path) -> dict[str, Any]:
    """Load the public contract and sealed oracle for offline evaluation only."""

    loaded = load_finbench_primary_public_workload(root)
    oracle = _read_json_object(
        loaded["root"] / "sealed_oracles.json", name="FinBench sealed oracles"
    )
    instances = loaded["public_instances"].get("instances")
    queries = oracle.get("queries")
    if not isinstance(queries, Mapping) or set(queries) != {
        item.get("query_id") for item in instances if isinstance(item, Mapping)
    }:
        raise ValueError("FinBench oracle query set mismatch")
    return {**loaded, "sealed_oracles": oracle}


def build_finbench_primary_workload(
    *,
    archive_path: str | Path,
    partition_root: str | Path,
    output_root: str | Path,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    spec_path: str | Path = DEFAULT_SPEC_PATH,
) -> dict[str, Any]:
    archive = Path(archive_path).resolve()
    lock_file = Path(lock_path).resolve()
    spec_file = Path(spec_path).resolve()
    destination = Path(output_root).resolve()
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = load_finbench_artifact_lock(lock_file)
    spec = _validate_population_spec(spec_file)
    partition = load_finbench_source_partition(partition_root)
    if spec.get("source_artifact_id") != lock.artifact.artifact_id:
        raise ValueError("FinBench population source artifact identity mismatch")
    if partition.get("artifact_id") != lock.artifact.artifact_id:
        raise ValueError("FinBench partition artifact identity mismatch")
    source_archive = partition.get("source_archive")
    if not isinstance(source_archive, Mapping) or source_archive.get("sha256") != lock.artifact.digest_value:
        raise ValueError("FinBench partition archive identity mismatch")
    data = load_finbench_query_data(archive, lock)
    family_specs = {
        family["family_id"]: family for family in spec["families"]
    }
    f1_instances, f1_oracles = _f1_instances(data)
    f2_instances, f2_oracles = _f2_instances(data)
    f3_spec = family_specs[_FAMILY_IDS[2]]
    f3_instances, f3_oracles = _f3_instances(
        data, f3_spec["risk_levels"], f3_spec["top_k"]
    )
    instances = [*f1_instances, *f2_instances, *f3_instances]
    if len(instances) != 36 or len({item["query_id"] for item in instances}) != 36:
        raise ValueError("FinBench primary workload must contain 36 unique query instances")
    family_counts = Counter(item["family_id"] for item in instances)
    split_counts = Counter(item["split_role"] for item in instances)
    if family_counts != Counter({family_id: 12 for family_id in _FAMILY_IDS}):
        raise ValueError("FinBench primary workload family counts drifted")
    if split_counts != Counter({"training": 16, "heldout_instance": 8, "heldout_family": 12}):
        raise ValueError("FinBench primary workload split counts drifted")
    oracles = {**f1_oracles, **f2_oracles, **f3_oracles}
    if set(oracles) != {item["query_id"] for item in instances}:
        raise ValueError("FinBench oracle query set drifted")

    staging = Path(
        tempfile.mkdtemp(prefix=destination.name + ".partial-", dir=destination.parent)
    )
    try:
        template_root = staging / "templates"
        template_root.mkdir()
        template_records: dict[str, Any] = {}
        for name, text in sorted(_templates().items()):
            path = template_root / name
            payload = text.rstrip() + "\n"
            path.write_text(payload, encoding="utf-8")
            template_records[name] = {
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        public_instances = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "population_id": spec["population_id"],
            "instances": instances,
            "oracle_fields_present": False,
            "paper_result": False,
        }
        oracle_payload = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "population_id": spec["population_id"],
            "selection_access": "forbidden_until_selected_plan_is_sealed",
            "queries": oracles,
            "paper_result": False,
        }
        family_contracts = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "population_id": spec["population_id"],
            "families": spec["families"],
            "paper_result": False,
        }
        (staging / "public_instances.json").write_text(
            _json_text(public_instances), encoding="utf-8"
        )
        (staging / "sealed_oracles.json").write_text(
            _json_text(oracle_payload), encoding="utf-8"
        )
        (staging / "family_contracts.json").write_text(
            _json_text(family_contracts), encoding="utf-8"
        )
        output_files = {
            name: {
                "sha256": _file_sha256(staging / name),
                "size_bytes": (staging / name).stat().st_size,
            }
            for name in (
                "public_instances.json",
                "sealed_oracles.json",
                "family_contracts.json",
            )
        }
        manifest: dict[str, Any] = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "population_id": spec["population_id"],
            "source_artifact_id": lock.artifact.artifact_id,
            "source_archive_sha256": lock.artifact.digest_value,
            "source_lock_sha256": _file_sha256(lock_file),
            "source_partition_sha256": partition["partition_sha256"],
            "population_spec_sha256": _file_sha256(spec_file),
            "instance_count": len(instances),
            "family_counts": dict(sorted(family_counts.items())),
            "split_counts": dict(sorted(split_counts.items())),
            "time_domain": {
                "minimum": data.minimum_transfer_time,
                "maximum": data.maximum_transfer_time,
            },
            "template_files": template_records,
            "output_files": output_files,
            "oracle_isolation": {
                "separate_file": True,
                "selection_access": "forbidden_until_selected_plan_is_sealed",
                "public_instances_contain_oracle_fields": False,
            },
            "automatic_retries": 0,
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
            "paper_result": False,
        }
        manifest["workload_sha256"] = _canonical_sha256(manifest)
        (staging / "workload_manifest.json").write_text(
            _json_text(manifest), encoding="utf-8"
        )
        os.replace(staging, destination)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--partition-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--spec", default=str(DEFAULT_SPEC_PATH))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = build_finbench_primary_workload(
            archive_path=args.archive,
            partition_root=args.partition_root,
            output_root=args.output_root,
            lock_path=args.lock,
            spec_path=args.spec,
        )
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
