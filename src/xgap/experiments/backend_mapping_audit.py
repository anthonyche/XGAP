"""Audit DatasetBundle RDF data, native mappings, and M9-emitted IRIs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.algebra.conditions import EdgeRef, LabelEquals, NodeRef, PropertyEquals
from xgap.algebra.ops import EdgesOp, NodesOp, SelectionOp
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.compilers.sparql import compile_sparql
from xgap.experiments.bundles import DatasetBundle


_PREFIX_RE = re.compile(r"^@prefix\s+([A-Za-z][\w-]*):\s*<([^>]+)>\s*\.\s*$")
_QNAME_RE = re.compile(r"\b([A-Za-z][\w-]*):([A-Za-z0-9_.-]+)\b")


def audit_dataset_backend_mapping(dataset: DatasetBundle) -> dict[str, Any]:
    mapping = RdfBackendMapping.from_artifact(dataset.backend_mapping)
    data_ref = dataset.backend_load.get("fuseki")
    if not isinstance(data_ref, str) or not data_ref:
        raise ValueError("DatasetBundle has no Fuseki load artifact.")
    data_path = (dataset.root / data_ref).resolve()
    roles = _turtle_iri_roles(data_path)
    records: list[dict[str, Any]] = []

    for token_kind in ("node_labels", "edge_labels", "properties"):
        for logical_token in sorted(mapping.compiler_tokens[token_kind]):
            mapped = mapping.resolve(logical_token, token_kind)
            artifact = compile_sparql(
                _representative_plan(token_kind, logical_token),
                profile=default_profile("fuseki"),
                artifact_id=f"mapping-audit-{token_kind}-{logical_token}",
                backend_mapping=mapping,
            )
            emitted = _emitted_iri(artifact.parameters, token_kind, logical_token)
            expected_role = "class" if token_kind == "node_labels" else "predicate"
            data_iri = (
                mapped.iri if mapped.iri in roles[f"{expected_role}_iris"] else None
            )
            consistent = data_iri == mapped.iri == emitted
            records.append(
                {
                    "logical_token": logical_token,
                    "canonical_term_id": mapped.canonical_term_id,
                    "kind": mapped.kind,
                    "data_role": expected_role,
                    "URI_data": data_iri,
                    "URI_mapping": mapped.iri,
                    "URI_m9": emitted,
                    "consistent": consistent,
                }
            )

    mismatches = [record for record in records if not record["consistent"]]
    return {
        "schema_version": "post-m12d-backend-mapping-audit-v1",
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.version,
        "backend_id": "fuseki",
        "mapping_id": mapping.mapping_id,
        "mapping_version": mapping.version,
        "mapping_hash": mapping.mapping_hash,
        "data_artifact": str(data_path),
        "status": "pass" if not mismatches else "fail",
        "records": records,
        "mismatches": mismatches,
    }


def _representative_plan(token_kind: str, token: str):
    if token_kind == "node_labels":
        return SelectionOp(LabelEquals(NodeRef.first(), token), NodesOp())
    if token_kind == "edge_labels":
        return SelectionOp(LabelEquals(EdgeRef(1), token), EdgesOp())
    if token_kind == "properties":
        return SelectionOp(PropertyEquals(NodeRef.first(), token, "audit"), NodesOp())
    raise ValueError(f"Unknown compiler token kind '{token_kind}'.")


def _emitted_iri(
    parameters: Mapping[str, Any],
    token_kind: str,
    logical_token: str,
) -> str | None:
    mapping = parameters.get("backend_mapping")
    if not isinstance(mapping, Mapping):
        return None
    terms = mapping.get("relevant_mapped_iris", ())
    if not isinstance(terms, list):
        return None
    for term in terms:
        if not isinstance(term, Mapping):
            continue
        if (
            term.get("logical_token") == logical_token
            and _token_kind_for_term(str(term.get("kind", ""))) == token_kind
        ):
            value = term.get("iri")
            return str(value) if value is not None else None
    return None


def _token_kind_for_term(kind: str) -> str:
    return {
        "class": "node_labels",
        "relation": "edge_labels",
        "property": "properties",
    }.get(kind, "")


def _turtle_iri_roles(path: Path) -> dict[str, set[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    prefixes = {
        match.group(1): match.group(2)
        for line in lines
        if (match := _PREFIX_RE.match(line.strip()))
    }
    class_iris: set[str] = set()
    predicate_iris: set[str] = set()
    statement_lines: list[str] = []

    def expand(qname: tuple[str, str]) -> str | None:
        namespace = prefixes.get(qname[0])
        return namespace + qname[1] if namespace else None

    def consume(statement: str) -> None:
        segments = [item.strip() for item in statement.rstrip(".").split(";")]
        for index, segment in enumerate(segments):
            qnames = _QNAME_RE.findall(segment)
            if index == 0:
                if " a " in f" {segment} " and len(qnames) >= 2:
                    iri = expand(qnames[1])
                    if iri:
                        class_iris.add(iri)
                elif len(qnames) >= 2:
                    iri = expand(qnames[1])
                    if iri:
                        predicate_iris.add(iri)
            elif segment.startswith("a ") and qnames:
                iri = expand(qnames[0])
                if iri:
                    class_iris.add(iri)
            elif qnames:
                iri = expand(qnames[0])
                if iri:
                    predicate_iris.add(iri)

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("@prefix"):
            continue
        statement_lines.append(stripped)
        if stripped.endswith("."):
            consume(" ".join(statement_lines))
            statement_lines = []
    if statement_lines:
        raise ValueError(f"Unterminated Turtle statement in {path}.")
    return {"class_iris": class_iris, "predicate_iris": predicate_iris}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit RDF data, DatasetBundle mapping, and M9 SPARQL IRIs."
    )
    parser.add_argument("--dataset", default="datasets/financial_risk_dev")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = audit_dataset_backend_mapping(DatasetBundle.load(args.dataset))
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
