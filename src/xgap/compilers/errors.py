"""Compiler errors for the M9 native-query boundary."""

from __future__ import annotations

from dataclasses import dataclass

from xgap.backends.capabilities import (
    CompilerFailureSpec,
    SupportLevel,
    SupportReason,
    UnsupportedFeature,
)


@dataclass(frozen=True)
class CompilerError(Exception):
    """Base class for deterministic compiler failures."""

    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class UnsupportedCompilationError(CompilerError, NotImplementedError):
    """Raised when M9 cannot safely compile a requested feature."""

    failure: CompilerFailureSpec


def unsupported_compilation(
    *,
    backend_id: str,
    language: str,
    feature_id: str,
    message: str,
    support_level: SupportLevel = SupportLevel.UNSUPPORTED,
    future_milestone_hint: str | None = "M10+",
    metadata: dict[str, object] | None = None,
) -> UnsupportedCompilationError:
    reason = SupportReason(
        code="m9_unsupported_compilation",
        message=message,
        future_milestone=future_milestone_hint,
    )
    unsupported = UnsupportedFeature(
        feature_id=feature_id,
        level=support_level,
        reason=reason,
    )
    failure = CompilerFailureSpec(
        backend_id=backend_id,
        language=language,
        unsupported_feature=unsupported,
        reason=reason,
        support_level=support_level,
        future_milestone_hint=future_milestone_hint,
        metadata=dict(metadata or {}),
    )
    return UnsupportedCompilationError(message=message, failure=failure)
