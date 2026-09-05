"""Deterministic, hash-bound workload bundles for M15 federation scaling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SPEC_SCHEMA_VERSION = "m15-f0-workload-spec-v1"
BUNDLE_SCHEMA_VERSION = "m15-f0-workload-bundle-v1"
GENERATOR_VERSION = "m15-f0-generator-v2"
_SAFE_WORKLOAD_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FILES = (
    "workload_spec.json",
    "load_neo4j.cypher",
    "load_fuseki.ttl",
    "query_recent_transfers.cypher",
    "query_recent_transfers_bound.cypher",
    "query_high_risk.rq",
    "expected_source_results.json",
    "expected_result.json",
)


def _bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class M15WorkloadSpec:
    """Exact parameters for one deterministic two-source workload."""

    workload_id: str
    seed: str
    company_count: int
    transfer_count: int
    high_risk_company_count: int
    hot_company_count: int
    hot_transfer_count: int
    high_risk_placement: str
    max_bindings: int

    def __post_init__(self) -> None:
        if not isinstance(self.workload_id, str):
            raise ValueError("workload_id must be a string")
        if not _SAFE_WORKLOAD_ID.fullmatch(self.workload_id):
            raise ValueError(
                "workload_id must match [a-z][a-z0-9_-]{0,63}"
            )
        if not isinstance(self.seed, str):
            raise ValueError("seed must be a string")
        if not self.seed or len(self.seed.encode("utf-8")) > 256:
            raise ValueError("seed must be nonempty and at most 256 UTF-8 bytes")
        _bounded_int(self.company_count, "company_count", minimum=2, maximum=100_000)
        _bounded_int(
            self.transfer_count,
            "transfer_count",
            minimum=1,
            maximum=5_000_000,
        )
        _bounded_int(
            self.high_risk_company_count,
            "high_risk_company_count",
            minimum=1,
            maximum=self.company_count,
        )
        _bounded_int(
            self.hot_company_count,
            "hot_company_count",
            minimum=1,
            maximum=self.company_count - 1,
        )
        _bounded_int(
            self.hot_transfer_count,
            "hot_transfer_count",
            minimum=0,
            maximum=self.transfer_count,
        )
        if not isinstance(self.high_risk_placement, str) or (
            self.high_risk_placement not in {"hot_first", "cold_first"}
        ):
            raise ValueError(
                "high_risk_placement must be 'hot_first' or 'cold_first'"
            )
        _bounded_int(
            self.max_bindings,
            "max_bindings",
            minimum=1,
            maximum=100_000,
        )
        if self.max_bindings < self.high_risk_company_count:
            raise ValueError(
                "max_bindings must cover every high-risk company in the exact bind plan"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "M15WorkloadSpec":
        if value.get("schema_version") != SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"workload spec schema_version must be {SPEC_SCHEMA_VERSION}"
            )
        expected = {
            "schema_version",
            "workload_id",
            "seed",
            "company_count",
            "transfer_count",
            "high_risk_company_count",
            "hot_company_count",
            "hot_transfer_count",
            "high_risk_placement",
            "max_bindings",
        }
        unknown = set(value) - expected
        missing = expected - set(value)
        if unknown:
            raise ValueError(f"unknown workload spec fields: {', '.join(sorted(unknown))}")
        if missing:
            raise ValueError(f"missing workload spec fields: {', '.join(sorted(missing))}")
        return cls(
            workload_id=value["workload_id"],
            seed=value["seed"],
            company_count=_bounded_int(
                value["company_count"],
                "company_count",
                minimum=2,
                maximum=100_000,
            ),
            transfer_count=_bounded_int(
                value["transfer_count"],
                "transfer_count",
                minimum=1,
                maximum=5_000_000,
            ),
            high_risk_company_count=_bounded_int(
                value["high_risk_company_count"],
                "high_risk_company_count",
                minimum=1,
                maximum=100_000,
            ),
            hot_company_count=_bounded_int(
                value["hot_company_count"],
                "hot_company_count",
                minimum=1,
                maximum=100_000,
            ),
            hot_transfer_count=_bounded_int(
                value["hot_transfer_count"],
                "hot_transfer_count",
                minimum=0,
                maximum=5_000_000,
            ),
            high_risk_placement=value["high_risk_placement"],
            max_bindings=_bounded_int(
                value["max_bindings"],
                "max_bindings",
                minimum=1,
                maximum=100_000,
            ),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "M15WorkloadSpec":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workload spec must be a JSON object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SPEC_SCHEMA_VERSION,
            "workload_id": self.workload_id,
            "seed": self.seed,
            "company_count": self.company_count,
            "transfer_count": self.transfer_count,
            "high_risk_company_count": self.high_risk_company_count,
            "hot_company_count": self.hot_company_count,
            "hot_transfer_count": self.hot_transfer_count,
            "high_risk_placement": self.high_risk_placement,
            "max_bindings": self.max_bindings,
        }


@dataclass(frozen=True)
class M15WorkloadBundle:
    root: Path
    spec: M15WorkloadSpec
    manifest: Mapping[str, Any]
    expected_source_rows: Mapping[str, list[dict[str, Any]]]
    expected_rows: list[dict[str, Any]]

    def path(self, filename: str) -> Path:
        if filename not in _FILES:
            raise KeyError(f"unknown workload bundle file: {filename}")
        return self.root / filename

    @property
    def source_hashes(self) -> dict[str, str]:
        raw = self.manifest["files_sha256"]
        return {str(key): str(value) for key, value in dict(raw).items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "spec": self.spec.to_dict(),
            "manifest": dict(self.manifest),
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _cypher_literal(value: object) -> str:
    """Encode the generator's bounded values as Cypher, not JSON.

    JSON objects quote their keys, while Cypher map literals require property
    key identifiers.  The workload only admits identifier-shaped internal map
    keys and JSON-compatible scalar values.
    """

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise ValueError("workload Cypher literals do not admit floating-point values")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_cypher_literal(item) for item in value) + "]"
    if isinstance(value, Mapping):
        fields: list[str] = []
        for key in sorted(value):
            if not isinstance(key, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                key,
            ):
                raise ValueError(f"invalid generated Cypher map key: {key!r}")
            fields.append(f"{key}:{_cypher_literal(value[key])}")
        return "{" + ",".join(fields) + "}"
    raise ValueError(
        f"unsupported generated Cypher literal type: {type(value).__name__}"
    )


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.write_text(_json_text(value), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ranked_company_ids(spec: M15WorkloadSpec) -> list[str]:
    width = max(6, len(str(spec.company_count)))
    company_ids = [f"C{index:0{width}d}" for index in range(1, spec.company_count + 1)]
    return sorted(
        company_ids,
        key=lambda item: (
            hashlib.sha256(f"{spec.seed}:company:{item}".encode("utf-8")).hexdigest(),
            item,
        ),
    )


def _workload_rows(
    spec: M15WorkloadSpec,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = _ranked_company_ids(spec)
    hot = ranked[: spec.hot_company_count]
    cold = ranked[spec.hot_company_count :]
    risk_order = hot + cold if spec.high_risk_placement == "hot_first" else cold + hot
    high_risk = set(risk_order[: spec.high_risk_company_count])

    company_rows = [
        {
            "id": company_id,
            "account_id": f"acct-{spec.workload_id}-{company_id.lower()}",
            "name": f"Company {company_id}",
            "risk": "HIGH" if company_id in high_risk else "LOW",
        }
        for company_id in sorted(ranked)
    ]
    transfers: list[dict[str, Any]] = []
    transfer_width = max(7, len(str(spec.transfer_count)))
    for offset in range(spec.transfer_count):
        target_pool = hot if offset < spec.hot_transfer_count else cold
        company_id = target_pool[
            (offset if offset < spec.hot_transfer_count else offset - spec.hot_transfer_count)
            % len(target_pool)
        ]
        transfers.append(
            {
                "id": f"T{offset + 1:0{transfer_width}d}",
                "target_account_id": f"acct-{spec.workload_id}-{company_id.lower()}",
                "company_id": company_id,
                "amount": 50_000 + offset,
                "currency": "USD",
                "occurred_on": "2026-08-20",
            }
        )
    return company_rows, transfers, sorted(
        (row for row in company_rows if row["risk"] == "HIGH"),
        key=lambda row: row["id"],
    )


def _cypher_token(workload_id: str) -> str:
    return workload_id.replace("-", "_").upper()


def _neo4j_load(
    spec: M15WorkloadSpec,
    companies: list[dict[str, Any]],
    transfers: list[dict[str, Any]],
) -> str:
    token = _cypher_token(spec.workload_id)
    person_label = f"M15F0_{token}_Person"
    account_label = f"M15F0_{token}_Account"
    company_label = f"M15F0_{token}_CompanyRef"
    owns = f"M15F0_{token}_OWNS"
    transfer = f"M15F0_{token}_TRANSFER"
    compact_companies = [
        {"id": row["id"], "account_id": row["account_id"]} for row in companies
    ]
    compact_transfers = [
        {
            "id": row["id"],
            "target_account_id": row["target_account_id"],
            "amount": row["amount"],
            "currency": row["currency"],
            "occurred_on": row["occurred_on"],
        }
        for row in transfers
    ]
    source_account = f"acct-{spec.workload_id}-alice"
    return "\n\n".join(
        (
            f"CREATE CONSTRAINT m15f0_{token.lower()}_person_id IF NOT EXISTS\n"
            f"FOR (p:{person_label}) REQUIRE p.id IS UNIQUE;",
            f"CREATE CONSTRAINT m15f0_{token.lower()}_account_id IF NOT EXISTS\n"
            f"FOR (a:{account_label}) REQUIRE a.id IS UNIQUE;",
            f"CREATE CONSTRAINT m15f0_{token.lower()}_company_id IF NOT EXISTS\n"
            f"FOR (c:{company_label}) REQUIRE c.id IS UNIQUE;",
            f'MERGE (person:{person_label} {{id: "person-alice-smith"}})\n'
            'SET person.name = "Alice Smith"\n'
            f'MERGE (source:{account_label} {{id: "{source_account}"}})\n'
            f"MERGE (person)-[:{owns}]->(source);",
            f"UNWIND {_cypher_literal(compact_companies)} AS row\n"
            f"MERGE (company:{company_label} {{id: row.id}})\n"
            f"MERGE (target:{account_label} {{id: row.account_id}})\n"
            f"MERGE (company)-[:{owns}]->(target);",
            f"UNWIND {_cypher_literal(compact_transfers)} AS row\n"
            f'MATCH (source:{account_label} {{id: "{source_account}"}})\n'
            f"MATCH (target:{account_label} {{id: row.target_account_id}})\n"
            f"MERGE (source)-[edge:{transfer} {{id: row.id}}]->(target)\n"
            "SET edge.amount = row.amount,\n"
            "    edge.currency = row.currency,\n"
            "    edge.occurred_on = date(row.occurred_on);",
        )
    ) + "\n"


def _neo4j_query(spec: M15WorkloadSpec, *, bound: bool) -> str:
    token = _cypher_token(spec.workload_id)
    predicate = "\n  AND company.id IN $company_ids" if bound else ""
    return (
        f'MATCH (person:M15F0_{token}_Person {{id: "person-alice-smith"}})'
        f"-[:M15F0_{token}_OWNS]->(source:M15F0_{token}_Account)\n"
        f"MATCH (source)-[edge:M15F0_{token}_TRANSFER]->"
        f"(target:M15F0_{token}_Account)\n"
        f"MATCH (company:M15F0_{token}_CompanyRef)"
        f"-[:M15F0_{token}_OWNS]->(target)\n"
        'WHERE edge.occurred_on >= date("2026-08-05")\n'
        f"  AND edge.amount >= 50000{predicate}\n"
        "RETURN person.id AS person_id,\n"
        "       person.name AS person,\n"
        f'       "neo:{spec.workload_id}:" + company.id AS company_id,\n'
        "       edge.id AS transfer_id,\n"
        "       edge.amount AS amount,\n"
        "       edge.currency AS currency,\n"
        "       toString(edge.occurred_on) AS occurred_on\n"
        "ORDER BY company_id, transfer_id;\n"
    )


def _turtle_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _fuseki_load(spec: M15WorkloadSpec, companies: list[dict[str, Any]]) -> str:
    prefix = f"http://xgap.example.org/m15-f0/{spec.workload_id}/"
    blocks = [f"@prefix data: <{prefix}> .", ""]
    for row in companies:
        company_id = str(row["id"]).lower()
        rdf_company_id = f"rdf:{spec.workload_id}:{row['id']}"
        blocks.extend(
            (
                f"data:company-{company_id}",
                "    a data:Company ;",
                f"    data:companyId {_turtle_literal(rdf_company_id)} ;",
                f"    data:name {_turtle_literal(str(row['name']))} ;",
                f"    data:riskLevel {_turtle_literal(str(row['risk']))} .",
                "",
            )
        )
    return "\n".join(blocks)


def _fuseki_query(spec: M15WorkloadSpec) -> str:
    prefix = f"http://xgap.example.org/m15-f0/{spec.workload_id}/"
    return (
        f"PREFIX data: <{prefix}>\n\n"
        "SELECT ?company_id ?company ?risk\n"
        "WHERE {\n"
        "  ?company_node a data:Company ;\n"
        "      data:companyId ?company_id ;\n"
        "      data:name ?company ;\n"
        "      data:riskLevel ?risk .\n"
        '  FILTER (?risk = "HIGH")\n'
        "}\n"
        "ORDER BY ?company_id\n"
    )


def _expected_rows(
    spec: M15WorkloadSpec,
    transfers: list[dict[str, Any]],
    high_risk_companies: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    high_risk_by_id = {str(row["id"]): row for row in high_risk_companies}
    neo4j = sorted(
        (
            {
                "person_id": "person-alice-smith",
                "person": "Alice Smith",
                "company_id": f"neo:{spec.workload_id}:{row['company_id']}",
                "transfer_id": row["id"],
                "amount": row["amount"],
                "currency": row["currency"],
                "occurred_on": row["occurred_on"],
            }
            for row in transfers
        ),
        key=lambda row: (str(row["company_id"]), str(row["transfer_id"])),
    )
    fuseki = [
        {
            "company_id": f"rdf:{spec.workload_id}:{row['id']}",
            "company": row["name"],
            "risk": row["risk"],
        }
        for row in high_risk_companies
    ]
    final = sorted(
        (
            {
                "person": "Alice Smith",
                "company": high_risk_by_id[str(row["company_id"])]["name"],
                "amount": row["amount"],
                "currency": row["currency"],
                "occurred_on": row["occurred_on"],
                "risk": "HIGH",
            }
            for row in transfers
            if str(row["company_id"]) in high_risk_by_id
        ),
        key=_canonical_json,
    )
    return {"neo4j": neo4j, "fuseki": fuseki}, final


def generate_m15_workload_bundle(
    spec: M15WorkloadSpec,
    destination: str | Path,
) -> M15WorkloadBundle:
    """Generate one bundle atomically and refuse to overwrite any destination."""

    destination_path = Path(destination).resolve()
    if destination_path.exists():
        raise FileExistsError(f"workload bundle destination already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination_path.name}.tmp-", dir=destination_path.parent)
    )
    try:
        companies, transfers, high_risk = _workload_rows(spec)
        expected_sources, expected = _expected_rows(spec, transfers, high_risk)
        if not expected:
            raise ValueError(
                "workload configuration produces an empty federated answer"
            )
        _write_json(temporary / "workload_spec.json", spec.to_dict())
        (temporary / "load_neo4j.cypher").write_text(
            _neo4j_load(spec, companies, transfers), encoding="utf-8"
        )
        (temporary / "load_fuseki.ttl").write_text(
            _fuseki_load(spec, companies), encoding="utf-8"
        )
        (temporary / "query_recent_transfers.cypher").write_text(
            _neo4j_query(spec, bound=False), encoding="utf-8"
        )
        (temporary / "query_recent_transfers_bound.cypher").write_text(
            _neo4j_query(spec, bound=True), encoding="utf-8"
        )
        (temporary / "query_high_risk.rq").write_text(
            _fuseki_query(spec), encoding="utf-8"
        )
        _write_json(temporary / "expected_source_results.json", expected_sources)
        _write_json(temporary / "expected_result.json", expected)
        hashes = {name: _sha256_file(temporary / name) for name in _FILES}
        manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "workload_id": spec.workload_id,
            "spec_sha256": hashes["workload_spec.json"],
            "files_sha256": hashes,
            "counts": {
                "companies": spec.company_count,
                "transfers": spec.transfer_count,
                "high_risk_companies": spec.high_risk_company_count,
                "answer_rows": len(expected),
            },
            "deterministic": True,
            "automatic_retries": 0,
            "paper_result": False,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, destination_path)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return load_m15_workload_bundle(destination_path)


def load_m15_workload_bundle(root: str | Path) -> M15WorkloadBundle:
    """Load a bundle only after validating its exact files and SHA-256 bindings."""

    bundle_root = Path(root).resolve()
    if not bundle_root.is_dir():
        raise ValueError(f"workload bundle root is not a directory: {bundle_root}")
    actual = {path.name for path in bundle_root.iterdir()}
    expected_files = {*_FILES, "manifest.json"}
    if actual != expected_files:
        missing = sorted(expected_files - actual)
        extra = sorted(actual - expected_files)
        raise ValueError(f"workload bundle file set mismatch: missing={missing}, extra={extra}")
    for name in expected_files:
        path = bundle_root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"workload bundle member must be a regular file: {name}")
    manifest_payload = json.loads((bundle_root / "manifest.json").read_text("utf-8"))
    if not isinstance(manifest_payload, dict):
        raise ValueError("workload bundle manifest must be a JSON object")
    if manifest_payload.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError(f"bundle schema_version must be {BUNDLE_SCHEMA_VERSION}")
    if manifest_payload.get("generator_version") != GENERATOR_VERSION:
        raise ValueError(f"bundle generator_version must be {GENERATOR_VERSION}")
    manifest_fields = {
        "schema_version",
        "generator_version",
        "workload_id",
        "spec_sha256",
        "files_sha256",
        "counts",
        "deterministic",
        "automatic_retries",
        "paper_result",
    }
    if set(manifest_payload) != manifest_fields:
        raise ValueError("workload bundle manifest field set is invalid")
    if manifest_payload.get("deterministic") is not True:
        raise ValueError("workload bundle must declare deterministic=true")
    if manifest_payload.get("automatic_retries") != 0:
        raise ValueError("workload bundle must declare automatic_retries=0")
    raw_hashes = manifest_payload.get("files_sha256")
    if not isinstance(raw_hashes, dict) or set(raw_hashes) != set(_FILES):
        raise ValueError("workload bundle manifest has an invalid file hash set")
    for name in _FILES:
        expected_hash = raw_hashes.get(name)
        if not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_hash
        ):
            raise ValueError(f"invalid SHA-256 value for workload file: {name}")
        if _sha256_file(bundle_root / name) != expected_hash:
            raise ValueError(f"workload bundle SHA-256 mismatch: {name}")
    spec = M15WorkloadSpec.from_json(bundle_root / "workload_spec.json")
    if manifest_payload.get("workload_id") != spec.workload_id:
        raise ValueError("workload bundle manifest workload_id does not match its spec")
    if manifest_payload.get("spec_sha256") != raw_hashes["workload_spec.json"]:
        raise ValueError("workload bundle spec digest is inconsistent")
    expected_sources = json.loads(
        (bundle_root / "expected_source_results.json").read_text("utf-8")
    )
    expected_rows = json.loads((bundle_root / "expected_result.json").read_text("utf-8"))
    if (
        not isinstance(expected_sources, dict)
        or set(expected_sources) != {"neo4j", "fuseki"}
        or any(
            not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
            for rows in expected_sources.values()
        )
    ):
        raise ValueError("expected source results must contain Neo4j and Fuseki row lists")
    if not isinstance(expected_rows, list) or any(
        not isinstance(row, dict) for row in expected_rows
    ):
        raise ValueError("expected result must be a JSON list of objects")
    companies, transfers, high_risk = _workload_rows(spec)
    deterministic_sources, deterministic_rows = _expected_rows(
        spec,
        transfers,
        high_risk,
    )
    deterministic_content = {
        "workload_spec.json": _json_text(spec.to_dict()),
        "load_neo4j.cypher": _neo4j_load(spec, companies, transfers),
        "load_fuseki.ttl": _fuseki_load(spec, companies),
        "query_recent_transfers.cypher": _neo4j_query(spec, bound=False),
        "query_recent_transfers_bound.cypher": _neo4j_query(spec, bound=True),
        "query_high_risk.rq": _fuseki_query(spec),
        "expected_source_results.json": _json_text(deterministic_sources),
        "expected_result.json": _json_text(deterministic_rows),
    }
    for name, expected_text in deterministic_content.items():
        if (bundle_root / name).read_text(encoding="utf-8") != expected_text:
            raise ValueError(
                f"workload bundle content is not deterministic for its spec: {name}"
            )
    counts = manifest_payload.get("counts")
    expected_counts = {
        "companies": spec.company_count,
        "transfers": spec.transfer_count,
        "high_risk_companies": spec.high_risk_company_count,
        "answer_rows": len(expected_rows),
    }
    if counts != expected_counts:
        raise ValueError("workload bundle manifest counts do not match its artifacts")
    if (
        len(expected_sources["neo4j"]) != spec.transfer_count
        or len(expected_sources["fuseki"]) != spec.high_risk_company_count
    ):
        raise ValueError("workload source oracle counts do not match its spec")
    if manifest_payload.get("paper_result") is not False:
        raise ValueError("development workload bundle must declare paper_result=false")
    return M15WorkloadBundle(
        root=bundle_root,
        spec=spec,
        manifest=manifest_payload,
        expected_source_rows={
            key: [dict(row) for row in rows]
            for key, rows in expected_sources.items()
        },
        expected_rows=[dict(row) for row in expected_rows],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        spec = M15WorkloadSpec.from_json(args.spec)
        bundle = generate_m15_workload_bundle(spec, args.output)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **bundle.to_dict()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
