"""Compile a typed, parameterized query-family template and one instance.

This F2C2 primitive supports both immutable and explicitly relaxable semantic
constraints without deciding which policy a concrete research query should
use.  Concrete binding values affect instance identity but are excluded from
the structural family key.  Compilation is side-effect free.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, MutableSet, Sequence

from xgap.experiments.hashing import content_hash
from xgap.semantic import (
    ConstraintPolicy,
    SemanticConstraint,
    SemanticGraphProgram,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticProgramError,
    SemanticValueKind,
)


PARAMETERIZED_QUERY_SPEC_SCHEMA_VERSION = "m15-f2c-parameterized-query-spec-v2"
PARAMETERIZED_QUERY_CONTRACT_SCHEMA_VERSION = (
    "m15-f2c-parameterized-query-contract-v1"
)
FAMILY_TEMPLATE_COMPATIBILITY_VERSION = "m15-f2c-typed-family-template-v1"
QUERY_INSTANCE_IDENTITY_VERSION = "m15-f2c-typed-query-instance-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SLOT_TOKEN = re.compile(r"\{\{slot:([A-Za-z0-9][A-Za-z0-9._-]{0,191})\}\}")
_BINDING_KINDS = frozenset({"entity_id", "date", "integer", "enum", "string"})
_PARAMETER_TYPES = frozenset(
    {"string", "date", "integer", "enum", "array[string]"}
)
_BINDING_STAGES = frozenset(
    {"runtime_parameter", "compile_time_template", "runtime_intermediate"}
)
_COMPATIBLE_PARAMETER_TYPES = {
    "entity_id": frozenset({"string"}),
    "date": frozenset({"date"}),
    "integer": frozenset({"integer"}),
    "enum": frozenset({"enum"}),
    "string": frozenset({"string"}),
}


class M15ParameterizedQueryError(ValueError):
    """Raised before output when a parameterized query is invalid."""


@dataclass(frozen=True)
class M15ParameterizedQueryContract:
    payload: Mapping[str, Any]
    typed_program: SemanticGraphProgram

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @property
    def family_hash(self) -> str:
        return str(self.payload["family_compatibility_sha256"])

    @property
    def instance_hash(self) -> str:
        return str(self.payload["query_instance_sha256"])


def _object(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise M15ParameterizedQueryError(f"{name} must be an object")
    return dict(value)


def _strict_object(
    value: object,
    *,
    name: str,
    fields: set[str],
) -> dict[str, Any]:
    result = _object(value, name=name)
    if set(result) != fields:
        raise M15ParameterizedQueryError(
            f"{name} fields do not match the v2 contract"
        )
    return result


def _array(value: object, *, name: str, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "an array" if allow_empty else "a nonempty array"
        raise M15ParameterizedQueryError(f"{name} must be {qualifier}")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15ParameterizedQueryError(f"{name} must be a safe identifier")
    return value


def _safe_id_list(
    value: object,
    *,
    name: str,
    allow_empty: bool = False,
) -> list[str]:
    return [
        _safe_id(item, name=f"{name}[]")
        for item in _array(value, name=name, allow_empty=allow_empty)
    ]


def _safe_ids(
    value: object,
    *,
    name: str,
    allow_empty: bool = False,
) -> list[str]:
    result = _safe_id_list(value, name=name, allow_empty=allow_empty)
    if len(result) != len(set(result)):
        raise M15ParameterizedQueryError(
            f"{name} must contain unique identifiers"
        )
    return result


def _json_value(value: object, *, name: str) -> Any:
    try:
        content_hash(value)
    except (TypeError, ValueError) as exc:
        raise M15ParameterizedQueryError(
            f"{name} must be a finite JSON value"
        ) from exc
    return value


def _binding_value(value: object, *, kind: str, name: str) -> Any:
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise M15ParameterizedQueryError(f"{name} must be an integer")
        return value
    if not isinstance(value, str) or not value.strip():
        raise M15ParameterizedQueryError(f"{name} must be a nonempty string")
    if kind == "date":
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise M15ParameterizedQueryError(
                f"{name} must be an ISO-8601 calendar date"
            ) from exc
        if parsed.isoformat() != value:
            raise M15ParameterizedQueryError(
                f"{name} must be a canonical ISO-8601 calendar date"
            )
    return value


def _bindings(value: object) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    for index, item in enumerate(_array(value, name="binding_slots")):
        raw = _strict_object(
            item,
            name=f"binding_slots[{index}]",
            fields={"slot_id", "kind", "value"},
        )
        slot_id = _safe_id(raw["slot_id"], name="binding slot_id")
        kind = _safe_id(raw["kind"], name="binding kind")
        if kind not in _BINDING_KINDS:
            raise M15ParameterizedQueryError(
                f"binding slot '{slot_id}' has unsupported kind '{kind}'"
            )
        if slot_id in values:
            raise M15ParameterizedQueryError("binding slot IDs must be unique")
        bound = _binding_value(
            raw["value"],
            kind=kind,
            name=f"binding_slots[{index}].value",
        )
        values[slot_id] = bound
        records.append({"slot_id": slot_id, "kind": kind, "value": bound})
    return records, values


def _bind_json(
    value: object,
    *,
    binding_values: Mapping[str, Any],
    used_slots: MutableSet[str],
    name: str,
) -> Any:
    if isinstance(value, Mapping):
        raw = dict(value)
        if "$binding" in raw:
            if set(raw) != {"$binding"}:
                raise M15ParameterizedQueryError(
                    f"{name} binding placeholder cannot have sibling fields"
                )
            slot_id = _safe_id(raw["$binding"], name=f"{name}.$binding")
            if slot_id not in binding_values:
                raise M15ParameterizedQueryError(
                    f"{name} references unknown binding slot '{slot_id}'"
                )
            used_slots.add(slot_id)
            return binding_values[slot_id]
        result: dict[str, Any] = {}
        for key, item in raw.items():
            if not isinstance(key, str):
                raise M15ParameterizedQueryError(f"{name} keys must be strings")
            result[key] = _bind_json(
                item,
                binding_values=binding_values,
                used_slots=used_slots,
                name=f"{name}.{key}",
            )
        return result
    if isinstance(value, list):
        return [
            _bind_json(
                item,
                binding_values=binding_values,
                used_slots=used_slots,
                name=f"{name}[]",
            )
            for item in value
        ]
    return _json_value(value, name=name)


def _relaxation(value: object, *, policy: str, name: str) -> dict[str, Any] | None:
    if policy == ConstraintPolicy.HARD.value:
        if value is not None:
            raise M15ParameterizedQueryError(
                f"{name} hard constraint cannot declare relaxation"
            )
        return None
    if value is None:
        raise M15ParameterizedQueryError(
            f"{name} relaxable constraint requires a relaxation contract"
        )
    raw = _strict_object(
        value,
        name=f"{name}.relaxation",
        fields={"transformations", "max_steps", "deviation_metric"},
    )
    transformations = _safe_ids(
        raw["transformations"],
        name=f"{name}.relaxation.transformations",
    )
    max_steps = raw["max_steps"]
    if (
        isinstance(max_steps, bool)
        or not isinstance(max_steps, int)
        or not 1 <= max_steps <= 16
    ):
        raise M15ParameterizedQueryError(
            f"{name}.relaxation.max_steps must be between 1 and 16"
        )
    if raw["deviation_metric"] != "semantic_deviation":
        raise M15ParameterizedQueryError(
            f"{name}.relaxation must use semantic_deviation"
        )
    return {
        "transformations": transformations,
        "max_steps": max_steps,
        "deviation_metric": "semantic_deviation",
    }


def _constraint(
    value: object,
    *,
    name: str,
    binding_values: Mapping[str, Any],
    used_slots: MutableSet[str],
) -> tuple[dict[str, Any], SemanticConstraint]:
    raw = _strict_object(
        value,
        name=name,
        fields={
            "constraint_id",
            "expression_template",
            "policy",
            "binding_slot_ids",
            "relaxation",
        },
    )
    constraint_id = _safe_id(raw["constraint_id"], name=f"{name}.constraint_id")
    policy = _safe_id(raw["policy"], name=f"{name}.policy")
    if policy not in {item.value for item in ConstraintPolicy}:
        raise M15ParameterizedQueryError(f"{name}.policy is unsupported")
    slot_ids = _safe_ids(
        raw["binding_slot_ids"],
        name=f"{name}.binding_slot_ids",
        allow_empty=True,
    )
    expression_template = raw["expression_template"]
    if not isinstance(expression_template, str) or not expression_template.strip():
        raise M15ParameterizedQueryError(
            f"{name}.expression_template must be nonempty"
        )
    token_ids = _SLOT_TOKEN.findall(expression_template)
    if token_ids != slot_ids:
        raise M15ParameterizedQueryError(
            f"{name} binding_slot_ids must match expression token order exactly"
        )
    expression = expression_template
    for slot_id in slot_ids:
        if slot_id not in binding_values:
            raise M15ParameterizedQueryError(
                f"{name} references unknown binding slot '{slot_id}'"
            )
        used_slots.add(slot_id)
        expression = expression.replace(
            f"{{{{slot:{slot_id}}}}}",
            json.dumps(
                binding_values[slot_id],
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            ),
            1,
        )
    if "{{slot:" in expression:
        raise M15ParameterizedQueryError(f"{name} has an invalid slot token")
    relaxation = _relaxation(raw["relaxation"], policy=policy, name=name)
    record = {
        "constraint_id": constraint_id,
        "expression_template": expression_template,
        "policy": policy,
        "binding_slot_ids": slot_ids,
        "relaxation": relaxation,
    }
    return record, SemanticConstraint(
        constraint_id=constraint_id,
        expression=expression,
        policy=ConstraintPolicy(policy),
    )


def _semantic_template(
    value: object,
    *,
    query_id: str,
    binding_values: Mapping[str, Any],
) -> tuple[dict[str, Any], SemanticGraphProgram, set[str]]:
    raw = _strict_object(
        value,
        name="semantic_template",
        fields={"template_id", "operators", "roots"},
    )
    template_id = _safe_id(raw["template_id"], name="semantic_template.template_id")
    operators: list[SemanticOperator] = []
    records: list[dict[str, Any]] = []
    operator_ids: list[str] = []
    constraint_ids: list[str] = []
    used_slots: set[str] = set()
    for index, item in enumerate(_array(raw["operators"], name="operators")):
        operator = _strict_object(
            item,
            name=f"operators[{index}]",
            fields={
                "operator_id",
                "kind",
                "input_ids",
                "input_kinds",
                "output_kind",
                "parameters",
                "constraints",
                "required_capabilities",
            },
        )
        operator_id = _safe_id(operator["operator_id"], name="operator_id")
        operator_ids.append(operator_id)
        kind_name = _safe_id(operator["kind"], name="operator kind")
        output_name = _safe_id(operator["output_kind"], name="operator output_kind")
        try:
            kind = SemanticOperatorKind(kind_name)
            output_kind = SemanticValueKind(output_name)
        except ValueError as exc:
            raise M15ParameterizedQueryError(
                f"operator '{operator_id}' has an unsupported kind"
            ) from exc
        input_ids = _safe_ids(
            operator["input_ids"], name="operator.input_ids", allow_empty=True
        )
        input_kind_names = _safe_id_list(
            operator["input_kinds"],
            name="operator.input_kinds",
            allow_empty=True,
        )
        try:
            input_kinds = [SemanticValueKind(item) for item in input_kind_names]
        except ValueError as exc:
            raise M15ParameterizedQueryError(
                f"operator '{operator_id}' has an unsupported input kind"
            ) from exc
        parameters = _bind_json(
            operator["parameters"],
            binding_values=binding_values,
            used_slots=used_slots,
            name=f"operators[{index}].parameters",
        )
        if not isinstance(parameters, Mapping):
            raise M15ParameterizedQueryError("operator parameters must be an object")
        constraint_records: list[dict[str, Any]] = []
        typed_constraints: list[SemanticConstraint] = []
        for constraint_index, raw_constraint in enumerate(
            _array(
                operator["constraints"],
                name="operator.constraints",
                allow_empty=True,
            )
        ):
            record, typed = _constraint(
                raw_constraint,
                name=f"operators[{index}].constraints[{constraint_index}]",
                binding_values=binding_values,
                used_slots=used_slots,
            )
            constraint_records.append(record)
            typed_constraints.append(typed)
            constraint_ids.append(typed.constraint_id)
        capabilities = _safe_ids(
            operator["required_capabilities"],
            name="operator.required_capabilities",
            allow_empty=True,
        )
        record = {
            "operator_id": operator_id,
            "kind": kind.value,
            "input_ids": input_ids,
            "input_kinds": [item.value for item in input_kinds],
            "output_kind": output_kind.value,
            "parameters": operator["parameters"],
            "constraints": constraint_records,
            "required_capabilities": capabilities,
        }
        records.append(record)
        try:
            operators.append(
                SemanticOperator(
                    operator_id=operator_id,
                    kind=kind,
                    input_ids=tuple(input_ids),
                    input_kinds=tuple(input_kinds),
                    output_kind=output_kind,
                    parameters=dict(parameters),
                    constraints=tuple(typed_constraints),
                    required_capabilities=tuple(capabilities),
                )
            )
        except SemanticProgramError as exc:
            raise M15ParameterizedQueryError(str(exc)) from exc
    if len(operator_ids) != len(set(operator_ids)):
        raise M15ParameterizedQueryError("semantic operator IDs must be unique")
    if len(constraint_ids) != len(set(constraint_ids)):
        raise M15ParameterizedQueryError("semantic constraint IDs must be unique")
    roots = _safe_ids(raw["roots"], name="semantic_template.roots")
    try:
        program = SemanticGraphProgram(
            program_id=f"{query_id}.bound",
            operators=tuple(operators),
            roots=tuple(roots),
            metadata={
                "template_id": template_id,
                "query_id": query_id,
                "evidence_class": "parameterized_query_instance",
                "paper_result": False,
            },
        )
    except SemanticProgramError as exc:
        raise M15ParameterizedQueryError(str(exc)) from exc
    return {
        "template_id": template_id,
        "operators": records,
        "roots": roots,
    }, program, used_slots


def _artifact_interfaces(
    value: object,
    *,
    binding_values: Mapping[str, Any],
    binding_kinds: Mapping[str, str],
) -> tuple[list[dict[str, Any]], set[str]]:
    result: list[dict[str, Any]] = []
    roles: list[str] = []
    used_slots: set[str] = set()
    for index, item in enumerate(_array(value, name="artifact_interfaces")):
        raw = _strict_object(
            item,
            name=f"artifact_interfaces[{index}]",
            fields={
                "role",
                "backend_id",
                "language",
                "parameter_schema",
                "binding_parameters",
            },
        )
        role = _safe_id(raw["role"], name="artifact role")
        roles.append(role)
        raw_parameter_schema = _object(
            raw["parameter_schema"], name="artifact parameter_schema"
        )
        if not raw_parameter_schema:
            raise M15ParameterizedQueryError(
                f"artifact '{role}' parameter_schema must be nonempty"
            )
        parameter_schema: dict[str, dict[str, Any]] = {}
        for parameter, item_schema in raw_parameter_schema.items():
            parameter_id = _safe_id(parameter, name="artifact parameter")
            schema = _strict_object(
                item_schema,
                name=f"artifact '{role}' parameter '{parameter_id}' schema",
                fields={"type", "required", "binding_stage"},
            )
            parameter_type = schema["type"]
            if (
                not isinstance(parameter_type, str)
                or parameter_type not in _PARAMETER_TYPES
            ):
                raise M15ParameterizedQueryError(
                    f"artifact '{role}' parameter '{parameter_id}' has unsupported type"
                )
            if not isinstance(schema["required"], bool):
                raise M15ParameterizedQueryError(
                    f"artifact '{role}' parameter '{parameter_id}' required "
                    "must be boolean"
                )
            binding_stage = _safe_id(
                schema["binding_stage"],
                name=f"artifact '{role}' parameter '{parameter_id}' binding_stage",
            )
            if binding_stage not in _BINDING_STAGES:
                raise M15ParameterizedQueryError(
                    f"artifact '{role}' parameter '{parameter_id}' has "
                    "unsupported binding_stage"
                )
            parameter_schema[parameter_id] = {
                "type": parameter_type,
                "required": schema["required"],
                "binding_stage": binding_stage,
            }
        binding_parameters = _object(
            raw["binding_parameters"], name="artifact binding_parameters"
        )
        compiled_bindings: dict[str, str] = {}
        for parameter, raw_slot_id in binding_parameters.items():
            parameter_id = _safe_id(parameter, name="artifact parameter")
            if parameter_id not in parameter_schema:
                raise M15ParameterizedQueryError(
                    f"artifact binding parameter '{parameter_id}' has no schema"
                )
            schema = parameter_schema[parameter_id]
            if schema["binding_stage"] == "runtime_intermediate":
                raise M15ParameterizedQueryError(
                    f"artifact binding parameter '{parameter_id}' cannot use "
                    "runtime_intermediate"
                )
            slot_id = _safe_id(raw_slot_id, name="artifact binding slot")
            if slot_id not in binding_values:
                raise M15ParameterizedQueryError(
                    f"artifact binding references unknown slot '{slot_id}'"
                )
            slot_kind = binding_kinds[slot_id]
            if schema["type"] not in _COMPATIBLE_PARAMETER_TYPES[slot_kind]:
                raise M15ParameterizedQueryError(
                    f"artifact parameter '{parameter_id}' type '{schema['type']}' "
                    f"is incompatible with binding slot '{slot_id}' kind '{slot_kind}'"
                )
            used_slots.add(slot_id)
            compiled_bindings[parameter_id] = slot_id
        missing_required = sorted(
            parameter_id
            for parameter_id, schema in parameter_schema.items()
            if schema["required"]
            and schema["binding_stage"] != "runtime_intermediate"
            and parameter_id not in compiled_bindings
        )
        if missing_required:
            raise M15ParameterizedQueryError(
                f"artifact '{role}' required binding parameters are missing: "
                f"{missing_required}"
            )
        result.append(
            {
                "role": role,
                "backend_id": _safe_id(raw["backend_id"], name="backend_id"),
                "language": _safe_id(raw["language"], name="language"),
                "parameter_schema": parameter_schema,
                "binding_parameters": compiled_bindings,
            }
        )
    if len(roles) != len(set(roles)):
        raise M15ParameterizedQueryError("artifact roles must be unique")
    return result, used_slots


def _normalized_template_dag(template: Mapping[str, Any]) -> dict[str, Any]:
    operators = []
    for raw_operator in template["operators"]:
        operator = dict(raw_operator)
        operator["constraints"] = sorted(
            [dict(item) for item in operator["constraints"]],
            key=lambda item: item["constraint_id"],
        )
        operator["required_capabilities"] = sorted(
            operator["required_capabilities"]
        )
        operators.append(operator)
    operators.sort(key=lambda item: item["operator_id"])
    return {
        "operators": operators,
        "roots": sorted(template["roots"]),
    }


def _normalized_bound_program(program: SemanticGraphProgram) -> dict[str, Any]:
    operators = []
    for raw_operator in program.to_dict()["operators"]:
        operator = dict(raw_operator)
        operator["constraints"] = sorted(
            [dict(item) for item in operator["constraints"]],
            key=lambda item: item["constraint_id"],
        )
        operator["required_capabilities"] = sorted(
            operator["required_capabilities"]
        )
        operators.append(operator)
    operators.sort(key=lambda item: item["operator_id"])
    return {
        "operators": operators,
        "roots": sorted(program.roots),
    }


def compile_m15_parameterized_query(
    spec: Mapping[str, Any],
) -> M15ParameterizedQueryContract:
    """Validate one v2 specification and materialize its typed DAG."""

    raw = _strict_object(
        spec,
        name="parameterized query spec",
        fields={
            "schema_version",
            "query_id",
            "family_id",
            "resolved_intent",
            "binding_slots",
            "semantic_template",
            "output_fields",
            "artifact_interfaces",
            "candidate_strategy_ids",
            "automatic_retries",
            "paper_result",
        },
    )
    if raw["schema_version"] != PARAMETERIZED_QUERY_SPEC_SCHEMA_VERSION:
        raise M15ParameterizedQueryError(
            "parameterized query schema_version is unsupported"
        )
    query_id = _safe_id(raw["query_id"], name="query_id")
    family_id = _safe_id(raw["family_id"], name="family_id")
    intent = raw["resolved_intent"]
    if not isinstance(intent, str) or not intent.strip():
        raise M15ParameterizedQueryError("resolved_intent must be nonempty")
    if raw["automatic_retries"] != 0 or raw["paper_result"] is not False:
        raise M15ParameterizedQueryError(
            "development parameterized query must disable retry and remain "
            "paper_result=false"
        )
    bindings, binding_values = _bindings(raw["binding_slots"])
    binding_kinds = {item["slot_id"]: item["kind"] for item in bindings}
    semantic_template, typed_program, semantic_uses = _semantic_template(
        raw["semantic_template"],
        query_id=query_id,
        binding_values=binding_values,
    )
    artifact_interfaces, artifact_uses = _artifact_interfaces(
        raw["artifact_interfaces"],
        binding_values=binding_values,
        binding_kinds=binding_kinds,
    )
    expected_slots = set(binding_values)
    if semantic_uses != expected_slots:
        missing = sorted(expected_slots - semantic_uses)
        extra = sorted(semantic_uses - expected_slots)
        raise M15ParameterizedQueryError(
            "semantic template binding coverage mismatch: "
            f"missing={missing}, extra={extra}"
        )
    if artifact_uses != expected_slots:
        missing = sorted(expected_slots - artifact_uses)
        extra = sorted(artifact_uses - expected_slots)
        raise M15ParameterizedQueryError(
            f"artifact binding coverage mismatch: missing={missing}, extra={extra}"
        )
    output_fields = _safe_ids(raw["output_fields"], name="output_fields")
    by_id = {operator.operator_id: operator for operator in typed_program.operators}
    if len(typed_program.roots) != 1:
        raise M15ParameterizedQueryError("parameterized query requires one root")
    root = by_id[typed_program.roots[0]]
    if root.kind is not SemanticOperatorKind.PROJECT:
        raise M15ParameterizedQueryError("parameterized query root must be project")
    if root.parameters.get("fields") != output_fields:
        raise M15ParameterizedQueryError(
            "root project fields disagree with output_fields"
        )
    candidate_ids = _safe_ids(
        raw["candidate_strategy_ids"], name="candidate_strategy_ids"
    )
    if len(candidate_ids) < 2:
        raise M15ParameterizedQueryError(
            "parameterized optimizer query requires at least two candidate strategies"
        )

    binding_schema = sorted(
        [
            {"slot_id": item["slot_id"], "kind": item["kind"]}
            for item in bindings
        ],
        key=lambda item: item["slot_id"],
    )
    normalized_template = _normalized_template_dag(semantic_template)
    normalized_interfaces = sorted(
        artifact_interfaces,
        key=lambda item: item["role"],
    )
    normalized_candidate_ids = sorted(candidate_ids)
    family_body = {
        "compatibility_version": FAMILY_TEMPLATE_COMPATIBILITY_VERSION,
        "binding_schema": binding_schema,
        "semantic_template": normalized_template,
        "output_fields": output_fields,
        "artifact_interfaces": normalized_interfaces,
        "candidate_strategy_ids": normalized_candidate_ids,
    }
    family_hash = content_hash(family_body)
    binding_body = sorted(
        [
            {
                "slot_id": item["slot_id"],
                "kind": item["kind"],
                "value": item["value"],
            }
            for item in bindings
        ],
        key=lambda item: item["slot_id"],
    )
    typed_program_sha256 = content_hash(_normalized_bound_program(typed_program))
    instance_body = {
        "identity_version": QUERY_INSTANCE_IDENTITY_VERSION,
        "family_compatibility_sha256": family_hash,
        "binding_sha256": content_hash(binding_body),
        "typed_program_sha256": typed_program_sha256,
    }
    payload = {
        "schema_version": PARAMETERIZED_QUERY_CONTRACT_SCHEMA_VERSION,
        "query_id": query_id,
        "family_id": family_id,
        "resolved_intent": intent,
        "semantic_template_id": semantic_template["template_id"],
        "family_template": family_body,
        "family_compatibility_sha256": family_hash,
        "bindings": binding_body,
        "binding_sha256": instance_body["binding_sha256"],
        "typed_program": typed_program.to_dict(),
        "typed_program_sha256": instance_body["typed_program_sha256"],
        "query_instance_sha256": content_hash(instance_body),
        "claim_boundary": {
            "artifact_class": "unexecuted_parameterized_query_contract",
            "backend_query_templates_bound": False,
            "workload_bundle_bound": False,
            "oracles_bound": False,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return M15ParameterizedQueryContract(payload, typed_program)


def compile_m15_parameterized_query_file(
    spec_path: str | Path,
) -> M15ParameterizedQueryContract:
    candidate = Path(spec_path)
    if candidate.is_symlink() or not candidate.is_file():
        raise M15ParameterizedQueryError(
            "parameterized query spec must be a regular non-symbolic-link file"
        )
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15ParameterizedQueryError("parameterized query spec must be an object")
    return compile_m15_parameterized_query(payload)


def write_m15_parameterized_query_contract(
    contract: M15ParameterizedQueryContract,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"parameterized query contract exists: {destination}")
    destination.write_text(
        json.dumps(
            contract.to_dict(),
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
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        contract = compile_m15_parameterized_query_file(args.spec)
        if args.output:
            write_m15_parameterized_query_contract(contract, args.output)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(contract.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
