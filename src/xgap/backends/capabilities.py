"""Program-checkable backend capability profiles for M8."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from xgap.infrastructure.descriptors import BackendDescriptor, DescriptorError, JsonMap
from xgap.infrastructure.runtime import QueryArtifact


class SupportLevel(str, Enum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"

    @classmethod
    def from_value(cls, value: object) -> "SupportLevel":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            for level in cls:
                if level.value == normalized:
                    return level
        raise ValueError(f"Unsupported support level {value!r}.")


@dataclass(frozen=True)
class SupportReason:
    code: str
    message: str
    future_milestone: str | None = None

    @classmethod
    def from_value(cls, value: object) -> "SupportReason":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(code="profile_reason", message=value)
        if isinstance(value, Mapping):
            code = str(value.get("code", "profile_reason"))
            message = str(value.get("message", ""))
            future_milestone = value.get("future_milestone")
            return cls(
                code=code,
                message=message,
                future_milestone=str(future_milestone) if future_milestone is not None else None,
            )
        return cls(code="profile_reason", message=str(value))

    def to_dict(self) -> JsonMap:
        return {
            "code": self.code,
            "message": self.message,
            "future_milestone": self.future_milestone,
        }


def _tuple_of_strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    raise ValueError(f"Expected a string or list of strings, got {value!r}.")


def _mapping(value: object, field_name: str) -> JsonMap:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping.")
    return dict(value)


@dataclass(frozen=True)
class FeatureSupport:
    feature_id: str
    level: SupportLevel
    reason: SupportReason
    conditions: tuple[str, ...] = ()
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, feature_id: str, data: Mapping[str, Any]) -> "FeatureSupport":
        if not feature_id:
            raise ValueError("feature_id must be non-empty.")
        return cls(
            feature_id=feature_id,
            level=SupportLevel.from_value(data.get("level")),
            reason=SupportReason.from_value(data.get("reason", "")),
            conditions=_tuple_of_strings(data.get("conditions")),
            metadata=_mapping(data.get("metadata"), "FeatureSupport metadata"),
        )

    def to_dict(self) -> JsonMap:
        return {
            "feature_id": self.feature_id,
            "level": self.level.value,
            "reason": self.reason.to_dict(),
            "conditions": list(self.conditions),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class UnsupportedFeature:
    feature_id: str
    reason: SupportReason
    level: SupportLevel = SupportLevel.UNSUPPORTED
    conditions: tuple[str, ...] = ()

    @classmethod
    def from_feature_support(cls, support: FeatureSupport) -> "UnsupportedFeature":
        return cls(
            feature_id=support.feature_id,
            reason=support.reason,
            level=support.level,
            conditions=support.conditions,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnsupportedFeature":
        return cls(
            feature_id=str(data["feature_id"]),
            reason=SupportReason.from_value(data.get("reason", "")),
            level=SupportLevel.from_value(data.get("level", SupportLevel.UNSUPPORTED.value)),
            conditions=_tuple_of_strings(data.get("conditions")),
        )

    def to_dict(self) -> JsonMap:
        return {
            "feature_id": self.feature_id,
            "level": self.level.value,
            "reason": self.reason.to_dict(),
            "conditions": list(self.conditions),
        }


@dataclass(frozen=True)
class BackendCapabilityProfile:
    backend_id: str
    engine: str
    language: str
    data_model: str
    version: int
    feature_namespace: str
    features: dict[str, FeatureSupport]
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_descriptor(cls, descriptor: BackendDescriptor) -> "BackendCapabilityProfile":
        profile_data = descriptor.capabilities.get("capability_profile")
        if not isinstance(profile_data, Mapping):
            raise DescriptorError(
                f"Backend descriptor '{descriptor.id}' has no capability_profile mapping."
            )
        return cls.from_dict(
            {
                "backend_id": descriptor.id,
                "engine": descriptor.engine,
                "language": descriptor.language,
                "data_model": descriptor.data_model,
                **dict(profile_data),
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackendCapabilityProfile":
        features_data = data.get("features")
        if not isinstance(features_data, Mapping):
            raise ValueError("BackendCapabilityProfile features must be a mapping.")
        features = {
            str(feature_id): FeatureSupport.from_dict(str(feature_id), feature_data)
            for feature_id, feature_data in sorted(features_data.items())
            if isinstance(feature_data, Mapping)
        }
        if len(features) != len(features_data):
            raise ValueError("Every capability profile feature must be a mapping.")
        return cls(
            backend_id=str(data["backend_id"]),
            engine=str(data["engine"]),
            language=str(data["language"]),
            data_model=str(data["data_model"]),
            version=int(data.get("version", 1)),
            feature_namespace=str(data.get("feature_namespace", "xgap.path_gpc")),
            features=features,
            metadata=_mapping(data.get("metadata"), "BackendCapabilityProfile metadata"),
        )

    def feature(self, feature_id: str) -> FeatureSupport | None:
        return self.features.get(feature_id)

    def to_dict(self) -> JsonMap:
        return {
            "backend_id": self.backend_id,
            "engine": self.engine,
            "language": self.language,
            "data_model": self.data_model,
            "version": self.version,
            "feature_namespace": self.feature_namespace,
            "features": {
                feature_id: self.features[feature_id].to_dict()
                for feature_id in sorted(self.features)
            },
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True)
class CompatibilityReport:
    backend_id: str
    feature_id: str
    level: SupportLevel
    reason: SupportReason
    conditions: tuple[str, ...] = ()
    unsupported_features: tuple[UnsupportedFeature, ...] = ()
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompatibilityReport":
        return cls(
            backend_id=str(data["backend_id"]),
            feature_id=str(data["feature_id"]),
            level=SupportLevel.from_value(data["level"]),
            reason=SupportReason.from_value(data.get("reason", "")),
            conditions=_tuple_of_strings(data.get("conditions")),
            unsupported_features=tuple(
                UnsupportedFeature.from_dict(item)
                for item in data.get("unsupported_features", [])
            ),
            metadata=_mapping(data.get("metadata"), "CompatibilityReport metadata"),
        )

    @property
    def supported(self) -> bool:
        return self.level is SupportLevel.SUPPORTED

    def to_dict(self) -> JsonMap:
        return {
            "backend_id": self.backend_id,
            "feature_id": self.feature_id,
            "level": self.level.value,
            "reason": self.reason.to_dict(),
            "conditions": list(self.conditions),
            "unsupported_features": [
                feature.to_dict() for feature in self.unsupported_features
            ],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True)
class CompilerInputSpec:
    logical_plan_id: str
    logical_plan_kind: str
    target_backend_id: str
    target_language: str
    expected_result_model: str
    required_features: tuple[str, ...] = ()
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompilerInputSpec":
        return cls(
            logical_plan_id=str(data["logical_plan_id"]),
            logical_plan_kind=str(data["logical_plan_kind"]),
            target_backend_id=str(data["target_backend_id"]),
            target_language=str(data["target_language"]),
            expected_result_model=str(data["expected_result_model"]),
            required_features=_tuple_of_strings(data.get("required_features")),
            metadata=_mapping(data.get("metadata"), "CompilerInputSpec metadata"),
        )

    def to_dict(self) -> JsonMap:
        return {
            "logical_plan_id": self.logical_plan_id,
            "logical_plan_kind": self.logical_plan_kind,
            "target_backend_id": self.target_backend_id,
            "target_language": self.target_language,
            "expected_result_model": self.expected_result_model,
            "required_features": list(self.required_features),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CompilerOutputSpec:
    target_backend_id: str
    artifact: QueryArtifact
    result_model: str
    semantic_assumptions: tuple[str, ...] = ()
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompilerOutputSpec":
        return cls(
            target_backend_id=str(data["target_backend_id"]),
            artifact=QueryArtifact.from_dict(data["artifact"]),
            result_model=str(data["result_model"]),
            semantic_assumptions=_tuple_of_strings(data.get("semantic_assumptions")),
            metadata=_mapping(data.get("metadata"), "CompilerOutputSpec metadata"),
        )

    def to_dict(self) -> JsonMap:
        return {
            "target_backend_id": self.target_backend_id,
            "artifact": self.artifact.to_dict(),
            "result_model": self.result_model,
            "semantic_assumptions": list(self.semantic_assumptions),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CompilerFailureSpec:
    backend_id: str
    language: str
    unsupported_feature: UnsupportedFeature
    reason: SupportReason
    support_level: SupportLevel
    future_milestone_hint: str | None = None
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompilerFailureSpec":
        return cls(
            backend_id=str(data["backend_id"]),
            language=str(data["language"]),
            unsupported_feature=UnsupportedFeature.from_dict(data["unsupported_feature"]),
            reason=SupportReason.from_value(data.get("reason", "")),
            support_level=SupportLevel.from_value(data["support_level"]),
            future_milestone_hint=data.get("future_milestone_hint"),
            metadata=_mapping(data.get("metadata"), "CompilerFailureSpec metadata"),
        )

    def to_dict(self) -> JsonMap:
        return {
            "backend_id": self.backend_id,
            "language": self.language,
            "unsupported_feature": self.unsupported_feature.to_dict(),
            "reason": self.reason.to_dict(),
            "support_level": self.support_level.value,
            "future_milestone_hint": self.future_milestone_hint,
            "metadata": dict(self.metadata),
        }
