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
from xgap.backends.mapping import BackendMappingError, MappedNativeTerm, RdfBackendMapping
from xgap.backends.protocol import BackendClient

__all__ = [
    "BackendCapabilityProfile",
    "BackendClient",
    "BackendMappingError",
    "CompatibilityReport",
    "CompilerFailureSpec",
    "CompilerInputSpec",
    "CompilerOutputSpec",
    "FeatureSupport",
    "MappedNativeTerm",
    "RdfBackendMapping",
    "SupportLevel",
    "SupportReason",
    "UnsupportedFeature",
]
