"""Isolated KQA Pro artifact-feasibility audit for M13-B."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import statistics
from typing import Any, Mapping, Sequence

from xgap.algebra.conditions import And, Condition, LabelEquals, NodeRef, PropertyEquals
from xgap.algebra.ops import RecursiveMode
from xgap.backends import registry
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.cypher import compile_cypher
from xgap.compilers.features import plan_from_compiler_input
from xgap.compilers.sparql import compile_sparql
from xgap.pattern.ast import (
    Direction,
    EdgePattern,
    NodePattern,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Var,
)
from xgap.pattern.lowering import lower_to_logical_plan
from xgap.planning.cost import conservative_state_space_bound
from xgap.planning.search import ExchangeCatalog
from xgap.planning.topology import index_logical_plan


SCHEMA_VERSION = "m13b-kqapro-audit-v1"
OFFICIAL_REPOSITORY_URL = "https://github.com/shijx12/KQAPro_Baselines"
OFFICIAL_DATASET_URL = "https://cloud.tsinghua.edu.cn/f/04ce81541e704a648b03/?dl=1"
MIRROR_DATASET_URL = "https://huggingface.co/datasets/drt/kqa_pro"
MIRROR_REVISION = "0b26da66cec9a4d1e42bde3560aeae9f89f6433b"
OFFICIAL_REPOSITORY_REVISION = "14d87cd22eb79f702fd4ad5c09240bef126d9dce"
OFFICIAL_DATASET_LICENSE = "CC BY-SA 4.0"
ORACLE_STATE_LIMIT = 4096
DATASET_FILES = {"train": "train.json", "val": "val.json", "test": "test.json"}

QUALIFIER_OPERATORS = {
    "QFilterStr",
    "QFilterNum",
    "QFilterYear",
    "QFilterDate",
    "QueryAttrQualifier",
    "QueryAttrUnderCondition",
    "QueryRelationQualifier",
}
TYPED_FILTER_OPERATORS = {"FilterNum", "FilterYear", "FilterDate"}
SET_OPERATORS = {"And", "Or"}
ORDERING_OPERATORS = {"SelectBetween", "SelectAmong"}
VERIFY_OPERATORS = {"VerifyStr", "VerifyNum", "VerifyYear", "VerifyDate"}
SCALAR_PROJECTION_OPERATORS = {"QueryAttr"}
RELATION_PROJECTION_OPERATORS = {"QueryRelation"}
LINEAR_PATH_OPERATORS = {"Find", "Relate", "FilterConcept", "What"}

KOPL_OPERATOR_MAPPING: dict[str, tuple[str, str]] = {
    "FindAll": ("Nodes(G); no edge-bearing PathPatternQuery seed", "partial"),
    "Find": ("node name predicate on a path endpoint", "partial"),
    "FilterConcept": ("LabelEquals on the current path node", "partial"),
    "FilterStr": ("PropertyEquals after a dataset representation policy", "unsupported"),
    "FilterNum": ("numeric property condition lacks KQA quantity/unit encoding", "unsupported"),
    "FilterYear": ("typed temporal property condition", "unsupported"),
    "FilterDate": ("typed temporal property condition", "unsupported"),
    "QFilterStr": ("fact qualifier filter", "unsupported"),
    "QFilterNum": ("fact qualifier filter", "unsupported"),
    "QFilterYear": ("fact qualifier filter", "unsupported"),
    "QFilterDate": ("fact qualifier filter", "unsupported"),
    "Relate": ("Rel(EdgePattern), composed with Seq for a uniform direction", "partial"),
    "And": ("KoPL entity-set intersection is not a PathPatternQuery join", "unsupported"),
    "Or": ("KoPL entity-set union is not the audited path fragment", "unsupported"),
    "What": ("answer endpoint name extraction after path execution", "partial"),
    "Count": ("entity-set cardinality", "unsupported"),
    "SelectBetween": ("attribute comparison and entity selection", "unsupported"),
    "SelectAmong": ("attribute ordering and entity selection", "unsupported"),
    "QueryAttr": ("scalar attribute projection", "unsupported"),
    "QueryAttrUnderCondition": ("qualified scalar attribute projection", "unsupported"),
    "VerifyStr": ("Boolean scalar verification", "unsupported"),
    "VerifyNum": ("Boolean scalar verification", "unsupported"),
    "VerifyYear": ("Boolean scalar verification", "unsupported"),
    "VerifyDate": ("Boolean scalar verification", "unsupported"),
    "QueryRelation": ("edge-label projection between bound entities", "unsupported"),
    "QueryAttrQualifier": ("attribute qualifier projection", "unsupported"),
    "QueryRelationQualifier": ("relation qualifier projection", "unsupported"),
}


@dataclass(frozen=True)
class KqaProKbResources:
    concept_ids: frozenset[str]
    entity_ids: frozenset[str]
    concept_name_to_ids: Mapping[str, tuple[str, ...]]
    entity_name_to_ids: Mapping[str, tuple[str, ...]]
    relation_names: frozenset[str]
    attribute_names: frozenset[str]
    qualifier_names: frozenset[str]
    hierarchy_edges: tuple[tuple[str, str], ...]
    relation_direction_occurrences: Mapping[str, int]
    attribute_type_occurrences: Mapping[str, int]
    qualifier_type_occurrences: Mapping[str, int]
    relation_occurrences: int
    attribute_occurrences: int
    qualifier_value_occurrences: int
    hierarchy_cycle_count: int
    hierarchy_cycle_nodes: int
    source_hash: str

    @property
    def node_name_to_ids(self) -> Mapping[str, tuple[str, ...]]:
        combined: dict[str, tuple[str, ...]] = {}
        for name in sorted(set(self.concept_name_to_ids) | set(self.entity_name_to_ids)):
            combined[name] = tuple(
                sorted(
                    (*self.concept_name_to_ids.get(name, ()), *self.entity_name_to_ids.get(name, ()))
                )
            )
        return combined


@dataclass(frozen=True)
class ConversionResult:
    record: dict[str, Any]
    supported: bool


@dataclass
class AuditAccumulator:
    total: int = 0
    gold_available: int = 0
    supported: int = 0
    by_split: dict[str, Counter[str]] | None = None
    unsupported_reasons: Counter[str] | None = None
    operator_occurrences: Counter[str] | None = None
    operator_questions: Counter[str] | None = None
    operator_supported_questions: Counter[str] | None = None
    terminal_operators: Counter[str] | None = None
    program_sizes: list[int] | None = None
    program_complexities: list[int] | None = None
    reference_operator_counts: list[int] | None = None
    reference_dependency_counts: list[int] | None = None
    planning_operator_counts: list[int] | None = None
    planning_dependency_counts: list[int] | None = None
    planning_complexities: list[int] | None = None
    path_lengths: list[int] | None = None
    placement_products: list[int] | None = None
    state_space_bounds: list[int] | None = None
    sparql_triple_counts: list[int] | None = None
    sparql_features: Counter[str] | None = None

    def __post_init__(self) -> None:
        self.by_split = defaultdict(Counter)
        self.unsupported_reasons = Counter()
        self.operator_occurrences = Counter()
        self.operator_questions = Counter()
        self.operator_supported_questions = Counter()
        self.terminal_operators = Counter()
        self.program_sizes = []
        self.program_complexities = []
        self.reference_operator_counts = []
        self.reference_dependency_counts = []
        self.planning_operator_counts = []
        self.planning_dependency_counts = []
        self.planning_complexities = []
        self.path_lengths = []
        self.placement_products = []
        self.state_space_bounds = []
        self.sparql_triple_counts = []
        self.sparql_features = Counter()


def load_kb_resources(path: str | Path) -> KqaProKbResources:
    """Load only explicitly present KQA Pro KB schema and catalog evidence."""

    kb_path = Path(path)
    raw = json.loads(kb_path.read_text(encoding="utf-8"))
    concepts = _mapping(raw.get("concepts"), "concepts")
    entities = _mapping(raw.get("entities"), "entities")
    concept_names: dict[str, list[str]] = defaultdict(list)
    entity_names: dict[str, list[str]] = defaultdict(list)
    hierarchy: set[tuple[str, str]] = set()
    for concept_id, value in concepts.items():
        record = _mapping(value, f"concepts.{concept_id}")
        concept_names[str(record.get("name", ""))].append(str(concept_id))
        for parent in _string_list(record.get("instanceOf"), f"concepts.{concept_id}.instanceOf"):
            hierarchy.add((str(concept_id), parent))

    relations: set[str] = set()
    attributes: set[str] = set()
    qualifiers: set[str] = set()
    directions: Counter[str] = Counter()
    attribute_types: Counter[str] = Counter()
    qualifier_types: Counter[str] = Counter()
    relation_occurrences = attribute_occurrences = qualifier_values = 0
    for entity_id, value in entities.items():
        record = _mapping(value, f"entities.{entity_id}")
        entity_names[str(record.get("name", ""))].append(str(entity_id))
        raw_attributes = record.get("attributes", [])
        raw_relations = record.get("relations", [])
        if not isinstance(raw_attributes, list) or not isinstance(raw_relations, list):
            raise ValueError(f"Entity '{entity_id}' attributes/relations must be lists.")
        for attribute in raw_attributes:
            item = _mapping(attribute, f"entities.{entity_id}.attributes")
            key = str(item.get("key", ""))
            if key:
                attributes.add(key)
            attribute_occurrences += 1
            value_record = _mapping(item.get("value"), "attribute.value")
            attribute_types[str(value_record.get("type", "missing"))] += 1
            count = _collect_qualifiers(
                item.get("qualifiers"), qualifiers, qualifier_types
            )
            qualifier_values += count
        for relation in raw_relations:
            item = _mapping(relation, f"entities.{entity_id}.relations")
            predicate = str(item.get("predicate", ""))
            if predicate:
                relations.add(predicate)
            directions[str(item.get("direction", "missing"))] += 1
            relation_occurrences += 1
            count = _collect_qualifiers(
                item.get("qualifiers"), qualifiers, qualifier_types
            )
            qualifier_values += count

    cycle_count, cycle_nodes = _hierarchy_cycles(set(concepts), hierarchy)
    return KqaProKbResources(
        concept_ids=frozenset(str(item) for item in concepts),
        entity_ids=frozenset(str(item) for item in entities),
        concept_name_to_ids={key: tuple(sorted(value)) for key, value in sorted(concept_names.items())},
        entity_name_to_ids={key: tuple(sorted(value)) for key, value in sorted(entity_names.items())},
        relation_names=frozenset(relations),
        attribute_names=frozenset(attributes),
        qualifier_names=frozenset(qualifiers),
        hierarchy_edges=tuple(sorted(hierarchy)),
        relation_direction_occurrences=dict(sorted(directions.items())),
        attribute_type_occurrences=dict(sorted(attribute_types.items())),
        qualifier_type_occurrences=dict(sorted(qualifier_types.items())),
        relation_occurrences=relation_occurrences,
        attribute_occurrences=attribute_occurrences,
        qualifier_value_occurrences=qualifier_values,
        hierarchy_cycle_count=cycle_count,
        hierarchy_cycle_nodes=cycle_nodes,
        source_hash=_sha256(kb_path),
    )


def build_audit_rdf_mapping(kb: KqaProKbResources) -> RdfBackendMapping:
    """Build an in-memory compiler probe, never a persisted DatasetBundle mapping."""

    terms: dict[str, dict[str, str]] = {}
    tokens = {"node_labels": {}, "edge_labels": {}, "properties": {}}

    def add(token: str, token_kind: str, kind: str) -> None:
        term_id = f"audit:{kind}:{hashlib.sha256(token.encode('utf-8')).hexdigest()[:20]}"
        tokens[token_kind][token] = term_id
        terms[term_id] = {
            "kind": kind,
            "representation": f"urn:kqapro-audit:{kind}:{hashlib.sha256(token.encode('utf-8')).hexdigest()}",
        }

    for name, ids in sorted(kb.concept_name_to_ids.items()):
        if name and len(ids) == 1:
            add(name, "node_labels", "class")
    for name in sorted(kb.relation_names):
        add(name, "edge_labels", "relation")
    add("name", "properties", "property")
    artifact = {
        "mapping_id": "m13b-in-memory-compiler-probe",
        "version": "1",
        "backends": {
            "fuseki": {
                "namespace": "urn:kqapro-audit:",
                "prefixes": {"kqa": "urn:kqapro-audit:"},
                "compiler_tokens": tokens,
            }
        },
        "term_mappings": {"fuseki": terms},
    }
    return RdfBackendMapping.from_artifact(artifact)


def convert_question_for_audit(
    question: Mapping[str, Any],
    split: str,
    question_index: int,
    kb: KqaProKbResources,
    *,
    rdf_mapping: RdfBackendMapping,
    backend_profiles: Sequence[BackendCapabilityProfile],
) -> ConversionResult:
    """Conservatively convert a paired KoPL/SPARQL record through existing XGAP."""

    question_id = f"{split}-{question_index:06d}"
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "query_id": question_id,
        "split": split,
        "status": "unsupported",
    }
    if split == "test":
        return _unsupported(base, "missing_gold_annotations", "public test contains question and choices only")

    try:
        steps = _program_steps(question.get("program"))
    except (TypeError, ValueError) as error:
        return _unsupported(base, "malformed_program", str(error))
    operators = tuple(step["function"] for step in steps)
    base["kopl_operators"] = list(operators)
    base["program_size"] = len(steps)
    base["program_dependency_count"] = sum(len(step["dependencies"]) for step in steps)
    base["terminal_operator"] = operators[-1] if operators else None

    sparql = question.get("sparql")
    if not isinstance(sparql, str) or not sparql.strip():
        return _unsupported(base, "missing_gold_sparql", "gold SPARQL field is absent")

    reason = _operator_rejection_reason(operators)
    if reason is not None:
        return _unsupported(base, reason[0], reason[1])
    if not _sparql_has_supported_path_surface(sparql):
        return _unsupported(
            base,
            "unsupported_sparql_fragment",
            "gold SPARQL uses a non-path surface construct",
        )
    try:
        query, path_metadata = _linear_path_query(steps, kb)
        reference_plan = lower_to_logical_plan(query)
        reference_index = index_logical_plan(reference_plan)
        planning_plan, _, _ = plan_from_compiler_input(
            query, backend_id="neo4j", language="cypher"
        )
        planning_index = index_logical_plan(planning_plan)
        cypher = compile_cypher(query, profile=_profile(backend_profiles, "neo4j"))
        sparql_artifact = compile_sparql(
            query,
            profile=_profile(backend_profiles, "fuseki"),
            backend_mapping=rdf_mapping,
        )
    except AuditUnsupportedError as error:
        return _unsupported(base, error.reason, error.detail)
    except (TypeError, ValueError, NotImplementedError) as error:
        return _unsupported(base, "xgap_conversion_failure", str(error))

    root = planning_index.root_state(question_id)
    bound = conservative_state_space_bound(
        root, backend_profiles, ExchangeCatalog()
    )
    placement_counts = [count for _, count in bound.placement_choice_counts]
    planning_supported = all(count > 0 for count in placement_counts)
    if not planning_supported:
        return _unsupported(base, "unsupported_backend_capability", "one or more logical operators have no native placement")
    placement_product = 1
    for count in placement_counts:
        placement_product *= count

    record = {
        **base,
        "status": "planning-supported",
        "support_classification": "planning-supported",
        "reference_source": "paired_gold_kopl_and_sparql",
        "conversion_ambiguity": False,
        "semantic_supported": True,
        "native_compilation_feasible": True,
        "currently_executable_with_repository_dataset": False,
        "planning_supported": True,
        "answer": question.get("answer"),
        **path_metadata,
        "operators": [item.operator_name for item in reference_index.operators],
        "logical_operator_count": len(reference_index.operators),
        "logical_dependency_count": len(reference_index.dependencies),
        "logical_plan_size": len(reference_index.operators) + len(reference_index.dependencies),
        "planning_operators": [item.operator_name for item in planning_index.operators],
        "planning_operator_count": len(planning_index.operators),
        "planning_dependency_count": len(planning_index.dependencies),
        "planning_q": len(planning_index.operators) + len(planning_index.dependencies),
        "backend_compiler_artifacts": {
            "neo4j": cypher.language,
            "fuseki": sparql_artifact.language,
        },
        "backend_placement_choices_per_operator": placement_counts,
        "unconstrained_placement_product": placement_product,
        "backend_local_physical_realizations": len(backend_profiles),
        "cross_backend_realizations": 0,
        "conservative_state_space_bound": bound.value,
        "oracle_compatible": bound.value <= ORACLE_STATE_LIMIT,
        "execution_blocker": "KQA Pro DatasetBundle loaders and final backend mappings are not implemented",
    }
    return ConversionResult(record, True)


class AuditUnsupportedError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _linear_path_query(
    steps: Sequence[Mapping[str, Any]], kb: KqaProKbResources
) -> tuple[PathPatternQuery, dict[str, Any]]:
    if not steps or steps[0]["function"] != "Find" or steps[-1]["function"] != "What":
        raise AuditUnsupportedError(
            "unsupported_path_seed_or_projection",
            "audited PathPatternQuery requires Find ... What",
        )
    for index, step in enumerate(steps):
        expected = [] if index == 0 else [index - 1]
        if step["dependencies"] != expected:
            raise AuditUnsupportedError(
                "unsupported_branching_dependencies",
                f"step {index} dependencies are not a single linear predecessor",
            )
    find_inputs = steps[0]["inputs"]
    if len(find_inputs) != 1 or find_inputs[0] not in kb.node_name_to_ids:
        raise AuditUnsupportedError(
            "missing_entity_mapping", find_inputs[0] if find_inputs else "missing Find input"
        )

    node_constraints: dict[int, list[Condition]] = defaultdict(list)
    node_constraints[0].append(PropertyEquals(NodeRef(1), "name", find_inputs[0]))
    relation_labels: list[str] = []
    directions: list[str] = []
    program_node = 0
    for index, step in enumerate(steps[1:-1], 1):
        function = step["function"]
        inputs = step["inputs"]
        if function == "Relate":
            if len(inputs) != 2 or inputs[1] not in {"forward", "backward"}:
                raise AuditUnsupportedError("malformed_program", f"invalid Relate inputs at step {index}")
            if inputs[0] not in kb.relation_names:
                raise AuditUnsupportedError("missing_relation_mapping", inputs[0])
            relation_labels.append(inputs[0])
            directions.append(inputs[1])
            program_node += 1
        elif function == "FilterConcept":
            if len(inputs) != 1:
                raise AuditUnsupportedError("malformed_program", f"invalid FilterConcept inputs at step {index}")
            concept_ids = kb.concept_name_to_ids.get(inputs[0], ())
            if not concept_ids:
                raise AuditUnsupportedError("missing_concept_mapping", inputs[0])
            if len(concept_ids) != 1:
                raise AuditUnsupportedError("ambiguous_concept_mapping", inputs[0])
            node_constraints[program_node].append(
                LabelEquals(NodeRef(program_node + 1), inputs[0])
            )
        else:
            raise AuditUnsupportedError("unsupported_operator", function)
    if not relation_labels:
        raise AuditUnsupportedError(
            "unsupported_focus_only_path_pattern", "PathPatternQuery requires at least one pattern edge"
        )
    if len(set(directions)) != 1:
        raise AuditUnsupportedError(
            "unsupported_mixed_direction_path", ",".join(directions)
        )

    edge_count = len(relation_labels)
    if directions[0] == "backward":
        relation_labels.reverse()
        remapped: dict[int, list[Condition]] = defaultdict(list)
        for old_position, constraints in node_constraints.items():
            new_position = edge_count - old_position
            for condition in constraints:
                if isinstance(condition, LabelEquals):
                    remapped[new_position].append(
                        LabelEquals(NodeRef(new_position + 1), condition.value)
                    )
                elif isinstance(condition, PropertyEquals):
                    remapped[new_position].append(
                        PropertyEquals(
                            NodeRef(new_position + 1),
                            condition.property_name,
                            condition.value,
                        )
                    )
                else:
                    raise AssertionError(type(condition).__name__)
        node_constraints = remapped

    source, source_remainder = _endpoint_pattern(node_constraints.pop(0, []), "source")
    target, target_remainder = _endpoint_pattern(
        node_constraints.pop(edge_count, []), "target"
    )
    remaining = [*source_remainder, *target_remainder]
    for position in sorted(node_constraints):
        remaining.extend(node_constraints[position])
    condition: Condition | None = None
    if len(remaining) == 1:
        condition = remaining[0]
    elif remaining:
        condition = And(*remaining)

    expressions = [Rel(EdgePattern(label=label, direction=Direction.OUT)) for label in relation_labels]
    expression = expressions[0]
    for child in expressions[1:]:
        expression = Seq(expression, child)
    query = PathPatternQuery(
        path_var=Var("path"),
        source=source,
        expr=expression,
        target=target,
        selector=Selector(SelectorKind.ALL),
        restrictor=RecursiveMode.WALK,
        condition=condition,
    )
    return query, {
        "path_edge_count": edge_count,
        "program_direction": directions[0],
        "physical_edge_labels": relation_labels,
        "answer_endpoint": "target" if directions[0] == "forward" else "source",
    }


def _endpoint_pattern(
    constraints: Sequence[Condition], variable: str
) -> tuple[NodePattern, tuple[Condition, ...]]:
    label: str | None = None
    properties: dict[str, object] = {}
    remainder: list[Condition] = []
    for condition in constraints:
        if isinstance(condition, LabelEquals) and label is None:
            label = condition.value
        elif isinstance(condition, PropertyEquals) and condition.property_name not in properties:
            properties[condition.property_name] = condition.value
        else:
            remainder.append(condition)
    return NodePattern(var=Var(variable), label=label, properties=properties), tuple(remainder)


def _operator_rejection_reason(operators: Sequence[str]) -> tuple[str, str] | None:
    if not operators:
        return "malformed_program", "empty KoPL program"
    if any(operator in QUALIFIER_OPERATORS for operator in operators):
        return "unsupported_qualifier_semantics", "KoPL fact qualifiers"
    if "Count" in operators:
        return "unsupported_aggregation", "Count"
    if any(operator in ORDERING_OPERATORS for operator in operators):
        return "unsupported_ordering", operators[-1]
    if any(operator in VERIFY_OPERATORS for operator in operators):
        return "unsupported_comparison", operators[-1]
    if any(operator in SET_OPERATORS for operator in operators):
        return "unsupported_set_operation", "And/Or entity-set semantics"
    if any(operator in TYPED_FILTER_OPERATORS for operator in operators):
        return "unsupported_typed_value_semantics", "KQA quantity/date/year representation"
    if any(operator in SCALAR_PROJECTION_OPERATORS for operator in operators):
        return "unsupported_scalar_projection", operators[-1]
    if any(operator in RELATION_PROJECTION_OPERATORS for operator in operators):
        return "unsupported_relation_projection", operators[-1]
    if "FilterStr" in operators:
        return "unsupported_attribute_representation", "KQA attributes are value-node facts, not scalar node properties"
    unsupported = sorted(set(operators) - LINEAR_PATH_OPERATORS)
    if unsupported:
        return "unsupported_operator", ",".join(unsupported)
    return None


def _sparql_has_supported_path_surface(sparql: str) -> bool:
    upper = sparql.upper()
    return (
        upper.count("SELECT") == 1
        and "WHERE" in upper
        and not any(
            marker in upper
            for marker in (" UNION ", "FILTER", "OPTIONAL", "ORDER BY", "COUNT(", "ASK ")
        )
        and "<PRED:FACT_" not in upper
    )


def analyze_sparql(sparql: str) -> tuple[int, tuple[str, ...]]:
    upper = sparql.upper()
    triple_count = len(re.findall(r"\s\.\s", sparql))
    features: set[str] = set()
    where = sparql[sparql.find("{") + 1 : sparql.rfind("}")] if "{" in sparql else sparql
    variables = re.findall(r"\?[A-Za-z_][A-Za-z0-9_]*", where)
    if any(count > 1 for count in Counter(variables).values()):
        features.add("joins")
    for marker, name in (
        ("FILTER", "filters"),
        ("OPTIONAL", "optional"),
        (" UNION ", "union"),
        ("ORDER BY", "ordering"),
        ("COUNT(", "aggregation"),
    ):
        if marker in upper:
            features.add(name)
    if upper.count("SELECT") > 1:
        features.add("subqueries")
    if "<PRED:FACT_" in upper:
        features.add("qualifier_fact_reification")
    if re.search(r">\s*(?:/|\||\*|\+)\s*<", sparql):
        features.add("property_paths")
    if "FILTER" in upper and re.search(r"(?:!=|<=|>=|\s<\s|\s>\s|\s=\s)", upper):
        features.add("comparison")
    return triple_count, tuple(sorted(features))


def run_audit(
    dataset_root: str | Path,
    output_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    repository = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    kb = load_kb_resources(dataset / "kb.json")
    rdf_mapping = build_audit_rdf_mapping(kb)
    registry.load_descriptors(repository / "descriptors" / "backends")
    profiles = tuple(registry.get_capability_profile(name) for name in ("fuseki", "neo4j"))
    accumulator = AuditAccumulator()
    supported_path = output / "supported_questions.jsonl"
    unsupported_path = output / "unsupported_questions.jsonl"
    oracle_path = output / "oracle_candidates.jsonl"
    file_records: dict[str, dict[str, Any]] = {}

    with supported_path.open("w", encoding="utf-8") as supported_file, unsupported_path.open(
        "w", encoding="utf-8"
    ) as unsupported_file, oracle_path.open("w", encoding="utf-8") as oracle_file:
        for split, filename in DATASET_FILES.items():
            path = dataset / filename
            questions = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(questions, list):
                raise ValueError(f"{filename} must contain a JSON array.")
            file_records[split] = {
                "file": filename,
                "format": "JSON array",
                "question_count": len(questions),
                "gold_annotations": split != "test",
                "sha256": _sha256(path),
            }
            for index, question in enumerate(questions):
                if not isinstance(question, Mapping):
                    raise ValueError(f"{filename} question {index} must be an object.")
                accumulator.total += 1
                if split != "test":
                    accumulator.gold_available += 1
                    steps = _program_steps(question.get("program"))
                    operators = tuple(step["function"] for step in steps)
                    accumulator.operator_occurrences.update(operators)
                    accumulator.operator_questions.update(set(operators))
                    accumulator.terminal_operators.update([operators[-1]])
                    accumulator.program_sizes.append(len(steps))
                    dependency_count = sum(len(step["dependencies"]) for step in steps)
                    accumulator.program_complexities.append(len(steps) + dependency_count)
                    sparql = str(question.get("sparql", ""))
                    triple_count, features = analyze_sparql(sparql)
                    accumulator.sparql_triple_counts.append(triple_count)
                    accumulator.sparql_features.update(features)
                result = convert_question_for_audit(
                    question,
                    split,
                    index,
                    kb,
                    rdf_mapping=rdf_mapping,
                    backend_profiles=profiles,
                )
                target = supported_file if result.supported else unsupported_file
                target.write(_canonical_json(result.record) + "\n")
                counter = accumulator.by_split[split]  # type: ignore[index]
                counter["total"] += 1
                if result.supported:
                    accumulator.supported += 1
                    counter["supported"] += 1
                    accumulator.operator_supported_questions.update(
                        set(result.record["kopl_operators"])
                    )
                    accumulator.reference_operator_counts.append(result.record["logical_operator_count"])
                    accumulator.reference_dependency_counts.append(result.record["logical_dependency_count"])
                    accumulator.planning_operator_counts.append(result.record["planning_operator_count"])
                    accumulator.planning_dependency_counts.append(result.record["planning_dependency_count"])
                    accumulator.planning_complexities.append(result.record["planning_q"])
                    accumulator.path_lengths.append(result.record["path_edge_count"])
                    accumulator.placement_products.append(result.record["unconstrained_placement_product"])
                    accumulator.state_space_bounds.append(result.record["conservative_state_space_bound"])
                    if result.record["oracle_compatible"]:
                        oracle_file.write(
                            _canonical_json(
                                {
                                    "schema_version": SCHEMA_VERSION,
                                    "query_id": result.record["query_id"],
                                    "split": split,
                                    "planning_q": result.record["planning_q"],
                                    "operator_count": result.record["planning_operator_count"],
                                    "dependency_count": result.record["planning_dependency_count"],
                                    "path_edge_count": result.record["path_edge_count"],
                                    "conservative_state_space_bound": result.record["conservative_state_space_bound"],
                                    "backend_local_physical_realizations": result.record["backend_local_physical_realizations"],
                                    "oracle_state_limit": ORACLE_STATE_LIMIT,
                                }
                            )
                            + "\n"
                        )
                else:
                    counter["unsupported"] += 1
                    accumulator.unsupported_reasons.update([result.record["reason"]])

    ontology_summary = _ontology_summary(kb)
    kopl_statistics = _kopl_statistics(accumulator)
    sparql_statistics = _sparql_statistics(accumulator)
    complexity = _complexity_distribution(accumulator)
    oracle_count = sum(1 for line in oracle_path.read_text(encoding="utf-8").splitlines() if line)
    summary = _audit_summary(
        accumulator,
        file_records,
        kb,
        oracle_count,
    )
    _write_json(output / "ontology_summary.json", ontology_summary)
    _write_json(output / "kopl_operator_statistics.json", kopl_statistics)
    _write_json(output / "sparql_statistics.json", sparql_statistics)
    _write_json(output / "complexity_distribution.json", complexity)
    _write_json(output / "audit_summary.json", summary)
    return summary


def _ontology_summary(kb: KqaProKbResources) -> dict[str, Any]:
    duplicate_concepts = sum(len(ids) > 1 for ids in kb.concept_name_to_ids.values())
    duplicate_entities = sum(len(ids) > 1 for ids in kb.entity_name_to_ids.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "classes": len(kb.concept_ids),
        "relations": len(kb.relation_names),
        "attributes": len(kb.attribute_names),
        "qualifier_keys": len(kb.qualifier_names),
        "hierarchy_edges": len(kb.hierarchy_edges),
        "entities": len(kb.entity_ids),
        "relation_fact_occurrences": kb.relation_occurrences,
        "attribute_fact_occurrences": kb.attribute_occurrences,
        "qualifier_value_occurrences": kb.qualifier_value_occurrences,
        "relation_direction_occurrences": dict(kb.relation_direction_occurrences),
        "attribute_value_types": dict(kb.attribute_type_occurrences),
        "qualifier_value_types": dict(kb.qualifier_type_occurrences),
        "duplicate_concept_names": duplicate_concepts,
        "duplicate_entity_names": duplicate_entities,
        "hierarchy_cycle_count": kb.hierarchy_cycle_count,
        "hierarchy_cycle_nodes": kb.hierarchy_cycle_nodes,
        "source_sha256": kb.source_hash,
        "artifact_feasibility": {
            "ontology_yaml": "constructible_after_identifier_and_transitive_type_policy",
            "aliases_yaml": "not_available_from_canonical_names_alone",
            "entity_catalog": "constructible_from_kb_json",
            "schema_snapshot_json": "constructible_with_explicit_observed-schema_scope",
            "relation_domain_range_schema": "not_provided",
            "final_backend_mapping": "not_created_in_m13b",
        },
    }


def _kopl_statistics(accumulator: AuditAccumulator) -> dict[str, Any]:
    records = {}
    for operator in sorted(set(KOPL_OPERATOR_MAPPING) | set(accumulator.operator_occurrences)):  # type: ignore[arg-type]
        mapping, status = KOPL_OPERATOR_MAPPING.get(operator, ("none", "unsupported"))
        questions = accumulator.operator_questions[operator]  # type: ignore[index]
        supported = accumulator.operator_supported_questions[operator]  # type: ignore[index]
        records[operator] = {
            "occurrences": accumulator.operator_occurrences[operator],  # type: ignore[index]
            "questions": questions,
            "supported_questions": supported,
            "supported_question_ratio": supported / questions if questions else 0.0,
            "xgap_mapping": mapping,
            "status": status,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "train and val gold programs",
        "operator_count": len(records),
        "operators": records,
        "terminal_operator_questions": dict(sorted(accumulator.terminal_operators.items())),  # type: ignore[union-attr]
    }


def _sparql_statistics(accumulator: AuditAccumulator) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "train and val gold SPARQL",
        "query_count": accumulator.gold_available,
        "triple_patterns": _distribution(accumulator.sparql_triple_counts),
        "feature_question_counts": dict(sorted(accumulator.sparql_features.items())),  # type: ignore[union-attr]
        "method": "deterministic lexical audit of the official generated SPARQL surface",
        "limitations": [
            "Triple-pattern counts use statement terminators and treat bracketed fact reification as one statement.",
            "The audit is not a general SPARQL parser.",
        ],
    }


def _complexity_distribution(accumulator: AuditAccumulator) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "definition": "Q(u)=|Omega_u^gold|+|D_u^gold|",
        "gold_kopl_programs": {
            "program_steps": _distribution(accumulator.program_sizes),
            "operator_plus_dependency_proxy": _distribution(accumulator.program_complexities),
            "note": "KoPL syntax proxy only; unsupported programs are not XGAP LogicalPlans.",
        },
        "reference_logical_plans": {
            "operator_count": _distribution(accumulator.reference_operator_counts),
            "dependency_count": _distribution(accumulator.reference_dependency_counts),
            "q": _sum_distribution(
                accumulator.reference_operator_counts, accumulator.reference_dependency_counts
            ),
        },
        "m11_planning_logical_plans": {
            "operator_count": _distribution(accumulator.planning_operator_counts),
            "dependency_count": _distribution(accumulator.planning_dependency_counts),
            "q": _distribution(accumulator.planning_complexities),
            "path_edge_count": _distribution(accumulator.path_lengths),
        },
        "physical_feasibility": {
            "backend_ids": ["fuseki", "neo4j"],
            "exchange_catalog": "empty",
            "unconstrained_placement_product": _distribution(accumulator.placement_products),
            "backend_local_complete_realizations_per_query": 2,
            "cross_backend_complete_realizations_per_query": 0,
            "conservative_state_space_bound": _distribution(accumulator.state_space_bounds),
        },
    }


def _audit_summary(
    accumulator: AuditAccumulator,
    files: Mapping[str, Mapping[str, Any]],
    kb: KqaProKbResources,
    oracle_count: int,
) -> dict[str, Any]:
    gold_unsupported = accumulator.gold_available - accumulator.supported
    by_split = {}
    for split, counter in sorted(accumulator.by_split.items()):  # type: ignore[union-attr]
        by_split[split] = {
            **dict(counter),
            "supported_ratio": counter["supported"] / counter["total"] if counter["total"] else 0.0,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M13-B KQA Pro Paper Artifact Feasibility Audit",
        "benchmark_integration_complete": False,
        "recommendation": "unsuitable",
        "recommendation_scope": "primary current XGAP end-to-end/physical-planning benchmark",
        "source": {
            "official_repository_url": OFFICIAL_REPOSITORY_URL,
            "official_repository_revision": OFFICIAL_REPOSITORY_REVISION,
            "official_dataset_url": OFFICIAL_DATASET_URL,
            "official_dataset_url_status": "link_did_not_exist_at_audit_time",
            "mirror_url": MIRROR_DATASET_URL,
            "mirror_revision": MIRROR_REVISION,
            "dataset_license": OFFICIAL_DATASET_LICENSE,
            "mirror_license_metadata_conflict": "mirror card says MIT; official repository README says CC BY-SA 4.0",
            "files": dict(files),
            "kb": {"file": "kb.json", "sha256": kb.source_hash},
        },
        "totals": {
            "public_questions": accumulator.total,
            "gold_available_questions": accumulator.gold_available,
            "supported_questions": accumulator.supported,
            "unsupported_questions": accumulator.total - accumulator.supported,
            "gold_available_unsupported_questions": gold_unsupported,
            "supported_ratio_public": accumulator.supported / accumulator.total,
            "supported_ratio_gold_available": accumulator.supported / accumulator.gold_available,
            "native_compilation_feasible_questions": accumulator.supported,
            "currently_executable_with_repository_dataset": 0,
            "planning_supported_questions": accumulator.supported,
            "oracle_compatible_questions": oracle_count,
        },
        "by_split": by_split,
        "unsupported_reasons": dict(sorted(accumulator.unsupported_reasons.items())),  # type: ignore[union-attr]
        "support_definition": {
            "fragment": "linear Find-(Relate-FilterConcept)+-What with uniform relation direction",
            "production_semantics_modified": False,
            "gold_pairing": "KoPL supplies dependency structure; SPARQL supplies a required compatible surface guard",
            "compiler_probe_mapping": "ephemeral in-memory IRIs only; not a final DatasetBundle mapping",
            "execution_claim": "native compilation feasibility only; no KQA Pro loader or live execution",
        },
        "cost_model_feasibility": {
            "calibration": "supported train subset after backend integration",
            "evaluation": "supported val subset after backend integration",
            "online_stream": "deterministic supported train/val order after a frozen split policy",
            "d0_measurements_collected": False,
            "blockers": [
                "No final Neo4j/RDF mapping or KQA Pro loader is present.",
                "No live KQA Pro execution measurements were collected.",
                "The supported planning fragment has limited structural diversity.",
            ],
        },
        "ambiguity_feasibility": {
            "gold_reference_available": "train_val_only",
            "ontology_hierarchy_available": True,
            "public_alias_resource_available": False,
            "ambiguity_labels_generated": False,
            "strategy": "future ontology-neighborhood candidates around gold concept/relation slots",
        },
    }


def _program_steps(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("program must be a non-empty list")
    result = []
    for index, raw_step in enumerate(value):
        step = _mapping(raw_step, f"program[{index}]")
        function = step.get("function")
        dependencies = step.get("dependencies")
        inputs = step.get("inputs")
        if not isinstance(function, str) or not function:
            raise ValueError(f"program[{index}].function must be non-empty")
        if not isinstance(dependencies, list) or not all(isinstance(item, int) for item in dependencies):
            raise ValueError(f"program[{index}].dependencies must be integer indices")
        if any(item < 0 or item >= index for item in dependencies):
            raise ValueError(f"program[{index}] has a non-preceding dependency")
        if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
            raise ValueError(f"program[{index}].inputs must be strings")
        result.append(
            {"function": function, "dependencies": list(dependencies), "inputs": list(inputs)}
        )
    return tuple(result)


def _profile(
    profiles: Sequence[BackendCapabilityProfile], backend_id: str
) -> BackendCapabilityProfile:
    for profile in profiles:
        if profile.backend_id == backend_id:
            return profile
    raise ValueError(f"Missing backend profile '{backend_id}'.")


def _collect_qualifiers(
    raw: object, names: set[str], types: Counter[str]
) -> int:
    qualifiers = _mapping(raw, "qualifiers")
    count = 0
    for key, values in qualifiers.items():
        names.add(str(key))
        if not isinstance(values, list):
            raise ValueError("qualifier values must be lists")
        for value in values:
            record = _mapping(value, "qualifier.value")
            types[str(record.get("type", "missing"))] += 1
            count += 1
    return count


def _hierarchy_cycles(
    nodes: set[str], edges: set[tuple[str, str]]
) -> tuple[int, int]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for child, parent in edges:
        if parent in nodes:
            adjacency[child].append(parent)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    cyclic_components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            has_self_edge = len(component) == 1 and (component[0], component[0]) in edges
            if len(component) > 1 or has_self_edge:
                cyclic_components.append(tuple(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return len(cyclic_components), sum(len(item) for item in cyclic_components)


def _unsupported(base: Mapping[str, Any], reason: str, detail: str) -> ConversionResult:
    return ConversionResult({**base, "reason": reason, "detail": detail}, False)


def _distribution(values: Sequence[int] | None) -> dict[str, Any]:
    data = list(values or ())
    if not data:
        return {"count": 0, "mean": None, "median": None, "p90": None, "max": None, "histogram": {}}
    ordered = sorted(data)
    p90_index = min(len(ordered) - 1, max(0, int(0.9 * len(ordered) + 0.999999) - 1))
    return {
        "count": len(data),
        "mean": statistics.fmean(data),
        "median": statistics.median(data),
        "p90": ordered[p90_index],
        "max": max(data),
        "histogram": {str(key): value for key, value in sorted(Counter(data).items())},
    }


def _sum_distribution(
    left: Sequence[int] | None, right: Sequence[int] | None
) -> dict[str, Any]:
    return _distribution([a + b for a, b in zip(left or (), right or (), strict=True)])


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(value)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output-root", default="datasets/kqapro_audit")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    summary = run_audit(args.dataset_root, args.output_root, repo_root=args.repo_root)
    totals = summary["totals"]
    print(
        "M13-B KQA Pro audit complete: "
        f"{totals['supported_questions']} supported, "
        f"{totals['unsupported_questions']} unsupported."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
