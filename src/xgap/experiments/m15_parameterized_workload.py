"""Build a deterministic multi-instance workload for one typed query family.

F2C3 binds the F2C2 semantic contract to literal-free backend templates,
shared Neo4j/Fuseki data, per-instance runtime parameters, and independently
computed exact-answer oracles.  It makes no backend, LLM, or ontology call.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_parameterized_query import (
    M15ParameterizedQueryContract,
    compile_m15_parameterized_query,
)


PARAMETERIZED_WORKLOAD_SPEC_SCHEMA_VERSION = (
    "m15-f2c-parameterized-workload-spec-v1"
)
PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION = (
    "m15-f2c-parameterized-workload-bundle-v1"
)
PARAMETERIZED_WORKLOAD_GENERATOR_VERSION = (
    "m15-f2c-parameterized-workload-generator-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SAFE_WORKLOAD_ID = re.compile(r"^[a-z][a-z0-9_-]{0,95}$")
_COMPILE_TOKEN = re.compile(r"\{\{compile:([a-z][a-z0-9_]*)\}\}")
_RUNTIME_TOKEN = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_TEMPLATE_FILES = {
    "neo4j_full": "neo4j_full.cypher.tmpl",
    "neo4j_bound": "neo4j_bound.cypher.tmpl",
    "fuseki_risk": "fuseki_risk.rq.tmpl",
}
_RISK_LEVELS = ("HIGH", "MEDIUM", "LOW")
_SPLIT_ROLES = frozenset({"seed", "heldout_instance"})
_NEO4J_BATCH_SIZE = 100
PARAMETERIZED_RELATIONSHIP_TYPES = {
    "transfer_to_company": "TRANSFER_TO_COMPANY",
}
PARAMETERIZED_PATH_QUANTIFIERS = {
    "direct": "",
}


class M15ParameterizedWorkloadError(ValueError):
    """Raised before publication when the F2C3 bundle is invalid."""


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise M15ParameterizedWorkloadError(
            f"{name} fields do not match the F2C3 contract"
        )
    return dict(value)


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15ParameterizedWorkloadError(f"{name} must be a safe identifier")
    return value


def _bounded_int(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise M15ParameterizedWorkloadError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise M15ParameterizedWorkloadError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _json_text(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )


def _json_clone(value: object) -> Any:
    return json.loads(_json_text(value))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _content_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _read_regular_text(path: str | Path, *, name: str) -> str:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise M15ParameterizedWorkloadError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return candidate.read_text(encoding="utf-8")


@dataclass(frozen=True)
class M15ParameterizedWorkloadSpec:
    workload_id: str
    seed: str
    company_count: int
    transfers_per_person: int
    risk_levels: tuple[str, ...]
    persons: tuple[Mapping[str, str], ...]
    query_instances: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "M15ParameterizedWorkloadSpec":
        raw = _strict_object(
            value,
            name="parameterized workload spec",
            fields={
                "schema_version",
                "workload_id",
                "seed",
                "company_count",
                "transfers_per_person",
                "risk_levels",
                "persons",
                "query_instances",
                "automatic_retries",
                "paper_result",
            },
        )
        if raw["schema_version"] != PARAMETERIZED_WORKLOAD_SPEC_SCHEMA_VERSION:
            raise M15ParameterizedWorkloadError(
                "parameterized workload schema_version is unsupported"
            )
        workload_id = raw["workload_id"]
        if not isinstance(workload_id, str) or not _SAFE_WORKLOAD_ID.fullmatch(
            workload_id
        ):
            raise M15ParameterizedWorkloadError("workload_id is invalid")
        seed = raw["seed"]
        if (
            not isinstance(seed, str)
            or not seed
            or len(seed.encode("utf-8")) > 256
        ):
            raise M15ParameterizedWorkloadError("seed is invalid")
        company_count = _bounded_int(
            raw["company_count"],
            name="company_count",
            minimum=6,
            maximum=10_000,
        )
        transfers_per_person = _bounded_int(
            raw["transfers_per_person"],
            name="transfers_per_person",
            minimum=10,
            maximum=100_000,
        )
        if raw["risk_levels"] != list(_RISK_LEVELS):
            raise M15ParameterizedWorkloadError(
                "risk_levels must be exactly HIGH, MEDIUM, LOW"
            )
        raw_persons = raw["persons"]
        if not isinstance(raw_persons, list) or len(raw_persons) < 2:
            raise M15ParameterizedWorkloadError(
                "persons must contain at least two entries"
            )
        persons: list[dict[str, str]] = []
        person_ids: list[str] = []
        person_names: list[str] = []
        for index, item in enumerate(raw_persons):
            person = _strict_object(
                item,
                name=f"persons[{index}]",
                fields={"person_id", "name"},
            )
            person_id = _safe_id(person["person_id"], name="person_id")
            name = person["name"]
            if not isinstance(name, str) or not name.strip():
                raise M15ParameterizedWorkloadError("person name must be nonempty")
            persons.append({"person_id": person_id, "name": name})
            person_ids.append(person_id)
            person_names.append(name)
        if len(person_ids) != len(set(person_ids)):
            raise M15ParameterizedWorkloadError("person IDs must be unique")
        if len(person_names) != len(set(person_names)):
            raise M15ParameterizedWorkloadError("person names must be unique")

        raw_instances = raw["query_instances"]
        if not isinstance(raw_instances, list) or len(raw_instances) < 3:
            raise M15ParameterizedWorkloadError(
                "query_instances must contain at least three entries"
            )
        instances: list[dict[str, Any]] = []
        query_ids: list[str] = []
        split_counts = {"seed": 0, "heldout_instance": 0}
        for index, item in enumerate(raw_instances):
            instance = _strict_object(
                item,
                name=f"query_instances[{index}]",
                fields={
                    "query_id",
                    "resolved_intent",
                    "split_role",
                    "binding_values",
                },
            )
            query_id = _safe_id(instance["query_id"], name="query_id")
            intent = instance["resolved_intent"]
            if not isinstance(intent, str) or not intent.strip():
                raise M15ParameterizedWorkloadError(
                    "resolved_intent must be nonempty"
                )
            split_role = instance["split_role"]
            if split_role not in _SPLIT_ROLES:
                raise M15ParameterizedWorkloadError("split_role is unsupported")
            bindings = instance["binding_values"]
            if not isinstance(bindings, Mapping) or not bindings:
                raise M15ParameterizedWorkloadError(
                    "binding_values must be a nonempty object"
                )
            for slot_id in bindings:
                _safe_id(slot_id, name="binding slot")
            try:
                normalized_bindings = _json_clone(dict(bindings))
            except (TypeError, ValueError) as exc:
                raise M15ParameterizedWorkloadError(
                    "binding_values must contain finite JSON values"
                ) from exc
            instances.append(
                {
                    "query_id": query_id,
                    "resolved_intent": intent,
                    "split_role": split_role,
                    "binding_values": normalized_bindings,
                }
            )
            query_ids.append(query_id)
            split_counts[split_role] += 1
        if len(query_ids) != len(set(query_ids)):
            raise M15ParameterizedWorkloadError("query IDs must be unique")
        if min(split_counts.values()) < 1:
            raise M15ParameterizedWorkloadError(
                "query instances require seed and heldout_instance roles"
            )
        if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
            raise M15ParameterizedWorkloadError(
                "development workload must disable retry and remain paper_result=false"
            )
        return cls(
            workload_id=workload_id,
            seed=seed,
            company_count=company_count,
            transfers_per_person=transfers_per_person,
            risk_levels=_RISK_LEVELS,
            persons=tuple(persons),
            query_instances=tuple(instances),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "M15ParameterizedWorkloadSpec":
        payload = json.loads(_read_regular_text(path, name="workload spec"))
        if not isinstance(payload, Mapping):
            raise M15ParameterizedWorkloadError("workload spec must be an object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PARAMETERIZED_WORKLOAD_SPEC_SCHEMA_VERSION,
            "workload_id": self.workload_id,
            "seed": self.seed,
            "company_count": self.company_count,
            "transfers_per_person": self.transfers_per_person,
            "risk_levels": list(self.risk_levels),
            "persons": [dict(item) for item in self.persons],
            "query_instances": [_json_clone(item) for item in self.query_instances],
            "automatic_retries": 0,
            "paper_result": False,
        }


@dataclass(frozen=True)
class M15ParameterizedWorkloadBundle:
    root: Path
    spec: M15ParameterizedWorkloadSpec
    manifest: Mapping[str, Any]

    def path(self, relative_path: str) -> Path:
        if relative_path not in self.manifest["files_sha256"]:
            raise KeyError(f"unknown bundle file: {relative_path}")
        return self.root / relative_path

    def instance_ids(self) -> tuple[str, ...]:
        return tuple(item["query_id"] for item in self.manifest["instances"])


def _load_template_inputs(
    template_spec_path: str | Path,
    backend_template_root: str | Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    raw_spec = json.loads(
        _read_regular_text(template_spec_path, name="parameterized query template")
    )
    if not isinstance(raw_spec, Mapping):
        raise M15ParameterizedWorkloadError(
            "parameterized query template must be an object"
        )
    compile_m15_parameterized_query(raw_spec)
    root = Path(backend_template_root)
    if root.is_symlink() or not root.is_dir():
        raise M15ParameterizedWorkloadError(
            "backend template root must be a regular directory"
        )
    actual = {item.name for item in root.iterdir()}
    if actual != set(_TEMPLATE_FILES.values()):
        raise M15ParameterizedWorkloadError(
            "backend template directory file set is invalid"
        )
    templates = {
        role: _read_regular_text(root / filename, name=f"{role} template")
        for role, filename in _TEMPLATE_FILES.items()
    }
    return _json_clone(raw_spec), templates


def _hash_int(seed: str, *parts: object) -> int:
    material = ":".join([seed, *(str(part) for part in parts)])
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest(), 16)


def _dataset_rows(
    spec: M15ParameterizedWorkloadSpec,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    width = max(4, len(str(spec.company_count)))
    company_ids = [f"C{index:0{width}d}" for index in range(1, spec.company_count + 1)]
    risk_order = sorted(
        company_ids,
        key=lambda company_id: (_hash_int(spec.seed, "risk", company_id), company_id),
    )
    risk_by_company = {
        company_id: spec.risk_levels[index % len(spec.risk_levels)]
        for index, company_id in enumerate(risk_order)
    }
    companies = [
        {
            "id": company_id,
            "account_id": f"acct-{spec.workload_id}-{company_id.lower()}",
            "name": f"Company {company_id}",
            "risk": risk_by_company[company_id],
        }
        for company_id in company_ids
    ]
    start = date(2026, 5, 1)
    transfers: list[dict[str, Any]] = []
    transfer_width = max(
        7,
        len(str(spec.transfers_per_person * len(spec.persons))),
    )
    ordinal = 0
    for person in spec.persons:
        person_id = person["person_id"]
        for offset in range(spec.transfers_per_person):
            ordinal += 1
            digest = _hash_int(spec.seed, "transfer", person_id, offset)
            company_id = company_ids[digest % len(company_ids)]
            amount = 10_000 + (digest // 101 % 190_001)
            occurred_on = start + timedelta(days=digest // 1009 % 123)
            transfers.append(
                {
                    "id": f"T{ordinal:0{transfer_width}d}",
                    "person_id": person_id,
                    "source_account_id": f"acct-{spec.workload_id}-{person_id}",
                    "target_account_id": (
                        f"acct-{spec.workload_id}-{company_id.lower()}"
                    ),
                    "company_id": company_id,
                    "amount": amount,
                    "currency": "USD",
                    "occurred_on": occurred_on.isoformat(),
                }
            )
    return companies, transfers


def _cypher_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_cypher_literal(item) for item in value) + "]"
    if isinstance(value, Mapping):
        fields: list[str] = []
        for key in sorted(value):
            if not isinstance(key, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", key
            ):
                raise M15ParameterizedWorkloadError("invalid Cypher map key")
            fields.append(f"{key}:{_cypher_literal(value[key])}")
        return "{" + ",".join(fields) + "}"
    raise M15ParameterizedWorkloadError("unsupported Cypher literal")


def _workload_token(workload_id: str) -> str:
    return workload_id.replace("-", "_").upper()


def _neo4j_load(
    spec: M15ParameterizedWorkloadSpec,
    companies: list[dict[str, Any]],
    transfers: list[dict[str, Any]],
) -> str:
    token = _workload_token(spec.workload_id)
    compact_people = [
        {
            "id": person["person_id"],
            "name": person["name"],
            "source_account_id": f"acct-{spec.workload_id}-{person['person_id']}",
        }
        for person in spec.persons
    ]
    compact_companies = [
        {"id": row["id"], "account_id": row["account_id"]}
        for row in companies
    ]
    compact_transfers = [
        {
            key: row[key]
            for key in (
                "id",
                "source_account_id",
                "target_account_id",
                "amount",
                "currency",
                "occurred_on",
            )
        }
        for row in transfers
    ]
    statements = [
        f"CREATE CONSTRAINT m15f2c_{token.lower()}_person_id IF NOT EXISTS\n"
        f"FOR (p:M15F2C_{token}_Person) REQUIRE p.id IS UNIQUE;",
        f"CREATE CONSTRAINT m15f2c_{token.lower()}_account_id IF NOT EXISTS\n"
        f"FOR (a:M15F2C_{token}_Account) REQUIRE a.id IS UNIQUE;",
        f"CREATE CONSTRAINT m15f2c_{token.lower()}_company_id IF NOT EXISTS\n"
        f"FOR (c:M15F2C_{token}_CompanyRef) REQUIRE c.id IS UNIQUE;",
        f"UNWIND {_cypher_literal(compact_people)} AS row\n"
        f"MERGE (person:M15F2C_{token}_Person {{id: row.id}})\n"
        "SET person.name = row.name\n"
        f"MERGE (source:M15F2C_{token}_Account {{id: row.source_account_id}})\n"
        f"MERGE (person)-[:M15F2C_{token}_OWNS]->(source);",
    ]
    for start in range(0, len(compact_companies), _NEO4J_BATCH_SIZE):
        batch = compact_companies[start : start + _NEO4J_BATCH_SIZE]
        statements.append(
            f"UNWIND {_cypher_literal(batch)} AS row\n"
            f"MERGE (company:M15F2C_{token}_CompanyRef {{id: row.id}})\n"
            f"MERGE (target:M15F2C_{token}_Account {{id: row.account_id}})\n"
            f"MERGE (company)-[:M15F2C_{token}_OWNS]->(target);"
        )
    for start in range(0, len(compact_transfers), _NEO4J_BATCH_SIZE):
        batch = compact_transfers[start : start + _NEO4J_BATCH_SIZE]
        statements.append(
            f"UNWIND {_cypher_literal(batch)} AS row\n"
            f"MATCH (source:M15F2C_{token}_Account "
            "{id: row.source_account_id})\n"
            f"MATCH (target:M15F2C_{token}_Account "
            "{id: row.target_account_id})\n"
            f"MERGE (source)-[edge:M15F2C_{token}_TRANSFER_TO_COMPANY "
            "{id: row.id}]->(target)\n"
            "SET edge.amount = row.amount,\n"
            "    edge.currency = row.currency,\n"
            "    edge.occurred_on = date(row.occurred_on);"
        )
    return "\n\n".join(statements) + "\n"


def _fuseki_load(
    spec: M15ParameterizedWorkloadSpec,
    companies: list[dict[str, Any]],
) -> str:
    prefix = f"http://xgap.example.org/m15-f2c/{spec.workload_id}/"
    blocks = [f"@prefix data: <{prefix}> .", ""]
    for row in companies:
        company_id = str(row["id"])
        rdf_company_id = f"rdf:{spec.workload_id}:{company_id}"
        blocks.extend(
            (
                f"data:company-{company_id.lower()}",
                "    a data:Company ;",
                f"    data:companyId {_cypher_literal(rdf_company_id)} ;",
                f"    data:name {_cypher_literal(row['name'])} ;",
                f"    data:riskLevel {_cypher_literal(row['risk'])} .",
                "",
            )
        )
    return "\n".join(blocks)


def _render_template(
    template: str,
    *,
    compile_values: Mapping[str, str],
    expected_runtime_parameters: set[str],
    role: str,
) -> str:
    tokens = set(_COMPILE_TOKEN.findall(template))
    if tokens != set(compile_values):
        raise M15ParameterizedWorkloadError(
            f"{role} compile placeholder set mismatch"
        )
    rendered = template
    for key, value in compile_values.items():
        rendered = rendered.replace(f"{{{{compile:{key}}}}}", value)
    if "{{compile:" in rendered:
        raise M15ParameterizedWorkloadError(
            f"{role} has an unresolved compile placeholder"
        )
    runtime_parameters = set(_RUNTIME_TOKEN.findall(rendered))
    if runtime_parameters != expected_runtime_parameters:
        raise M15ParameterizedWorkloadError(
            f"{role} runtime parameter set mismatch"
        )
    return rendered


def _instantiate_contract(
    base_spec: Mapping[str, Any],
    instance: Mapping[str, Any],
) -> M15ParameterizedQueryContract:
    concrete = copy.deepcopy(dict(base_spec))
    concrete["query_id"] = instance["query_id"]
    concrete["resolved_intent"] = instance["resolved_intent"]
    bindings = instance["binding_values"]
    slot_records = concrete["binding_slots"]
    slot_ids = {item["slot_id"] for item in slot_records}
    if set(bindings) != slot_ids:
        missing = sorted(slot_ids - set(bindings))
        extra = sorted(set(bindings) - slot_ids)
        raise M15ParameterizedWorkloadError(
            f"instance binding coverage mismatch: missing={missing}, extra={extra}"
        )
    for record in slot_records:
        record["value"] = bindings[record["slot_id"]]
    return compile_m15_parameterized_query(concrete)


def _interface_by_role(
    contract: M15ParameterizedQueryContract,
) -> dict[str, Mapping[str, Any]]:
    interfaces = contract.to_dict()["family_template"]["artifact_interfaces"]
    by_role = {item["role"]: item for item in interfaces}
    if set(by_role) != set(_TEMPLATE_FILES):
        raise M15ParameterizedWorkloadError(
            "parameterized query artifact roles are incompatible with F2C3"
        )
    return by_role


def _runtime_parameter_names(interface: Mapping[str, Any]) -> set[str]:
    return {
        parameter
        for parameter, schema in interface["parameter_schema"].items()
        if schema["binding_stage"] in {"runtime_parameter", "runtime_intermediate"}
    }


def _instance_oracles(
    spec: M15ParameterizedWorkloadSpec,
    companies: list[dict[str, Any]],
    transfers: list[dict[str, Any]],
    bindings: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    people = {item["person_id"]: item["name"] for item in spec.persons}
    person_id = bindings["person-identity"]
    if person_id not in people:
        raise M15ParameterizedWorkloadError(
            f"query binding references unknown person '{person_id}'"
        )
    risk = bindings["risk-level"]
    if risk not in spec.risk_levels:
        raise M15ParameterizedWorkloadError("query risk binding is absent from data")
    if bindings["transfer-predicate"] not in PARAMETERIZED_RELATIONSHIP_TYPES:
        raise M15ParameterizedWorkloadError(
            "exact F2C3 workload supports transfer_to_company only"
        )
    if bindings["path-shape"] not in PARAMETERIZED_PATH_QUANTIFIERS:
        raise M15ParameterizedWorkloadError(
            "exact F2C3 workload supports direct path shape only"
        )
    date_lower = bindings["time-lower-bound"]
    amount_lower = bindings["amount-lower-bound"]
    company_by_id = {item["id"]: item for item in companies}
    full = sorted(
        (
            {
                "person_id": person_id,
                "person": people[person_id],
                "company_id": f"neo:{spec.workload_id}:{row['company_id']}",
                "transfer_id": row["id"],
                "amount": row["amount"],
                "currency": row["currency"],
                "occurred_on": row["occurred_on"],
            }
            for row in transfers
            if row["person_id"] == person_id
            and row["occurred_on"] >= date_lower
            and row["amount"] >= amount_lower
        ),
        key=lambda row: (row["company_id"], row["transfer_id"]),
    )
    risk_rows = [
        {
            "company_id": f"rdf:{spec.workload_id}:{row['id']}",
            "company": row["name"],
            "risk": row["risk"],
        }
        for row in companies
        if row["risk"] == risk
    ]
    risk_ids = {item["id"] for item in companies if item["risk"] == risk}
    bound = [
        row
        for row in full
        if row["company_id"].rsplit(":", 1)[-1] in risk_ids
    ]
    final = sorted(
        (
            {
                "person": row["person"],
                "company": company_by_id[row["company_id"].rsplit(":", 1)[-1]][
                    "name"
                ],
                "amount": row["amount"],
                "currency": row["currency"],
                "occurred_on": row["occurred_on"],
                "risk": risk,
            }
            for row in bound
        ),
        key=_json_text,
    )
    if not full or not risk_rows or not final:
        raise M15ParameterizedWorkloadError(
            "every development query requires nonempty source and final oracles"
        )
    return {
        "neo4j_full": full,
        "neo4j_bound": bound,
        "fuseki_risk": risk_rows,
    }, final


def _build_content(
    *,
    spec: M15ParameterizedWorkloadSpec,
    base_spec: Mapping[str, Any],
    templates: Mapping[str, str],
) -> tuple[dict[str, str], list[dict[str, Any]], str]:
    base_contract = compile_m15_parameterized_query(base_spec)
    interfaces = _interface_by_role(base_contract)
    companies, transfers = _dataset_rows(spec)
    content = {
        "workload_spec.json": _json_text(spec.to_dict()),
        "parameterized_query_template.json": _json_text(base_spec),
        "load_neo4j.cypher": _neo4j_load(spec, companies, transfers),
        "load_fuseki.ttl": _fuseki_load(spec, companies),
    }
    for role, filename in _TEMPLATE_FILES.items():
        content[f"templates/{filename}"] = templates[role]
    token = _workload_token(spec.workload_id)
    prefix = f"http://xgap.example.org/m15-f2c/{spec.workload_id}/"
    instance_records: list[dict[str, Any]] = []
    instance_hashes: set[str] = set()
    family_hash = base_contract.family_hash
    for instance in spec.query_instances:
        contract = _instantiate_contract(base_spec, instance)
        if contract.family_hash != family_hash:
            raise M15ParameterizedWorkloadError(
                "query instance changed family compatibility"
            )
        if contract.instance_hash in instance_hashes:
            raise M15ParameterizedWorkloadError(
                "query instances must have unique semantic binding identities"
            )
        instance_hashes.add(contract.instance_hash)
        bindings = instance["binding_values"]
        relationship_type = PARAMETERIZED_RELATIONSHIP_TYPES.get(
            bindings["transfer-predicate"]
        )
        path_quantifier = PARAMETERIZED_PATH_QUANTIFIERS.get(
            bindings["path-shape"]
        )
        if relationship_type is None or path_quantifier is None:
            raise M15ParameterizedWorkloadError(
                "exact backend template cannot compile this predicate or path shape"
            )
        compiled = {
            "neo4j_full": _render_template(
                templates["neo4j_full"],
                compile_values={
                    "workload_token": token,
                    "workload_id": spec.workload_id,
                    "relationship_type": relationship_type,
                    "path_quantifier": path_quantifier,
                },
                expected_runtime_parameters=_runtime_parameter_names(
                    interfaces["neo4j_full"]
                ),
                role="neo4j_full",
            ),
            "neo4j_bound": _render_template(
                templates["neo4j_bound"],
                compile_values={
                    "workload_token": token,
                    "workload_id": spec.workload_id,
                    "relationship_type": relationship_type,
                    "path_quantifier": path_quantifier,
                },
                expected_runtime_parameters=_runtime_parameter_names(
                    interfaces["neo4j_bound"]
                ),
                role="neo4j_bound",
            ),
            "fuseki_risk": _render_template(
                templates["fuseki_risk"],
                compile_values={
                    "workload_prefix": prefix,
                    "risk_literal": json.dumps(bindings["risk-level"]),
                },
                expected_runtime_parameters=_runtime_parameter_names(
                    interfaces["fuseki_risk"]
                ),
                role="fuseki_risk",
            ),
        }
        runtime_parameters: dict[str, dict[str, Any]] = {}
        compile_parameters: dict[str, dict[str, Any]] = {}
        for role, interface in interfaces.items():
            runtime_parameters[role] = {}
            compile_parameters[role] = {}
            for parameter, slot_id in interface["binding_parameters"].items():
                stage = interface["parameter_schema"][parameter]["binding_stage"]
                target = (
                    runtime_parameters
                    if stage == "runtime_parameter"
                    else compile_parameters
                )
                target[role][parameter] = bindings[slot_id]
        runtime_intermediates = {
            "neo4j_bound": {
                "company_ids": {
                    "source": "align(fuseki_risk.company_id)",
                    "representation": "backend_local_company_id",
                }
            }
        }
        source_oracles, final_oracle = _instance_oracles(
            spec,
            companies,
            transfers,
            bindings,
        )
        query_id = instance["query_id"]
        root = f"instances/{query_id}"
        content[f"{root}/parameterized_contract.json"] = _json_text(
            contract.to_dict()
        )
        content[f"{root}/neo4j_full.cypher"] = compiled["neo4j_full"]
        content[f"{root}/neo4j_bound.cypher"] = compiled["neo4j_bound"]
        content[f"{root}/fuseki_risk.rq"] = compiled["fuseki_risk"]
        content[f"{root}/bindings.json"] = _json_text(
            {
                "query_id": query_id,
                "query_instance_sha256": contract.instance_hash,
                "runtime_parameters": runtime_parameters,
                "compile_time_parameters": compile_parameters,
                "runtime_intermediates": runtime_intermediates,
                "automatic_retries": 0,
                "paper_result": False,
            }
        )
        content[f"{root}/expected_source_results.json"] = _json_text(
            source_oracles
        )
        content[f"{root}/expected_result.json"] = _json_text(final_oracle)
        instance_records.append(
            {
                "query_id": query_id,
                "split_role": instance["split_role"],
                "query_instance_sha256": contract.instance_hash,
                "binding_sha256": contract.to_dict()["binding_sha256"],
                "oracle_counts": {
                    role: len(rows) for role, rows in source_oracles.items()
                }
                | {"final": len(final_oracle)},
            }
        )
    content["instances.json"] = _json_text(instance_records)
    return content, instance_records, family_hash


def _manifest(
    *,
    content: Mapping[str, str],
    records: Sequence[Mapping[str, Any]],
    family_hash: str,
    spec: M15ParameterizedWorkloadSpec,
) -> dict[str, Any]:
    hashes = {path: _sha256_text(text) for path, text in sorted(content.items())}
    split_counts = {
        role: sum(record["split_role"] == role for record in records)
        for role in sorted(_SPLIT_ROLES)
    }
    identity = {
        "schema_version": PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION,
        "generator_version": PARAMETERIZED_WORKLOAD_GENERATOR_VERSION,
        "workload_id": spec.workload_id,
        "family_compatibility_sha256": family_hash,
        "counts": {
            "persons": len(spec.persons),
            "companies": spec.company_count,
            "transfers": spec.transfers_per_person * len(spec.persons),
            "query_instances": len(records),
            "split_roles": split_counts,
        },
        "instances": [dict(record) for record in records],
        "files_sha256": hashes,
    }
    return {
        **identity,
        "bundle_content_sha256": _content_hash(identity),
        "input_hashes": {
            "workload_spec": hashes["workload_spec.json"],
            "parameterized_query_template": hashes[
                "parameterized_query_template.json"
            ],
            "backend_templates": {
                role: hashes[f"templates/{filename}"]
                for role, filename in sorted(_TEMPLATE_FILES.items())
            },
        },
        "claim_boundary": {
            "artifact_class": "unexecuted_parameterized_workload_bundle",
            "backend_query_templates_bound": True,
            "workload_bundle_bound": True,
            "oracles_bound": True,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }


def generate_m15_parameterized_workload_bundle(
    *,
    workload_spec: M15ParameterizedWorkloadSpec | str | Path,
    query_template_spec: str | Path,
    backend_template_root: str | Path,
    destination: str | Path,
) -> M15ParameterizedWorkloadBundle:
    spec = (
        workload_spec
        if isinstance(workload_spec, M15ParameterizedWorkloadSpec)
        else M15ParameterizedWorkloadSpec.from_json(workload_spec)
    )
    base_spec, templates = _load_template_inputs(
        query_template_spec,
        backend_template_root,
    )
    content, records, family_hash = _build_content(
        spec=spec,
        base_spec=base_spec,
        templates=templates,
    )
    manifest = _manifest(
        content=content,
        records=records,
        family_hash=family_hash,
        spec=spec,
    )
    destination_path = Path(destination).resolve()
    if destination_path.exists():
        raise FileExistsError(
            f"parameterized workload destination exists: {destination_path}"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.tmp-",
            dir=destination_path.parent,
        )
    )
    try:
        for relative_path, text in content.items():
            target = temporary / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (temporary / "manifest.json").write_text(
            _json_text(manifest), encoding="utf-8"
        )
        os.replace(temporary, destination_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return load_m15_parameterized_workload_bundle(destination_path)


def load_m15_parameterized_workload_bundle(
    root: str | Path,
) -> M15ParameterizedWorkloadBundle:
    bundle_root = Path(root).resolve()
    if not bundle_root.is_dir():
        raise M15ParameterizedWorkloadError("bundle root must be a directory")
    manifest_path = bundle_root / "manifest.json"
    manifest = json.loads(_read_regular_text(manifest_path, name="bundle manifest"))
    if not isinstance(manifest, Mapping):
        raise M15ParameterizedWorkloadError("bundle manifest must be an object")
    manifest = dict(manifest)
    if manifest.get("schema_version") != PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION:
        raise M15ParameterizedWorkloadError("bundle schema_version is unsupported")
    if manifest.get("generator_version") != PARAMETERIZED_WORKLOAD_GENERATOR_VERSION:
        raise M15ParameterizedWorkloadError("bundle generator_version is unsupported")
    raw_hashes = manifest.get("files_sha256")
    if not isinstance(raw_hashes, Mapping) or not raw_hashes:
        raise M15ParameterizedWorkloadError("bundle file hashes are invalid")
    for path in bundle_root.rglob("*"):
        if path.is_symlink():
            raise M15ParameterizedWorkloadError("bundle cannot contain symbolic links")
    actual_files = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_files != set(raw_hashes):
        raise M15ParameterizedWorkloadError("bundle file set mismatch")
    for relative_path, expected_hash in raw_hashes.items():
        if (
            not isinstance(relative_path, str)
            or not isinstance(expected_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        ):
            raise M15ParameterizedWorkloadError("bundle hash entry is invalid")
        candidate = bundle_root / relative_path
        if candidate.is_symlink() or not candidate.is_file():
            raise M15ParameterizedWorkloadError("bundle member is not regular")
        if _sha256_bytes(candidate.read_bytes()) != expected_hash:
            raise M15ParameterizedWorkloadError(
                f"bundle SHA-256 mismatch: {relative_path}"
            )
    spec_payload = json.loads(
        (bundle_root / "workload_spec.json").read_text(encoding="utf-8")
    )
    spec = M15ParameterizedWorkloadSpec.from_dict(spec_payload)
    base_spec = json.loads(
        (bundle_root / "parameterized_query_template.json").read_text(
            encoding="utf-8"
        )
    )
    templates = {
        role: (bundle_root / "templates" / filename).read_text(encoding="utf-8")
        for role, filename in _TEMPLATE_FILES.items()
    }
    deterministic, records, family_hash = _build_content(
        spec=spec,
        base_spec=base_spec,
        templates=templates,
    )
    for relative_path, expected_text in deterministic.items():
        if (bundle_root / relative_path).read_text(encoding="utf-8") != expected_text:
            raise M15ParameterizedWorkloadError(
                f"bundle content is not deterministic: {relative_path}"
            )
    expected_manifest = _manifest(
        content=deterministic,
        records=records,
        family_hash=family_hash,
        spec=spec,
    )
    if manifest != expected_manifest:
        raise M15ParameterizedWorkloadError("bundle manifest is not deterministic")
    return M15ParameterizedWorkloadBundle(bundle_root, spec, manifest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-spec", required=True)
    parser.add_argument("--query-template-spec", required=True)
    parser.add_argument("--backend-template-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        bundle = generate_m15_parameterized_workload_bundle(
            workload_spec=args.workload_spec,
            query_template_spec=args.query_template_spec,
            backend_template_root=args.backend_template_root,
            destination=args.output,
        )
    except (
        FileExistsError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {"status": "success", "root": str(bundle.root), **bundle.manifest},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
