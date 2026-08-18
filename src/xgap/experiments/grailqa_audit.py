"""Isolated GrailQA artifact-feasibility audit for M13-A."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence

from xgap.algebra.conditions import NodeRef, PropertyNotEquals
from xgap.algebra.ops import RecursiveMode
from xgap.pattern.ast import (
    Direction,
    EdgePattern,
    NodePattern,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
    Var,
)
from xgap.pattern.lowering import lower_to_logical_plan
from xgap.planning.topology import index_logical_plan


SCHEMA_VERSION = "m13a-grailqa-audit-v1"
OFFICIAL_DATASET_URL = "https://dl.orangedox.com/WyaCpL/"
OFFICIAL_REPOSITORY_URL = "https://github.com/dki-lab/GrailQA"
DATASET_LICENSE = "CC BY-SA 4.0"
ONTOLOGY_REPOSITORY_LICENSE = "Apache-2.0"
DATASET_FILES = {
    "train": "grailqa_v1.0_train.json",
    "dev": "grailqa_v1.0_dev.json",
    "test_public": "grailqa_v1.0_test_public.json",
}
ONTOLOGY_FILES = (
    "fb_roles",
    "fb_types",
    "reverse_properties",
    "domain_dict",
    "domain_info",
)
KNOWN_GOLD_OPERATORS = {
    "AND",
    "ARGMAX",
    "ARGMIN",
    "COUNT",
    "GE",
    "GT",
    "JOIN",
    "LE",
    "LT",
    "R",
}
COMPARISON_FUNCTIONS = {"<", "<=", ">", ">="}
SUPERLATIVE_FUNCTIONS = {"argmax", "argmin", "max", "min"}
SCALAR_RANGES = {
    "type.boolean",
    "type.datetime",
    "type.enumeration",
    "type.float",
    "type.id",
    "type.int",
    "type.key",
    "type.lang",
    "type.rawstring",
    "type.text",
    "type.uri",
}


class SExpressionError(ValueError):
    """Raised when a GrailQA S-expression is malformed."""


@dataclass(frozen=True)
class GoldExpressionAnalysis:
    operators: tuple[str, ...]
    operator_count: int
    dependency_count: int

    @property
    def complexity(self) -> int:
        return self.operator_count + self.dependency_count


@dataclass(frozen=True)
class OntologyResources:
    classes: frozenset[str]
    relations: frozenset[str]
    properties: frozenset[str]
    datatypes: frozenset[str]
    hierarchy_edges: tuple[tuple[str, str], ...]
    domain_range: Mapping[str, tuple[str, str]]
    reverse_relations: Mapping[str, str]
    malformed_role_lines: tuple[int, ...]
    malformed_type_lines: tuple[int, ...]
    source_hashes: Mapping[str, str]

    @property
    def predicates(self) -> frozenset[str]:
        return self.relations | self.properties


@dataclass(frozen=True)
class ConversionResult:
    record: dict[str, Any]
    supported: bool


@dataclass
class AuditAccumulator:
    total: int = 0
    gold_available: int = 0
    supported: int = 0
    by_split: dict[str, Counter[str]] = None  # type: ignore[assignment]
    by_query_type: dict[str, Counter[str]] = None  # type: ignore[assignment]
    by_level: dict[str, Counter[str]] = None  # type: ignore[assignment]
    by_complexity: dict[str, Counter[str]] = None  # type: ignore[assignment]
    unsupported_reasons: Counter[str] = None  # type: ignore[assignment]
    operator_occurrences: Counter[str] = None  # type: ignore[assignment]
    operator_questions: Counter[str] = None  # type: ignore[assignment]
    operator_supported_questions: Counter[str] = None  # type: ignore[assignment]
    plan_complexities: list[int] = None  # type: ignore[assignment]
    plan_operator_counts: list[int] = None  # type: ignore[assignment]
    plan_dependency_counts: list[int] = None  # type: ignore[assignment]
    gold_complexities: list[int] = None  # type: ignore[assignment]
    anchorable_gold_slots: int = 0
    anchorable_xgap_reference: int = 0
    anchor_reasons: Counter[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.by_split = defaultdict(Counter)
        self.by_query_type = defaultdict(Counter)
        self.by_level = defaultdict(Counter)
        self.by_complexity = defaultdict(Counter)
        self.unsupported_reasons = Counter()
        self.operator_occurrences = Counter()
        self.operator_questions = Counter()
        self.operator_supported_questions = Counter()
        self.plan_complexities = []
        self.plan_operator_counts = []
        self.plan_dependency_counts = []
        self.gold_complexities = []
        self.anchor_reasons = Counter()


def load_ontology_resources(ontology_root: str | Path) -> OntologyResources:
    """Load the official processed Freebase ontology files without inference."""

    root = Path(ontology_root)
    source_hashes = {name: _sha256(root / name) for name in ONTOLOGY_FILES}
    domain_range: dict[str, tuple[str, str]] = {}
    malformed_roles: list[int] = []
    for line_number, line in enumerate((root / "fb_roles").read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            malformed_roles.append(line_number)
            continue
        domain, relation, range_term = parts
        domain_range[relation] = (domain, range_term)

    hierarchy: set[tuple[str, str]] = set()
    malformed_types: list[int] = []
    for line_number, line in enumerate((root / "fb_types").read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        valid_trailing_separator = len(parts) == 4 and parts[3] == "."
        if (
            len(parts) not in {3, 4}
            or parts[1] != "meta.subclassOf"
            or (len(parts) == 4 and not valid_trailing_separator)
        ):
            malformed_types.append(line_number)
            continue
        hierarchy.add((parts[0], parts[2]))

    reverse_relations: dict[str, str] = {}
    for line in (root / "reverse_properties").read_text().splitlines():
        if not line.strip():
            continue
        left, right = line.split()
        reverse_relations[left] = right
        reverse_relations[right] = left

    properties = {
        relation
        for relation, (_, range_term) in domain_range.items()
        if range_term in SCALAR_RANGES
    }
    relations = set(domain_range) - properties
    datatypes = {
        range_term
        for _, range_term in domain_range.values()
        if range_term in SCALAR_RANGES
    }
    classes = {term for edge in hierarchy for term in edge}
    classes.update(domain for domain, _ in domain_range.values())
    classes.update(
        range_term
        for _, range_term in domain_range.values()
        if range_term not in SCALAR_RANGES
    )
    classes.difference_update(relations)
    classes.difference_update(properties)

    return OntologyResources(
        classes=frozenset(classes),
        relations=frozenset(relations),
        properties=frozenset(properties),
        datatypes=frozenset(datatypes),
        hierarchy_edges=tuple(sorted(hierarchy)),
        domain_range=dict(sorted(domain_range.items())),
        reverse_relations=dict(sorted(reverse_relations.items())),
        malformed_role_lines=tuple(malformed_roles),
        malformed_type_lines=tuple(malformed_types),
        source_hashes=source_hashes,
    )


def analyze_s_expression(expression: str) -> GoldExpressionAnalysis:
    """Parse one gold S-expression and count its operator-call tree."""

    tokens = _tokenize_s_expression(expression)
    parsed, next_index = _parse_s_expression(tokens, 0)
    if next_index != len(tokens):
        raise SExpressionError("Unexpected tokens after the root expression.")

    operators: list[str] = []
    dependencies = 0

    def visit(node: str | list[Any], parent_is_operator: bool = False) -> None:
        nonlocal dependencies
        if not isinstance(node, list):
            return
        if not node or not isinstance(node[0], str):
            raise SExpressionError("Every expression list must have an operator head.")
        operator = _normalize_gold_operator(node[0])
        is_operator = operator in KNOWN_GOLD_OPERATORS
        if is_operator:
            operators.append(operator)
            if parent_is_operator:
                dependencies += 1
        for child in node[1:]:
            visit(child, is_operator)

    visit(parsed)
    return GoldExpressionAnalysis(
        operators=tuple(operators),
        operator_count=len(operators),
        dependency_count=dependencies,
    )


def convert_question_for_audit(
    question: Mapping[str, Any],
    split: str,
    ontology: OntologyResources,
) -> ConversionResult:
    """Conservatively attempt one gold query through production M5 lowering."""

    question_id = str(question.get("qid", ""))
    base = {
        "schema_version": SCHEMA_VERSION,
        "question_id": question_id,
        "split": split,
        "level": str(question.get("level", "not_available")),
        "status": "unsupported",
    }
    expression = question.get("s_expression")
    graph_query = question.get("graph_query")
    if not isinstance(expression, str) or not isinstance(graph_query, Mapping):
        return _unsupported(base, "missing_gold_logical_form", "public annotation is masked")

    try:
        expression_analysis = analyze_s_expression(expression)
    except (SExpressionError, TypeError, ValueError) as error:
        return _unsupported(base, "parser_failure", str(error))

    base["gold_operators"] = list(expression_analysis.operators)
    function = str(question.get("function", "none"))
    if function == "count":
        return _unsupported(base, "unsupported_aggregation", "COUNT")
    if function in COMPARISON_FUNCTIONS:
        return _unsupported(base, "unsupported_comparison", function)
    if function in SUPERLATIVE_FUNCTIONS:
        return _unsupported(base, "unsupported_ordering", function)
    if function != "none":
        return _unsupported(base, "unsupported_operator", function)

    nodes = graph_query.get("nodes")
    edges = graph_query.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return _unsupported(base, "parser_failure", "graph_query nodes/edges are malformed")
    if len(edges) != 1 or len(nodes) != 2:
        detail = _path_shape_detail(nodes, edges)
        return _unsupported(base, "unsupported_path_semantics", detail)

    question_nodes = [node for node in nodes if node.get("question_node") == 1]
    entity_nodes = [node for node in nodes if node.get("node_type") == "entity"]
    if len(question_nodes) != 1:
        return _unsupported(base, "ambiguous_conversion", "expected one question node")
    if len(entity_nodes) != 1:
        return _unsupported(base, "missing_entity_mapping", "expected one entity anchor")
    question_node = question_nodes[0]
    entity_node = entity_nodes[0]
    if question_node.get("node_type") != "class":
        return _unsupported(base, "unsupported_path_semantics", "question node is not a class")

    question_class = str(question_node.get("class") or question_node.get("id") or "")
    entity_class = str(entity_node.get("class") or "")
    entity_id = str(entity_node.get("id") or "")
    if not entity_id or not entity_class:
        return _unsupported(base, "missing_entity_mapping", "entity ID or type is unavailable")
    missing_classes = sorted(
        term for term in (question_class, entity_class) if term not in ontology.classes
    )
    if missing_classes:
        return _unsupported(
            base,
            "missing_ontology_term",
            ",".join(missing_classes),
        )

    edge = edges[0]
    relation = str(edge.get("relation") or "")
    if relation not in ontology.predicates:
        return _unsupported(base, "missing_relation_mapping", relation or "missing relation")
    entity_nid = entity_node.get("nid")
    question_nid = question_node.get("nid")
    reverse_used = False
    if edge.get("start") == entity_nid and edge.get("end") == question_nid:
        traversal_relation = relation
    elif edge.get("start") == question_nid and edge.get("end") == entity_nid:
        traversal_relation = ontology.reverse_relations.get(relation, "")
        reverse_used = True
        if not traversal_relation or traversal_relation not in ontology.predicates:
            return _unsupported(
                base,
                "missing_relation_mapping",
                f"no declared inverse for {relation}",
            )
    else:
        return _unsupported(base, "ambiguous_conversion", "edge does not join the two nodes")

    query = PathPatternQuery(
        path_var=Var("path"),
        source=NodePattern(
            var=Var("source"),
            label=entity_class,
            properties={"freebase_id": entity_id},
        ),
        expr=Rel(
            EdgePattern(
                var=Var("edge"),
                label=traversal_relation,
                direction=Direction.OUT,
            )
        ),
        target=NodePattern(var=Var("answer"), label=question_class),
        selector=Selector(SelectorKind.ALL),
        restrictor=RecursiveMode.SIMPLE,
        condition=PropertyNotEquals(NodeRef.last(), "freebase_id", entity_id),
    )
    try:
        indexed = index_logical_plan(lower_to_logical_plan(query))
    except (NotImplementedError, TypeError, ValueError) as error:
        return _unsupported(base, "lowering_failure", str(error))

    result = dict(base)
    result.update(
        {
            "status": "supported",
            "operators": [operator.operator_name for operator in indexed.operators],
            "logical_plan_size": len(indexed.operators) + len(indexed.dependencies),
            "logical_operator_count": len(indexed.operators),
            "logical_dependency_count": len(indexed.dependencies),
            "logical_plan_id": indexed.logical_plan_id,
            "source_entity_id": entity_id,
            "source_class": entity_class,
            "target_class": question_class,
            "gold_relation": relation,
            "traversal_relation": traversal_relation,
            "reverse_property_used": reverse_used,
            "mapping_contract": "freebase_id node property plus Freebase type-as-label projection",
        }
    )
    return ConversionResult(record=result, supported=True)


def run_audit(
    dataset_root: str | Path,
    ontology_root: str | Path,
    output_root: str | Path,
    *,
    dataset_archive: str | Path | None = None,
    ontology_revision: str | None = None,
) -> dict[str, Any]:
    """Audit every public GrailQA question and write deterministic artifacts."""

    dataset_path = Path(dataset_root)
    output_path = Path(output_root)
    ontology = load_ontology_resources(ontology_root)
    supported_records: list[dict[str, Any]] = []
    unsupported_records: list[dict[str, Any]] = []
    stats = AuditAccumulator()
    schema_labels: dict[str, set[str]] = defaultdict(set)
    entity_labels: dict[str, set[str]] = defaultdict(set)
    dataset_sources: dict[str, Any] = {}

    for split, filename in DATASET_FILES.items():
        source_path = dataset_path / filename
        questions = _load_json_array(source_path)
        dataset_sources[split] = {
            "file": filename,
            "format": "JSON array",
            "sha256": _sha256(source_path),
            "question_count": len(questions),
            "gold_annotations": split != "test_public",
        }
        for question in questions:
            result = convert_question_for_audit(question, split, ontology)
            _collect_labels(question, schema_labels, entity_labels)
            _update_stats(stats, question, split, result, ontology)
            if result.supported:
                supported_records.append(result.record)
            else:
                unsupported_records.append(result.record)

    ontology_summary = _ontology_summary(
        ontology,
        schema_labels,
        entity_labels,
        ontology_revision=ontology_revision,
    )
    complexity_distribution = {
        "schema_version": SCHEMA_VERSION,
        "definition": "Q(u)=|Omega_u^gold|+|D_u^gold|",
        "xgap_logical_plans": {
            "scope": "audit-supported train/dev questions",
            **_distribution(stats.plan_complexities),
            "operator_count": _distribution(stats.plan_operator_counts),
            "dependency_count": _distribution(stats.plan_dependency_counts),
        },
        "gold_s_expression_operator_trees": {
            "scope": "all train/dev questions with public gold S-expressions",
            "note": "Workload proxy only; unsupported trees are not XGAP LogicalPlans.",
            **_distribution(stats.gold_complexities),
        },
    }
    archive = None
    if dataset_archive is not None:
        archive_path = Path(dataset_archive)
        archive = {
            "file": archive_path.name,
            "sha256": _sha256(archive_path),
        }
    summary = _build_summary(
        stats,
        dataset_sources,
        ontology_summary,
        archive=archive,
        ontology_revision=ontology_revision,
    )

    output_path.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path / "supported_questions.jsonl", supported_records)
    _write_jsonl(output_path / "unsupported_questions.jsonl", unsupported_records)
    _write_json(output_path / "audit_summary.json", summary)
    _write_json(output_path / "ontology_summary.json", ontology_summary)
    _write_json(output_path / "complexity_distribution.json", complexity_distribution)
    return summary


def _update_stats(
    stats: AuditAccumulator,
    question: Mapping[str, Any],
    split: str,
    result: ConversionResult,
    ontology: OntologyResources,
) -> None:
    stats.total += 1
    function = str(question.get("function", "not_available"))
    level = str(question.get("level", "not_available"))
    complexity = str(question.get("num_edge", "not_available"))
    buckets = (
        stats.by_split[split],
        stats.by_query_type[function],
        stats.by_level[level],
        stats.by_complexity[complexity],
    )
    for bucket in buckets:
        bucket["total"] += 1

    expression = question.get("s_expression")
    analysis: GoldExpressionAnalysis | None = None
    if isinstance(expression, str):
        stats.gold_available += 1
        try:
            analysis = analyze_s_expression(expression)
        except SExpressionError:
            analysis = None
        if analysis is not None:
            stats.gold_complexities.append(analysis.complexity)
            stats.operator_occurrences.update(analysis.operators)
            stats.operator_questions.update(set(analysis.operators))

    ontology_terms = _question_ontology_terms(question)
    missing_terms = ontology_terms - (
        ontology.classes | ontology.predicates | ontology.datatypes
    )
    if not isinstance(expression, str):
        stats.anchor_reasons["missing_gold_annotations"] += 1
    elif missing_terms:
        stats.anchor_reasons["missing_ontology_term"] += 1
    else:
        stats.anchorable_gold_slots += 1

    if result.supported:
        stats.supported += 1
        stats.anchorable_xgap_reference += 1
        for bucket in buckets:
            bucket["supported"] += 1
        if analysis is not None:
            stats.operator_supported_questions.update(set(analysis.operators))
        record = result.record
        stats.plan_complexities.append(int(record["logical_plan_size"]))
        stats.plan_operator_counts.append(int(record["logical_operator_count"]))
        stats.plan_dependency_counts.append(int(record["logical_dependency_count"]))
    else:
        reason = str(result.record["reason"])
        stats.unsupported_reasons[reason] += 1
        stats.anchor_reasons["unsupported_xgap_reference"] += 1
        for bucket in buckets:
            bucket["unsupported"] += 1


def _build_summary(
    stats: AuditAccumulator,
    dataset_sources: Mapping[str, Any],
    ontology_summary: Mapping[str, Any],
    *,
    archive: Mapping[str, str] | None,
    ontology_revision: str | None,
) -> dict[str, Any]:
    gold_unsupported = stats.gold_available - stats.supported
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M13-A GrailQA Paper Artifact Feasibility Audit",
        "recommendation": "suitable_with_restrictions",
        "benchmark_integration_complete": False,
        "source": {
            "dataset_url": OFFICIAL_DATASET_URL,
            "dataset_license": DATASET_LICENSE,
            "repository_url": OFFICIAL_REPOSITORY_URL,
            "ontology_repository_license": ONTOLOGY_REPOSITORY_LICENSE,
            "dataset_archive": archive,
            "ontology_revision": ontology_revision,
            "dataset_files": dict(dataset_sources),
            "ontology_files": dict(ontology_summary["source_files"]),
        },
        "totals": {
            "public_questions": stats.total,
            "gold_available_questions": stats.gold_available,
            "supported_questions": stats.supported,
            "unsupported_questions": stats.total - stats.supported,
            "gold_available_unsupported_questions": gold_unsupported,
            "supported_ratio_public": _ratio(stats.supported, stats.total),
            "supported_ratio_gold_available": _ratio(stats.supported, stats.gold_available),
        },
        "support_definition": {
            "scope": "logical-structure feasibility, not executable Freebase integration",
            "supported_fragment": (
                "single-hop non-aggregate/non-comparative query with one entity anchor, "
                "one answer class, and a declared forward or inverse relation"
            ),
            "mapping_contract": (
                "Freebase MID is exposed as node property freebase_id and Freebase class "
                "membership is projected to an XGAP node label"
            ),
            "production_lowering_modified": False,
        },
        "by_split": _serialize_buckets(stats.by_split),
        "by_query_type": _serialize_buckets(stats.by_query_type),
        "by_generalization_level": _serialize_buckets(stats.by_level),
        "by_gold_edge_count": _serialize_buckets(stats.by_complexity),
        "gold_operator_coverage": {
            operator: {
                "occurrences": stats.operator_occurrences[operator],
                "questions": stats.operator_questions[operator],
                "supported_questions": stats.operator_supported_questions[operator],
                "supported_ratio": _ratio(
                    stats.operator_supported_questions[operator],
                    stats.operator_questions[operator],
                ),
            }
            for operator in sorted(stats.operator_occurrences)
        },
        "unsupported_reasons": dict(sorted(stats.unsupported_reasons.items())),
        "anchor_feasibility": {
            "gold_slot_anchorable_questions": stats.anchorable_gold_slots,
            "xgap_reference_anchorable_questions": stats.anchorable_xgap_reference,
            "non_anchorable_public_questions": stats.total - stats.anchorable_gold_slots,
            "reasons": dict(sorted(stats.anchor_reasons.items())),
            "llm_anchor_generation_used": False,
        },
        "ontology_artifact_feasibility": dict(ontology_summary["m12_artifact_feasibility"]),
    }


def _ontology_summary(
    ontology: OntologyResources,
    schema_labels: Mapping[str, set[str]],
    entity_labels: Mapping[str, set[str]],
    *,
    ontology_revision: str | None,
) -> dict[str, Any]:
    cycles = _hierarchy_cycle_summary(ontology.hierarchy_edges)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_repository": OFFICIAL_REPOSITORY_URL,
        "source_revision": ontology_revision,
        "source_files": {
            name: {"sha256": digest, "format": "whitespace-delimited text"}
            for name, digest in sorted(ontology.source_hashes.items())
        },
        "counts": {
            "classes": len(ontology.classes),
            "relations": len(ontology.relations),
            "properties": len(ontology.properties),
            "datatypes": len(ontology.datatypes),
            "predicates_total": len(ontology.predicates),
            "domain_range_records": len(ontology.domain_range),
            "hierarchy_edges": len(ontology.hierarchy_edges),
            "hierarchy_self_edges": cycles["self_edges"],
            "hierarchy_cyclic_components": cycles["cyclic_components"],
            "hierarchy_terms_in_cycles": cycles["terms_in_cycles"],
            "reverse_property_directed_entries": len(ontology.reverse_relations),
            "reverse_property_pairs": len(ontology.reverse_relations) // 2,
            "malformed_fb_roles_lines": len(ontology.malformed_role_lines),
            "malformed_fb_types_lines": len(ontology.malformed_type_lines),
            "schema_terms_with_annotation_labels": len(schema_labels),
            "schema_terms_with_multiple_annotation_labels": sum(
                len(values) > 1 for values in schema_labels.values()
            ),
            "entity_ids_with_annotation_labels": len(entity_labels),
            "entity_ids_with_multiple_annotation_labels": sum(
                len(values) > 1 for values in entity_labels.values()
            ),
            "public_alias_lists": 0,
        },
        "malformed_source_lines": {
            "fb_roles": list(ontology.malformed_role_lines),
            "fb_types": list(ontology.malformed_type_lines),
        },
        "m12_artifact_feasibility": {
            "ontology_yaml": "requires_documented_normalization_and_validation",
            "aliases_yaml": "not_constructible_from_public_artifacts_alone",
            "schema_snapshot_json": "constructible_with_mapping_policy",
            "entity_catalog": "partial_train_dev_only",
            "blockers": [
                "No public ontology alias lexicon is provided.",
                "Public test annotations and entity labels are masked.",
                "Freebase multi-type nodes require an explicit type-to-label projection policy.",
                "The public class hierarchy contains cyclic components rejected by M12 OntologyGraph.",
                "Two malformed concatenated lines in each of fb_roles and fb_types require "
                "source-side repair or exclusion.",
            ],
        },
        "no_inferred_edges": True,
        "llm_inference_used": False,
    }


def _collect_labels(
    question: Mapping[str, Any],
    schema_labels: dict[str, set[str]],
    entity_labels: dict[str, set[str]],
) -> None:
    graph_query = question.get("graph_query")
    if not isinstance(graph_query, Mapping):
        return
    nodes = graph_query.get("nodes", ())
    edges = graph_query.get("edges", ())
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            identifier = str(node.get("id") or "")
            label = str(node.get("friendly_name") or "").strip()
            if not identifier or not label:
                continue
            if node.get("node_type") == "entity":
                entity_labels[identifier].add(label)
            elif node.get("node_type") == "class":
                schema_labels[identifier].add(label)
    if isinstance(edges, list):
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            relation = str(edge.get("relation") or "")
            label = str(edge.get("friendly_name") or "").strip()
            if relation and label:
                schema_labels[relation].add(label)


def _hierarchy_cycle_summary(
    edges: Sequence[tuple[str, str]],
) -> dict[str, int]:
    graph: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for child, parent in edges:
        graph[child].append(parent)
        nodes.update((child, parent))

    index = 0
    indexes: dict[str, int] = {}
    low_links: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        low_links[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for parent in graph.get(node, ()):
            if parent not in indexes:
                visit(parent)
                low_links[node] = min(low_links[node], low_links[parent])
            elif parent in on_stack:
                low_links[node] = min(low_links[node], indexes[parent])
        if low_links[node] != indexes[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        components.append(tuple(component))

    for node in sorted(nodes):
        if node not in indexes:
            visit(node)

    self_edges = sum(child == parent for child, parent in edges)
    cyclic = [
        component
        for component in components
        if len(component) > 1
        or (len(component) == 1 and component[0] in graph.get(component[0], ()))
    ]
    return {
        "self_edges": self_edges,
        "cyclic_components": len(cyclic),
        "terms_in_cycles": sum(len(component) for component in cyclic),
    }


def _question_ontology_terms(question: Mapping[str, Any]) -> set[str]:
    graph_query = question.get("graph_query")
    if not isinstance(graph_query, Mapping):
        return set()
    terms: set[str] = set()
    for node in graph_query.get("nodes", ()):
        if isinstance(node, Mapping):
            node_class = str(node.get("class") or "")
            if node_class:
                terms.add(node_class)
            if node.get("node_type") == "class" and node.get("id"):
                terms.add(str(node["id"]))
    for edge in graph_query.get("edges", ()):
        if isinstance(edge, Mapping) and edge.get("relation"):
            terms.add(str(edge["relation"]))
    return terms


def _path_shape_detail(nodes: Sequence[Any], edges: Sequence[Any]) -> str:
    if not nodes or not edges:
        return "focus-only or edgeless GrailQA form is outside the audit converter"
    degree: Counter[Any] = Counter()
    for edge in edges:
        if isinstance(edge, Mapping):
            degree[edge.get("start")] += 1
            degree[edge.get("end")] += 1
    if any(value > 2 for value in degree.values()):
        return "branching join is outside PathPatternQuery"
    return "multi-hop intermediate type constraints and pairwise distinctness are not representable"


def _unsupported(base: Mapping[str, Any], reason: str, detail: str) -> ConversionResult:
    result = dict(base)
    result.update({"status": "unsupported", "reason": reason, "detail": detail})
    return ConversionResult(record=result, supported=False)


def _tokenize_s_expression(expression: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for character in expression:
        if character in "()":
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(character)
        elif character.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(character)
    if current:
        tokens.append("".join(current))
    if not tokens:
        raise SExpressionError("S-expression is empty.")
    return tokens


def _parse_s_expression(tokens: Sequence[str], index: int) -> tuple[str | list[Any], int]:
    if index >= len(tokens):
        raise SExpressionError("Unexpected end of S-expression.")
    token = tokens[index]
    if token == ")":
        raise SExpressionError("Unexpected closing parenthesis.")
    if token != "(":
        return token, index + 1
    items: list[Any] = []
    index += 1
    while index < len(tokens) and tokens[index] != ")":
        item, index = _parse_s_expression(tokens, index)
        items.append(item)
    if index >= len(tokens):
        raise SExpressionError("Unclosed parenthesis.")
    if not items:
        raise SExpressionError("Empty expression list.")
    return items, index + 1


def _normalize_gold_operator(operator: str) -> str:
    return {
        "ge": "GE",
        "gt": "GT",
        "le": "LE",
        "lt": "LT",
    }.get(operator, operator.upper())


def _distribution(values: Sequence[int]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p90": None,
            "max": None,
            "histogram": {},
        }
    ordered = sorted(values)
    p90_index = max(0, math.ceil(0.9 * len(ordered)) - 1)
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": ordered[p90_index],
        "max": ordered[-1],
        "histogram": {
            str(value): count for value, count in sorted(Counter(values).items())
        },
    }


def _serialize_buckets(buckets: Mapping[str, Counter[str]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, counts in sorted(buckets.items()):
        total = counts["total"]
        supported = counts["supported"]
        result[name] = {
            "total": total,
            "supported": supported,
            "unsupported": counts["unsupported"],
            "supported_ratio": _ratio(supported, total),
        }
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array of objects.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--ontology-root", required=True, type=Path)
    parser.add_argument("--output-root", default=Path("datasets/grailqa_audit"), type=Path)
    parser.add_argument("--dataset-archive", type=Path)
    parser.add_argument("--ontology-revision")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = run_audit(
        args.dataset_root,
        args.ontology_root,
        args.output_root,
        dataset_archive=args.dataset_archive,
        ontology_revision=args.ontology_revision,
    )
    totals = summary["totals"]
    print(f"M13-A GrailQA audit: {totals['supported_questions']} supported")
    print(f"Artifacts: {args.output_root.resolve()}")


if __name__ == "__main__":
    main()
