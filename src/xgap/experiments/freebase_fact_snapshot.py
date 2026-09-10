"""Build reusable typed RDF fact parts, independent of questions and catalogs."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Sequence

from xgap.experiments.freebase_facts import FactSource, _positive


SCHEMA = "freebase-typed-fact-snapshot-v1"


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def export_fact_snapshot(*, parquet_root: str | Path, source_manifest_path: str | Path,
                         expected_manifest_sha256: str, output_root: str | Path,
                         max_input_bytes: int, max_output_bytes: int, max_rows: int,
                         shard_paths: Sequence[str] | None = None,
                         part_bytes: int = 64 * 1024 * 1024, batch_size: int = 65_536) -> dict[str, Any]:
    for name, value in (("max_output_bytes", max_output_bytes), ("max_rows", max_rows),
                        ("part_bytes", part_bytes), ("batch_size", batch_size)):
        _positive(value, name)
    source = FactSource.load(parquet_root=parquet_root, source_manifest_path=source_manifest_path,
        expected_manifest_sha256=expected_manifest_sha256, max_input_bytes=max_input_bytes, shard_paths=shard_paths)
    output = Path(output_root).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Fact snapshot output already exists; no implicit resume.")
    if output.resolve().is_relative_to(source.root) or source.manifest_path.is_relative_to(output.resolve()):
        raise ValueError("Fact output must be outside protected source inputs.")
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    clock = time.perf_counter()
    counts: Counter[str] = Counter()
    parts: list[dict[str, Any]] = []
    active = None
    digest = hashlib.sha256()
    size = rows = total_bytes = total_rows = 0

    def finish_part() -> None:
        nonlocal active, size, rows, digest
        if active is None:
            return
        active.flush()
        os.fsync(active.fileno())
        active.close()
        parts.append({"path": f"part-{len(parts):06d}.nt", "bytes": size,
                      "fact_occurrences": rows, "sha256": digest.hexdigest()})
        active = None
        size = rows = 0
        digest = hashlib.sha256()

    request = {
        "schema_version": SCHEMA, "source": source.description(),
        "limits": {"max_input_bytes": max_input_bytes, "max_output_bytes": max_output_bytes,
                   "max_rows": max_rows, "part_bytes": part_bytes, "batch_size": batch_size},
        "started_at": started, "automatic_retries": 0,
    }
    _write_json(output / "build_request.json", request)
    try:
        for record in source.records(batch_size=batch_size):
            encoded = record.fact.ntriples().encode("utf-8")
            if total_rows + 1 > max_rows or total_bytes + len(encoded) > max_output_bytes:
                raise ValueError("Fact output budget exceeded; the selected source was not fully consumed.")
            if len(encoded) > part_bytes:
                raise ValueError("One fact exceeds the explicit part byte limit.")
            if active is not None and size + len(encoded) > part_bytes:
                finish_part()
            if active is None:
                active = (output / f"part-{len(parts):06d}.nt").open("xb")
            active.write(encoded)
            digest.update(encoded)
            size += len(encoded)
            rows += 1
            total_bytes += len(encoded)
            total_rows += 1
            term = record.fact.object
            counts["resource" if term.kind == "uri" else "language_literal" if term.language else "datatype_literal"] += 1
        finish_part()
        manifest = {
            **request, "status": "complete", "selected_shards_fully_consumed": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.perf_counter() - clock,
            "fact_occurrences": total_rows, "output_bytes": total_bytes,
            "object_kind_occurrences": dict(sorted(counts.items())), "parts": parts,
            "rdf_set_deduplication_performed": False,
            "backend_loaded": False, "answer_accuracy_measured": False, "paper_result": False,
        }
        _write_json(output / "manifest.json", manifest)
        return manifest
    except Exception as error:
        finish_part()
        _write_json(output / "snapshot_failure.json", {
            "schema_version": SCHEMA, "status": "failed", "error_type": type(error).__name__,
            "error": str(error), "completed_fact_occurrences": total_rows,
            "output_bytes": total_bytes, "parts": parts, "selected_shards_fully_consumed": False,
        })
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parquet-root", "source-manifest-path", "expected-manifest-sha256", "output-root"):
        parser.add_argument("--" + name, required=True)
    for name in ("max-input-bytes", "max-output-bytes", "max-rows"):
        parser.add_argument("--" + name, type=int, required=True)
    parser.add_argument("--shard", dest="shard_paths", action="append")
    parser.add_argument("--part-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--batch-size", type=int, default=65_536)
    args = parser.parse_args(argv)
    try:
        result = export_fact_snapshot(**vars(args))
    except Exception as error:
        print(json.dumps({"schema_version": SCHEMA, "status": "failed", "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
