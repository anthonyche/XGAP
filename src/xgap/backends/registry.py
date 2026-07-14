"""Descriptor registry for backend infrastructure."""

from __future__ import annotations

from pathlib import Path

from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.infrastructure.descriptors import BackendDescriptor


_REGISTRY: dict[str, BackendDescriptor] = {}


def load_descriptor(path: str | Path) -> BackendDescriptor:
    """Load one backend descriptor from a YAML file."""

    descriptor = BackendDescriptor.from_yaml(path)
    _REGISTRY[descriptor.id] = descriptor
    return descriptor


def load_descriptors(directory: str | Path) -> list[BackendDescriptor]:
    """Load all YAML descriptors from a directory into the registry."""

    descriptor_dir = Path(directory)
    descriptors: list[BackendDescriptor] = []
    for path in sorted([*descriptor_dir.glob("*.yaml"), *descriptor_dir.glob("*.yml")]):
        descriptors.append(load_descriptor(path))
    return descriptors


def get(backend_id: str) -> BackendDescriptor:
    """Return a loaded descriptor by id."""

    try:
        return _REGISTRY[backend_id]
    except KeyError as exc:
        raise KeyError(f"Backend descriptor '{backend_id}' has not been loaded") from exc


def list_backends() -> list[BackendDescriptor]:
    """Return loaded descriptors in deterministic id order."""

    return [_REGISTRY[key] for key in sorted(_REGISTRY)]


def find_by_language(language: str) -> list[BackendDescriptor]:
    """Return loaded descriptors using a specific native language."""

    return [
        descriptor
        for descriptor in list_backends()
        if descriptor.language.lower() == language.lower()
    ]


def get_capability_profile(backend_id: str) -> BackendCapabilityProfile:
    """Return a program-checkable capability profile for a loaded backend."""

    return BackendCapabilityProfile.from_descriptor(get(backend_id))
