"""Frozen, query-independent upper bounds for exact string equality keys."""
from dataclasses import dataclass
import hashlib
import json
import re

SCHEMA = "xgap-equality-key-bounds-v1"
SEMANTICS = "typed_binding_values_v1/exact-string/matching-record-upper-bound"


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Equality statistics require nonempty identifiers")
    return value


@dataclass(frozen=True)
class FrozenEqualityKeyBounds:
    source_id: str
    snapshot_version: str
    resource_namespace: str
    sha256: str
    # Matching records upper-bound distinct identities, including duplicate input rows.
    entries: tuple[tuple[str, str, int], ...]

    @classmethod
    def from_bytes(cls, data, *, expected_sha256, source_id, snapshot_version):
        if (not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or hashlib.sha256(data).hexdigest() != expected_sha256):
            raise ValueError("Equality statistics hash mismatch")
        doc = json.loads(data)
        required = {"schema_version", "semantics", "source_id", "snapshot_version", "resource_namespace",
                    "coverage", "input", "entries", "offline"}
        if not isinstance(doc, dict) or set(doc) != required:
            raise ValueError("Invalid equality statistics fields")
        if (doc["schema_version"] != SCHEMA or doc["semantics"] != SEMANTICS
                or doc["source_id"] != source_id or doc["snapshot_version"] != snapshot_version):
            raise ValueError("Equality statistics source/snapshot/semantics mismatch")
        coverage = doc["coverage"]
        if (not isinstance(coverage, dict) or set(coverage) != {"complete_node_records", "record_count", "labels"}
                or coverage["complete_node_records"] is not True
                or type(coverage["record_count"]) is not int or coverage["record_count"] < 0
                or not isinstance(coverage["labels"], list)):
            raise ValueError("Equality statistics require explicit complete coverage")
        labels = [_text(label) for label in coverage["labels"]]
        if len(set(labels)) != len(labels):
            raise ValueError("Duplicate equality coverage label")
        pin = doc["input"]
        if (not isinstance(pin, dict) or set(pin) != {"sha256", "size_bytes"}
                or not isinstance(pin["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
                or type(pin["size_bytes"]) is not int or pin["size_bytes"] < 0):
            raise ValueError("Equality input provenance needs a content pin")
        if not isinstance(doc["offline"], dict) or not isinstance(doc["entries"], list):
            raise ValueError("Invalid equality preparation provenance/entries")
        entries = []
        for entry in doc["entries"]:
            if not isinstance(entry, dict) or set(entry) != {"label", "property", "maximum_matching_records"}:
                raise ValueError("Invalid equality bound entry")
            label, prop, limit = entry["label"], _text(entry["property"]), entry["maximum_matching_records"]
            if label not in labels or type(limit) is not int or not 0 <= limit <= coverage["record_count"]:
                raise ValueError("Invalid equality bound scope/value")
            entries.append((label, prop, limit))
        if len({e[:2] for e in entries}) != len(entries):
            raise ValueError("Duplicate equality bound scope")
        return cls(_text(source_id), _text(snapshot_version), _text(doc["resource_namespace"]),
                   expected_sha256, tuple(entries))

    def bound(self, label, prop):
        # Linear lookup is bounded by the explicit frozen metadata input size.
        return next((limit for name, field, limit in self.entries if name == label and field == prop), None)
