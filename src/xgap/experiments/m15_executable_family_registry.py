"""Compile executable M15 query-family packages from hash-bound sources.

This compiler upgrades the earlier label-oriented family registry into a
reconstructable package contract.  It regenerates the typed query, native
templates, per-instance workload/oracles, direct semantic workload, and
family-memory policy without making a backend, LLM, or ontology-service call.
It does not select future benchmark domains or promote development artifacts
to paper evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    DIRECT_FAMILY_PREDICTOR_POLICY_SCHEMA_VERSION,
    _predictor_policy,
)
from xgap.experiments.m15_direct_semantic_workload import (
    DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION,
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_query import (
    PARAMETERIZED_QUERY_CONTRACT_SCHEMA_VERSION,
    compile_m15_parameterized_query_file,
)
from xgap.experiments.m15_parameterized_workload import (
    PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION,
    generate_m15_parameterized_workload_bundle,
)


EXECUTABLE_FAMILY_REGISTRY_SCHEMA_VERSION = (
    "m15-f2c14-executable-family-registry-v1"
)
EXECUTABLE_FAMILY_PLAN_SCHEMA_VERSION = "m15-f2c14-executable-family-plan-v1"
EXECUTABLE_FAMILY_PACKAGE_SCHEMA_VERSION = (
    "m15-f2c14-executable-family-package-v1"
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAMILY_ROLES = frozenset({"seen_family", "held_out_family"})
_SOURCE_ROLES = frozenset(
    {
        "workload_spec",
        "query_template",
        "semantic_catalog",
        "predicate_mapping",
        "semantic_workload_policy",
        "family_memory_policy",
        "neo4j_full_template",
        "neo4j_bound_template",
        "fuseki_risk_template",
    }
)
_EXPECTED_FIELDS = frozenset(
    {
        "family_compatibility_sha256",
        "base_bundle_content_sha256",
        "direct_manifest_sha256",
        "direct_bundle_content_sha256",
        "training_view_sha256",
        "heldout_view_sha256",
        "evaluation_registry_sha256",
        "operator_count",
        "base_query_instances",
        "training_base_queries",
        "heldout_base_queries",
        "direct_semantic_tasks",
        "training_semantic_tasks",
        "heldout_semantic_tasks",
        "physical_candidates",
    }
)


class M15ExecutableFamilyRegistryError(ValueError):
    """Raised before output when an executable family package is invalid."""


@dataclass(frozen=True)
class M15ExecutableFamilyPlan:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def plan_hash(self) -> str:
        return str(self.payload["executable_family_plan_sha256"])


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15ExecutableFamilyRegistryError(f"{name} must be an object")
    return dict(value)


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str] | frozenset[str],
) -> dict[str, Any]:
    result = _object(value, name=name)
    if set(result) != set(fields):
        raise M15ExecutableFamilyRegistryError(
            f"{name} fields do not match the v1 contract"
        )
    return result


def _array(value: object, *, name: str, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a nonempty array"
        raise M15ExecutableFamilyRegistryError(f"{name} must be {qualifier}")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15ExecutableFamilyRegistryError(f"{name} must be a safe identifier")
    return value


def _safe_ids(value: object, *, name: str, allow_empty: bool = False) -> list[str]:
    result = [
        _safe_id(item, name=f"{name}[]")
        for item in _array(value, name=name, allow_empty=allow_empty)
    ]
    if len(result) != len(set(result)):
        raise M15ExecutableFamilyRegistryError(f"{name} must be unique")
    return result


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15ExecutableFamilyRegistryError(f"{name} must be a SHA-256 digest")
    return value


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise M15ExecutableFamilyRegistryError(f"{name} must be a positive integer")
    return value


def _relative_path(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise M15ExecutableFamilyRegistryError(f"{name} must be a nonempty path")
    path = Path(value)
    if path.is_absolute() or path == Path(".") or ".." in path.parts:
        raise M15ExecutableFamilyRegistryError(
            f"{name} must be a normalized repository-relative path"
        )
    return path.as_posix()


def _resolve_repo_file(repo_root: Path, relative: str, *, name: str) -> Path:
    candidate = repo_root / relative
    if candidate.is_symlink():
        raise M15ExecutableFamilyRegistryError(f"{name} must not be a symlink")
    path = candidate.resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise M15ExecutableFamilyRegistryError(
            f"{name} escapes repository root"
        ) from exc
    if not path.is_file():
        raise M15ExecutableFamilyRegistryError(f"{name} must be a regular file")
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json_file(path: Path, *, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M15ExecutableFamilyRegistryError(f"{name} is not valid JSON") from exc
    return _object(payload, name=name)


def _source_bindings(
    value: object,
    *,
    repo_root: Path,
    family_name: str,
) -> tuple[dict[str, dict[str, str]], dict[str, Path]]:
    raw = _strict_object(
        value,
        name=f"{family_name}.sources",
        fields=_SOURCE_ROLES,
    )
    portable: dict[str, dict[str, str]] = {}
    paths: dict[str, Path] = {}
    for role in sorted(_SOURCE_ROLES):
        source = _strict_object(
            raw[role],
            name=f"{family_name}.sources.{role}",
            fields={"path", "sha256"},
        )
        relative = _relative_path(
            source["path"], name=f"{family_name}.sources.{role}.path"
        )
        expected_hash = _sha256(
            source["sha256"], name=f"{family_name}.sources.{role}.sha256"
        )
        path = _resolve_repo_file(
            repo_root, relative, name=f"{family_name}.sources.{role}"
        )
        if _file_sha256(path) != expected_hash:
            raise M15ExecutableFamilyRegistryError(
                f"{family_name} source SHA-256 mismatch: {role}"
            )
        portable[role] = {"path": relative, "sha256": expected_hash}
        paths[role] = path
    template_parents = {
        paths[role].parent
        for role in (
            "neo4j_full_template",
            "neo4j_bound_template",
            "fuseki_risk_template",
        )
    }
    if len(template_parents) != 1:
        raise M15ExecutableFamilyRegistryError(
            f"{family_name} backend templates must share one directory"
        )
    return portable, paths


def _agent_contract(value: object) -> dict[str, Any]:
    raw = _strict_object(
        value,
        name="agent_contract",
        fields={"environment", "tools", "allowed_actions", "forbidden_actions"},
    )
    environment = _strict_object(
        raw["environment"],
        name="agent_contract.environment",
        fields={"coordinator", "backends", "optional_inputs"},
    )
    if environment["coordinator"] != "xgap":
        raise M15ExecutableFamilyRegistryError("agent coordinator must be xgap")
    backends: list[dict[str, str]] = []
    backend_ids: list[str] = []
    for index, item in enumerate(
        _array(environment["backends"], name="agent_contract.environment.backends")
    ):
        backend = _strict_object(
            item,
            name=f"agent_contract.environment.backends[{index}]",
            fields={"backend_id", "boundary"},
        )
        backend_id = _safe_id(
            backend["backend_id"],
            name=f"agent_contract.environment.backends[{index}].backend_id",
        )
        if backend["boundary"] != "black_box_public_interface":
            raise M15ExecutableFamilyRegistryError(
                "every backend must use the black-box public interface"
            )
        backend_ids.append(backend_id)
        backends.append(
            {"backend_id": backend_id, "boundary": "black_box_public_interface"}
        )
    if len(backend_ids) != len(set(backend_ids)) or not {
        "neo4j",
        "fuseki",
    }.issubset(backend_ids):
        raise M15ExecutableFamilyRegistryError(
            "agent environment requires unique Neo4j and Fuseki backends"
        )
    optional_inputs = _safe_ids(
        environment["optional_inputs"],
        name="agent_contract.environment.optional_inputs",
        allow_empty=True,
    )
    if not {"catalog", "llm", "ontology"}.issubset(optional_inputs):
        raise M15ExecutableFamilyRegistryError(
            "catalog, LLM, and ontology must remain explicit optional inputs"
        )

    tools: list[dict[str, Any]] = []
    tool_ids: list[str] = []
    for index, item in enumerate(_array(raw["tools"], name="agent_contract.tools")):
        tool = _strict_object(
            item,
            name=f"agent_contract.tools[{index}]",
            fields={"tool_id", "kind", "operations"},
        )
        tool_id = _safe_id(tool["tool_id"], name=f"tool[{index}].tool_id")
        tool_ids.append(tool_id)
        tools.append(
            {
                "tool_id": tool_id,
                "kind": _safe_id(tool["kind"], name=f"tool[{index}].kind"),
                "operations": _safe_ids(
                    tool["operations"], name=f"tool[{index}].operations"
                ),
            }
        )
    if len(tool_ids) != len(set(tool_ids)):
        raise M15ExecutableFamilyRegistryError("agent tool IDs must be unique")
    required_tools = {
        "backend.execute.neo4j",
        "backend.execute.fuseki",
        "coordinator.federate",
        "memory.family",
        "semantic.direct",
    }
    if not required_tools.issubset(tool_ids):
        raise M15ExecutableFamilyRegistryError("agent tool contract is incomplete")

    allowed = _safe_ids(raw["allowed_actions"], name="agent_contract.allowed_actions")
    forbidden = _safe_ids(
        raw["forbidden_actions"], name="agent_contract.forbidden_actions"
    )
    if set(allowed) & set(forbidden):
        raise M15ExecutableFamilyRegistryError(
            "allowed and forbidden agent actions must be disjoint"
        )
    required_forbidden = {
        "change_hard_constraints",
        "emit_unregistered_native_query",
        "inspect_backend_internals",
        "read_answer_oracle_before_execution",
        "retry_automatically",
    }
    if not required_forbidden.issubset(forbidden):
        raise M15ExecutableFamilyRegistryError(
            "agent forbidden-action boundary is incomplete"
        )
    return {
        "environment": {
            "coordinator": "xgap",
            "backends": backends,
            "optional_inputs": optional_inputs,
        },
        "tools": tools,
        "allowed_actions": allowed,
        "forbidden_actions": forbidden,
    }


def _expected(value: object, *, family_name: str) -> dict[str, Any]:
    raw = _strict_object(
        value,
        name=f"{family_name}.expected",
        fields=_EXPECTED_FIELDS,
    )
    result: dict[str, Any] = {}
    for field in sorted(_EXPECTED_FIELDS):
        result[field] = (
            _sha256(raw[field], name=f"{family_name}.expected.{field}")
            if field.endswith("sha256")
            else _positive_int(raw[field], name=f"{family_name}.expected.{field}")
        )
    return result


def _require_expected(
    *,
    family_name: str,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> None:
    differences = {
        key: {"expected": expected[key], "observed": observed.get(key)}
        for key in expected
        if observed.get(key) != expected[key]
    }
    if differences:
        raise M15ExecutableFamilyRegistryError(
            f"{family_name} generated package drift: "
            + json.dumps(differences, sort_keys=True, allow_nan=False)
        )


def _compile_family(
    value: object,
    *,
    repo_root: Path,
    temporary_root: Path,
    index: int,
) -> dict[str, Any]:
    name = f"families[{index}]"
    raw = _strict_object(
        value,
        name=name,
        fields={"family_id", "evaluation_role", "sources", "expected"},
    )
    family_id = _safe_id(raw["family_id"], name=f"{name}.family_id")
    role = _safe_id(raw["evaluation_role"], name=f"{name}.evaluation_role")
    if role not in _FAMILY_ROLES:
        raise M15ExecutableFamilyRegistryError(f"{name}.evaluation_role is invalid")
    sources, paths = _source_bindings(
        raw["sources"], repo_root=repo_root, family_name=name
    )
    expected = _expected(raw["expected"], family_name=name)

    try:
        query_contract = compile_m15_parameterized_query_file(paths["query_template"])
        base_bundle = generate_m15_parameterized_workload_bundle(
            workload_spec=paths["workload_spec"],
            query_template_spec=paths["query_template"],
            backend_template_root=paths["neo4j_full_template"].parent,
            destination=temporary_root / f"family-{index}-base",
        )
        direct_bundle = generate_m15_direct_semantic_workload_bundle(
            base_bundle=base_bundle,
            catalog=paths["semantic_catalog"],
            mapping=paths["predicate_mapping"],
            policy=paths["semantic_workload_policy"],
            destination=temporary_root / f"family-{index}-direct",
        )
        predictor = _predictor_policy(paths["family_memory_policy"])
    except M15ExecutableFamilyRegistryError:
        raise
    except Exception as exc:
        raise M15ExecutableFamilyRegistryError(
            f"{name} could not be reconstructed: {exc}"
        ) from exc

    contract = query_contract.to_dict()
    if contract["family_id"] != family_id:
        raise M15ExecutableFamilyRegistryError(
            f"{name}.family_id disagrees with the typed query contract"
        )
    operators = contract["typed_program"]["operators"]
    operator_kinds = dict(sorted(Counter(item["kind"] for item in operators).items()))
    direct_counts = direct_bundle.manifest["counts"]
    base_counts = base_bundle.manifest["counts"]
    observed = {
        "family_compatibility_sha256": contract[
            "family_compatibility_sha256"
        ],
        "base_bundle_content_sha256": base_bundle.manifest[
            "bundle_content_sha256"
        ],
        "direct_manifest_sha256": direct_bundle.manifest["manifest_sha256"],
        "direct_bundle_content_sha256": direct_bundle.manifest[
            "direct_workload_bundle_content_sha256"
        ],
        "training_view_sha256": direct_bundle.manifest["selection_views"][
            "training"
        ],
        "heldout_view_sha256": direct_bundle.manifest["selection_views"][
            "heldout"
        ],
        "evaluation_registry_sha256": direct_bundle.manifest[
            "evaluation_registry_sha256"
        ],
        "operator_count": len(operators),
        "base_query_instances": base_counts["query_instances"],
        "training_base_queries": direct_counts["training_base_queries"],
        "heldout_base_queries": direct_counts["heldout_base_queries"],
        "direct_semantic_tasks": direct_counts["direct_semantic_tasks"],
        "training_semantic_tasks": direct_counts["training_semantic_tasks"],
        "heldout_semantic_tasks": direct_counts["heldout_semantic_tasks"],
        "physical_candidates": direct_counts["physical_candidates"],
    }
    _require_expected(
        family_name=name,
        expected=expected,
        observed=observed,
    )
    if role == "held_out_family" and direct_counts["training_semantic_tasks"]:
        raise M15ExecutableFamilyRegistryError(
            f"{name} held-out family must not expose family-local training tasks"
        )
    family_template = contract["family_template"]
    hard_constraints = sorted(
        {
            constraint["constraint_id"]
            for operator in operators
            for constraint in operator["constraints"]
            if constraint["policy"] == "hard"
        }
    )
    relaxable_constraints = sorted(
        {
            constraint["constraint_id"]
            for operator in operators
            for constraint in operator["constraints"]
            if constraint["policy"] == "relaxable"
        }
    )
    package_body = {
        "schema_version": EXECUTABLE_FAMILY_PACKAGE_SCHEMA_VERSION,
        "family_id": family_id,
        "evaluation_role": role,
        "source_bindings": sources,
        "typed_semantic_program": {
            "contract_schema_version": PARAMETERIZED_QUERY_CONTRACT_SCHEMA_VERSION,
            "template_id": contract["semantic_template_id"],
            "family_compatibility_sha256": contract[
                "family_compatibility_sha256"
            ],
            "operator_ids": [item["operator_id"] for item in operators],
            "operator_kind_counts": operator_kinds,
            "root_ids": contract["typed_program"]["roots"],
            "binding_schema": family_template["binding_schema"],
            "hard_constraint_ids": hard_constraints,
            "relaxable_constraint_ids": relaxable_constraints,
            "output_fields": family_template["output_fields"],
        },
        "backend_artifacts": {
            "bundle_schema_version": PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION,
            "interfaces": family_template["artifact_interfaces"],
            "template_source_roles": [
                "neo4j_full_template",
                "neo4j_bound_template",
                "fuseki_risk_template",
            ],
            "registered_templates_bound": True,
            "literal_free_templates": True,
        },
        "workload": {
            "base_bundle_content_sha256": observed[
                "base_bundle_content_sha256"
            ],
            "counts": base_counts,
            "instance_ids": [
                item["query_id"] for item in base_bundle.manifest["instances"]
            ],
            "per_instance_source_and_final_oracles_bound": True,
        },
        "semantic_workload": {
            "schema_version": DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION,
            "manifest_sha256": observed["direct_manifest_sha256"],
            "bundle_content_sha256": observed[
                "direct_bundle_content_sha256"
            ],
            "selection_view_sha256": {
                "training": observed["training_view_sha256"],
                "heldout": observed["heldout_view_sha256"],
            },
            "evaluation_registry_sha256": observed[
                "evaluation_registry_sha256"
            ],
            "counts": direct_counts,
            "hard_slot_ids": direct_bundle.manifest["hard_slot_ids"],
            "multihop_materialized": False,
        },
        "physical_planning": {
            "candidate_strategy_ids": family_template["candidate_strategy_ids"],
            "selection_pipeline": (
                "physical_then_pareto_then_epsilon_then_k"
            ),
        },
        "family_memory": {
            "policy_schema_version": (
                DIRECT_FAMILY_PREDICTOR_POLICY_SCHEMA_VERSION
            ),
            "policy_id": predictor["policy_id"],
            "model_version": predictor["model_version"],
            "policy_source_sha256": sources["family_memory_policy"]["sha256"],
            "cold_start_policy": predictor["cold_start_policy"],
            "current_query_observation_operations": predictor[
                "current_query_observation_operations"
            ],
            "training_admission": predictor["training_admission"],
        },
        "execution_capabilities": {
            "semantic": ["match", "traverse", "align", "join", "project"],
            "runtime": [
                "registered_remote_query",
                "align",
                "exchange",
                "coordinator_hash_join",
                "remote_bind_query",
                "project",
            ],
            "backend_boundaries": ["neo4j.public_api", "fuseki.public_api"],
        },
        "claim_boundary": {
            "artifact_class": "unexecuted_executable_query_family_package",
            "development_population_only": True,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {
        **package_body,
        "executable_family_package_sha256": content_hash(package_body),
    }


def compile_m15_executable_family_registry(
    registry: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> M15ExecutableFamilyPlan:
    """Reconstruct every declared family and emit one portable plan."""

    raw = _strict_object(
        registry,
        name="executable family registry",
        fields={
            "schema_version",
            "registry_id",
            "agent_contract",
            "families",
            "paper_target",
            "automatic_retries",
            "paper_result",
        },
    )
    if raw["schema_version"] != EXECUTABLE_FAMILY_REGISTRY_SCHEMA_VERSION:
        raise M15ExecutableFamilyRegistryError(
            "executable family registry schema is unsupported"
        )
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise M15ExecutableFamilyRegistryError(
            "development family registry must disable retry and remain "
            "paper_result=false"
        )
    root = Path(repo_root).resolve()
    if root.is_symlink() or not root.is_dir():
        raise M15ExecutableFamilyRegistryError(
            "repo_root must be a regular directory"
        )
    agent_contract = _agent_contract(raw["agent_contract"])
    paper_target = _strict_object(
        raw["paper_target"],
        name="paper_target",
        fields={
            "minimum_families",
            "minimum_query_instances",
            "maximum_query_instances",
            "heldout_family_required",
            "inferential_analysis_preregistered",
        },
    )
    minimum_families = _positive_int(
        paper_target["minimum_families"], name="paper_target.minimum_families"
    )
    minimum_instances = _positive_int(
        paper_target["minimum_query_instances"],
        name="paper_target.minimum_query_instances",
    )
    maximum_instances = _positive_int(
        paper_target["maximum_query_instances"],
        name="paper_target.maximum_query_instances",
    )
    if minimum_families < 2 or minimum_instances > maximum_instances:
        raise M15ExecutableFamilyRegistryError("paper target bounds are invalid")
    if paper_target["heldout_family_required"] is not True or not isinstance(
        paper_target["inferential_analysis_preregistered"], bool
    ):
        raise M15ExecutableFamilyRegistryError("paper target policy is invalid")

    with tempfile.TemporaryDirectory(prefix="xgap-f2c14-family-") as temporary:
        packages = [
            _compile_family(
                family,
                repo_root=root,
                temporary_root=Path(temporary),
                index=index,
            )
            for index, family in enumerate(
                _array(raw["families"], name="families")
            )
        ]
    family_ids = [item["family_id"] for item in packages]
    compatibility_hashes = [
        item["typed_semantic_program"]["family_compatibility_sha256"]
        for item in packages
    ]
    if len(family_ids) != len(set(family_ids)):
        raise M15ExecutableFamilyRegistryError("family IDs must be unique")
    if len(compatibility_hashes) != len(set(compatibility_hashes)):
        raise M15ExecutableFamilyRegistryError(
            "distinct family labels cannot share one compatibility hash"
        )

    family_count = len(packages)
    query_count = sum(
        item["workload"]["counts"]["query_instances"] for item in packages
    )
    heldout_family_count = sum(
        item["evaluation_role"] == "held_out_family" for item in packages
    )
    blockers: list[str] = []
    if family_count < minimum_families:
        blockers.append("fewer_than_target_executable_query_families")
    if query_count < minimum_instances:
        blockers.append("fewer_than_target_base_query_instances")
    if query_count > maximum_instances:
        blockers.append("more_than_target_base_query_instances")
    if paper_target["heldout_family_required"] and heldout_family_count == 0:
        blockers.append("no_executable_held_out_query_family")
    if not paper_target["inferential_analysis_preregistered"]:
        blockers.append("inferential_analysis_not_preregistered")

    body = {
        "schema_version": EXECUTABLE_FAMILY_PLAN_SCHEMA_VERSION,
        "registry_id": _safe_id(raw["registry_id"], name="registry_id"),
        "agent_contract": agent_contract,
        "families": packages,
        "summary": {
            "executable_family_count": family_count,
            "seen_family_count": family_count - heldout_family_count,
            "heldout_family_count": heldout_family_count,
            "base_query_instance_count": query_count,
            "direct_semantic_task_count": sum(
                item["semantic_workload"]["counts"]["direct_semantic_tasks"]
                for item in packages
            ),
            "physical_candidate_count": sum(
                item["semantic_workload"]["counts"]["physical_candidates"]
                for item in packages
            ),
        },
        "paper_target": {
            "minimum_families": minimum_families,
            "minimum_query_instances": minimum_instances,
            "maximum_query_instances": maximum_instances,
            "heldout_family_required": True,
            "inferential_analysis_preregistered": paper_target[
                "inferential_analysis_preregistered"
            ],
        },
        "paper_readiness": {
            "ready": not blockers,
            "blockers": blockers,
        },
        "claim_boundary": {
            "artifact_class": "unexecuted_executable_family_registry_plan",
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "future_domains_selected": False,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15ExecutableFamilyPlan(
        {
            **body,
            "executable_family_plan_sha256": content_hash(body),
        }
    )


def compile_m15_executable_family_registry_file(
    registry_path: str | Path,
    *,
    repo_root: str | Path,
) -> M15ExecutableFamilyPlan:
    candidate = Path(registry_path)
    if candidate.is_symlink() or not candidate.is_file():
        raise M15ExecutableFamilyRegistryError(
            "registry must be a regular non-symbolic-link file"
        )
    return compile_m15_executable_family_registry(
        _load_json_file(candidate, name="executable family registry"),
        repo_root=repo_root,
    )


def write_m15_executable_family_plan(
    plan: M15ExecutableFamilyPlan,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"executable family plan exists: {destination}")
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
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    plan = compile_m15_executable_family_registry_file(
        args.registry,
        repo_root=args.repo_root,
    )
    write_m15_executable_family_plan(plan, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
