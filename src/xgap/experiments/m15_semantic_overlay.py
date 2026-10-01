"""Materialize currently supported relaxed interpretations as an overlay.

F2C7B1 consumes one verified F2C3 bundle and the F2C7A readiness audit.  It
adds only semantic classes marked ``overlay_generation_ready`` to a new,
fully regenerable parameterized workload bundle.  The base bundle is never
modified.  Unsupported predicate and path interpretations remain blocked.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    M15ParameterizedWorkloadSpec,
    generate_m15_parameterized_workload_bundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_execution_readiness import (
    M15SemanticExecutionReadiness,
    audit_m15_semantic_execution_readiness,
)
from xgap.experiments.m15_semantic_frontier import M15SemanticRelaxationCatalog


SEMANTIC_OVERLAY_SCHEMA_VERSION = "m15-f2c7-semantic-overlay-v1"
SEMANTIC_OVERLAY_GENERATOR_VERSION = "m15-f2c7-semantic-overlay-generator-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SHARED_DATA_FILES = ("load_fuseki.ttl", "load_neo4j.cypher")


class M15SemanticOverlayError(ValueError):
    """Raised before publication when a semantic overlay is invalid."""


@dataclass(frozen=True)
class M15SemanticOverlayBundle:
    root: Path
    workload_bundle: M15ParameterizedWorkloadBundle
    manifest: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.manifest))


def _json_text(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15SemanticOverlayError(f"{name} must be a safe identifier")
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M15SemanticOverlayError(
            "semantic overlay manifest must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15SemanticOverlayError("semantic overlay manifest must be an object")
    return dict(payload)


def _select_overlay_classes(
    readiness: M15SemanticExecutionReadiness,
) -> list[dict[str, Any]]:
    selected = [
        dict(item)
        for item in readiness.to_dict()["interpretations"]
        if item["status"] == "overlay_generation_ready"
    ]
    if not selected:
        raise M15SemanticOverlayError(
            "readiness audit has no overlay_generation_ready semantic class"
        )
    if any(item["blockers"] for item in selected):
        raise M15SemanticOverlayError(
            "overlay_generation_ready class cannot contain blockers"
        )
    return sorted(selected, key=lambda item: item["semantic_class_id"])


def _overlay_query_id(base_query_id: str, semantic_class_id: str) -> str:
    suffix = semantic_class_id.removeprefix("m15-class-")
    return _safe_id(
        f"{base_query_id}-relaxed-{suffix}",
        name="overlay query_id",
    )


def _extended_spec(
    base_bundle: M15ParameterizedWorkloadBundle,
    base_query_id: str,
    selected: Sequence[Mapping[str, Any]],
) -> tuple[M15ParameterizedWorkloadSpec, list[dict[str, Any]]]:
    payload = base_bundle.spec.to_dict()
    additions: list[dict[str, Any]] = []
    for semantic_class in selected:
        semantic_class_id = _safe_id(
            semantic_class["semantic_class_id"], name="semantic_class_id"
        )
        bindings = semantic_class.get("bindings")
        if not isinstance(bindings, list):
            raise M15SemanticOverlayError("semantic class bindings are invalid")
        binding_values = {
            _safe_id(item["slot_id"], name="binding slot_id"): item["value"]
            for item in bindings
        }
        query_id = _overlay_query_id(base_query_id, semantic_class_id)
        record = {
            "query_id": query_id,
            "resolved_intent": (
                f"Development relaxed interpretation {semantic_class_id} "
                f"derived from {base_query_id}."
            ),
            "split_role": "heldout_instance",
            "binding_values": binding_values,
        }
        payload["query_instances"].append(record)
        additions.append(
            {
                "semantic_class_id": semantic_class_id,
                "semantic_deviation": semantic_class["semantic_deviation"],
                "expected_query_instance_sha256": semantic_class[
                    "query_instance_sha256"
                ],
                "query_id": query_id,
                "binding_values": binding_values,
            }
        )
    return M15ParameterizedWorkloadSpec.from_dict(payload), additions


def _manifest(
    *,
    base_bundle: M15ParameterizedWorkloadBundle,
    overlay_bundle: M15ParameterizedWorkloadBundle,
    base_query_id: str,
    readiness: M15SemanticExecutionReadiness,
    additions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if (
        base_bundle.manifest["family_compatibility_sha256"]
        != overlay_bundle.manifest["family_compatibility_sha256"]
    ):
        raise M15SemanticOverlayError("overlay changed query-family compatibility")
    shared_hashes: dict[str, dict[str, Any]] = {}
    for relative_path in _SHARED_DATA_FILES:
        base_hash = base_bundle.manifest["files_sha256"][relative_path]
        overlay_hash = overlay_bundle.manifest["files_sha256"][relative_path]
        if base_hash != overlay_hash:
            raise M15SemanticOverlayError(
                f"overlay changed shared data artifact '{relative_path}'"
            )
        shared_hashes[relative_path] = {
            "base_sha256": base_hash,
            "overlay_sha256": overlay_hash,
            "identical": True,
        }
    overlay_by_query = {
        item["query_id"]: item for item in overlay_bundle.manifest["instances"]
    }
    records: list[dict[str, Any]] = []
    for addition in additions:
        query_id = addition["query_id"]
        if query_id not in overlay_by_query:
            raise M15SemanticOverlayError(
                f"overlay query '{query_id}' is absent from generated bundle"
            )
        generated = overlay_by_query[query_id]
        if (
            generated["query_instance_sha256"]
            != addition["expected_query_instance_sha256"]
        ):
            raise M15SemanticOverlayError(
                f"overlay query '{query_id}' changed semantic instance identity"
            )
        records.append(
            {
                "semantic_class_id": addition["semantic_class_id"],
                "semantic_deviation": addition["semantic_deviation"],
                "query_id": query_id,
                "query_instance_sha256": generated[
                    "query_instance_sha256"
                ],
                "binding_sha256": generated["binding_sha256"],
                "oracle_counts": dict(generated["oracle_counts"]),
            }
        )
    readiness_payload = readiness.to_dict()
    body = {
        "schema_version": SEMANTIC_OVERLAY_SCHEMA_VERSION,
        "generator_version": SEMANTIC_OVERLAY_GENERATOR_VERSION,
        "base_workload_id": base_bundle.manifest["workload_id"],
        "base_workload_bundle_content_sha256": base_bundle.manifest[
            "bundle_content_sha256"
        ],
        "overlay_workload_bundle_content_sha256": overlay_bundle.manifest[
            "bundle_content_sha256"
        ],
        "base_query_id": base_query_id,
        "family_compatibility_sha256": base_bundle.manifest[
            "family_compatibility_sha256"
        ],
        "semantic_readiness_sha256": readiness_payload["readiness_sha256"],
        "semantic_solution_space_sha256": readiness_payload[
            "semantic_solution_space_sha256"
        ],
        "semantic_catalog_sha256": readiness_payload[
            "semantic_catalog_sha256"
        ],
        "base_query_instance_count": len(base_bundle.manifest["instances"]),
        "overlay_query_instance_count": len(records),
        "total_query_instance_count": len(overlay_bundle.manifest["instances"]),
        "overlay_instances": sorted(records, key=lambda item: item["query_id"]),
        "shared_data_artifacts": dict(sorted(shared_hashes.items())),
        "blocked_semantic_class_count": readiness_payload["counts"]["blocked"],
        "blocked_classes_materialized": False,
        "claim_boundary": {
            "artifact_class": "unexecuted_semantic_interpretation_overlay",
            "only_readiness_approved_classes_materialized": True,
            "base_bundle_mutated": False,
            "relaxed_backend_artifacts_bound": True,
            "relaxed_oracles_bound": True,
            "backend_calls_made": 0,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "contains_measurements": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    return {**body, "overlay_sha256": content_hash(body)}


def generate_m15_semantic_overlay_bundle(
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    base_query_id: str,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    destination: str | Path,
) -> M15SemanticOverlayBundle:
    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    selected_query_id = _safe_id(base_query_id, name="base_query_id")
    readiness = audit_m15_semantic_execution_readiness(
        bundle=selected_base,
        query_id=selected_query_id,
        catalog=catalog,
    )
    selected_classes = _select_overlay_classes(readiness)
    extended_spec, additions = _extended_spec(
        selected_base, selected_query_id, selected_classes
    )
    destination_path = Path(destination).resolve()
    if destination_path.exists():
        raise FileExistsError(
            f"semantic overlay destination exists: {destination_path}"
        )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.tmp-",
            dir=destination_path.parent,
        )
    )
    try:
        overlay_bundle = generate_m15_parameterized_workload_bundle(
            workload_spec=extended_spec,
            query_template_spec=selected_base.path(
                "parameterized_query_template.json"
            ),
            backend_template_root=selected_base.root / "templates",
            destination=temporary / "parameterized-workload-bundle",
        )
        manifest = _manifest(
            base_bundle=selected_base,
            overlay_bundle=overlay_bundle,
            base_query_id=selected_query_id,
            readiness=readiness,
            additions=additions,
        )
        (temporary / "overlay_manifest.json").write_text(
            _json_text(manifest), encoding="utf-8"
        )
        load_m15_semantic_overlay_bundle(
            temporary,
            base_bundle=selected_base,
            catalog=catalog,
        )
        os.replace(temporary, destination_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return load_m15_semantic_overlay_bundle(
        destination_path,
        base_bundle=selected_base,
        catalog=catalog,
    )


def load_m15_semantic_overlay_bundle(
    root: str | Path,
    *,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
) -> M15SemanticOverlayBundle:
    overlay_root = Path(root).resolve()
    if overlay_root.is_symlink() or not overlay_root.is_dir():
        raise M15SemanticOverlayError(
            "semantic overlay root must be a regular directory"
        )
    if any(path.is_symlink() for path in overlay_root.rglob("*")):
        raise M15SemanticOverlayError("semantic overlay cannot contain symlinks")
    if {path.name for path in overlay_root.iterdir()} != {
        "overlay_manifest.json",
        "parameterized-workload-bundle",
    }:
        raise M15SemanticOverlayError("semantic overlay root members are invalid")
    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    recorded = _load_manifest(overlay_root / "overlay_manifest.json")
    if recorded.get("schema_version") != SEMANTIC_OVERLAY_SCHEMA_VERSION:
        raise M15SemanticOverlayError("semantic overlay schema_version is unsupported")
    if recorded.get("generator_version") != SEMANTIC_OVERLAY_GENERATOR_VERSION:
        raise M15SemanticOverlayError(
            "semantic overlay generator_version is unsupported"
        )
    base_query_id = _safe_id(recorded.get("base_query_id"), name="base_query_id")
    readiness = audit_m15_semantic_execution_readiness(
        bundle=selected_base,
        query_id=base_query_id,
        catalog=catalog,
    )
    selected_classes = _select_overlay_classes(readiness)
    expected_spec, additions = _extended_spec(
        selected_base, base_query_id, selected_classes
    )
    overlay_bundle = load_m15_parameterized_workload_bundle(
        overlay_root / "parameterized-workload-bundle"
    )
    if overlay_bundle.spec.to_dict() != expected_spec.to_dict():
        raise M15SemanticOverlayError(
            "semantic overlay workload specification is not deterministic"
        )
    expected_manifest = _manifest(
        base_bundle=selected_base,
        overlay_bundle=overlay_bundle,
        base_query_id=base_query_id,
        readiness=readiness,
        additions=additions,
    )
    if recorded != expected_manifest:
        raise M15SemanticOverlayError(
            "semantic overlay manifest is not deterministic"
        )
    return M15SemanticOverlayBundle(overlay_root, overlay_bundle, recorded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bundle-root", required=True)
    parser.add_argument("--base-query-id", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        overlay = generate_m15_semantic_overlay_bundle(
            base_bundle=arguments.base_bundle_root,
            base_query_id=arguments.base_query_id,
            catalog=arguments.catalog,
            destination=arguments.output,
        )
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {"status": "success", "root": str(overlay.root), **overlay.to_dict()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
