"""Lossless typed facts from archival Parquet, separate from catalog extraction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from xgap.backends.rdf_terms import RdfTerm
from xgap.experiments.freebase_sources import (
    EXPECTED_PARQUET_COLUMNS, _require_pyarrow, _safe_relative_path,
    load_parquet_source_manifest,
)


@dataclass(frozen=True)
class RdfFact:
    subject: RdfTerm
    predicate: RdfTerm
    object: RdfTerm

    def __post_init__(self) -> None:
        if not all(isinstance(term, RdfTerm) for term in (self.subject, self.predicate, self.object)):
            raise ValueError("Facts require typed RDF terms.")
        if self.subject.kind != "uri" or self.predicate.kind != "uri" or self.object.kind == "bnode":
            raise ValueError("This archival fact profile requires globally identified resources; blank nodes are unsupported.")

    def ntriples(self) -> str:
        return " ".join(term.ntriples() for term in (self.subject, self.predicate, self.object)) + " .\n"


@dataclass(frozen=True)
class FactRecord:
    fact: RdfFact
    source_shard: str
    row_group: int
    row_index: int


def fact_from_parquet_row(row: Mapping[str, Any]) -> RdfFact:
    """No predicate/language filter and no datatype or lexical-value coercion."""
    if not isinstance(row, Mapping) or set(row) != set(EXPECTED_PARQUET_COLUMNS):
        raise ValueError("Fact rows must contain exactly the six archival columns.")
    optional: dict[str, str | None] = {}
    for key in ("object_datatype", "object_language"):
        value = row[key]
        if value is not None and not isinstance(value, str):
            raise ValueError("RDF datatype/language metadata must be strings or null.")
        optional[key] = value or None
    kind = row["object_type"]
    if kind not in ("uri", "literal", "typed-literal"):
        raise ValueError("Unsupported archival RDF object type.")
    if kind == "typed-literal" and optional["object_datatype"] is None:
        raise ValueError("Typed literals require their actual datatype.")
    return RdfFact(
        RdfTerm("uri", row["subject"]), RdfTerm("uri", row["predicate"]),
        RdfTerm("literal" if kind == "typed-literal" else kind, row["object"],
                datatype=optional["object_datatype"], language=optional["object_language"]),
    )


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(name + " must be a positive integer.")


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


@dataclass(frozen=True)
class FactSource:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    revision: str
    manifest_shard_count: int
    shards: tuple[Mapping[str, Any], ...]

    @classmethod
    def load(cls, *, parquet_root: str | Path, source_manifest_path: str | Path,
             expected_manifest_sha256: str, max_input_bytes: int,
             shard_paths: Sequence[str] | None = None) -> "FactSource":
        _positive(max_input_bytes, "max_input_bytes")
        manifest_path = Path(source_manifest_path).resolve(strict=True)
        checksum = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if checksum != expected_manifest_sha256:
            raise ValueError("Explicit source manifest digest mismatch.")
        manifest = load_parquet_source_manifest(manifest_path)
        inventory = {item["path"]: item for item in manifest["shards"]}
        if shard_paths is None:
            selected = set(inventory)
        else:
            if isinstance(shard_paths, (str, bytes)) or not all(isinstance(p, str) for p in shard_paths):
                raise ValueError("Shard selection must be an explicit list of paths.")
            selected = set(shard_paths)
            if len(selected) != len(shard_paths) or not selected <= set(inventory):
                raise ValueError("Selected shards must be unique and present in the source manifest.")
        if not selected:
            raise ValueError("At least one complete shard must be selected.")
        shards = tuple(dict(item) for item in manifest["shards"] if item["path"] in selected)
        if sum(item["size_bytes"] for item in shards) > max_input_bytes:
            raise ValueError("Selected source exceeds max_input_bytes; no implicit truncation.")
        root = Path(parquet_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Parquet root must be a directory.")
        return cls(root, manifest_path, checksum, manifest["revision"], len(inventory), shards)

    def description(self) -> dict[str, Any]:
        return {
            "parquet_root": str(self.root), "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256, "revision": self.revision,
            "manifest_shard_count": self.manifest_shard_count,
            "selected_shards": [dict(item) for item in self.shards],
            "selection": "all_manifest_shards" if len(self.shards) == self.manifest_shard_count else "explicit_partial_shards",
            "question_or_reference_selection": False, "original_freebase_completeness_claimed": False,
        }

    def records(self, *, batch_size: int = 65_536) -> Iterator[FactRecord]:
        _positive(batch_size, "batch_size")
        _, _, parquet = _require_pyarrow()
        for shard in self.shards:
            relative = _safe_relative_path(shard["path"])
            path = self.root / relative
            if any(part.is_symlink() for part in (path, *path.parents) if part != self.root and part.is_relative_to(self.root)):
                raise ValueError("Selected shard has a symlinked path.")
            if not path.resolve(strict=True).is_relative_to(self.root) or not path.is_file():
                raise ValueError("Selected shard must be a regular source-contained file.")
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size != shard["size_bytes"]:
                    raise ValueError("Selected shard size mismatch: " + str(relative))
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                if digest.hexdigest() != shard["sha256"]:
                    raise ValueError("Selected shard digest mismatch: " + str(relative))
                handle.seek(0)
                source = parquet.ParquetFile(handle)
                if tuple(source.schema_arrow.names) != EXPECTED_PARQUET_COLUMNS or any(str(f.type) != "string" for f in source.schema_arrow):
                    raise ValueError("Unexpected typed fact Parquet schema.")
                for group in range(source.num_row_groups):
                    offset = 0
                    for batch in source.iter_batches(batch_size=batch_size, row_groups=[group], columns=list(EXPECTED_PARQUET_COLUMNS)):
                        for index, row in enumerate(batch.to_pylist()):
                            try:
                                fact = fact_from_parquet_row(row)
                            except ValueError as error:
                                raise ValueError(f"Invalid fact at {relative}, row group {group}, row {offset + index}: {error}") from error
                            yield FactRecord(fact, str(relative), group, offset + index)
                        offset += batch.num_rows
                if _signature(os.fstat(handle.fileno())) != _signature(before):
                    raise ValueError("Selected shard changed while reading.")
        if hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() != self.manifest_sha256:
            raise ValueError("Source manifest changed while reading.")
