"""Compile family-local transfer contracts for parameterized M15 queries.

A query family is a structural compatibility boundary, not a text label.  Its
instances may change declared hard binding values, while semantics, output,
artifact interfaces, candidate strategies, and compatibility versions remain
fixed.  Compilation is side-effect free and never promotes a development
registry into paper evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_method_policy import METHOD_POLICY_SCHEMA_VERSION
from xgap.experiments.m15_query_contract import (
    QUERY_CONTRACT_SCHEMA_VERSION,
    QUERY_SPEC_SCHEMA_VERSION,
    M15ResolvedQuerySpec,
)
from xgap.experiments.m15_query_stream import QUERY_STREAM_PLAN_SCHEMA_VERSION


QUERY_FAMILY_REGISTRY_SCHEMA_VERSION = "m15-f2c-query-family-registry-v1"
QUERY_FAMILY_PLAN_SCHEMA_VERSION = "m15-f2c-query-family-plan-v1"
FAMILY_COMPATIBILITY_VERSION = "m15-f2c-family-compatibility-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAMILY_ROLES = frozenset({"seen_family", "held_out_family"})
_INSTANCE_SPLITS = frozenset(
    {"memory_seed", "held_out_instance", "held_out_family"}
)
_COMPATIBILITY_FIELDS = {
    "query_spec_schema_version",
    "query_contract_schema_version",
    "method_policy_schema_version",
    "query_stream_schema_version",
    "backend_interface_version",
    "candidate_space_version",
}


class M15QueryFamilyError(ValueError):
    """Raised before output when a query-family registry is invalid."""


@dataclass(frozen=True)
class M15QueryFamilyPlan:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def plan_hash(self) -> str:
        return str(self.payload["query_family_plan_sha256"])


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15QueryFamilyError(f"{name} must be an object")
    return dict(value)


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    result = _object(value, name=name)
    if set(result) != fields:
        raise M15QueryFamilyError(f"{name} fields do not match the v1 contract")
    return result


def _array(value: object, *, name: str, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a nonempty array"
        raise M15QueryFamilyError(f"{name} must be {qualifier}")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15QueryFamilyError(f"{name} must be a safe identifier")
    return value


def _safe_ids(value: object, *, name: str) -> list[str]:
    result = [
        _safe_id(item, name=f"{name}[]")
        for item in _array(value, name=name)
    ]
    if len(result) != len(set(result)):
        raise M15QueryFamilyError(f"{name} must contain unique identifiers")
    return result


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15QueryFamilyError(f"{name} must be a SHA-256 digest")
    return value


def _relative_path(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise M15QueryFamilyError(f"{name} must be a nonempty path")
    path = Path(value)
    if path.is_absolute() or path == Path(".") or ".." in path.parts:
        raise M15QueryFamilyError(
            f"{name} must be a normalized repository-relative path"
        )
    return value


def _resolve_repo_file(repo_root: Path, relative: str, *, name: str) -> Path:
    candidate = repo_root / relative
    if candidate.is_symlink():
        raise M15QueryFamilyError(f"{name} must not be a symlink")
    path = candidate.resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise M15QueryFamilyError(f"{name} escapes repository root") from exc
    if not path.is_file():
        raise M15QueryFamilyError(f"{name} must be a regular file")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _constraint_schema(value: object, *, name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, item in enumerate(_array(value, name=name)):
        raw = _strict_object(
            item,
            name=f"{name}[{index}]",
            fields={"constraint_id", "kind", "relaxable"},
        )
        if raw["relaxable"] is not False:
            raise M15QueryFamilyError("family hard constraints cannot be relaxable")
        constraint_id = _safe_id(
            raw["constraint_id"], name=f"{name}[{index}].constraint_id"
        )
        ids.append(constraint_id)
        result.append(
            {
                "constraint_id": constraint_id,
                "kind": _safe_id(raw["kind"], name=f"{name}[{index}].kind"),
                "relaxable": False,
            }
        )
    if len(ids) != len(set(ids)):
        raise M15QueryFamilyError("family hard constraint IDs must be unique")
    return result


def _artifact_interface(value: object, *, name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    roles: list[str] = []
    for index, item in enumerate(_array(value, name=name)):
        raw = _strict_object(
            item,
            name=f"{name}[{index}]",
            fields={"role", "backend_id", "language", "parameters"},
        )
        parameters = raw["parameters"]
        if not isinstance(parameters, Mapping):
            raise M15QueryFamilyError("artifact parameters must be an object")
        try:
            content_hash(dict(parameters))
        except (TypeError, ValueError) as exc:
            raise M15QueryFamilyError(
                "artifact parameters must be finite JSON"
            ) from exc
        role = _safe_id(raw["role"], name=f"{name}[{index}].role")
        roles.append(role)
        result.append(
            {
                "role": role,
                "backend_id": _safe_id(
                    raw["backend_id"], name=f"{name}[{index}].backend_id"
                ),
                "language": _safe_id(
                    raw["language"], name=f"{name}[{index}].language"
                ),
                "parameters": dict(parameters),
            }
        )
    if len(roles) != len(set(roles)):
        raise M15QueryFamilyError("artifact interface roles must be unique")
    return result


def _instance(value: object, *, name: str) -> dict[str, str]:
    raw = _strict_object(
        value,
        name=name,
        fields={
            "instance_id",
            "split",
            "query_spec_path",
            "expected_query_spec_sha256",
        },
    )
    split = _safe_id(raw["split"], name=f"{name}.split")
    if split not in _INSTANCE_SPLITS:
        raise M15QueryFamilyError(f"{name}.split is unsupported")
    return {
        "instance_id": _safe_id(raw["instance_id"], name=f"{name}.instance_id"),
        "split": split,
        "query_spec_path": _relative_path(
            raw["query_spec_path"], name=f"{name}.query_spec_path"
        ),
        "expected_query_spec_sha256": _sha256(
            raw["expected_query_spec_sha256"],
            name=f"{name}.expected_query_spec_sha256",
        ),
    }


def _compatibility_versions(value: object) -> dict[str, str]:
    raw = _strict_object(
        value,
        name="compatibility_versions",
        fields=_COMPATIBILITY_FIELDS,
    )
    result = {
        key: _safe_id(raw[key], name=f"compatibility_versions.{key}")
        for key in sorted(raw)
    }
    expected = {
        "query_spec_schema_version": QUERY_SPEC_SCHEMA_VERSION,
        "query_contract_schema_version": QUERY_CONTRACT_SCHEMA_VERSION,
        "method_policy_schema_version": METHOD_POLICY_SCHEMA_VERSION,
        "query_stream_schema_version": QUERY_STREAM_PLAN_SCHEMA_VERSION,
    }
    if any(result[key] != version for key, version in expected.items()):
        raise M15QueryFamilyError("compatibility_versions disagree with runtime")
    return result


def _spec_structure(spec: M15ResolvedQuerySpec) -> dict[str, Any]:
    return {
        "semantic_operator_ids": list(spec.semantic_operator_ids),
        "output_fields": list(spec.output_fields),
        "hard_constraint_schema": [
            {
                "constraint_id": item["constraint_id"],
                "kind": item["kind"],
                "relaxable": item["relaxable"],
            }
            for item in spec.hard_constraints
        ],
        "artifact_interface": [
            {
                "role": item["role"],
                "backend_id": item["backend_id"],
                "language": item["language"],
                "parameters": dict(item["parameters"]),
            }
            for item in spec.artifacts
        ],
    }


def compile_m15_query_family_registry(
    registry: Mapping[str, Any],
    *,
    repo_root: str | Path | None = None,
) -> M15QueryFamilyPlan:
    """Compile a development family registry into portable transfer keys."""

    raw = _strict_object(
        registry,
        name="query family registry",
        fields={
            "schema_version",
            "registry_id",
            "compatibility_versions",
            "families",
            "paper_target",
            "automatic_retries",
            "paper_result",
        },
    )
    if raw["schema_version"] != QUERY_FAMILY_REGISTRY_SCHEMA_VERSION:
        raise M15QueryFamilyError("query family registry schema_version is unsupported")
    registry_id = _safe_id(raw["registry_id"], name="registry_id")
    versions = _compatibility_versions(raw["compatibility_versions"])
    target = _strict_object(
        raw["paper_target"],
        name="paper_target",
        fields={"minimum_families", "minimum_instances", "maximum_instances"},
    )
    minimum_families = target["minimum_families"]
    minimum_instances = target["minimum_instances"]
    maximum_instances = target["maximum_instances"]
    if (
        not isinstance(minimum_families, int)
        or isinstance(minimum_families, bool)
        or minimum_families < 3
    ):
        raise M15QueryFamilyError("minimum_families must be an integer at least 3")
    if (
        not isinstance(minimum_instances, int)
        or isinstance(minimum_instances, bool)
        or minimum_instances < 30
        or not isinstance(maximum_instances, int)
        or isinstance(maximum_instances, bool)
        or maximum_instances > 50
        or maximum_instances < minimum_instances
    ):
        raise M15QueryFamilyError("paper instance target must remain within 30 to 50")
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise M15QueryFamilyError(
            "development family registry must disable retry and set paper_result=false"
        )

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    if not root.is_dir():
        raise M15QueryFamilyError("repository root does not exist")

    compiled_families: list[dict[str, Any]] = []
    family_ids: list[str] = []
    instance_ids: list[str] = []
    compatibility_hashes: list[str] = []
    for family_index, item in enumerate(_array(raw["families"], name="families")):
        family = _strict_object(
            item,
            name=f"families[{family_index}]",
            fields={
                "family_id",
                "evaluation_role",
                "semantic_operator_ids",
                "output_fields",
                "hard_constraint_schema",
                "artifact_interface",
                "candidate_strategy_ids",
                "instances",
            },
        )
        family_id = _safe_id(family["family_id"], name="family_id")
        family_ids.append(family_id)
        role = _safe_id(family["evaluation_role"], name="evaluation_role")
        if role not in _FAMILY_ROLES:
            raise M15QueryFamilyError("family evaluation_role is unsupported")
        structure = {
            "semantic_operator_ids": _safe_ids(
                family["semantic_operator_ids"], name="semantic_operator_ids"
            ),
            "output_fields": _safe_ids(
                family["output_fields"], name="output_fields"
            ),
            "hard_constraint_schema": _constraint_schema(
                family["hard_constraint_schema"], name="hard_constraint_schema"
            ),
            "artifact_interface": _artifact_interface(
                family["artifact_interface"], name="artifact_interface"
            ),
        }
        candidate_ids = _safe_ids(
            family["candidate_strategy_ids"], name="candidate_strategy_ids"
        )
        family_signature = {
            "compatibility_version": FAMILY_COMPATIBILITY_VERSION,
            **structure,
            "candidate_strategy_ids": candidate_ids,
            "compatibility_versions": versions,
        }
        compatibility_hash = content_hash(family_signature)
        compatibility_hashes.append(compatibility_hash)

        compiled_instances: list[dict[str, Any]] = []
        binding_hashes: list[str] = []
        for instance_index, raw_instance in enumerate(
            _array(family["instances"], name="instances")
        ):
            instance = _instance(
                raw_instance,
                name=f"families[{family_index}].instances[{instance_index}]",
            )
            instance_ids.append(instance["instance_id"])
            if role == "seen_family" and instance["split"] == "held_out_family":
                raise M15QueryFamilyError(
                    "seen families cannot contain held_out_family instances"
                )
            if role == "held_out_family" and instance["split"] != "held_out_family":
                raise M15QueryFamilyError(
                    "held-out families may contain only held_out_family instances"
                )
            path = _resolve_repo_file(
                root,
                instance["query_spec_path"],
                name="query spec",
            )
            observed_sha = _sha256_file(path)
            if observed_sha != instance["expected_query_spec_sha256"]:
                raise M15QueryFamilyError(
                    f"query spec hash drifted for {instance['instance_id']}"
                )
            try:
                spec = M15ResolvedQuerySpec.from_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise M15QueryFamilyError(
                    f"query spec is invalid for {instance['instance_id']}: {exc}"
                ) from exc
            if _spec_structure(spec) != structure:
                raise M15QueryFamilyError(
                    f"query spec structure drifted outside family {family_id}"
                )
            hard_bindings = [
                {
                    "constraint_id": constraint["constraint_id"],
                    "kind": constraint["kind"],
                    "value": constraint["value"],
                }
                for constraint in spec.hard_constraints
            ]
            binding_hash = content_hash(hard_bindings)
            binding_hashes.append(binding_hash)
            instance_body = {
                "instance_id": instance["instance_id"],
                "split": instance["split"],
                "query_id": spec.query_id,
                "query_spec_sha256": observed_sha,
                "hard_bindings": hard_bindings,
                "hard_binding_sha256": binding_hash,
            }
            compiled_instances.append(
                {
                    **instance_body,
                    "query_spec_path": instance["query_spec_path"],
                    "instance_sha256": content_hash(instance_body),
                }
            )
        if len(binding_hashes) != len(set(binding_hashes)):
            raise M15QueryFamilyError(
                f"family {family_id} contains duplicate hard bindings"
            )

        seed_ids = [
            instance["instance_id"]
            for instance in compiled_instances
            if instance["split"] == "memory_seed"
        ]
        held_out_instance_ids = [
            instance["instance_id"]
            for instance in compiled_instances
            if instance["split"] == "held_out_instance"
        ]
        held_out_family_ids = [
            instance["instance_id"]
            for instance in compiled_instances
            if instance["split"] == "held_out_family"
        ]
        compiled_families.append(
            {
                "family_id": family_id,
                "evaluation_role": role,
                **family_signature,
                "family_compatibility_sha256": compatibility_hash,
                "instances": compiled_instances,
                "memory_protocol": {
                    "namespace_template": (
                        "{method}." + compatibility_hash
                    ),
                    "cross_family_reads_allowed": False,
                    "seed_instance_ids": seed_ids,
                    "held_out_instance_ids": held_out_instance_ids,
                    "held_out_family_instance_ids": held_out_family_ids,
                    "evaluation_snapshot": (
                        "freeze_after_successful_exact_memory_seed_commits"
                        if role == "seen_family"
                        else "empty_cold_start"
                    ),
                    "evaluation_writes_allowed": False,
                },
            }
        )

    if len(family_ids) != len(set(family_ids)):
        raise M15QueryFamilyError("family IDs must be unique")
    if len(instance_ids) != len(set(instance_ids)):
        raise M15QueryFamilyError("instance IDs must be globally unique")
    if len(compatibility_hashes) != len(set(compatibility_hashes)):
        raise M15QueryFamilyError(
            "different family IDs cannot share one structural compatibility key"
        )

    family_count = len(compiled_families)
    instance_count = sum(len(item["instances"]) for item in compiled_families)
    seen = [
        item for item in compiled_families if item["evaluation_role"] == "seen_family"
    ]
    held_out = [
        item
        for item in compiled_families
        if item["evaluation_role"] == "held_out_family"
    ]
    blockers: list[str] = []
    if family_count < minimum_families:
        blockers.append("fewer_than_target_query_families")
    if not seen:
        blockers.append("no_seen_query_family")
    if not held_out:
        blockers.append("no_held_out_query_family")
    if instance_count < minimum_instances:
        blockers.append("fewer_than_30_query_instances")
    if instance_count > maximum_instances:
        blockers.append("more_than_50_query_instances")
    if any(not item["memory_protocol"]["seed_instance_ids"] for item in seen):
        blockers.append("seen_family_without_memory_seed_instance")
    if any(not item["memory_protocol"]["held_out_instance_ids"] for item in seen):
        blockers.append("seen_family_without_held_out_instance")
    blockers.extend(
        [
            "typed_semantic_operator_dag_not_yet_bound",
            "backend_query_template_structure_not_yet_bound",
            "query_instances_not_yet_bound_to_workload_contracts_and_oracles",
            "family_split_and_inferential_analysis_not_preregistered",
        ]
    )

    portable_families = []
    for family in compiled_families:
        portable_families.append(
            {
                **{
                    key: value
                    for key, value in family.items()
                    if key != "instances"
                },
                "instances": [
                    {
                        key: value
                        for key, value in instance.items()
                        if key != "query_spec_path"
                    }
                    for instance in family["instances"]
                ],
            }
        )
    expected_counts = {
        "families": family_count,
        "seen_families": len(seen),
        "held_out_families": len(held_out),
        "query_instances": instance_count,
        "memory_seed_instances": sum(
            len(item["memory_protocol"]["seed_instance_ids"])
            for item in compiled_families
        ),
        "held_out_instances": sum(
            len(item["memory_protocol"]["held_out_instance_ids"])
            for item in compiled_families
        ),
        "held_out_family_instances": sum(
            len(item["memory_protocol"]["held_out_family_instance_ids"])
            for item in compiled_families
        ),
    }
    plan_body = {
        "registry_id": registry_id,
        "compatibility_versions": versions,
        "paper_target": {
            "minimum_families": minimum_families,
            "minimum_instances": minimum_instances,
            "maximum_instances": maximum_instances,
        },
        "families": portable_families,
        "expected_counts": expected_counts,
        "design_validation": {
            "family_local_transfer_only": True,
            "cross_family_reads_allowed": False,
            "held_out_family_cold_start_required": True,
            "evaluation_writes_allowed": False,
            "paper_workload_ready": not blockers,
            "blocking_conditions": blockers,
        },
    }
    return M15QueryFamilyPlan(
        {
            "schema_version": QUERY_FAMILY_PLAN_SCHEMA_VERSION,
            "registry_spec_sha256": content_hash(raw),
            **plan_body,
            "query_family_plan_sha256": content_hash(plan_body),
            "provenance": {
                "query_spec_paths": [
                    {
                        "family_id": family["family_id"],
                        "instance_id": instance["instance_id"],
                        "query_spec_path": instance["query_spec_path"],
                    }
                    for family in compiled_families
                    for instance in family["instances"]
                ]
            },
            "claim_boundary": {
                "artifact_class": "unexecuted_query_family_plan",
                "backend_calls_made": 0,
                "llm_calls_made": 0,
                "ontology_calls_made": 0,
                "contains_measurements": False,
                "cross_task_memory_benefit_measured": False,
                "paper_comparison_ready": False,
                "paper_result": False,
            },
            "automatic_retries": 0,
            "paper_result": False,
        }
    )


def compile_m15_query_family_file(
    registry_path: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> M15QueryFamilyPlan:
    candidate = Path(registry_path)
    if candidate.is_symlink():
        raise M15QueryFamilyError("query family registry must not be a symlink")
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15QueryFamilyError("query family registry must be an object")
    return compile_m15_query_family_registry(payload, repo_root=repo_root)


def write_m15_query_family_plan(
    plan: M15QueryFamilyPlan,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"query family plan exists: {destination}")
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
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        plan = compile_m15_query_family_file(
            args.registry,
            repo_root=args.repo_root,
        )
        if args.output:
            write_m15_query_family_plan(plan, args.output)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
