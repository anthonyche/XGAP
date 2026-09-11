"""Read-only, caller-pinned resolution snapshots. No builder imports or writes."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from xgap.semantic.binding import SemanticBindingValue
from xgap.semantic.program import SemanticHoleKind
from xgap.tools.artifact_resolution import ArtifactCatalogProvider, ArtifactOntologyProvider


SCHEMA = "xgap-frozen-resolution-bundle-v1"
FILES = frozenset(("catalog.json", "bindings.json", "ontology.json"))
MAX_FILE_BYTES = 16 * 1024 * 1024


def content_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Prepared artifact must be a regular file: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Resolution artifact exceeds 16 MiB")
    return data


def binding_values(raw) -> dict[str, SemanticBindingValue]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Binding values require a nonempty object")
    result = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not name or not isinstance(spec, dict):
            raise ValueError("Binding entries need candidate IDs and typed values")
        if not {"kind", "value"} <= spec.keys() or spec.keys() - {"kind", "value", "identity_property"}:
            raise ValueError("Binding value fields are invalid")
        identity = spec.get("identity_property", "id")
        if not isinstance(identity, str) or not identity:
            raise ValueError("Binding identity_property must be a nonempty string")
        result[name] = SemanticBindingValue(SemanticHoleKind(spec["kind"]), spec["value"], identity)
    return result


@dataclass(frozen=True)
class FrozenResolutionBundle:
    bundle_hash: str
    catalog: ArtifactCatalogProvider
    bindings: Mapping[str, SemanticBindingValue]
    ontology: ArtifactOntologyProvider | None = None

    @property
    def identity(self) -> dict:
        return {"schema_version": SCHEMA, "bundle_hash": self.bundle_hash,
                "catalog_id": self.catalog.catalog_id, "catalog_version": self.catalog.catalog_version,
                "ontology_source": self.ontology.source_id if self.ontology else None}

    @classmethod
    def load(cls, root: str | Path, *, expected_bundle_hash: str) -> "FrozenResolutionBundle":
        root = Path(root)
        manifest = json.loads(read_file(root / "manifest.json"))
        if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "files", "bundle_hash"}:
            raise ValueError("Frozen resolution manifest fields are invalid")
        if manifest["schema_version"] != SCHEMA:
            raise ValueError("Unsupported frozen resolution schema")
        files = manifest["files"]
        if not isinstance(files, dict) or not {"catalog.json", "bindings.json"} <= files.keys() or files.keys() - FILES:
            raise ValueError("Frozen resolution files are incomplete or unknown")
        digest = content_hash({"schema_version": SCHEMA, "files": files})
        if digest != manifest["bundle_hash"] or digest != expected_bundle_hash:
            raise ValueError("Frozen resolution bundle version mismatch")
        data = {}
        for name, expected in files.items():
            data[name] = read_file(root / name)
            if hashlib.sha256(data[name]).hexdigest() != expected:
                raise ValueError(f"Frozen resolution hash mismatch: {name}")
        catalog = ArtifactCatalogProvider(root / "catalog.json", expected_sha256=files["catalog.json"])
        ontology = (ArtifactOntologyProvider(root / "ontology.json", expected_sha256=files["ontology.json"])
                    if "ontology.json" in files else None)
        bindings = binding_values(json.loads(data["bindings.json"]))
        kinds = dict(catalog.candidate_kinds)
        if ontology:
            for name, kind in ontology.candidate_kinds.items():
                if name in kinds and kinds[name] is not kind:
                    raise ValueError("Catalog/ontology candidate kinds conflict")
                kinds[name] = kind
        if set(bindings) != set(kinds) or any(bindings[name].kind is not kind for name, kind in kinds.items()):
            raise ValueError("Catalog/ontology candidates and typed bindings must agree exactly")
        return cls(digest, catalog, MappingProxyType(bindings), ontology)
