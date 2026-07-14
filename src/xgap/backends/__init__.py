"""Backend descriptors, protocols, native-query clients, and profiles."""

from __future__ import annotations

from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    CompatibilityReport,
    CompilerFailureSpec,
    CompilerInputSpec,
    CompilerOutputSpec,
    FeatureSupport,
    SupportLevel,
    SupportReason,
    UnsupportedFeature,
)
from xgap.backends.protocol import BackendClient

__all__ = [
    "BackendCapabilityProfile",
    "BackendClient",
    "CompatibilityReport",
    "CompilerFailureSpec",
    "CompilerInputSpec",
    "CompilerOutputSpec",
    "FeatureSupport",
    "SupportLevel",
    "SupportReason",
    "UnsupportedFeature",
]
