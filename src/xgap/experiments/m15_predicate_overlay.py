"""Build a versioned executable overlay for predicate relaxation.

F2C8A adds a deterministic ``payment_to_company`` edge family without
rewriting the frozen F2C3 transfer dataset.  It materializes every non-exact
direct-path semantic class, binds compiled artifacts and exact oracles, and
keeps all multihop classes blocked.  The catalog entry is treated as a
development mapping fixture rather than an ontology or paper claim.
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

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_workload import (
    PARAMETERIZED_PATH_QUANTIFIERS,
    PARAMETERIZED_RELATIONSHIP_TYPES,
    M15ParameterizedWorkloadBundle,
    M15ParameterizedWorkloadSpec,
    _NEO4J_BATCH_SIZE,
    _build_content,
    _cypher_literal,
    _dataset_rows,
    _hash_int,
    _load_template_inputs,
    _neo4j_load,
    _workload_token,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
    M15SemanticSolutionSpace,
    build_m15_semantic_solution_space,
    load_m15_semantic_relaxation_catalog,
)


PREDICATE_MAPPING_SPEC_SCHEMA_VERSION = "m15-f2c8-predicate-mapping-spec-v1"
PREDICATE_WORKLOAD_BUNDLE_SCHEMA_VERSION = (
    "m15-f2c8-predicate-parameterized-workload-bundle-v1"
)
PREDICATE_WORKLOAD_GENERATOR_VERSION = (
    "m15-f2c8-predicate-parameterized-workload-generator-v1"
)
PREDICATE_OVERLAY_SCHEMA_VERSION = "m15-f2c8-predicate-overlay-v1"
PREDICATE_OVERLAY_GENERATOR_VERSION = "m15-f2c8-predicate-overlay-generator-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SAFE_RELATIONSHIP = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HARD_SLOT_IDS = (
    "amount-lower-bound",
    "person-identity",
    "time-lower-bound",
)


class M15PredicateOverlayError(ValueError):
    """Raised before publication when the F2C8A overlay is invalid."""


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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15PredicateOverlayError(f"{name} must be a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15PredicateOverlayError(f"{name} must be a lowercase SHA-256")
    return value


def _bounded_int(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise M15PredicateOverlayError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise M15PredicateOverlayError(
            f"{name} fields do not match the F2C8A contract"
        )
    return dict(value)


def _regular_json_object(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M15PredicateOverlayError(
            f"{name} must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15PredicateOverlayError(f"{name} must be an object")
    return dict(payload)


@dataclass(frozen=True)
class M15PredicateMappingSpec:
    mapping_id: str
    family_compatibility_sha256: str
    transition_id: str
    source_predicate: str
    target_predicate: str
    transformation: str
    evidence: Mapping[str, str]
    relationship_type: str
    seed_namespace: str
    events_per_person: int
    date_start: str
    date_span_days: int
    amount_min: int
    amount_max: int
    currency: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "M15PredicateMappingSpec":
        raw = _strict_object(
            value,
            name="predicate mapping spec",
            fields={
                "schema_version",
                "mapping_id",
                "family_compatibility_sha256",
                "transition_id",
                "source_predicate",
                "target_predicate",
                "transformation",
                "evidence",
                "backend_mapping",
                "data_fixture",
                "automatic_retries",
                "paper_result",
            },
        )
        if raw["schema_version"] != PREDICATE_MAPPING_SPEC_SCHEMA_VERSION:
            raise M15PredicateOverlayError(
                "predicate mapping schema_version is unsupported"
            )
        evidence = _strict_object(
            raw["evidence"],
            name="predicate mapping evidence",
            fields={"kind", "reference"},
        )
        if evidence["kind"] != "development_mapping_fixture":
            raise M15PredicateOverlayError(
                "predicate evidence must remain a development mapping fixture"
            )
        backend = _strict_object(
            raw["backend_mapping"],
            name="predicate backend mapping",
            fields={"backend_id", "relationship_type"},
        )
        if backend["backend_id"] != "neo4j":
            raise M15PredicateOverlayError(
                "F2C8A supports only the declared Neo4j predicate mapping"
            )
        relationship_type = backend["relationship_type"]
        if (
            not isinstance(relationship_type, str)
            or not _SAFE_RELATIONSHIP.fullmatch(relationship_type)
        ):
            raise M15PredicateOverlayError("relationship_type is invalid")
        fixture = _strict_object(
            raw["data_fixture"],
            name="predicate data fixture",
            fields={
                "kind",
                "seed_namespace",
                "events_per_person",
                "date_start",
                "date_span_days",
                "amount_min",
                "amount_max",
                "currency",
            },
        )
        if fixture["kind"] != "deterministic_independent_edge_family":
            raise M15PredicateOverlayError("predicate data fixture kind is invalid")
        date_start = fixture["date_start"]
        if not isinstance(date_start, str):
            raise M15PredicateOverlayError("date_start must be an ISO date")
        try:
            date.fromisoformat(date_start)
        except ValueError as exc:
            raise M15PredicateOverlayError(
                "date_start must be an ISO date"
            ) from exc
        amount_min = _bounded_int(
            fixture["amount_min"],
            name="amount_min",
            minimum=0,
            maximum=10**12,
        )
        amount_max = _bounded_int(
            fixture["amount_max"],
            name="amount_max",
            minimum=amount_min,
            maximum=10**12,
        )
        currency = fixture["currency"]
        if (
            not isinstance(currency, str)
            or not re.fullmatch(r"[A-Z]{3}", currency)
        ):
            raise M15PredicateOverlayError("currency must be a three-letter code")
        source = _safe_id(raw["source_predicate"], name="source_predicate")
        target = _safe_id(raw["target_predicate"], name="target_predicate")
        if source == target:
            raise M15PredicateOverlayError("predicate mapping must change value")
        if raw["transformation"] != "ontology_sibling":
            raise M15PredicateOverlayError(
                "F2C8A requires the declared ontology_sibling transformation"
            )
        if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
            raise M15PredicateOverlayError(
                "predicate mapping must disable retry and remain paper_result=false"
            )
        return cls(
            mapping_id=_safe_id(raw["mapping_id"], name="mapping_id"),
            family_compatibility_sha256=_sha256(
                raw["family_compatibility_sha256"],
                name="family_compatibility_sha256",
            ),
            transition_id=_safe_id(raw["transition_id"], name="transition_id"),
            source_predicate=source,
            target_predicate=target,
            transformation=raw["transformation"],
            evidence={
                "kind": evidence["kind"],
                "reference": _safe_id(
                    evidence["reference"], name="evidence reference"
                ),
            },
            relationship_type=relationship_type,
            seed_namespace=_safe_id(
                fixture["seed_namespace"], name="seed_namespace"
            ),
            events_per_person=_bounded_int(
                fixture["events_per_person"],
                name="events_per_person",
                minimum=1,
                maximum=100_000,
            ),
            date_start=date_start,
            date_span_days=_bounded_int(
                fixture["date_span_days"],
                name="date_span_days",
                minimum=1,
                maximum=3660,
            ),
            amount_min=amount_min,
            amount_max=amount_max,
            currency=currency,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "M15PredicateMappingSpec":
        return cls.from_dict(
            _regular_json_object(Path(path), name="predicate mapping spec")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PREDICATE_MAPPING_SPEC_SCHEMA_VERSION,
            "mapping_id": self.mapping_id,
            "family_compatibility_sha256": self.family_compatibility_sha256,
            "transition_id": self.transition_id,
            "source_predicate": self.source_predicate,
            "target_predicate": self.target_predicate,
            "transformation": self.transformation,
            "evidence": dict(self.evidence),
            "backend_mapping": {
                "backend_id": "neo4j",
                "relationship_type": self.relationship_type,
            },
            "data_fixture": {
                "kind": "deterministic_independent_edge_family",
                "seed_namespace": self.seed_namespace,
                "events_per_person": self.events_per_person,
                "date_start": self.date_start,
                "date_span_days": self.date_span_days,
                "amount_min": self.amount_min,
                "amount_max": self.amount_max,
                "currency": self.currency,
            },
            "automatic_retries": 0,
            "paper_result": False,
        }


@dataclass(frozen=True)
class M15PredicateOverlayBundle:
    root: Path
    workload_bundle: M15ParameterizedWorkloadBundle
    mapping: M15PredicateMappingSpec
    manifest: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.manifest))


def _selected_catalog(
    value: M15SemanticRelaxationCatalog | str | Path,
) -> M15SemanticRelaxationCatalog:
    return (
        value
        if isinstance(value, M15SemanticRelaxationCatalog)
        else load_m15_semantic_relaxation_catalog(value)
    )


def _selected_mapping(
    value: M15PredicateMappingSpec | str | Path,
) -> M15PredicateMappingSpec:
    return (
        value
        if isinstance(value, M15PredicateMappingSpec)
        else M15PredicateMappingSpec.from_json(value)
    )


def _concrete_query_spec(
    bundle: M15ParameterizedWorkloadBundle,
    query_id: str,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    matches = [
        item for item in bundle.spec.query_instances if item["query_id"] == query_id
    ]
    if len(matches) != 1:
        raise M15PredicateOverlayError(
            "base_query_id must identify exactly one workload instance"
        )
    instance = matches[0]
    template = _regular_json_object(
        bundle.path("parameterized_query_template.json"),
        name="parameterized query template",
    )
    concrete = copy.deepcopy(template)
    concrete["query_id"] = query_id
    concrete["resolved_intent"] = instance["resolved_intent"]
    bindings = dict(instance["binding_values"])
    slots = concrete.get("binding_slots")
    if not isinstance(slots, list) or {
        item.get("slot_id") for item in slots if isinstance(item, Mapping)
    } != set(bindings):
        raise M15PredicateOverlayError(
            "base query and template binding coverage differ"
        )
    for slot in slots:
        slot["value"] = bindings[slot["slot_id"]]
    return concrete, instance


def _binding_values(semantic_class: Mapping[str, Any]) -> dict[str, Any]:
    records = semantic_class.get("bindings")
    if not isinstance(records, list):
        raise M15PredicateOverlayError("semantic class bindings are invalid")
    result: dict[str, Any] = {}
    for item in records:
        if not isinstance(item, Mapping):
            raise M15PredicateOverlayError("semantic binding must be an object")
        slot_id = _safe_id(item.get("slot_id"), name="binding slot_id")
        if slot_id in result:
            raise M15PredicateOverlayError(
                "semantic class binding slot IDs must be unique"
            )
        result[slot_id] = item.get("value")
    return result


def _catalog_transition(
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
) -> Mapping[str, Any]:
    payload = catalog.to_dict()
    if payload["family_compatibility_sha256"] != (
        mapping.family_compatibility_sha256
    ):
        raise M15PredicateOverlayError("mapping and catalog families differ")
    dimensions = [
        item
        for item in payload["dimensions"]
        if item["constraint_id"] == "transfer-predicate"
        and item["slot_id"] == "transfer-predicate"
    ]
    if len(dimensions) != 1:
        raise M15PredicateOverlayError(
            "catalog must define exactly one transfer-predicate dimension"
        )
    transitions = [
        item
        for item in dimensions[0]["transitions"]
        if item["transition_id"] == mapping.transition_id
    ]
    if len(transitions) != 1:
        raise M15PredicateOverlayError(
            "mapping transition is absent from the semantic catalog"
        )
    transition = transitions[0]
    expected = {
        "from_value": mapping.source_predicate,
        "to_value": mapping.target_predicate,
        "transformation": mapping.transformation,
        "evidence": dict(mapping.evidence),
    }
    observed = {key: transition[key] for key in expected}
    if observed != expected:
        raise M15PredicateOverlayError(
            "predicate mapping disagrees with its catalog transition"
        )
    return transition


def build_m15_catalog_bound_direct_semantic_classes(
    *,
    bundle: M15ParameterizedWorkloadBundle,
    query_id: str,
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
) -> tuple[M15SemanticSolutionSpace, list[dict[str, Any]], dict[str, Any]]:
    """Return every executable direct class admitted by the frozen catalog.

    Unlike the original F2C8 overlay gate, this helper is cardinality
    independent.  HIGH/LOW currently yield four classes while MEDIUM yields
    six because both adjacent risk transitions remain available.
    """

    if bundle.manifest["family_compatibility_sha256"] != (
        mapping.family_compatibility_sha256
    ):
        raise M15PredicateOverlayError("mapping and workload families differ")
    _catalog_transition(catalog, mapping)
    concrete, base_instance = _concrete_query_spec(bundle, query_id)
    solution = build_m15_semantic_solution_space(concrete, catalog)
    payload = solution.to_dict()
    exact_bindings = dict(base_instance["binding_values"])
    if exact_bindings["transfer-predicate"] != mapping.source_predicate:
        raise M15PredicateOverlayError(
            "base query does not use the mapping source predicate"
        )
    if exact_bindings["path-shape"] != "direct":
        raise M15PredicateOverlayError("F2C8A requires a direct base query")
    supported: list[dict[str, Any]] = []
    for semantic_class in payload["semantic_equivalence_classes"]:
        record = dict(semantic_class)
        bindings = _binding_values(record)
        if bindings["path-shape"] != "direct":
            continue
        if bindings["transfer-predicate"] not in {
            mapping.source_predicate,
            mapping.target_predicate,
        }:
            raise M15PredicateOverlayError(
                "direct semantic class uses an undeclared predicate"
            )
        if any(bindings[slot_id] != exact_bindings[slot_id] for slot_id in _HARD_SLOT_IDS):
            raise M15PredicateOverlayError("semantic class changed a hard binding")
        changed = sorted(
            slot_id
            for slot_id, value in bindings.items()
            if exact_bindings.get(slot_id) != value
        )
        record["changed_slot_ids"] = changed
        record["binding_values"] = bindings
        supported.append(record)
    exact = [
        item for item in supported if not item["changed_slot_ids"]
    ]
    if len(exact) != 1:
        raise M15PredicateOverlayError(
            "direct semantic space requires exactly one exact class"
        )
    if len(supported) not in {4, 6}:
        raise M15PredicateOverlayError(
            "direct semantic class count is outside the approved F2C10 policy"
        )
    return solution, sorted(
        supported, key=lambda item: item["semantic_class_id"]
    ), exact_bindings


def _direct_semantic_classes(
    *,
    bundle: M15ParameterizedWorkloadBundle,
    query_id: str,
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
) -> tuple[M15SemanticSolutionSpace, list[dict[str, Any]], dict[str, Any]]:
    """Retain the frozen four-class F2C8 overlay contract."""

    solution, supported, exact_bindings = (
        build_m15_catalog_bound_direct_semantic_classes(
            bundle=bundle,
            query_id=query_id,
            catalog=catalog,
            mapping=mapping,
        )
    )
    selected = [item for item in supported if item["changed_slot_ids"]]
    expected_changes = {
        ("risk-level",),
        ("transfer-predicate",),
        ("risk-level", "transfer-predicate"),
    }
    if {tuple(item["changed_slot_ids"]) for item in selected} != expected_changes:
        raise M15PredicateOverlayError(
            "F2C8A requires exactly the three non-exact direct semantic classes"
        )
    if len(supported) != 4:
        raise M15PredicateOverlayError(
            "F2C8A requires four direct semantic classes including exact"
        )
    return solution, sorted(
        selected, key=lambda item: item["semantic_class_id"]
    ), exact_bindings


def build_m15_predicate_semantic_solution_space(
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    base_query_id: str,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
) -> M15SemanticSolutionSpace:
    """Return the verified full solution space used by the predicate overlay.

    The result still contains blocked multihop classes.  Consumers must use
    the overlay manifest to distinguish executable direct classes from those
    declared-but-unbound interpretations.
    """

    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    solution, _, _ = build_m15_catalog_bound_direct_semantic_classes(
        bundle=selected_base,
        query_id=_safe_id(base_query_id, name="base_query_id"),
        catalog=_selected_catalog(catalog),
        mapping=_selected_mapping(mapping),
    )
    return solution


def _overlay_query_id(base_query_id: str, semantic_class_id: str) -> str:
    suffix = semantic_class_id.removeprefix("m15-class-")
    return _safe_id(
        f"{base_query_id}-relaxed-{suffix}",
        name="predicate overlay query_id",
    )


def _extended_spec(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    base_query_id: str,
    semantic_classes: Sequence[Mapping[str, Any]],
) -> tuple[M15ParameterizedWorkloadSpec, list[dict[str, Any]]]:
    payload = base_bundle.spec.to_dict()
    additions: list[dict[str, Any]] = []
    for semantic_class in semantic_classes:
        semantic_class_id = _safe_id(
            semantic_class["semantic_class_id"], name="semantic_class_id"
        )
        query_id = _overlay_query_id(base_query_id, semantic_class_id)
        bindings = copy.deepcopy(dict(semantic_class["binding_values"]))
        payload["query_instances"].append(
            {
                "query_id": query_id,
                "resolved_intent": (
                    f"Development relaxed interpretation {semantic_class_id} "
                    f"derived from {base_query_id}."
                ),
                "split_role": "heldout_instance",
                "binding_values": bindings,
            }
        )
        additions.append(
            {
                "semantic_class_id": semantic_class_id,
                "semantic_deviation": semantic_class["semantic_deviation"],
                "expected_query_instance_sha256": semantic_class[
                    "query_instance_sha256"
                ],
                "changed_slot_ids": list(semantic_class["changed_slot_ids"]),
                "query_id": query_id,
                "binding_values": bindings,
            }
        )
    return M15ParameterizedWorkloadSpec.from_dict(payload), additions


def _payment_rows(
    spec: M15ParameterizedWorkloadSpec,
    mapping: M15PredicateMappingSpec,
) -> list[dict[str, Any]]:
    companies, _ = _dataset_rows(spec)
    company_ids = [str(item["id"]) for item in companies]
    first_date = date.fromisoformat(mapping.date_start)
    width = max(7, len(str(mapping.events_per_person * len(spec.persons))))
    rows: list[dict[str, Any]] = []
    ordinal = 0
    amount_width = mapping.amount_max - mapping.amount_min + 1
    for person in spec.persons:
        person_id = str(person["person_id"])
        for offset in range(mapping.events_per_person):
            ordinal += 1
            digest = _hash_int(
                spec.seed,
                mapping.seed_namespace,
                person_id,
                offset,
            )
            company_id = company_ids[digest % len(company_ids)]
            occurred_on = first_date + timedelta(
                days=digest // 1009 % mapping.date_span_days
            )
            rows.append(
                {
                    "id": f"P{ordinal:0{width}d}",
                    "person_id": person_id,
                    "source_account_id": f"acct-{spec.workload_id}-{person_id}",
                    "target_account_id": (
                        f"acct-{spec.workload_id}-{company_id.lower()}"
                    ),
                    "company_id": company_id,
                    "amount": mapping.amount_min
                    + (digest // 101 % amount_width),
                    "currency": mapping.currency,
                    "occurred_on": occurred_on.isoformat(),
                }
            )
    return rows


def _payment_load(
    spec: M15ParameterizedWorkloadSpec,
    mapping: M15PredicateMappingSpec,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    token = _workload_token(spec.workload_id)
    compact = [
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
        for row in rows
    ]
    statements: list[str] = []
    for start in range(0, len(compact), _NEO4J_BATCH_SIZE):
        batch = compact[start : start + _NEO4J_BATCH_SIZE]
        statements.append(
            f"UNWIND {_cypher_literal(batch)} AS row\n"
            f"MATCH (source:M15F2C_{token}_Account "
            "{id: row.source_account_id})\n"
            f"MATCH (target:M15F2C_{token}_Account "
            "{id: row.target_account_id})\n"
            f"MERGE (source)-[edge:M15F2C_{token}_"
            f"{mapping.relationship_type} {{id: row.id}}]->(target)\n"
            "SET edge.amount = row.amount,\n"
            "    edge.currency = row.currency,\n"
            "    edge.occurred_on = date(row.occurred_on);"
        )
    return "\n\n".join(statements) + "\n"


def _bundle_content(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    spec: M15ParameterizedWorkloadSpec,
    mapping: M15PredicateMappingSpec,
) -> tuple[dict[str, str], list[dict[str, Any]], str, list[dict[str, Any]]]:
    base_spec, templates = _load_template_inputs(
        base_bundle.path("parameterized_query_template.json"),
        base_bundle.root / "templates",
    )
    companies, transfers = _dataset_rows(spec)
    regenerated_base_load = _neo4j_load(spec, companies, transfers)
    recorded_base_load = base_bundle.path("load_neo4j.cypher").read_text(
        encoding="utf-8"
    )
    if regenerated_base_load != recorded_base_load:
        raise M15PredicateOverlayError(
            "extended query list changed the frozen base dataset"
        )
    payments = _payment_rows(spec, mapping)
    relationship_types = {
        **PARAMETERIZED_RELATIONSHIP_TYPES,
        mapping.target_predicate: mapping.relationship_type,
    }
    predicate_rows = {
        mapping.source_predicate: transfers,
        mapping.target_predicate: payments,
    }
    content, records, family_hash = _build_content(
        spec=spec,
        base_spec=base_spec,
        templates=templates,
        relationship_types=relationship_types,
        path_quantifiers=PARAMETERIZED_PATH_QUANTIFIERS,
        predicate_rows=predicate_rows,
        neo4j_load_text=recorded_base_load + "\n" + _payment_load(
            spec, mapping, payments
        ),
    )
    content["predicate_mapping.json"] = _json_text(mapping.to_dict())
    return content, records, family_hash, payments


def _bundle_manifest(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    content: Mapping[str, str],
    records: Sequence[Mapping[str, Any]],
    family_hash: str,
    spec: M15ParameterizedWorkloadSpec,
    mapping: M15PredicateMappingSpec,
    payment_count: int,
) -> dict[str, Any]:
    hashes = {path: _sha256_text(text) for path, text in sorted(content.items())}
    split_counts = {
        role: sum(record["split_role"] == role for record in records)
        for role in ("heldout_instance", "seed")
    }
    identity = {
        "schema_version": PREDICATE_WORKLOAD_BUNDLE_SCHEMA_VERSION,
        "generator_version": PREDICATE_WORKLOAD_GENERATOR_VERSION,
        "workload_id": spec.workload_id,
        "base_workload_bundle_content_sha256": base_bundle.manifest[
            "bundle_content_sha256"
        ],
        "predicate_mapping_sha256": content_hash(mapping.to_dict()),
        "family_compatibility_sha256": family_hash,
        "executor_capabilities": {
            "risk_levels": list(spec.risk_levels),
            "transfer_predicates": sorted(
                {
                    mapping.source_predicate,
                    mapping.target_predicate,
                }
            ),
            "path_shapes": ["direct"],
        },
        "load_protocol": {
            "neo4j_order": "frozen_base_then_payment_augmentation",
            "neo4j_base_statement_count": base_bundle.path(
                "load_neo4j.cypher"
            ).read_text(encoding="utf-8").count(";"),
            "neo4j_payment_batch_size": _NEO4J_BATCH_SIZE,
            "neo4j_payment_statement_count": (
                payment_count + _NEO4J_BATCH_SIZE - 1
            )
            // _NEO4J_BATCH_SIZE,
            "neo4j_combined_statement_count": content[
                "load_neo4j.cypher"
            ].count(";"),
            "fuseki_base_artifact_reused": True,
        },
        "counts": {
            "persons": len(spec.persons),
            "companies": spec.company_count,
            "transfer_edges": spec.transfers_per_person * len(spec.persons),
            "payment_edges": payment_count,
            "query_instances": len(records),
            "split_roles": split_counts,
        },
        "instances": [dict(record) for record in records],
        "files_sha256": hashes,
    }
    return {
        **identity,
        "bundle_content_sha256": content_hash(identity),
        "input_hashes": {
            "base_workload_bundle_content_sha256": base_bundle.manifest[
                "bundle_content_sha256"
            ],
            "predicate_mapping": hashes["predicate_mapping.json"],
            "workload_spec": hashes["workload_spec.json"],
            "parameterized_query_template": hashes[
                "parameterized_query_template.json"
            ],
            "backend_templates": {
                role: hashes[f"templates/{filename}"]
                for role, filename in sorted(
                    {
                        "fuseki_risk": "fuseki_risk.rq.tmpl",
                        "neo4j_bound": "neo4j_bound.cypher.tmpl",
                        "neo4j_full": "neo4j_full.cypher.tmpl",
                    }.items()
                )
            },
        },
        "claim_boundary": {
            "artifact_class": "unexecuted_predicate_augmented_workload_bundle",
            "development_mapping_fixture": True,
            "base_bundle_mutated": False,
            "predicate_backend_artifacts_bound": True,
            "predicate_data_bound": True,
            "predicate_oracles_bound": True,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }


def _write_bundle(
    *,
    destination: Path,
    base_bundle: M15ParameterizedWorkloadBundle,
    spec: M15ParameterizedWorkloadSpec,
    mapping: M15PredicateMappingSpec,
) -> M15ParameterizedWorkloadBundle:
    content, records, family_hash, payments = _bundle_content(
        base_bundle=base_bundle,
        spec=spec,
        mapping=mapping,
    )
    manifest = _bundle_manifest(
        base_bundle=base_bundle,
        content=content,
        records=records,
        family_hash=family_hash,
        spec=spec,
        mapping=mapping,
        payment_count=len(payments),
    )
    destination.mkdir(parents=True, exist_ok=False)
    for relative_path, text in content.items():
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (destination / "manifest.json").write_text(
        _json_text(manifest), encoding="utf-8"
    )
    return _load_predicate_workload_bundle(
        destination,
        base_bundle=base_bundle,
        expected_spec=spec,
        mapping=mapping,
    )


def _load_predicate_workload_bundle(
    root: str | Path,
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    expected_spec: M15ParameterizedWorkloadSpec,
    mapping: M15PredicateMappingSpec,
) -> M15ParameterizedWorkloadBundle:
    bundle_root = Path(root).resolve()
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise M15PredicateOverlayError(
            "predicate workload root must be a regular directory"
        )
    manifest_path = bundle_root / "manifest.json"
    manifest = _regular_json_object(manifest_path, name="predicate bundle manifest")
    if manifest.get("schema_version") != PREDICATE_WORKLOAD_BUNDLE_SCHEMA_VERSION:
        raise M15PredicateOverlayError(
            "predicate workload schema_version is unsupported"
        )
    if manifest.get("generator_version") != PREDICATE_WORKLOAD_GENERATOR_VERSION:
        raise M15PredicateOverlayError(
            "predicate workload generator_version is unsupported"
        )
    hashes = manifest.get("files_sha256")
    if not isinstance(hashes, Mapping) or not hashes:
        raise M15PredicateOverlayError("predicate bundle file hashes are invalid")
    for path in bundle_root.rglob("*"):
        if path.is_symlink():
            raise M15PredicateOverlayError(
                "predicate workload bundle cannot contain symlinks"
            )
    actual_files = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_files != set(hashes):
        raise M15PredicateOverlayError("predicate bundle file set mismatch")
    for relative_path, expected_hash in hashes.items():
        if (
            not isinstance(relative_path, str)
            or not isinstance(expected_hash, str)
            or not _SHA256.fullmatch(expected_hash)
        ):
            raise M15PredicateOverlayError("predicate bundle hash entry is invalid")
        candidate = bundle_root / relative_path
        if candidate.is_symlink() or not candidate.is_file():
            raise M15PredicateOverlayError(
                "predicate bundle member is not regular"
            )
        if _sha256_bytes(candidate.read_bytes()) != expected_hash:
            raise M15PredicateOverlayError(
                f"predicate bundle SHA-256 mismatch: {relative_path}"
            )
    recorded_mapping = M15PredicateMappingSpec.from_dict(
        _regular_json_object(
            bundle_root / "predicate_mapping.json",
            name="embedded predicate mapping",
        )
    )
    if recorded_mapping != mapping:
        raise M15PredicateOverlayError("embedded predicate mapping changed")
    recorded_spec = M15ParameterizedWorkloadSpec.from_dict(
        _regular_json_object(
            bundle_root / "workload_spec.json",
            name="predicate workload spec",
        )
    )
    if recorded_spec != expected_spec:
        raise M15PredicateOverlayError("predicate workload spec changed")
    deterministic, records, family_hash, payments = _bundle_content(
        base_bundle=base_bundle,
        spec=recorded_spec,
        mapping=recorded_mapping,
    )
    for relative_path, expected_text in deterministic.items():
        if (bundle_root / relative_path).read_text(encoding="utf-8") != expected_text:
            raise M15PredicateOverlayError(
                f"predicate bundle content is not deterministic: {relative_path}"
            )
    expected_manifest = _bundle_manifest(
        base_bundle=base_bundle,
        content=deterministic,
        records=records,
        family_hash=family_hash,
        spec=recorded_spec,
        mapping=recorded_mapping,
        payment_count=len(payments),
    )
    if manifest != expected_manifest:
        raise M15PredicateOverlayError(
            "predicate workload manifest is not deterministic"
        )
    return M15ParameterizedWorkloadBundle(bundle_root, recorded_spec, manifest)


def _overlay_manifest(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    overlay_bundle: M15ParameterizedWorkloadBundle,
    base_query_id: str,
    catalog: M15SemanticRelaxationCatalog,
    mapping: M15PredicateMappingSpec,
    solution: Mapping[str, Any],
    additions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if overlay_bundle.manifest["family_compatibility_sha256"] != (
        base_bundle.manifest["family_compatibility_sha256"]
    ):
        raise M15PredicateOverlayError(
            "predicate overlay changed query-family compatibility"
        )
    overlay_by_query = {
        item["query_id"]: item for item in overlay_bundle.manifest["instances"]
    }
    records: list[dict[str, Any]] = []
    for addition in additions:
        generated = overlay_by_query.get(addition["query_id"])
        if generated is None or generated["query_instance_sha256"] != (
            addition["expected_query_instance_sha256"]
        ):
            raise M15PredicateOverlayError(
                "predicate overlay changed semantic instance identity"
            )
        records.append(
            {
                "semantic_class_id": addition["semantic_class_id"],
                "semantic_deviation": addition["semantic_deviation"],
                "changed_slot_ids": list(addition["changed_slot_ids"]),
                "query_id": addition["query_id"],
                "query_instance_sha256": generated[
                    "query_instance_sha256"
                ],
                "binding_sha256": generated["binding_sha256"],
                "oracle_counts": dict(generated["oracle_counts"]),
            }
        )
    base_files = base_bundle.manifest["files_sha256"]
    overlay_files = overlay_bundle.manifest["files_sha256"]
    shared_paths = sorted(
        path
        for path in base_files
        if path
        not in {
            "instances.json",
            "load_neo4j.cypher",
            "workload_spec.json",
        }
    )
    for path in shared_paths:
        if overlay_files.get(path) != base_files[path]:
            raise M15PredicateOverlayError(
                f"predicate overlay changed frozen base artifact '{path}'"
            )
    base_load = base_bundle.path("load_neo4j.cypher").read_text(encoding="utf-8")
    overlay_load = overlay_bundle.path("load_neo4j.cypher").read_text(
        encoding="utf-8"
    )
    if not overlay_load.startswith(base_load + "\n"):
        raise M15PredicateOverlayError(
            "predicate load does not preserve the frozen Neo4j load prefix"
        )
    solution_payload = dict(solution)
    path_blocked = sum(
        _binding_values(item)["path-shape"] != "direct"
        for item in solution_payload["semantic_equivalence_classes"]
    )
    predicate_records = [
        item
        for item in records
        if "transfer-predicate" in item["changed_slot_ids"]
    ]
    body = {
        "schema_version": PREDICATE_OVERLAY_SCHEMA_VERSION,
        "generator_version": PREDICATE_OVERLAY_GENERATOR_VERSION,
        "base_workload_id": base_bundle.manifest["workload_id"],
        "base_workload_bundle_content_sha256": base_bundle.manifest[
            "bundle_content_sha256"
        ],
        "overlay_workload_bundle_content_sha256": overlay_bundle.manifest[
            "bundle_content_sha256"
        ],
        "base_query_id": base_query_id,
        "family_compatibility_sha256": base_bundle.manifest[
            "family_compatibility_sha256"
        ],
        "semantic_catalog_sha256": catalog.catalog_hash,
        "semantic_solution_space_sha256": solution_payload[
            "solution_space_sha256"
        ],
        "predicate_mapping": {
            "mapping_id": mapping.mapping_id,
            "mapping_sha256": content_hash(mapping.to_dict()),
            "transition_id": mapping.transition_id,
            "source_predicate": mapping.source_predicate,
            "target_predicate": mapping.target_predicate,
            "transformation": mapping.transformation,
            "evidence": dict(mapping.evidence),
            "backend_relationship_type": mapping.relationship_type,
        },
        "counts": {
            "semantic_classes": solution_payload["semantic_class_count"],
            "direct_supported_classes": 4,
            "overlay_instances": len(records),
            "predicate_enabled_instances": len(predicate_records),
            "path_blocked_classes": path_blocked,
            "base_query_instances": len(base_bundle.manifest["instances"]),
            "total_query_instances": len(overlay_bundle.manifest["instances"]),
            "payment_edges": overlay_bundle.manifest["counts"]["payment_edges"],
        },
        "overlay_instances": sorted(records, key=lambda item: item["query_id"]),
        "base_artifact_preservation": {
            "base_bundle_mutated": False,
            "unchanged_file_count": len(shared_paths),
            "unchanged_files": shared_paths,
            "base_neo4j_load_sha256": base_files["load_neo4j.cypher"],
            "base_neo4j_load_is_exact_prefix": True,
            "fuseki_load_identical": overlay_files["load_fuseki.ttl"]
            == base_files["load_fuseki.ttl"],
        },
        "remaining_blockers": [
            "path_semantics_unbound",
            "path_backend_template_missing",
            "path_data_missing",
            "path_oracle_support_missing",
        ],
        "claim_boundary": {
            "artifact_class": "unexecuted_predicate_relaxation_overlay",
            "development_mapping_fixture": True,
            "all_direct_semantic_classes_bound": True,
            "multihop_classes_materialized": False,
            "base_bundle_mutated": False,
            "relaxed_backend_artifacts_bound": True,
            "relaxed_oracles_bound": True,
            "semantic_user_utility_validated": False,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {**body, "overlay_sha256": content_hash(body)}


def generate_m15_predicate_overlay_bundle(
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    base_query_id: str,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    destination: str | Path,
) -> M15PredicateOverlayBundle:
    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    selected_catalog = _selected_catalog(catalog)
    selected_mapping = _selected_mapping(mapping)
    selected_query_id = _safe_id(base_query_id, name="base_query_id")
    solution, selected_classes, _ = _direct_semantic_classes(
        bundle=selected_base,
        query_id=selected_query_id,
        catalog=selected_catalog,
        mapping=selected_mapping,
    )
    extended_spec, additions = _extended_spec(
        base_bundle=selected_base,
        base_query_id=selected_query_id,
        semantic_classes=selected_classes,
    )
    destination_path = Path(destination).resolve()
    if destination_path.exists():
        raise FileExistsError(
            f"predicate overlay destination exists: {destination_path}"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.tmp-",
            dir=destination_path.parent,
        )
    )
    try:
        overlay_bundle = _write_bundle(
            destination=temporary / "parameterized-workload-bundle",
            base_bundle=selected_base,
            spec=extended_spec,
            mapping=selected_mapping,
        )
        manifest = _overlay_manifest(
            base_bundle=selected_base,
            overlay_bundle=overlay_bundle,
            base_query_id=selected_query_id,
            catalog=selected_catalog,
            mapping=selected_mapping,
            solution=solution.to_dict(),
            additions=additions,
        )
        (temporary / "overlay_manifest.json").write_text(
            _json_text(manifest), encoding="utf-8"
        )
        load_m15_predicate_overlay_bundle(
            temporary,
            base_bundle=selected_base,
            catalog=selected_catalog,
            mapping=selected_mapping,
        )
        os.replace(temporary, destination_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return load_m15_predicate_overlay_bundle(
        destination_path,
        base_bundle=selected_base,
        catalog=selected_catalog,
        mapping=selected_mapping,
    )


def load_m15_predicate_overlay_bundle(
    root: str | Path,
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
) -> M15PredicateOverlayBundle:
    overlay_root = Path(root).resolve()
    if overlay_root.is_symlink() or not overlay_root.is_dir():
        raise M15PredicateOverlayError(
            "predicate overlay root must be a regular directory"
        )
    if any(path.is_symlink() for path in overlay_root.rglob("*")):
        raise M15PredicateOverlayError("predicate overlay cannot contain symlinks")
    if {path.name for path in overlay_root.iterdir()} != {
        "overlay_manifest.json",
        "parameterized-workload-bundle",
    }:
        raise M15PredicateOverlayError("predicate overlay root members are invalid")
    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    selected_catalog = _selected_catalog(catalog)
    selected_mapping = _selected_mapping(mapping)
    recorded = _regular_json_object(
        overlay_root / "overlay_manifest.json",
        name="predicate overlay manifest",
    )
    if recorded.get("schema_version") != PREDICATE_OVERLAY_SCHEMA_VERSION:
        raise M15PredicateOverlayError(
            "predicate overlay schema_version is unsupported"
        )
    if recorded.get("generator_version") != PREDICATE_OVERLAY_GENERATOR_VERSION:
        raise M15PredicateOverlayError(
            "predicate overlay generator_version is unsupported"
        )
    base_query_id = _safe_id(recorded.get("base_query_id"), name="base_query_id")
    solution, selected_classes, _ = _direct_semantic_classes(
        bundle=selected_base,
        query_id=base_query_id,
        catalog=selected_catalog,
        mapping=selected_mapping,
    )
    expected_spec, additions = _extended_spec(
        base_bundle=selected_base,
        base_query_id=base_query_id,
        semantic_classes=selected_classes,
    )
    overlay_bundle = _load_predicate_workload_bundle(
        overlay_root / "parameterized-workload-bundle",
        base_bundle=selected_base,
        expected_spec=expected_spec,
        mapping=selected_mapping,
    )
    expected_manifest = _overlay_manifest(
        base_bundle=selected_base,
        overlay_bundle=overlay_bundle,
        base_query_id=base_query_id,
        catalog=selected_catalog,
        mapping=selected_mapping,
        solution=solution.to_dict(),
        additions=additions,
    )
    if recorded != expected_manifest:
        raise M15PredicateOverlayError(
            "predicate overlay manifest is not deterministic"
        )
    return M15PredicateOverlayBundle(
        overlay_root,
        overlay_bundle,
        selected_mapping,
        recorded,
    )


def load_m15_predicate_overlay_workload_bundle(
    workload_root: str | Path,
    *,
    overlay_root: str | Path,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
) -> M15ParameterizedWorkloadBundle:
    """Revalidate an overlay and return only its exact workload root.

    This adapter lets the ordinary fixture loader retain a mandatory
    format-specific trust boundary instead of accepting an arbitrary bundle
    object merely because it has the expected Python type.
    """

    overlay = load_m15_predicate_overlay_bundle(
        overlay_root,
        base_bundle=base_bundle,
        catalog=catalog,
        mapping=mapping,
    )
    selected_root = Path(workload_root).resolve()
    if overlay.workload_bundle.root.resolve() != selected_root:
        raise M15PredicateOverlayError(
            "requested workload root does not belong to the predicate overlay"
        )
    return overlay.workload_bundle


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bundle-root", required=True)
    parser.add_argument("--base-query-id", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        overlay = generate_m15_predicate_overlay_bundle(
            base_bundle=arguments.base_bundle_root,
            base_query_id=arguments.base_query_id,
            catalog=arguments.catalog,
            mapping=arguments.mapping,
            destination=arguments.output,
        )
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {"status": "success", "root": str(overlay.root), **overlay.to_dict()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
