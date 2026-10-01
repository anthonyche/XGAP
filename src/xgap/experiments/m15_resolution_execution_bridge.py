"""Bridge one sealed E3 resolution commit to registry-backed plan classes.

The bridge is deliberately capability-aware.  It enumerates every bounded
interpretation before checking whether the selected executable-family package
can preserve that interpretation.  Missing capabilities remain explicit
unavailable classes; they are never approximated, dropped, or sent to a
backend.  Only a class with complete registered binding coverage may receive
physical candidates.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_executable_family_registry import (
    compile_m15_executable_family_registry_file,
)
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime import (
    FederatedExecutionPlan,
    RuntimeNode,
    RuntimeNodeKind,
)


RESOLUTION_EXECUTION_BRIDGE_SPEC_SCHEMA_VERSION = (
    "m15-e4-resolution-execution-bridge-spec-v1"
)
RESOLUTION_EXECUTION_BRIDGE_PLAN_SCHEMA_VERSION = (
    "m15-e4-resolution-execution-bridge-plan-v1"
)
_SOURCE_ROLES = frozenset(
    {
        "intake_template",
        "resolution_catalog",
        "resolution_ontology",
        "executable_family_registry",
        "neo4j_full_window_template",
        "neo4j_bound_window_template",
    }
)
_EVIDENCE_KINDS = frozenset(
    {
        "binding_slot",
        "hard_constraint",
        "predicate_mapping_source",
        "predicate_mapping_target",
        "extension_template_pair",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")


class M15ResolutionExecutionBridgeError(ValueError):
    """Raised when a resolution commit or capability binding drifts."""


@dataclass(frozen=True)
class M15ResolutionExecutionBridgePlan:
    payload: Mapping[str, Any]
    plans: Mapping[str, FederatedExecutionPlan]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def plan_hash(self) -> str:
        return str(self.payload["bridge_plan_sha256"])


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15ResolutionExecutionBridgeError(f"{name} must be an object")
    return copy.deepcopy(dict(value))


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str] | frozenset[str],
) -> dict[str, Any]:
    result = _object(value, name=name)
    if set(result) != set(fields):
        raise M15ResolutionExecutionBridgeError(
            f"{name} fields do not match the v1 contract"
        )
    return result


def _array(value: object, *, name: str, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a nonempty array"
        raise M15ResolutionExecutionBridgeError(f"{name} must be {qualifier}")
    return copy.deepcopy(value)


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15ResolutionExecutionBridgeError(f"{name} is not a safe identifier")
    return value


def _safe_ids(
    value: object,
    *,
    name: str,
    allow_empty: bool = False,
) -> list[str]:
    result = [
        _safe_id(item, name=f"{name}[]")
        for item in _array(value, name=name, allow_empty=allow_empty)
    ]
    if len(result) != len(set(result)):
        raise M15ResolutionExecutionBridgeError(f"{name} must be unique")
    return result


def _json_value(value: object, *, name: str) -> Any:
    try:
        content_hash(value)
    except (TypeError, ValueError) as exc:
        raise M15ResolutionExecutionBridgeError(
            f"{name} must contain finite JSON"
        ) from exc
    return copy.deepcopy(value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M15ResolutionExecutionBridgeError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M15ResolutionExecutionBridgeError(f"{name} is not valid JSON") from exc
    return _object(value, name=name)


def _repo_file(root: Path, relative: object, *, name: str) -> tuple[str, Path]:
    if not isinstance(relative, str) or not relative:
        raise M15ResolutionExecutionBridgeError(f"{name} path is invalid")
    portable = Path(relative)
    if portable.is_absolute() or portable == Path(".") or ".." in portable.parts:
        raise M15ResolutionExecutionBridgeError(
            f"{name} path must be repository-relative"
        )
    candidate = root / portable
    if candidate.is_symlink():
        raise M15ResolutionExecutionBridgeError(f"{name} must not be a symlink")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise M15ResolutionExecutionBridgeError(f"{name} escapes repo_root") from exc
    if not resolved.is_file():
        raise M15ResolutionExecutionBridgeError(f"{name} is not a regular file")
    return portable.as_posix(), resolved


def _source_artifacts(
    value: object,
    *,
    repo_root: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, Path]]:
    raw = _strict_object(value, name="source_artifacts", fields=_SOURCE_ROLES)
    portable: dict[str, dict[str, str]] = {}
    paths: dict[str, Path] = {}
    for role in sorted(_SOURCE_ROLES):
        record = _strict_object(
            raw[role],
            name=f"source_artifacts.{role}",
            fields={"path", "sha256"},
        )
        expected = record["sha256"]
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise M15ResolutionExecutionBridgeError(
                f"source_artifacts.{role}.sha256 is invalid"
            )
        relative, path = _repo_file(
            repo_root,
            record["path"],
            name=f"source_artifacts.{role}",
        )
        if _file_sha256(path) != expected:
            raise M15ResolutionExecutionBridgeError(
                f"source artifact SHA-256 mismatch: {role}"
            )
        portable[role] = {"path": relative, "sha256": expected}
        paths[role] = path
    return portable, paths


def _resolution_commit_hash(output: Mapping[str, Any]) -> str:
    body = {
        "schema_version": output["resolution_commit_schema_version"],
        "program_id": output["program_id"],
        "hard_constraints_sha256": output["hard_constraints_sha256"],
        "resolved_entity_bindings": output["resolved_entity_bindings"],
        "candidate_sets": output["candidate_sets"],
    }
    return hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _hard_constraints(program: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    records: list[dict[str, Any]] = []
    expressions: dict[str, str] = {}
    for operator in _array(program.get("operators"), name="program.operators"):
        raw_operator = _object(operator, name="program operator")
        operator_id = _safe_id(raw_operator.get("operator_id"), name="operator_id")
        for constraint in _array(
            raw_operator.get("constraints"),
            name=f"{operator_id}.constraints",
            allow_empty=True,
        ):
            raw_constraint = _object(constraint, name="semantic constraint")
            if raw_constraint.get("policy") != "hard":
                continue
            constraint_id = _safe_id(
                raw_constraint.get("constraint_id"), name="constraint_id"
            )
            expression = raw_constraint.get("expression")
            if not isinstance(expression, str) or not expression:
                raise M15ResolutionExecutionBridgeError(
                    "hard constraint expression is invalid"
                )
            if constraint_id in expressions:
                raise M15ResolutionExecutionBridgeError(
                    "hard constraint IDs must be unique"
                )
            expressions[constraint_id] = expression
            records.append(
                {"operator_id": operator_id, "constraint": raw_constraint}
            )
    digest = hashlib.sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return digest, expressions


def _merge_bindings(
    target: dict[str, Any],
    additions: Mapping[str, Any],
    *,
    name: str,
) -> None:
    for slot_id, value in additions.items():
        _safe_id(slot_id, name=f"{name} slot")
        if slot_id in target and target[slot_id] != value:
            raise M15ResolutionExecutionBridgeError(
                f"{name} assigns conflicting values to '{slot_id}'"
            )
        target[slot_id] = _json_value(value, name=f"{name}.{slot_id}")


def _candidate_mappings(value: object) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for index, item in enumerate(_array(value, name="candidate_mappings")):
        raw = _strict_object(
            item,
            name=f"candidate_mappings[{index}]",
            fields={
                "hole_id",
                "hole_kind",
                "candidate_id",
                "semantic_parameters",
                "required_capabilities",
                "target_bindings",
            },
        )
        hole_id = _safe_id(raw["hole_id"], name="candidate hole_id")
        hole_kind = _safe_id(raw["hole_kind"], name="candidate hole_kind")
        if hole_kind not in {"entity", "predicate", "constraint", "type", "source"}:
            raise M15ResolutionExecutionBridgeError("candidate hole_kind is invalid")
        candidate_id = _safe_id(raw["candidate_id"], name="candidate_id")
        key = (hole_id, candidate_id)
        if key in result:
            raise M15ResolutionExecutionBridgeError(
                "candidate mappings must be unique"
            )
        result[key] = {
            "hole_id": hole_id,
            "hole_kind": hole_kind,
            "candidate_id": candidate_id,
            "semantic_parameters": _object(
                raw["semantic_parameters"], name="semantic_parameters"
            ),
            "required_capabilities": _safe_ids(
                raw["required_capabilities"], name="required_capabilities"
            ),
            "target_bindings": _object(
                raw["target_bindings"], name="target_bindings"
            ),
        }
        _json_value(result[key]["semantic_parameters"], name="semantic_parameters")
        _json_value(result[key]["target_bindings"], name="target_bindings")
    return result


def _validate_capability_evidence(
    records: object,
    *,
    package: Mapping[str, Any],
    repo_root: Path,
    source_paths: Mapping[str, Path],
) -> tuple[list[dict[str, str]], set[str]]:
    binding_slots = {
        item["slot_id"] for item in package["typed_semantic_program"]["binding_schema"]
    }
    hard = set(package["typed_semantic_program"]["hard_constraint_ids"])
    mapping_source = package["source_bindings"]["predicate_mapping"]
    _, mapping_path = _repo_file(
        repo_root,
        mapping_source["path"],
        name="family predicate mapping",
    )
    if _file_sha256(mapping_path) != mapping_source["sha256"]:
        raise M15ResolutionExecutionBridgeError(
            "family predicate mapping source drifted"
        )
    predicate_mapping = _regular_json(mapping_path, name="family predicate mapping")
    result: list[dict[str, str]] = []
    capability_ids: set[str] = set()
    for index, item in enumerate(_array(records, name="available_capabilities")):
        raw = _strict_object(
            item,
            name=f"available_capabilities[{index}]",
            fields={"capability_id", "evidence_kind", "evidence_id"},
        )
        capability_id = _safe_id(raw["capability_id"], name="capability_id")
        evidence_kind = _safe_id(raw["evidence_kind"], name="evidence_kind")
        evidence_id = _safe_id(raw["evidence_id"], name="evidence_id")
        if capability_id in capability_ids:
            raise M15ResolutionExecutionBridgeError(
                "available capability IDs must be unique"
            )
        if evidence_kind not in _EVIDENCE_KINDS:
            raise M15ResolutionExecutionBridgeError(
                f"unsupported capability evidence kind '{evidence_kind}'"
            )
        if evidence_kind == "binding_slot" and evidence_id not in binding_slots:
            raise M15ResolutionExecutionBridgeError(
                f"capability evidence binding slot '{evidence_id}' is absent"
            )
        if evidence_kind == "hard_constraint" and evidence_id not in hard:
            raise M15ResolutionExecutionBridgeError(
                f"capability evidence hard constraint '{evidence_id}' is absent"
            )
        if evidence_kind == "predicate_mapping_source" and predicate_mapping.get(
            "source_predicate"
        ) != evidence_id:
            raise M15ResolutionExecutionBridgeError(
                "predicate source capability evidence is invalid"
            )
        if evidence_kind == "predicate_mapping_target" and predicate_mapping.get(
            "target_predicate"
        ) != evidence_id:
            raise M15ResolutionExecutionBridgeError(
                "predicate target capability evidence is invalid"
            )
        if evidence_kind == "extension_template_pair":
            if evidence_id != "time-upper-bound":
                raise M15ResolutionExecutionBridgeError(
                    "extension template capability evidence is invalid"
                )
            expected_clause = "edge.occurred_on < date($occurred_on_lt)"
            full_text = source_paths["neo4j_full_window_template"].read_text(
                encoding="utf-8"
            )
            bound_text = source_paths["neo4j_bound_window_template"].read_text(
                encoding="utf-8"
            )
            if expected_clause not in full_text or expected_clause not in bound_text:
                raise M15ResolutionExecutionBridgeError(
                    "window extension templates do not enforce the upper bound"
                )
            if "$company_ids" in full_text or "$company_ids" not in bound_text:
                raise M15ResolutionExecutionBridgeError(
                    "window extension full/bound template roles are invalid"
                )
        capability_ids.add(capability_id)
        result.append(
            {
                "capability_id": capability_id,
                "evidence_kind": evidence_kind,
                "evidence_id": evidence_id,
            }
        )
    return sorted(result, key=lambda item: item["capability_id"]), capability_ids


def _render_window_template(
    template_path: Path,
    *,
    workload_id: str,
    transfer_predicate: str,
    path_shape: str,
    role: str,
) -> str:
    mapping = {
        "transfer_to_company": "TRANSFER_TO_COMPANY",
        "payment_to_company": "PAYMENT_TO_COMPANY",
    }
    if transfer_predicate not in mapping:
        raise M15ResolutionExecutionBridgeError(
            "window extension cannot compile the transfer predicate"
        )
    if path_shape != "direct":
        raise M15ResolutionExecutionBridgeError(
            "window extension supports only the direct path"
        )
    text = template_path.read_text(encoding="utf-8")
    compile_values = {
        "workload_token": workload_id.replace("-", "_").upper(),
        "workload_id": workload_id,
        "relationship_type": mapping[transfer_predicate],
        "path_quantifier": "",
    }
    tokens = set(re.findall(r"\{\{compile:([a-z][a-z0-9_]*)\}\}", text))
    if tokens != set(compile_values):
        raise M15ResolutionExecutionBridgeError(
            f"{role} window template compile-token set drifted"
        )
    for key, value in compile_values.items():
        text = text.replace(f"{{{{compile:{key}}}}}", value)
    expected_runtime = {
        "person_id",
        "occurred_on_gte",
        "occurred_on_lt",
        "amount_gte",
    }
    if role == "neo4j_bound":
        expected_runtime.add("company_ids")
    runtime = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", text))
    if runtime != expected_runtime:
        raise M15ResolutionExecutionBridgeError(
            f"{role} window template runtime-parameter set drifted"
        )
    return text


def _window_extended_plan(
    plan: FederatedExecutionPlan,
    *,
    semantic_class_id: str,
    workload_id: str,
    target_bindings: Mapping[str, Any],
    source_paths: Mapping[str, Path],
) -> FederatedExecutionPlan:
    upper = target_bindings.get("time-upper-bound")
    if not isinstance(upper, str) or not upper:
        raise M15ResolutionExecutionBridgeError(
            "window-executable class lacks time-upper-bound"
        )
    transfer_predicate = target_bindings.get("transfer-predicate")
    path_shape = target_bindings.get("path-shape")
    nodes: list[RuntimeNode] = []
    changed_roles: list[str] = []
    for node in plan.nodes:
        if node.kind not in {
            RuntimeNodeKind.REMOTE_QUERY,
            RuntimeNodeKind.REMOTE_BIND_QUERY,
        } or node.parameters.get("backend_id") != "neo4j":
            nodes.append(node)
            continue
        role = (
            "neo4j_full"
            if node.kind is RuntimeNodeKind.REMOTE_QUERY
            else "neo4j_bound"
        )
        template_role = f"{role}_window_template"
        rendered = _render_window_template(
            source_paths[template_role],
            workload_id=workload_id,
            transfer_predicate=str(transfer_predicate),
            path_shape=str(path_shape),
            role=role,
        )
        artifact = QueryArtifact.from_dict(node.parameters["artifact"])
        parameters = {**artifact.parameters, "occurred_on_lt": upper}
        extended = replace(
            artifact,
            artifact_id=f"{artifact.artifact_id}-window-e4",
            text=rendered,
            source_path=(
                "bridge-template:"
                + source_paths[template_role].name
                + ":"
                + _file_sha256(source_paths[template_role])
            ),
            parameters=parameters,
        )
        nodes.append(
            replace(
                node,
                parameters={**dict(node.parameters), "artifact": extended.to_dict()},
            )
        )
        changed_roles.append(role)
    if changed_roles not in (["neo4j_full"], ["neo4j_bound"]):
        raise M15ResolutionExecutionBridgeError(
            "physical plan did not expose one registered Neo4j template role"
        )
    return replace(
        plan,
        plan_id=f"{plan.plan_id}-window-e4",
        nodes=tuple(nodes),
        metadata={
            **dict(plan.metadata),
            "semantic_class_id": semantic_class_id,
            "time_upper_bound": upper,
            "window_template_extension": "m15-e4-registered-upper-bound-v1",
            "answer_oracle_used_for_construction": False,
            "paper_result": False,
        },
    )


def _physical_candidates(
    *,
    package: Mapping[str, Any],
    repo_root: Path,
    classes: list[dict[str, Any]],
    maximum_per_class: int,
    source_paths: Mapping[str, Path],
) -> tuple[list[dict[str, Any]], dict[str, FederatedExecutionPlan]]:
    executable = [item for item in classes if item["availability"] == "executable"]
    if not executable:
        return [], {}
    sources = package["source_bindings"]
    paths = {
        role: repo_root / record["path"] for role, record in sources.items()
    }
    template_root = paths["neo4j_full_template"].parent
    with tempfile.TemporaryDirectory(prefix="xgap-e4-bridge-") as temporary:
        base = generate_m15_parameterized_workload_bundle(
            workload_spec=paths["workload_spec"],
            query_template_spec=paths["query_template"],
            backend_template_root=template_root,
            destination=Path(temporary) / "base",
        )
        direct = generate_m15_direct_semantic_workload_bundle(
            base_bundle=base,
            catalog=paths["semantic_catalog"],
            mapping=paths["predicate_mapping"],
            policy=paths["semantic_workload_policy"],
            destination=Path(temporary) / "direct",
        )
        tasks = [
            dict(item)
            for view in (direct.training_selection_view, direct.heldout_selection_view)
            for item in view["semantic_tasks"]
        ]
        records: list[dict[str, Any]] = []
        plans: dict[str, FederatedExecutionPlan] = {}
        allowed_strategies = set(package["physical_planning"]["candidate_strategy_ids"])
        binding_slots = {
            item["slot_id"]
            for item in package["typed_semantic_program"]["binding_schema"]
        }
        for semantic_class in executable:
            bindings = semantic_class["target_binding_values"]
            if set(bindings) != binding_slots | {"time-upper-bound"}:
                raise M15ResolutionExecutionBridgeError(
                    "executable class does not bind every family and extension slot"
                )
            base_bindings = {
                key: value for key, value in bindings.items() if key in binding_slots
            }
            matching_tasks = [
                item for item in tasks if item["binding_values"] == base_bindings
            ]
            if len(matching_tasks) != 1:
                raise M15ResolutionExecutionBridgeError(
                    "executable class does not identify one registered semantic task"
                )
            task = matching_tasks[0]
            candidates = build_m15_parameterized_plan_candidates(
                direct.workload_bundle,
                query_id=task["executable_query_id"],
            )
            if not 1 <= len(candidates) <= maximum_per_class:
                raise M15ResolutionExecutionBridgeError(
                    "physical candidate count exceeds the bridge bound"
                )
            strategies = {
                str(item.plan.metadata["physical_strategy"]) for item in candidates
            }
            if strategies != allowed_strategies:
                raise M15ResolutionExecutionBridgeError(
                    "physical candidates are not the registered strategy set"
                )
            candidate_ids: list[str] = []
            for candidate in candidates:
                plan = _window_extended_plan(
                    candidate.plan,
                    semantic_class_id=semantic_class["semantic_class_id"],
                    workload_id=direct.workload_bundle.spec.workload_id,
                    target_bindings=bindings,
                    source_paths=source_paths,
                )
                if plan.plan_id in plans:
                    raise M15ResolutionExecutionBridgeError(
                        "physical plan IDs must be unique"
                    )
                plans[plan.plan_id] = plan
                candidate_ids.append(plan.plan_id)
                neo4j_template_role = (
                    "neo4j_bound_window_template"
                    if any(
                        node.kind is RuntimeNodeKind.REMOTE_BIND_QUERY
                        for node in plan.nodes
                    )
                    else "neo4j_full_window_template"
                )
                records.append(
                    {
                        "plan_id": plan.plan_id,
                        "physical_plan_sha256": content_hash(plan.to_dict()),
                        "semantic_class_id": semantic_class["semantic_class_id"],
                        "query_id": task["executable_query_id"],
                        "physical_strategy": plan.metadata["physical_strategy"],
                        "registered_template_roles": [
                            "fuseki_risk_template",
                            neo4j_template_role,
                        ],
                    }
                )
            semantic_class["physical_candidate_ids"] = sorted(candidate_ids)
    return sorted(records, key=lambda item: item["plan_id"]), plans


def compile_m15_resolution_execution_bridge(
    resolution_run: Mapping[str, Any],
    bridge_spec: Mapping[str, Any],
    *,
    repo_root: str | Path,
    bridge_spec_sha256: str | None = None,
) -> M15ResolutionExecutionBridgePlan:
    """Enumerate and capability-check one E3 resolution result."""

    root = Path(repo_root).resolve()
    if root.is_symlink() or not root.is_dir():
        raise M15ResolutionExecutionBridgeError("repo_root must be a directory")
    spec = _strict_object(
        bridge_spec,
        name="bridge spec",
        fields={
            "schema_version",
            "bridge_id",
            "source_artifacts",
            "resolution_contract",
            "candidate_mappings",
            "executable_family",
            "missing_capability_reasons",
            "limits",
            "automatic_retries",
            "paper_result",
        },
    )
    if spec["schema_version"] != RESOLUTION_EXECUTION_BRIDGE_SPEC_SCHEMA_VERSION:
        raise M15ResolutionExecutionBridgeError("bridge spec schema is unsupported")
    if spec["automatic_retries"] != 0 or spec["paper_result"] is not False:
        raise M15ResolutionExecutionBridgeError(
            "bridge must disable retry and remain paper_result=false"
        )
    bridge_id = _safe_id(spec["bridge_id"], name="bridge_id")
    source_artifacts, source_paths = _source_artifacts(
        spec["source_artifacts"], repo_root=root
    )

    family_spec = _strict_object(
        spec["executable_family"],
        name="executable_family",
        fields={
            "family_id",
            "family_compatibility_sha256",
            "available_capabilities",
            "physical_strategy_ids",
        },
    )
    registry_plan = compile_m15_executable_family_registry_file(
        source_paths["executable_family_registry"], repo_root=root
    ).to_dict()
    family_id = _safe_id(family_spec["family_id"], name="family_id")
    packages = [item for item in registry_plan["families"] if item["family_id"] == family_id]
    if len(packages) != 1:
        raise M15ResolutionExecutionBridgeError(
            "bridge family_id must identify one registry package"
        )
    package = packages[0]
    expected_family_hash = family_spec["family_compatibility_sha256"]
    if not isinstance(expected_family_hash, str) or not _SHA256.fullmatch(
        expected_family_hash
    ):
        raise M15ResolutionExecutionBridgeError(
            "family_compatibility_sha256 is invalid"
        )
    if package["typed_semantic_program"]["family_compatibility_sha256"] != (
        expected_family_hash
    ):
        raise M15ResolutionExecutionBridgeError("family compatibility hash mismatch")
    strategies = _safe_ids(
        family_spec["physical_strategy_ids"], name="physical_strategy_ids"
    )
    if strategies != package["physical_planning"]["candidate_strategy_ids"]:
        raise M15ResolutionExecutionBridgeError("physical strategy registry drift")
    capabilities, available_capabilities = _validate_capability_evidence(
        family_spec["available_capabilities"],
        package=package,
        repo_root=root,
        source_paths=source_paths,
    )

    run = _object(resolution_run, name="resolution run")
    if run.get("schema_version") != "m15-e3-semantic-intake-run-v1":
        raise M15ResolutionExecutionBridgeError("resolution run schema is unsupported")
    artifacts = _strict_object(
        run.get("artifacts"),
        name="resolution artifacts",
        fields={"intake_template_sha256", "catalog_sha256", "ontology_sha256"},
    )
    expected_resolution_artifacts = {
        "intake_template_sha256": source_artifacts["intake_template"]["sha256"],
        "catalog_sha256": source_artifacts["resolution_catalog"]["sha256"],
        "ontology_sha256": source_artifacts["resolution_ontology"]["sha256"],
    }
    if artifacts != expected_resolution_artifacts:
        raise M15ResolutionExecutionBridgeError("resolution artifact identity drift")
    intake = _object(run.get("intake"), name="intake result")
    goal_state = _object(run.get("goal_state"), name="goal_state")
    output = _object(goal_state.get("output"), name="resolution output")
    if goal_state.get("status") != "succeeded":
        raise M15ResolutionExecutionBridgeError(
            "only a succeeded resolution commit can be bridged"
        )

    resolution_contract = _strict_object(
        spec["resolution_contract"],
        name="resolution_contract",
        fields={
            "intake_template_id",
            "required_holes",
            "required_hard_constraints",
            "fixed_semantics",
        },
    )
    if intake.get("template_id") != resolution_contract["intake_template_id"]:
        raise M15ResolutionExecutionBridgeError("intake template ID drift")
    if intake.get("template_sha256") != source_artifacts["intake_template"]["sha256"]:
        raise M15ResolutionExecutionBridgeError("intake template hash drift")
    program = _object(intake.get("program"), name="semantic program")
    hard_hash, hard_expressions = _hard_constraints(program)
    if output.get("hard_constraints_sha256") != hard_hash:
        raise M15ResolutionExecutionBridgeError("hard constraint hash drift")
    if output.get("hard_constraints_preserved") is not True:
        raise M15ResolutionExecutionBridgeError("hard constraints were not preserved")
    if output.get("resolved_entity_bindings_hard") is not True:
        raise M15ResolutionExecutionBridgeError("entity binding is not hard")
    if output.get("resolution_commit_schema_version") != (
        "m15-e3-resolution-commit-v1"
    ) or output.get("resolution_commit_sha256") != _resolution_commit_hash(output):
        raise M15ResolutionExecutionBridgeError("resolution commit hash mismatch")

    requirements: set[str] = set()
    target_bindings: dict[str, Any] = {}
    declared_hard: dict[str, str] = {}
    hard_records = _array(
        resolution_contract["required_hard_constraints"],
        name="required_hard_constraints",
    )
    for index, item in enumerate(hard_records):
        raw = _strict_object(
            item,
            name=f"required_hard_constraints[{index}]",
            fields={
                "constraint_id",
                "expression",
                "required_capabilities",
                "target_bindings",
            },
        )
        constraint_id = _safe_id(raw["constraint_id"], name="constraint_id")
        expression = raw["expression"]
        if not isinstance(expression, str) or not expression:
            raise M15ResolutionExecutionBridgeError(
                "required hard-constraint expression is invalid"
            )
        if constraint_id in declared_hard:
            raise M15ResolutionExecutionBridgeError(
                "required hard constraints must be unique"
            )
        declared_hard[constraint_id] = expression
        requirements.update(
            _safe_ids(raw["required_capabilities"], name="hard capabilities")
        )
        _merge_bindings(
            target_bindings,
            _object(raw["target_bindings"], name="hard target_bindings"),
            name=f"hard constraint {constraint_id}",
        )
    if hard_expressions != declared_hard:
        raise M15ResolutionExecutionBridgeError(
            "semantic-program hard constraints differ from the bridge contract"
        )

    fixed_semantics = _object(
        resolution_contract["fixed_semantics"], name="fixed_semantics"
    )
    normalized_fixed: dict[str, Any] = {}
    for semantic_id, value in sorted(fixed_semantics.items()):
        _safe_id(semantic_id, name="fixed semantic ID")
        raw = _strict_object(
            value,
            name=f"fixed_semantics.{semantic_id}",
            fields={"value", "required_capabilities", "target_bindings"},
        )
        requirements.update(
            _safe_ids(raw["required_capabilities"], name="fixed capabilities")
        )
        _merge_bindings(
            target_bindings,
            _object(raw["target_bindings"], name="fixed target_bindings"),
            name=f"fixed semantic {semantic_id}",
        )
        normalized_fixed[semantic_id] = _json_value(raw["value"], name="fixed value")

    mappings = _candidate_mappings(spec["candidate_mappings"])
    candidate_sets = _array(output.get("candidate_sets"), name="candidate_sets")
    by_hole: dict[str, dict[str, Any]] = {}
    for item in candidate_sets:
        raw = _object(item, name="candidate set")
        hole_id = _safe_id(raw.get("hole_id"), name="candidate set hole_id")
        if hole_id in by_hole:
            raise M15ResolutionExecutionBridgeError("candidate-set holes must be unique")
        candidate_ids = _safe_ids(raw.get("candidate_ids"), name="candidate_ids")
        by_hole[hole_id] = {**raw, "candidate_ids": candidate_ids}
    required_holes = _safe_ids(
        resolution_contract["required_holes"], name="required_holes"
    )
    if set(by_hole) != set(required_holes):
        raise M15ResolutionExecutionBridgeError("resolution hole coverage drift")
    resolved_entities = _object(
        output.get("resolved_entity_bindings"), name="resolved_entity_bindings"
    )
    for hole_id, candidate_set in by_hole.items():
        for candidate_id in candidate_set["candidate_ids"]:
            mapping = mappings.get((hole_id, candidate_id))
            if mapping is None:
                raise M15ResolutionExecutionBridgeError(
                    f"candidate '{candidate_id}' has no bridge mapping"
                )
            if mapping["hole_kind"] != candidate_set.get("hole_kind"):
                raise M15ResolutionExecutionBridgeError(
                    "candidate mapping hole kind drift"
                )
        if candidate_set.get("hole_kind") == "entity":
            if (
                candidate_set.get("authoritative") is not True
                or len(candidate_set["candidate_ids"]) != 1
                or resolved_entities.get(hole_id) != candidate_set["candidate_ids"][0]
            ):
                raise M15ResolutionExecutionBridgeError(
                    "entity candidate must be one authoritative resolved binding"
                )
    observed_mapping_keys = {
        (hole_id, candidate_id)
        for hole_id, candidate_set in by_hole.items()
        for candidate_id in candidate_set["candidate_ids"]
    }
    if set(mappings) != observed_mapping_keys:
        raise M15ResolutionExecutionBridgeError(
            "bridge mappings must exactly cover the sealed candidate sets"
        )

    limits = _strict_object(
        spec["limits"],
        name="limits",
        fields={
            "maximum_raw_semantic_classes",
            "maximum_physical_candidates_per_class",
        },
    )
    maximum_classes = limits["maximum_raw_semantic_classes"]
    maximum_physical = limits["maximum_physical_candidates_per_class"]
    for name, value in (
        ("maximum_raw_semantic_classes", maximum_classes),
        ("maximum_physical_candidates_per_class", maximum_physical),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise M15ResolutionExecutionBridgeError(f"{name} must be positive")
    raw_count = 1
    for candidate_set in by_hole.values():
        raw_count *= len(candidate_set["candidate_ids"])
    if raw_count > maximum_classes:
        raise M15ResolutionExecutionBridgeError(
            "raw semantic cross-product exceeds maximum_raw_semantic_classes"
        )

    reason_map = _object(
        spec["missing_capability_reasons"], name="missing_capability_reasons"
    )
    if not all(
        isinstance(key, str) and isinstance(value, str) and value
        for key, value in reason_map.items()
    ):
        raise M15ResolutionExecutionBridgeError(
            "missing capability reasons are invalid"
        )
    interpretation_records: list[dict[str, Any]] = []
    hole_order = sorted(by_hole)
    for choices in itertools.product(
        *(sorted(by_hole[hole_id]["candidate_ids"]) for hole_id in hole_order)
    ):
        selected = {
            hole_id: candidate_id
            for hole_id, candidate_id in zip(hole_order, choices)
        }
        class_requirements = set(requirements)
        class_bindings = copy.deepcopy(target_bindings)
        semantic_parameters: dict[str, Any] = {}
        for hole_id, candidate_id in selected.items():
            mapping = mappings[(hole_id, candidate_id)]
            class_requirements.update(mapping["required_capabilities"])
            _merge_bindings(
                class_bindings,
                mapping["target_bindings"],
                name=f"candidate {candidate_id}",
            )
            semantic_parameters[hole_id] = mapping["semantic_parameters"]
        canonical = {
            "hard_constraints_sha256": hard_hash,
            "resolved_entity_bindings": resolved_entities,
            "fixed_semantics": normalized_fixed,
            "semantic_parameters": semantic_parameters,
        }
        equivalence_hash = content_hash(canonical)
        interpretation_records.append(
            {
                "interpretation_id": "m15-e4-interpretation-"
                + content_hash(
                    {
                        "resolution_commit_sha256": output[
                            "resolution_commit_sha256"
                        ],
                        "selected_candidate_ids": selected,
                    }
                )[:24],
                "semantic_equivalence_sha256": equivalence_hash,
                "selected_candidate_ids": selected,
                "target_binding_values": dict(sorted(class_bindings.items())),
                "semantic_parameters": semantic_parameters,
                "required_capability_ids": sorted(class_requirements),
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in interpretation_records:
        grouped.setdefault(record["semantic_equivalence_sha256"], []).append(record)
    semantic_classes: list[dict[str, Any]] = []
    for equivalence_hash, members in sorted(grouped.items()):
        representative = min(members, key=lambda item: item["interpretation_id"])
        for member in members[1:]:
            if (
                member["target_binding_values"]
                != representative["target_binding_values"]
                or member["required_capability_ids"]
                != representative["required_capability_ids"]
            ):
                raise M15ResolutionExecutionBridgeError(
                    "semantic equivalence members disagree on execution requirements"
                )
        missing = sorted(
            set(representative["required_capability_ids"])
            - available_capabilities
        )
        unknown_reasons = sorted(set(missing) - set(reason_map))
        if unknown_reasons:
            raise M15ResolutionExecutionBridgeError(
                "missing capabilities have no explicit reasons: "
                + ", ".join(unknown_reasons)
            )
        semantic_classes.append(
            {
                "semantic_class_id": "m15-e4-class-" + equivalence_hash[:24],
                "semantic_equivalence_sha256": equivalence_hash,
                "member_interpretation_ids": sorted(
                    item["interpretation_id"] for item in members
                ),
                "selected_candidate_ids": representative[
                    "selected_candidate_ids"
                ],
                "target_binding_values": representative[
                    "target_binding_values"
                ],
                "semantic_parameters": representative["semantic_parameters"],
                "required_capability_ids": representative[
                    "required_capability_ids"
                ],
                "missing_capability_ids": missing,
                "availability": "unavailable" if missing else "executable",
                "unavailable_reasons": [
                    {"capability_id": item, "reason": reason_map[item]}
                    for item in missing
                ],
                "physical_candidate_ids": [],
            }
        )

    physical_records, plans = _physical_candidates(
        package=package,
        repo_root=root,
        classes=semantic_classes,
        maximum_per_class=maximum_physical,
        source_paths=source_paths,
    )
    executable_count = sum(
        item["availability"] == "executable" for item in semantic_classes
    )
    unavailable_count = len(semantic_classes) - executable_count
    spec_hash = bridge_spec_sha256 or content_hash(spec)
    if not isinstance(spec_hash, str) or not _SHA256.fullmatch(spec_hash):
        raise M15ResolutionExecutionBridgeError("bridge_spec_sha256 is invalid")
    body = {
        "schema_version": RESOLUTION_EXECUTION_BRIDGE_PLAN_SCHEMA_VERSION,
        "bridge_id": bridge_id,
        "bridge_spec_sha256": spec_hash,
        "source_artifacts": source_artifacts,
        "resolution": {
            "program_id": output["program_id"],
            "resolution_commit_sha256": output["resolution_commit_sha256"],
            "hard_constraints_sha256": hard_hash,
            "resolved_entity_bindings": resolved_entities,
            "hard_constraints_preserved": True,
        },
        "executable_family": {
            "registry_plan_sha256": registry_plan[
                "executable_family_plan_sha256"
            ],
            "family_id": family_id,
            "family_compatibility_sha256": expected_family_hash,
            "family_package_sha256": package[
                "executable_family_package_sha256"
            ],
            "available_capabilities": capabilities,
            "physical_strategy_ids": strategies,
        },
        "counts": {
            "raw_interpretations": len(interpretation_records),
            "semantic_equivalence_classes": len(semantic_classes),
            "executable_semantic_classes": executable_count,
            "unavailable_semantic_classes": unavailable_count,
            "physical_candidates": len(physical_records),
        },
        "semantic_classes": sorted(
            semantic_classes, key=lambda item: item["semantic_class_id"]
        ),
        "physical_candidates": physical_records,
        "claim_boundary": {
            "artifact_class": "capability_checked_unexecuted_bridge_plan",
            "development_artifacts_only": True,
            "all_bounded_interpretations_preserved": True,
            "unsupported_interpretations_silently_dropped": False,
            "hard_constraints_relaxed": False,
            "answer_oracle_used_for_selection": False,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "native_query_text_emitted": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15ResolutionExecutionBridgePlan(
        {**body, "bridge_plan_sha256": content_hash(body)}, plans
    )


def compile_m15_resolution_execution_bridge_files(
    *,
    resolution_run_path: str | Path,
    bridge_spec_path: str | Path,
    repo_root: str | Path,
) -> M15ResolutionExecutionBridgePlan:
    resolution_path = Path(resolution_run_path)
    spec_path = Path(bridge_spec_path)
    return compile_m15_resolution_execution_bridge(
        _regular_json(resolution_path, name="resolution run"),
        _regular_json(spec_path, name="bridge spec"),
        repo_root=repo_root,
        bridge_spec_sha256=_file_sha256(spec_path),
    )


def write_m15_resolution_execution_bridge_plan(
    plan: M15ResolutionExecutionBridgePlan,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"bridge plan already exists: {destination}")
    destination.write_text(
        json.dumps(
            plan.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution-run", required=True)
    parser.add_argument("--bridge-spec", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    plan = compile_m15_resolution_execution_bridge_files(
        resolution_run_path=args.resolution_run,
        bridge_spec_path=args.bridge_spec,
        repo_root=args.repo_root,
    )
    write_m15_resolution_execution_bridge_plan(plan, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
