"""Load reusable typed snapshots and an explicit Neo4j resource-edge mirror."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Iterator

from xgap.experiments.freebase_fact_snapshot import SCHEMA
from xgap.experiments.freebase_native_answers import EDGE_LABEL, RESOURCE_LABEL
from xgap.infrastructure.runtime import QueryArtifact


@dataclass(frozen=True)
class FactSnapshot:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str

    @classmethod
    def load(cls, root: str | Path, *, expected_manifest_sha256: str,
             max_bytes: int, max_part_bytes: int) -> "FactSnapshot":
        if any(type(v) is not int or v <= 0 for v in (max_bytes, max_part_bytes)):
            raise ValueError("Snapshot byte budgets must be positive integers")
        root = Path(root).resolve()
        content = (root / "manifest.json").read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_manifest_sha256:
            raise ValueError("Snapshot manifest hash mismatch")
        manifest = json.loads(content)
        if (manifest.get("schema_version") != SCHEMA or manifest.get("status") != "complete"
                or manifest.get("selected_shards_fully_consumed") is not True):
            raise ValueError("A complete selected-shard snapshot is required")
        parts = manifest.get("parts")
        if not isinstance(parts, list):
            raise ValueError("Invalid fact part inventory")
        seen: set[str] = set()
        for part in parts:
            name = part["path"]
            if (not isinstance(name, str) or Path(name).name != name or name in seen
                    or not name.endswith(".nt") or (root / name).is_symlink()):
                raise ValueError("Unsafe or duplicate fact part path")
            seen.add(name)
            if (type(part["bytes"]) is not int or not 0 < part["bytes"] <= max_part_bytes
                    or type(part["fact_occurrences"]) is not int or part["fact_occurrences"] <= 0):
                raise ValueError("Invalid or excessive fact part size")
        if (sum(p["bytes"] for p in parts) != manifest["output_bytes"]
                or manifest["output_bytes"] > max_bytes
                or sum(p["fact_occurrences"] for p in parts) != manifest["fact_occurrences"]):
            raise ValueError("Fact snapshot inventory totals exceed or disagree with budgets")
        return cls(root, manifest, digest)

    def parts(self) -> Iterator[tuple[Path, bytes, int]]:
        for part in self.manifest["parts"]:
            path = self.root / part["path"]
            if path.is_symlink() or path.stat().st_size != part["bytes"]:
                raise ValueError("Fact part changed")
            payload = path.read_bytes()
            if len(payload) != part["bytes"] or hashlib.sha256(payload).hexdigest() != part["sha256"]:
                raise ValueError("Fact part content hash mismatch")
            yield path, payload, part["fact_occurrences"]


def load_fact_snapshot(snapshot: FactSnapshot, *, neo4j: Any, fuseki: Any,
                       fuseki_loader: Any, output_root: str | Path,
                       batch_rows: int = 4096, max_operations: int = 2000) -> dict[str, Any]:
    """Bootstrap an empty owned database pair once; preserve any partial failure."""
    if any(type(v) is not int or v <= 0 for v in (batch_rows, max_operations)):
        raise ValueError("Loading budgets must be positive integers")
    from rdflib import URIRef
    from rdflib.plugins.parsers.ntriples import W3CNTriplesParser

    output = Path(output_root).resolve()
    if output == snapshot.root or output.is_relative_to(snapshot.root):
        raise ValueError("Load output must be outside source snapshot")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    operations: list[dict[str, Any]] = []
    counts = {"fact_occurrences": 0, "resource_occurrences": 0, "literal_occurrences": 0}
    request = {"schema_version": "freebase-backend-load-v1", "snapshot_manifest_sha256": snapshot.manifest_sha256,
        "snapshot_root": str(snapshot.root), "encoding": "rdf-resource-edge-mirror-v1",
        "batch_rows": batch_rows, "max_operations": max_operations, "automatic_retries": 0}
    (output / "request.json").write_text(json.dumps(request, indent=2))
    ledger = (output / "operations.jsonl").open("x")

    def record(value: dict[str, Any]) -> None:
        operations.append(value)
        ledger.write(json.dumps(value, sort_keys=True) + "\n")
        ledger.flush()

    def budget() -> None:
        if len(operations) >= max_operations:
            raise ValueError("Fact loading operation budget exhausted")

    def execute(client: Any, text: str, parameters: dict[str, Any] | None = None):
        budget()
        artifact = QueryArtifact(f"fact-load-{len(operations):04d}",
            "cypher" if client.backend_id == "neo4j" else "sparql", text, parameters=parameters or {})
        result = client.execute(artifact)
        record({"backend_id": client.backend_id, "artifact_id": artifact.artifact_id,
                "request_bytes": len(json.dumps(artifact.to_dict()).encode()), **result.to_dict()})
        if not result.success:
            raise RuntimeError(result.error or "Fact loading backend operation failed")
        return result.rows

    pending: list[dict[str, str]] = []

    def flush() -> None:
        if not pending:
            return
        rows = execute(neo4j,
            f"UNWIND $rows AS row MERGE (s:{RESOURCE_LABEL} {{iri: row.s}}) "
            f"MERGE (o:{RESOURCE_LABEL} {{iri: row.o}}) "
            f"MERGE (s)-[:{EDGE_LABEL} {{predicate: row.p}}]->(o) RETURN count(*) AS loaded",
            {"rows": list(pending)})
        if rows != [{"loaded": len(pending)}]:
            raise RuntimeError("Neo4j resource batch count mismatch")
        pending.clear()

    class Sink:
        def triple(self, subject, predicate, obj):
            if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
                raise ValueError("Snapshot requires URI subjects and predicates")
            counts["fact_occurrences"] += 1
            if isinstance(obj, URIRef):
                counts["resource_occurrences"] += 1
                pending.append({"s": str(subject), "p": str(predicate), "o": str(obj)})
                if len(pending) >= batch_rows:
                    flush()
            else:
                from rdflib import Literal
                if not isinstance(obj, Literal):
                    raise ValueError("Blank-node objects are unsupported")
                counts["literal_occurrences"] += 1

    result: dict[str, Any] = {**request, "success": False}
    try:
        if execute(neo4j, "MATCH (n) RETURN count(n) AS count") != [{"count": 0}]:
            raise ValueError("Neo4j target must be empty")
        rdf_empty = execute(fuseki, "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }")
        if len(rdf_empty) != 1 or str(rdf_empty[0].get("count")) != "0":
            raise ValueError("Fuseki target must be empty")
        execute(neo4j, f"CREATE CONSTRAINT xgap_rdf_resource_iri IF NOT EXISTS "
                       f"FOR (n:{RESOURCE_LABEL}) REQUIRE n.iri IS UNIQUE")
        parser = W3CNTriplesParser(Sink())
        for path, payload, expected_rows in snapshot.parts():
            budget()
            load = fuseki_loader.load(path)
            record(load.to_dict())
            if not load.success:
                raise RuntimeError(load.error or "Fuseki fact part load failed")
            # Detect source mutation across the existing file-based loader.
            if path.read_bytes() != payload:
                raise ValueError("Fact part changed while loading; target is partial")
            before = counts["fact_occurrences"]
            parser.parsestring(payload.decode("utf-8"))
            flush()
            if counts["fact_occurrences"] - before != expected_rows:
                raise ValueError("Fact part parsed count mismatch")
        if counts["fact_occurrences"] != snapshot.manifest["fact_occurrences"]:
            raise ValueError("Incomplete selected snapshot load")
        result["neo4j_counts"] = execute(neo4j,
            f"MATCH ()-[r:{EDGE_LABEL}]->() RETURN count(r) AS resource_edges")
        result["fuseki_counts"] = execute(fuseki, "SELECT (COUNT(*) AS ?triples) WHERE { ?s ?p ?o }")
        result["success"] = True
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        ledger.close()
        result.update(counts)
        result.update(operations_attempted=len(operations), elapsed_seconds=time.perf_counter()-started,
                      partial_target=not result["success"], paper_result=False)
        (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result
