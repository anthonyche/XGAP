"""Deterministic natural-language intake for typed semantic programs.

The intake compiler is deliberately narrower than a general NL parser.  A
versioned template declares every phrase that may bind a hole or constraint,
and compilation fails closed when a required phrase is absent or ambiguous.
It never emits backend-native query text and never chooses a candidate ID.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.semantic.program import (
    ConstraintPolicy,
    SemanticConstraint,
    SemanticGraphProgram,
    SemanticHole,
    SemanticHoleKind,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticProgramError,
    SemanticValueKind,
)


INTAKE_SCHEMA_VERSION = "m15-e3-semantic-intake-template-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_FORBIDDEN_NATIVE_KEYS = frozenset(
    {"cypher", "sparql", "gql", "native_query", "native_query_text", "query_text"}
)


class SemanticIntakeError(SemanticProgramError):
    """Raised when a request cannot be compiled by the declared template."""


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_semantic_mention(value: str) -> str:
    """Return the exact-match normalization shared by intake and providers."""

    if not isinstance(value, str) or not value.strip():
        raise SemanticIntakeError("semantic mention must be nonempty")
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(folded.split())


def _contains_phrase(question: str, phrase: str) -> bool:
    question_normalized = normalize_semantic_mention(question)
    phrase_normalized = normalize_semantic_mention(phrase)
    if _HAN.search(phrase_normalized):
        compact_question = re.sub(r"[\W_]+", "", question_normalized)
        compact_phrase = re.sub(r"[\W_]+", "", phrase_normalized)
        return bool(compact_phrase) and compact_phrase in compact_question
    escaped = re.escape(phrase_normalized).replace(r"\ ", r"\s+")
    return (
        re.search(
            rf"(?<![a-z0-9]){escaped}(?![a-z0-9])",
            question_normalized,
        )
        is not None
    )


def _safe_json_mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticIntakeError(f"{name} must be an object")

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise SemanticIntakeError(f"{name} keys must be strings")
                if key.casefold() in _FORBIDDEN_NATIVE_KEYS:
                    raise SemanticIntakeError(
                        "semantic intake templates must not contain native query text"
                    )
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    normalized = dict(value)
    visit(normalized)
    try:
        json.dumps(normalized, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SemanticIntakeError(f"{name} must contain finite JSON") from exc
    return normalized


def _string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise SemanticIntakeError(f"{name} must be a nonempty array")
    result = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in result):
        raise SemanticIntakeError(f"{name} must contain nonempty strings")
    normalized = tuple(normalize_semantic_mention(item) for item in result)
    if len(set(normalized)) != len(normalized):
        raise SemanticIntakeError(f"{name} must be unique after normalization")
    return result


@dataclass(frozen=True)
class IntakePhraseMatch:
    binding_id: str
    binding_kind: str
    declared_phrase: str
    normalized_phrase: str

    def to_dict(self) -> dict[str, str]:
        return {
            "binding_id": self.binding_id,
            "binding_kind": self.binding_kind,
            "declared_phrase": self.declared_phrase,
            "normalized_phrase": self.normalized_phrase,
        }


@dataclass(frozen=True)
class DeterministicIntakeResult:
    program: SemanticGraphProgram
    template_id: str
    template_version: str
    template_sha256: str
    question_sha256: str
    phrase_matches: tuple[IntakePhraseMatch, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "m15-e3-semantic-intake-result-v1",
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_sha256": self.template_sha256,
            "question_sha256": self.question_sha256,
            "matching_policy": "declared_exact_phrase_longest_unique_v1",
            "phrase_matches": [item.to_dict() for item in self.phrase_matches],
            "program": self.program.to_dict(),
            "external_calls": 0,
            "native_query_text_emitted": False,
        }


@dataclass(frozen=True)
class _HoleTemplate:
    hole_id: str
    kind: SemanticHoleKind
    phrases: tuple[str, ...]
    required: bool


@dataclass(frozen=True)
class _ConstraintTemplate:
    constraint_id: str
    operator_id: str
    expression: str
    policy: ConstraintPolicy
    phrases: tuple[str, ...]
    required: bool


def _match_declared_phrase(
    question: str,
    phrases: Sequence[str],
    *,
    binding_id: str,
    required: bool,
) -> str | None:
    matches = [phrase for phrase in phrases if _contains_phrase(question, phrase)]
    if not matches:
        if required:
            raise SemanticIntakeError(
                f"required binding '{binding_id}' has no declared phrase in the request"
            )
        return None
    longest = max(len(normalize_semantic_mention(item)) for item in matches)
    winners = {
        normalize_semantic_mention(item): item
        for item in matches
        if len(normalize_semantic_mention(item)) == longest
    }
    if len(winners) != 1:
        raise SemanticIntakeError(
            f"binding '{binding_id}' has ambiguous equal-specificity phrase matches"
        )
    return next(iter(winners.values()))


class DeterministicSemanticIntake:
    """Compile only requests covered by one immutable semantic template."""

    def __init__(
        self,
        template: Mapping[str, Any],
        *,
        artifact_sha256: str | None = None,
    ) -> None:
        payload = _safe_json_mapping(template, name="semantic intake template")
        required = {
            "schema_version",
            "template_id",
            "template_version",
            "holes",
            "constraints",
            "operators",
            "roots",
            "metadata",
        }
        if set(payload) != required:
            raise SemanticIntakeError(
                "semantic intake template fields do not match the v1 contract"
            )
        if payload["schema_version"] != INTAKE_SCHEMA_VERSION:
            raise SemanticIntakeError("semantic intake template schema is unsupported")
        for name in ("template_id", "template_version"):
            if not isinstance(payload[name], str) or not _SAFE_ID.fullmatch(payload[name]):
                raise SemanticIntakeError(f"{name} is invalid")
        computed_sha256 = _json_sha256(payload)
        if artifact_sha256 is not None:
            if not _SHA256.fullmatch(artifact_sha256):
                raise SemanticIntakeError("artifact_sha256 must be a SHA-256 digest")
            computed_sha256 = artifact_sha256

        raw_holes = payload["holes"]
        if not isinstance(raw_holes, list) or not raw_holes:
            raise SemanticIntakeError("semantic intake template requires holes")
        holes: list[_HoleTemplate] = []
        for raw in raw_holes:
            if not isinstance(raw, Mapping) or set(raw) != {
                "hole_id",
                "kind",
                "phrases",
                "required",
            }:
                raise SemanticIntakeError("hole template fields are invalid")
            try:
                kind = SemanticHoleKind(raw["kind"])
            except (TypeError, ValueError) as exc:
                raise SemanticIntakeError("hole template kind is invalid") from exc
            hole_id = raw["hole_id"]
            if not isinstance(hole_id, str) or not _SAFE_ID.fullmatch(hole_id):
                raise SemanticIntakeError("hole template id is invalid")
            if not isinstance(raw["required"], bool):
                raise SemanticIntakeError("hole template required must be boolean")
            holes.append(
                _HoleTemplate(
                    hole_id=hole_id,
                    kind=kind,
                    phrases=_string_tuple(raw["phrases"], name=f"{hole_id}.phrases"),
                    required=raw["required"],
                )
            )
        if len({item.hole_id for item in holes}) != len(holes):
            raise SemanticIntakeError("hole template IDs must be unique")

        raw_constraints = payload["constraints"]
        if not isinstance(raw_constraints, list):
            raise SemanticIntakeError("constraints must be an array")
        constraints: list[_ConstraintTemplate] = []
        for raw in raw_constraints:
            if not isinstance(raw, Mapping) or set(raw) != {
                "constraint_id",
                "operator_id",
                "expression",
                "policy",
                "phrases",
                "required",
            }:
                raise SemanticIntakeError("constraint template fields are invalid")
            try:
                policy = ConstraintPolicy(raw["policy"])
            except (TypeError, ValueError) as exc:
                raise SemanticIntakeError("constraint policy is invalid") from exc
            values = (raw["constraint_id"], raw["operator_id"], raw["expression"])
            if not all(isinstance(item, str) and item.strip() for item in values):
                raise SemanticIntakeError("constraint identifiers and expression are invalid")
            if not isinstance(raw["required"], bool):
                raise SemanticIntakeError("constraint required must be boolean")
            constraints.append(
                _ConstraintTemplate(
                    constraint_id=raw["constraint_id"],
                    operator_id=raw["operator_id"],
                    expression=raw["expression"],
                    policy=policy,
                    phrases=_string_tuple(
                        raw["phrases"],
                        name=f"{raw['constraint_id']}.phrases",
                    ),
                    required=raw["required"],
                )
            )
        if len({item.constraint_id for item in constraints}) != len(constraints):
            raise SemanticIntakeError("constraint template IDs must be unique")

        raw_operators = payload["operators"]
        if not isinstance(raw_operators, list) or not raw_operators:
            raise SemanticIntakeError("semantic intake template requires operators")
        operator_payloads: list[dict[str, Any]] = []
        for raw in raw_operators:
            if not isinstance(raw, Mapping) or set(raw) != {
                "operator_id",
                "kind",
                "input_ids",
                "input_kinds",
                "output_kind",
                "parameters",
                "required_capabilities",
                "hole_ids",
            }:
                raise SemanticIntakeError("operator template fields are invalid")
            operator_payloads.append(dict(raw))
        operator_ids = [item["operator_id"] for item in operator_payloads]
        if not all(isinstance(item, str) and _SAFE_ID.fullmatch(item) for item in operator_ids):
            raise SemanticIntakeError("operator template ID is invalid")
        if len(set(operator_ids)) != len(operator_ids):
            raise SemanticIntakeError("operator template IDs must be unique")
        if any(item.operator_id not in operator_ids for item in constraints):
            raise SemanticIntakeError("constraint references an unknown operator")

        declared_hole_ids = {item.hole_id for item in holes}
        bound_hole_ids: list[str] = []
        for raw in operator_payloads:
            hole_ids = raw["hole_ids"]
            if not isinstance(hole_ids, list) or not all(
                isinstance(item, str) for item in hole_ids
            ):
                raise SemanticIntakeError("operator hole_ids must be an array of strings")
            if len(set(hole_ids)) != len(hole_ids):
                raise SemanticIntakeError("operator hole_ids must be unique")
            if not set(hole_ids).issubset(declared_hole_ids):
                raise SemanticIntakeError("operator references an unknown semantic hole")
            bound_hole_ids.extend(hole_ids)
        if set(bound_hole_ids) != declared_hole_ids or len(bound_hole_ids) != len(
            declared_hole_ids
        ):
            raise SemanticIntakeError(
                "every semantic hole must be owned by exactly one operator"
            )

        roots = _string_tuple(payload["roots"], name="roots")
        if not set(roots).issubset(set(operator_ids)):
            raise SemanticIntakeError("roots reference an unknown operator")

        self._payload = payload
        self._holes = tuple(holes)
        self._constraints = tuple(constraints)
        self._operators = tuple(operator_payloads)
        self._roots = roots
        self._metadata = _safe_json_mapping(payload["metadata"], name="metadata")
        self.template_id = payload["template_id"]
        self.template_version = payload["template_version"]
        self.artifact_sha256 = computed_sha256

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> "DeterministicSemanticIntake":
        artifact_path = Path(path)
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise SemanticIntakeError("semantic intake artifact must be a regular file")
        if artifact_path.stat().st_size > 4 * 1024 * 1024:
            raise SemanticIntakeError("semantic intake artifact exceeds 4 MiB")
        digest = _file_sha256(artifact_path)
        if expected_sha256 is not None and digest != expected_sha256:
            raise SemanticIntakeError("semantic intake artifact SHA-256 mismatch")
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SemanticIntakeError("semantic intake artifact is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise SemanticIntakeError("semantic intake artifact must contain an object")
        return cls(payload, artifact_sha256=digest)

    def compile(self, question: str) -> DeterministicIntakeResult:
        if not isinstance(question, str) or not question.strip():
            raise SemanticIntakeError("natural-language request must be nonempty")
        question_sha256 = hashlib.sha256(question.encode("utf-8")).hexdigest()
        phrase_matches: list[IntakePhraseMatch] = []
        holes: list[SemanticHole] = []
        for template in self._holes:
            phrase = _match_declared_phrase(
                question,
                template.phrases,
                binding_id=template.hole_id,
                required=template.required,
            )
            if phrase is None:
                continue
            holes.append(
                SemanticHole(
                    hole_id=template.hole_id,
                    kind=template.kind,
                    mention=phrase,
                    required=template.required,
                    candidates=(),
                )
            )
            phrase_matches.append(
                IntakePhraseMatch(
                    binding_id=template.hole_id,
                    binding_kind="hole",
                    declared_phrase=phrase,
                    normalized_phrase=normalize_semantic_mention(phrase),
                )
            )

        constraints_by_operator: dict[str, list[SemanticConstraint]] = {
            raw["operator_id"]: [] for raw in self._operators
        }
        for template in self._constraints:
            phrase = _match_declared_phrase(
                question,
                template.phrases,
                binding_id=template.constraint_id,
                required=template.required,
            )
            if phrase is None:
                continue
            constraints_by_operator[template.operator_id].append(
                SemanticConstraint(
                    constraint_id=template.constraint_id,
                    expression=template.expression,
                    policy=template.policy,
                )
            )
            phrase_matches.append(
                IntakePhraseMatch(
                    binding_id=template.constraint_id,
                    binding_kind="constraint",
                    declared_phrase=phrase,
                    normalized_phrase=normalize_semantic_mention(phrase),
                )
            )

        operators: list[SemanticOperator] = []
        for raw in self._operators:
            try:
                kind = SemanticOperatorKind(raw["kind"])
                input_kinds = tuple(
                    SemanticValueKind(item) for item in raw["input_kinds"]
                )
                output_kind = SemanticValueKind(raw["output_kind"])
            except (TypeError, ValueError) as exc:
                raise SemanticIntakeError("operator kind contract is invalid") from exc
            parameters = _safe_json_mapping(
                raw["parameters"],
                name=f"{raw['operator_id']}.parameters",
            )
            parameters["semantic_hole_ids"] = list(raw["hole_ids"])
            operators.append(
                SemanticOperator(
                    operator_id=raw["operator_id"],
                    kind=kind,
                    input_ids=tuple(raw["input_ids"]),
                    input_kinds=input_kinds,
                    output_kind=output_kind,
                    parameters=parameters,
                    constraints=tuple(constraints_by_operator[raw["operator_id"]]),
                    required_capabilities=tuple(raw["required_capabilities"]),
                )
            )

        program_id = f"{self.template_id}:{question_sha256[:16]}"
        program = SemanticGraphProgram(
            program_id=program_id,
            operators=tuple(operators),
            roots=self._roots,
            holes=tuple(holes),
            metadata={
                **self._metadata,
                "intake_schema_version": INTAKE_SCHEMA_VERSION,
                "intake_template_id": self.template_id,
                "intake_template_version": self.template_version,
                "intake_template_sha256": self.artifact_sha256,
                "question_sha256": question_sha256,
                "matching_policy": "declared_exact_phrase_longest_unique_v1",
                "external_calls": 0,
                "native_query_text_emitted": False,
            },
        )
        return DeterministicIntakeResult(
            program=program,
            template_id=self.template_id,
            template_version=self.template_version,
            template_sha256=self.artifact_sha256,
            question_sha256=question_sha256,
            phrase_matches=tuple(phrase_matches),
        )
