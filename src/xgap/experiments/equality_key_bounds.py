"""Offline freeze from a complete normalized source export; never read questions."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from xgap.experiments.one_shot_records import write_once
from xgap.planning.equality_key_bounds import FrozenEqualityKeyBounds, SCHEMA, SEMANTICS
from xgap.runtime.scalars import value_key


def freeze_equality_key_bounds(*, records_path, records_sha256, source_id, snapshot_version,
                              resource_namespace, expected_records, properties, output):
    """Read complete JSONL {label, properties} records, with scalar binding values.

    The caller asserts complete coverage of each listed label and binds that
    export to a source snapshot. The publisher verifies bytes/counts, never
    infers completeness from a sample. Repeated records conservatively inflate
    the maximum. Missing properties cannot match an exact nonnull string.
    """
    at = time.perf_counter()
    if (type(expected_records) is not int or expected_records < 0 or not isinstance(properties, dict)
            or not properties or any(not isinstance(k, str) or not k or not isinstance(v, list)
                or any(not isinstance(p, str) or not p for p in v) or len(set(v)) != len(v)
                for k, v in properties.items())):
        raise ValueError("Explicit complete export count/label/property coverage required")
    counters = {(label, prop): Counter() for label, props in properties.items() for prop in props}
    count = size = 0; digest = hashlib.sha256()
    with Path(records_path).open("rb") as stream:
        for line in stream:
            digest.update(line); size += len(line)
            row = json.loads(line)
            if (not isinstance(row, dict) or set(row) != {"label", "properties"}
                    or row["label"] not in properties or not isinstance(row["properties"], dict)):
                raise ValueError("Invalid normalized complete source record")
            count += 1
            for prop in properties[row["label"]]:
                key = value_key(row["properties"].get(prop))
                if key[0] == "2-string":
                    counters[row["label"], prop][key[1]] += 1
    if digest.hexdigest() != records_sha256 or count != expected_records:
        raise ValueError("Complete source export hash/count mismatch")
    doc = {"schema_version": SCHEMA, "semantics": SEMANTICS,
        "source_id": source_id, "snapshot_version": snapshot_version, "resource_namespace": resource_namespace,
        "coverage": {"complete_node_records": True, "record_count": count, "labels": sorted(properties)},
        "input": {"sha256": records_sha256, "size_bytes": size},
        "entries": [{"label": label, "property": prop, "maximum_matching_records": max(values.values(), default=0)}
                    for (label, prop), values in sorted(counters.items())],
        "offline": {"elapsed_ms_before_publication": (time.perf_counter()-at)*1000,
                    "query_reads": 0, "answer_reads": 0, "backend_calls": 0, "model_calls": 0,
                    "cost_scope": "one-time export scan and statistics construction; input export accounted separately"}}
    # Validate before publishing any immutable statistics file.
    encoded = json.dumps(doc, sort_keys=True).encode()
    FrozenEqualityKeyBounds.from_bytes(encoded, expected_sha256=hashlib.sha256(encoded).hexdigest(),
                                      source_id=source_id, snapshot_version=snapshot_version)
    return write_once(Path(output), doc)


def derive_equality_profile(*, parent_path, parent_sha256, statistics, output):
    """Publish an optional-statistics child; old sources/model/policy remain frozen."""
    from xgap.experiments.one_shot_profile import FrozenOneShotProfile
    parent = FrozenOneShotProfile.load(parent_path, expected_sha256=parent_sha256)
    doc = json.loads(parent.document_json)
    if not statistics or set(statistics)-set(doc["sources"]):
        raise ValueError("Statistics must cover known logical sources")
    for key in ("catalog", "estimator"):
        doc[key]["path"] = str((parent.root/doc[key]["path"]).resolve())
    for spec in doc["sources"].values():
        if "equality_key_bounds" in spec:
            raise ValueError("Publish from a parent without equality statistics")
    for source, pin in statistics.items():
        doc["sources"][source]["equality_key_bounds"] = {"path": str(Path(pin["path"]).resolve()), "sha256": pin["sha256"]}
    for spec in doc["modes"].values():
        spec["provider"]["prompt"]["path"] = str((parent.root/spec["provider"]["prompt"]["path"]).resolve())
    doc["profile_id"] += ":equality-key-bounds-v1"
    doc["offline"]["equality_key_bounds_revision"] = {
        "parent": {"path": str(Path(parent_path).resolve()), "sha256": parent_sha256},
        "statistics": statistics, "fit_calls": 0, "backend_calls": 0, "query_reads": 0, "answer_reads": 0,
        "scope": "optional frozen source bounds; no changed model weights, source facts or runtime policy"}
    # In-memory validation resolves absolute dependencies, before publication.
    path = Path(output).resolve()
    FrozenOneShotProfile(path.parent, "unpublished", json.dumps(doc)).materialize()
    return write_once(path, doc)
