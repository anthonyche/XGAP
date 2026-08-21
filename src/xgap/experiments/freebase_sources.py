"""Frozen Freebase source adapters used by Catalog-v2 construction.

This module isolates artifact transport and source-format parsing from the
catalog extraction semantics.  Both supported modes emit the same compact
triple tuple consumed by the existing Catalog-v2 builder.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterator, Mapping, MutableMapping, Sequence


GOOGLE_RDF_GZIP = "google_rdf_gzip"
HF_ARCHIVAL_PARQUET = "hf_archival_parquet"
SUPPORTED_SOURCE_MODES = (GOOGLE_RDF_GZIP, HF_ARCHIVAL_PARQUET)

HF_FREEBASE_REPO_ID = "CleverThis/freebase"
HF_FREEBASE_REVISION = "dbb1931c2698295653effe9b980a02ab29f004e0"
HF_FREEBASE_DATASET_URL = f"https://huggingface.co/datasets/{HF_FREEBASE_REPO_ID}"
PARQUET_SPEC_SCHEMA_VERSION = "m13e3a-freebase-parquet-spec-v1"
PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION = "m13e3a-freebase-source-manifest-v1"
PARQUET_SOURCE_VERIFICATION_SCHEMA_VERSION = "m13e3a-freebase-source-verification-v1"

FREEBASE_NAMESPACE = "http://rdf.freebase.com/ns/"
NAME_PREDICATE = "type.object.name"
ALIAS_PREDICATE = "common.topic.alias"
TYPE_PREDICATE = "type.object.type"
EXPECTED_PARQUET_COLUMNS = (
    "subject",
    "predicate",
    "object",
    "object_type",
    "object_datatype",
    "object_language",
)

FreebaseTriple = tuple[str, str, str, str | None, bool]


@dataclass(frozen=True)
class ParquetTripleRecord:
    """One filtered Freebase triple with immutable shard provenance."""

    triple: FreebaseTriple
    source_shard: str


def normalize_source_mode(value: str) -> str:
    """Return a supported explicit mode; source fallback is never inferred."""

    mode = value.strip().casefold()
    if mode not in SUPPORTED_SOURCE_MODES:
        expected = ", ".join(SUPPORTED_SOURCE_MODES)
        raise ValueError(f"Unsupported Freebase source_mode '{value}'; expected {expected}.")
    return mode


def parquet_row_to_triple(row: Mapping[str, object]) -> FreebaseTriple | None:
    """Map one archival Parquet row to the Catalog-v2 triple representation."""

    missing = [name for name in EXPECTED_PARQUET_COLUMNS if name not in row]
    if missing:
        raise ValueError(f"Freebase Parquet row is missing columns: {', '.join(missing)}.")
    subject_value = row["subject"]
    predicate_value = row["predicate"]
    object_value = row["object"]
    object_type = row["object_type"]
    if not all(isinstance(value, str) for value in (subject_value, predicate_value, object_value)):
        return None
    subject = _freebase_id(subject_value)
    predicate = _freebase_id(predicate_value)
    value = str(object_value)
    if object_type == "uri":
        return subject, predicate, _freebase_id(value), None, True
    language = row["object_language"]
    if object_type == "literal" and isinstance(language, str) and language:
        return subject, predicate, value, language.casefold(), False
    # The N-Triples parser used by Catalog-v2 intentionally accepts only URI
    # objects and language-tagged literals. Keep the Parquet adapter identical.
    return None


def iter_parquet_triples(
    *,
    parquet_root: str | Path,
    source_manifest_path: str | Path,
    statistics: MutableMapping[str, int] | None = None,
    max_shards: int | None = None,
    max_row_groups_per_shard: int | None = None,
    batch_size: int = 65_536,
    predicates: Sequence[str] | None = None,
    subject_ids: Sequence[str] | None = None,
) -> Iterator[FreebaseTriple]:
    """Stream verified shards, row groups, and record batches in frozen order."""

    for record in iter_parquet_triple_records(
        parquet_root=parquet_root,
        source_manifest_path=source_manifest_path,
        statistics=statistics,
        max_shards=max_shards,
        max_row_groups_per_shard=max_row_groups_per_shard,
        batch_size=batch_size,
        predicates=predicates,
        subject_ids=subject_ids,
    ):
        yield record.triple


def iter_parquet_triple_records(
    *,
    parquet_root: str | Path,
    source_manifest_path: str | Path,
    statistics: MutableMapping[str, int] | None = None,
    max_shards: int | None = None,
    max_row_groups_per_shard: int | None = None,
    batch_size: int = 65_536,
    predicates: Sequence[str] | None = None,
    subject_ids: Sequence[str] | None = None,
) -> Iterator[ParquetTripleRecord]:
    """Stream selected triples with shard provenance and optional pushdown."""

    if max_shards is not None and max_shards < 1:
        raise ValueError("max_shards must be positive when supplied.")
    if max_row_groups_per_shard is not None and max_row_groups_per_shard < 1:
        raise ValueError("max_row_groups_per_shard must be positive when supplied.")
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    selected_predicates = tuple(
        predicates or (NAME_PREDICATE, ALIAS_PREDICATE, TYPE_PREDICATE)
    )
    unsupported = sorted(
        set(selected_predicates) - {NAME_PREDICATE, ALIAS_PREDICATE, TYPE_PREDICATE}
    )
    if unsupported:
        raise ValueError(f"Unsupported Freebase predicates: {unsupported}.")
    selected_subjects = None if subject_ids is None else tuple(sorted(set(subject_ids)))
    if selected_subjects == ():
        return
    arrow, compute, parquet = _require_pyarrow()
    root = Path(parquet_root)
    manifest = load_parquet_source_manifest(source_manifest_path)
    shards = tuple(_mapping(item, "source shard") for item in manifest["shards"])
    if max_shards is not None:
        shards = shards[:max_shards]
    stats = statistics if statistics is not None else {}
    stats.setdefault("input_records", 0)
    stats.setdefault("input_rows", 0)
    stats.setdefault("parquet_shards", 0)
    stats.setdefault("parquet_row_groups", 0)
    stats.setdefault("predicate_filtered_rows", 0)
    stats.setdefault("subject_filtered_rows", 0)
    stats.setdefault("unparsed_or_irrelevant_lines", 0)
    relevant_predicates = arrow.array(
        [FREEBASE_NAMESPACE + predicate for predicate in selected_predicates],
        type=arrow.string(),
    )
    relevant_subjects = (
        arrow.array(
            [FREEBASE_NAMESPACE + subject for subject in selected_subjects],
            type=arrow.string(),
        )
        if selected_subjects is not None
        else None
    )
    projected_columns = (
        "subject",
        "predicate",
        "object",
        "object_type",
        "object_language",
    )
    for shard in shards:
        relative_path = _safe_relative_path(str(shard["path"]))
        file_path = root / relative_path
        parquet_file = parquet.ParquetFile(file_path)
        actual_schema = tuple(parquet_file.schema_arrow.names)
        if actual_schema != EXPECTED_PARQUET_COLUMNS:
            raise ValueError(
                f"Unexpected Freebase Parquet schema in {relative_path}: {actual_schema}."
            )
        actual_types = tuple(str(field.type) for field in parquet_file.schema_arrow)
        if actual_types != tuple("string" for _ in EXPECTED_PARQUET_COLUMNS):
            raise ValueError(
                f"Unexpected Freebase Parquet field types in {relative_path}: {actual_types}."
            )
        stats["parquet_shards"] += 1
        row_group_count = parquet_file.num_row_groups
        if max_row_groups_per_shard is not None:
            row_group_count = min(row_group_count, max_row_groups_per_shard)
        for row_group in range(row_group_count):
            stats["parquet_row_groups"] += 1
            for batch in parquet_file.iter_batches(
                batch_size=batch_size,
                row_groups=[row_group],
                columns=list(projected_columns),
            ):
                stats["input_records"] += batch.num_rows
                stats["input_rows"] += batch.num_rows
                mask = compute.is_in(batch.column(1), value_set=relevant_predicates)
                predicate_count = int(compute.sum(mask).as_py() or 0)
                stats["predicate_filtered_rows"] += batch.num_rows - predicate_count
                if relevant_subjects is not None:
                    subject_mask = compute.is_in(batch.column(0), value_set=relevant_subjects)
                    mask = compute.and_(mask, subject_mask)
                relevant = compute.filter(batch, mask)
                stats["subject_filtered_rows"] += predicate_count - relevant.num_rows
                stats["unparsed_or_irrelevant_lines"] += batch.num_rows - relevant.num_rows
                columns = {
                    name: relevant.column(index).to_pylist()
                    for index, name in enumerate(projected_columns)
                }
                for index in range(relevant.num_rows):
                    triple = parquet_row_to_triple(
                        {
                            **{name: values[index] for name, values in columns.items()},
                            "object_datatype": None,
                        }
                    )
                    if triple is None:
                        stats["unparsed_or_irrelevant_lines"] += 1
                        continue
                    yield ParquetTripleRecord(triple=triple, source_shard=relative_path)


def load_frozen_parquet_spec(path: str | Path) -> dict[str, Any]:
    """Load and structurally validate the committed immutable shard inventory."""

    spec = _load_json_object(Path(path), "frozen Parquet source spec")
    if spec.get("schema_version") != PARQUET_SPEC_SCHEMA_VERSION:
        raise ValueError("Unsupported frozen Freebase Parquet spec schema.")
    if normalize_source_mode(str(spec.get("source_mode", ""))) != HF_ARCHIVAL_PARQUET:
        raise ValueError("Frozen Parquet spec must use hf_archival_parquet source mode.")
    if spec.get("repo_id") != HF_FREEBASE_REPO_ID:
        raise ValueError("Frozen Parquet spec repository differs from the M13-E3A contract.")
    if spec.get("revision") != HF_FREEBASE_REVISION:
        raise ValueError("Frozen Parquet spec revision differs from the M13-E3A contract.")
    if spec.get("resolved_parquet_revision") != HF_FREEBASE_REVISION:
        raise ValueError("Frozen Parquet conversion revision is not the verified commit.")
    if spec.get("all_shards_same_revision") is not True:
        raise ValueError("Frozen Parquet spec does not attest one immutable shard revision.")
    shards = _shard_records(spec)
    if int(spec.get("shard_count", -1)) != len(shards):
        raise ValueError("Frozen Parquet shard count does not match its inventory.")
    if int(spec.get("total_bytes", -1)) != sum(int(item["size_bytes"]) for item in shards):
        raise ValueError("Frozen Parquet total size does not match its inventory.")
    _validate_schema_record(spec.get("parquet_schema"), spec.get("schema_fingerprint"))
    _validate_shard_inventory(shards)
    return spec


def write_parquet_source_manifest(
    *,
    parquet_root: str | Path,
    frozen_spec_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Verify all frozen shards and write the generalized local source manifest."""

    root = Path(parquet_root).resolve()
    spec = load_frozen_parquet_spec(frozen_spec_path)
    shards = _verify_local_shards(root=root, expected=_shard_records(spec), exact=True)
    manifest = {
        "schema_version": PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION,
        "status": "downloaded",
        "source_mode": HF_ARCHIVAL_PARQUET,
        "underlying_knowledge_source": "Freebase",
        "benchmark_schema": "GrailQA processed Freebase ontology",
        "artifact_transport": "frozen archival Parquet representation",
        "derived_artifact": "XGAP Freebase inference Catalog-v2",
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "resolved_parquet_revision": spec["resolved_parquet_revision"],
        "dataset_source_url": spec["dataset_source_url"],
        "retrieved_at": _utc_now(),
        "builder_git_commit": _git_commit(),
        "parquet_schema": spec["parquet_schema"],
        "schema_fingerprint": spec["schema_fingerprint"],
        "shard_count": len(shards),
        "total_bytes": sum(int(item["size_bytes"]) for item in shards),
        "shards": shards,
        "frozen_spec_sha256": _sha256_file(Path(frozen_spec_path)),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file():
        previous = _load_json_object(output, "existing Parquet source manifest")
        comparable = dict(previous)
        comparable.pop("retrieved_at", None)
        candidate = dict(manifest)
        candidate.pop("retrieved_at", None)
        if comparable == candidate:
            return previous
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_parquet_source_manifest(path: str | Path) -> dict[str, Any]:
    manifest = _load_json_object(Path(path), "Parquet source manifest")
    if manifest.get("schema_version") != PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported archival Parquet source-manifest schema.")
    if normalize_source_mode(str(manifest.get("source_mode", ""))) != HF_ARCHIVAL_PARQUET:
        raise ValueError("Archival Parquet manifest has the wrong source mode.")
    if manifest.get("repo_id") != HF_FREEBASE_REPO_ID:
        raise ValueError("Archival Parquet manifest has the wrong repository.")
    if manifest.get("revision") != HF_FREEBASE_REVISION:
        raise ValueError("Archival Parquet manifest has the wrong revision.")
    if manifest.get("resolved_parquet_revision") != HF_FREEBASE_REVISION:
        raise ValueError("Archival Parquet manifest has the wrong conversion revision.")
    shards = _shard_records(manifest)
    if int(manifest.get("shard_count", -1)) != len(shards):
        raise ValueError("Parquet source-manifest shard count is inconsistent.")
    if int(manifest.get("total_bytes", -1)) != sum(
        int(item["size_bytes"]) for item in shards
    ):
        raise ValueError("Parquet source-manifest total size is inconsistent.")
    _validate_schema_record(
        manifest.get("parquet_schema"), manifest.get("schema_fingerprint")
    )
    _validate_shard_inventory(shards)
    return manifest


def verify_parquet_source_manifest(
    *, parquet_root: str | Path, source_manifest_path: str | Path
) -> dict[str, Any]:
    """Require the local Parquet tree to exactly match every frozen shard."""

    root = Path(parquet_root).resolve()
    manifest = load_parquet_source_manifest(source_manifest_path)
    shards = _verify_local_shards(root=root, expected=_shard_records(manifest), exact=True)
    return {
        "schema_version": PARQUET_SOURCE_VERIFICATION_SCHEMA_VERSION,
        "status": "ok",
        "source_mode": HF_ARCHIVAL_PARQUET,
        "repo_id": manifest["repo_id"],
        "revision": manifest["revision"],
        "shard_count": len(shards),
        "total_bytes": sum(int(item["size_bytes"]) for item in shards),
        "schema_fingerprint": manifest["schema_fingerprint"],
        "source_manifest_sha256": _sha256_file(Path(source_manifest_path)),
    }


def smoke_parquet_source(
    *,
    parquet_root: str | Path,
    frozen_spec_path: str | Path,
    shard_path: str = "default/data/0000.parquet",
    max_row_groups: int = 1,
) -> dict[str, Any]:
    """Inspect a bounded verified shard and require core Freebase constructs."""

    root = Path(parquet_root).resolve()
    spec = load_frozen_parquet_spec(frozen_spec_path)
    expected = {
        str(item["path"]): item for item in _shard_records(spec)
    }.get(shard_path)
    if expected is None:
        raise ValueError(f"Smoke shard is not in the frozen inventory: {shard_path}")
    verified = _verify_local_shards(root=root, expected=(expected,), exact=False)
    partial_manifest = {
        "schema_version": PARQUET_SOURCE_MANIFEST_SCHEMA_VERSION,
        "status": "smoke",
        "source_mode": HF_ARCHIVAL_PARQUET,
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "resolved_parquet_revision": spec["resolved_parquet_revision"],
        "parquet_schema": spec["parquet_schema"],
        "schema_fingerprint": spec["schema_fingerprint"],
        "shard_count": 1,
        "total_bytes": int(expected["size_bytes"]),
        "shards": verified,
    }
    temporary_manifest = root / ".xgap-freebase-smoke-manifest.json"
    temporary_manifest.write_text(
        json.dumps(partial_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    counts = {
        "mid_subjects": 0,
        "canonical_names": 0,
        "aliases": 0,
        "type_memberships": 0,
        "english_literals": 0,
    }
    statistics: dict[str, int] = {}
    try:
        for subject, predicate, _, language, is_resource in iter_parquet_triples(
            parquet_root=root,
            source_manifest_path=temporary_manifest,
            statistics=statistics,
            max_shards=1,
            max_row_groups_per_shard=max_row_groups,
        ):
            if subject.startswith(("m.", "g.")):
                counts["mid_subjects"] += 1
            if predicate == NAME_PREDICATE and language == "en" and not is_resource:
                counts["canonical_names"] += 1
            if predicate == ALIAS_PREDICATE and language == "en" and not is_resource:
                counts["aliases"] += 1
            if predicate == TYPE_PREDICATE and is_resource:
                counts["type_memberships"] += 1
            if language == "en" and not is_resource:
                counts["english_literals"] += 1
    finally:
        temporary_manifest.unlink(missing_ok=True)
    missing = [name for name, count in counts.items() if count == 0]
    if missing:
        raise ValueError("Freebase Parquet smoke is missing constructs: " + ", ".join(missing))
    return {
        "schema_version": "m13e3a-freebase-parquet-smoke-v1",
        "status": "ok",
        "source_mode": HF_ARCHIVAL_PARQUET,
        "repo_id": spec["repo_id"],
        "revision": spec["revision"],
        "shard_path": shard_path,
        "max_row_groups": max_row_groups,
        "counts": counts,
        "statistics": statistics,
    }


def frozen_download_records(path: str | Path) -> Iterator[tuple[str, int, str, str]]:
    spec = load_frozen_parquet_spec(path)
    for shard in _shard_records(spec):
        yield (
            str(shard["path"]),
            int(shard["size_bytes"]),
            str(shard["sha256"]),
            str(shard["url"]),
        )


def _verify_local_shards(
    *, root: Path, expected: Sequence[Mapping[str, Any]], exact: bool
) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(f"Freebase Parquet root is missing: {root}")
    expected_paths = {_safe_relative_path(str(item["path"])) for item in expected}
    if exact:
        actual_paths = {
            path.relative_to(root)
            for path in root.rglob("*.parquet")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            missing = sorted(str(path) for path in expected_paths - actual_paths)
            extra = sorted(str(path) for path in actual_paths - expected_paths)
            raise ValueError(
                "Local Freebase Parquet shard set differs from the manifest: "
                f"missing={missing[:10]}, extra={extra[:10]}."
            )
    verified: list[dict[str, Any]] = []
    for item in expected:
        relative = _safe_relative_path(str(item["path"]))
        file_path = root / relative
        if not file_path.is_file():
            raise FileNotFoundError(f"Freebase Parquet shard is missing: {file_path}")
        expected_size = int(item["size_bytes"])
        if file_path.stat().st_size != expected_size:
            raise ValueError(f"Freebase Parquet shard size mismatch: {relative}")
        actual_hash = _sha256_file(file_path)
        if actual_hash != str(item["sha256"]):
            raise ValueError(f"Freebase Parquet shard checksum mismatch: {relative}")
        verified.append(
            {
                "path": str(relative),
                "size_bytes": expected_size,
                "sha256": actual_hash,
                "blob_id": item.get("blob_id"),
                "xet_hash": item.get("xet_hash"),
                "url": item.get("url"),
            }
        )
    return verified


def _validate_shard_inventory(shards: Sequence[Mapping[str, Any]]) -> None:
    seen: set[Path] = set()
    for shard in shards:
        path = _safe_relative_path(str(shard.get("path", "")))
        if path in seen:
            raise ValueError(f"Duplicate Parquet shard path: {path}")
        seen.add(path)
        if int(shard.get("size_bytes", 0)) <= 0:
            raise ValueError(f"Invalid Parquet shard size: {path}")
        checksum = str(shard.get("sha256", ""))
        if len(checksum) != 64 or any(
            character not in "0123456789abcdef" for character in checksum
        ):
            raise ValueError(f"Invalid Parquet shard SHA-256: {path}")
        expected_url = (
            f"{HF_FREEBASE_DATASET_URL}/resolve/{HF_FREEBASE_REVISION}/{path}"
        )
        if shard.get("url") != expected_url:
            raise ValueError(f"Parquet shard URL is not immutable: {path}")


def _validate_schema_record(value: object, fingerprint: object) -> None:
    schema = _mapping(value, "Parquet schema")
    fields = schema.get("fields")
    if not isinstance(fields, list):
        raise ValueError("Parquet schema fields must be a list.")
    actual = tuple(
        (str(_mapping(field, "Parquet field").get("name")), str(field.get("type")))
        for field in fields
    )
    if actual != tuple((name, "string") for name in EXPECTED_PARQUET_COLUMNS):
        raise ValueError(f"Unexpected frozen Freebase Parquet schema: {actual}")
    expected_fingerprint = hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if fingerprint != expected_fingerprint:
        raise ValueError("Frozen Freebase Parquet schema fingerprint mismatch.")


def _shard_records(value: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    shards = value.get("shards")
    if not isinstance(shards, list):
        raise ValueError("Freebase Parquet shard inventory must be a list.")
    return tuple(_mapping(item, "Parquet shard") for item in shards)


def _safe_relative_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe Parquet shard path: {value!r}")
    return path


def _freebase_id(uri: str) -> str:
    return uri[len(FREEBASE_NAMESPACE) :] if uri.startswith(FREEBASE_NAMESPACE) else uri


def _require_pyarrow() -> tuple[Any, Any, Any]:
    try:
        import pyarrow as arrow
        import pyarrow.compute as compute
        import pyarrow.parquet as parquet
    except ImportError as error:
        raise RuntimeError(
            "hf_archival_parquet requires PyArrow; install XGAP with the 'parquet' extra."
        ) from error
    return arrow, compute, parquet


def _load_json_object(path: Path, name: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{name} is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object.")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    configured = os.environ.get("XGAP_GIT_COMMIT")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--frozen-spec", required=True)
    write_manifest = subparsers.add_parser("write-manifest")
    write_manifest.add_argument("--parquet-root", required=True)
    write_manifest.add_argument("--frozen-spec", required=True)
    write_manifest.add_argument("--output", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--parquet-root", required=True)
    verify.add_argument("--source-manifest", required=True)
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--parquet-root", required=True)
    smoke.add_argument("--frozen-spec", required=True)
    smoke.add_argument("--shard", default="default/data/0000.parquet")
    smoke.add_argument("--max-row-groups", type=int, default=1)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        for path, size, checksum, url in frozen_download_records(args.frozen_spec):
            print(f"{path}\t{size}\t{checksum}\t{url}")
        return 0
    if args.command == "write-manifest":
        result = write_parquet_source_manifest(
            parquet_root=args.parquet_root,
            frozen_spec_path=args.frozen_spec,
            output_path=args.output,
        )
    elif args.command == "verify":
        result = verify_parquet_source_manifest(
            parquet_root=args.parquet_root,
            source_manifest_path=args.source_manifest,
        )
    else:
        result = smoke_parquet_source(
            parquet_root=args.parquet_root,
            frozen_spec_path=args.frozen_spec,
            shard_path=args.shard,
            max_row_groups=args.max_row_groups,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
