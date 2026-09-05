"""Compile one resolved M15 query into a portable, hash-bound contract.

The contract maps a query identifier to exact backend artifacts, parameter
requirements, immutable semantic constraints, and answer oracles in an already
verified workload bundle. Compilation is side-effect free and makes no backend,
LLM, or ontology call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)


QUERY_SPEC_SCHEMA_VERSION = "m15-f2-query-spec-v1"
QUERY_CONTRACT_SCHEMA_VERSION = "m15-f2-query-contract-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ROLES = frozenset({"neo4j_full", "neo4j_bound", "fuseki_risk"})
_BACKEND_LANGUAGES = {"neo4j": "cypher", "fuseki": "sparql"}
_ARTIFACT_ROLE_CONTRACTS = {
    "neo4j_full": {
        "backend_id": "neo4j",
        "language": "cypher",
        "filename": "query_recent_transfers.cypher",
        "artifact_id_template": "m15-f0-{workload_id}-neo4j-full",
    },
    "neo4j_bound": {
        "backend_id": "neo4j",
        "language": "cypher",
        "filename": "query_recent_transfers_bound.cypher",
        "artifact_id_template": "m15-f0-{workload_id}-neo4j-bound",
    },
    "fuseki_risk": {
        "backend_id": "fuseki",
        "language": "sparql",
        "filename": "query_high_risk.rq",
        "artifact_id_template": "m15-f0-{workload_id}-fuseki-risk",
    },
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a safe identifier")
    return value


def _unique_safe_ids(value: object, *, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a nonempty array")
    items = [_safe_identifier(item, name=f"{name} item") for item in value]
    if len(items) != len(set(items)):
        raise ValueError(f"{name} must contain unique identifiers")
    return items


def _json_value(value: object, *, name: str) -> object:
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite JSON value") from exc
    return value


@dataclass(frozen=True)
class M15ResolvedQuerySpec:
    query_id: str
    resolved_intent: str
    hard_constraints: tuple[Mapping[str, Any], ...]
    semantic_operator_ids: tuple[str, ...]
    output_fields: tuple[str, ...]
    artifacts: tuple[Mapping[str, Any], ...]
    source_oracle_filename: str
    final_oracle_filename: str
    automatic_retries: int
    paper_result: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "M15ResolvedQuerySpec":
        expected = {
            "schema_version",
            "query_id",
            "resolved_intent",
            "hard_constraints",
            "semantic_operator_ids",
            "output_fields",
            "artifacts",
            "source_oracle_filename",
            "final_oracle_filename",
            "automatic_retries",
            "paper_result",
        }
        if set(value) != expected:
            raise ValueError("query spec fields do not match the v1 contract")
        if value.get("schema_version") != QUERY_SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"query spec schema_version must be {QUERY_SPEC_SCHEMA_VERSION}"
            )
        query_id = _safe_identifier(value.get("query_id"), name="query_id")
        resolved_intent = value.get("resolved_intent")
        if not isinstance(resolved_intent, str) or not resolved_intent.strip():
            raise ValueError("resolved_intent must be a nonempty string")

        raw_constraints = value.get("hard_constraints")
        if not isinstance(raw_constraints, list) or not raw_constraints:
            raise ValueError("hard_constraints must be a nonempty array")
        constraints: list[dict[str, Any]] = []
        constraint_ids: list[str] = []
        for raw in raw_constraints:
            if not isinstance(raw, Mapping) or set(raw) != {
                "constraint_id",
                "kind",
                "value",
                "relaxable",
            }:
                raise ValueError("hard constraint fields do not match the v1 contract")
            constraint_id = _safe_identifier(
                raw.get("constraint_id"), name="constraint_id"
            )
            kind = _safe_identifier(raw.get("kind"), name="constraint kind")
            if raw.get("relaxable") is not False:
                raise ValueError("resolved query hard constraints cannot be relaxable")
            constraints.append(
                {
                    "constraint_id": constraint_id,
                    "kind": kind,
                    "value": _json_value(raw.get("value"), name="constraint value"),
                    "relaxable": False,
                }
            )
            constraint_ids.append(constraint_id)
        if len(constraint_ids) != len(set(constraint_ids)):
            raise ValueError("hard constraint IDs must be unique")

        semantic_operator_ids = _unique_safe_ids(
            value.get("semantic_operator_ids"), name="semantic_operator_ids"
        )
        output_fields = _unique_safe_ids(
            value.get("output_fields"), name="output_fields"
        )
        artifacts = _validate_artifact_specs(value.get("artifacts"))
        source_oracle = _safe_bundle_filename(
            value.get("source_oracle_filename"), name="source oracle"
        )
        final_oracle = _safe_bundle_filename(
            value.get("final_oracle_filename"), name="final oracle"
        )
        if source_oracle != "expected_source_results.json":
            raise ValueError("source oracle must be expected_source_results.json")
        if final_oracle != "expected_result.json":
            raise ValueError("final oracle must be expected_result.json")
        if value.get("automatic_retries") != 0:
            raise ValueError("query contract must disable automatic retries")
        if value.get("paper_result") is not False:
            raise ValueError("development query spec must declare paper_result=false")
        return cls(
            query_id=query_id,
            resolved_intent=resolved_intent,
            hard_constraints=tuple(constraints),
            semantic_operator_ids=tuple(semantic_operator_ids),
            output_fields=tuple(output_fields),
            artifacts=tuple(artifacts),
            source_oracle_filename=source_oracle,
            final_oracle_filename=final_oracle,
            automatic_retries=0,
            paper_result=False,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "M15ResolvedQuerySpec":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("query spec must be a JSON object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": QUERY_SPEC_SCHEMA_VERSION,
            "query_id": self.query_id,
            "resolved_intent": self.resolved_intent,
            "hard_constraints": [dict(item) for item in self.hard_constraints],
            "semantic_operator_ids": list(self.semantic_operator_ids),
            "output_fields": list(self.output_fields),
            "artifacts": [dict(item) for item in self.artifacts],
            "source_oracle_filename": self.source_oracle_filename,
            "final_oracle_filename": self.final_oracle_filename,
            "automatic_retries": self.automatic_retries,
            "paper_result": self.paper_result,
        }


def _safe_bundle_filename(value: object, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or Path(value).name != value
        or value in {".", ".."}
    ):
        raise ValueError(f"{name} filename must name one bundle member")
    return value


def _validate_artifact_specs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(_ARTIFACT_ROLES):
        raise ValueError("artifacts must define the three M15 query roles")
    artifacts: list[dict[str, Any]] = []
    roles: list[str] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {
            "role",
            "backend_id",
            "language",
            "filename",
            "artifact_id_template",
            "parameters",
        }:
            raise ValueError("query artifact fields do not match the v1 contract")
        role = _safe_identifier(raw.get("role"), name="artifact role")
        backend_id = _safe_identifier(
            raw.get("backend_id"), name="artifact backend_id"
        )
        language = _safe_identifier(raw.get("language"), name="artifact language")
        if _BACKEND_LANGUAGES.get(backend_id) != language:
            raise ValueError("artifact backend and query language are inconsistent")
        filename = _safe_bundle_filename(raw.get("filename"), name="artifact")
        template = raw.get("artifact_id_template")
        if not isinstance(template, str) or template.count("{workload_id}") != 1:
            raise ValueError(
                "artifact_id_template must contain one {workload_id} placeholder"
            )
        if "{" in template.replace("{workload_id}", "") or "}" in template.replace(
            "{workload_id}", ""
        ):
            raise ValueError("artifact_id_template has an unsupported placeholder")
        parameters = raw.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError("artifact parameters must be an object")
        parameters = dict(_json_value(dict(parameters), name="artifact parameters"))
        artifacts.append(
            {
                "role": role,
                "backend_id": backend_id,
                "language": language,
                "filename": filename,
                "artifact_id_template": template,
                "parameters": parameters,
            }
        )
        roles.append(role)
    if set(roles) != _ARTIFACT_ROLES or len(roles) != len(set(roles)):
        raise ValueError("artifact roles must contain each M15 role exactly once")
    by_role = {item["role"]: item for item in artifacts}
    for role, expected in _ARTIFACT_ROLE_CONTRACTS.items():
        actual = {
            key: by_role[role][key]
            for key in (
                "backend_id",
                "language",
                "filename",
                "artifact_id_template",
            )
        }
        if actual != expected:
            raise ValueError(f"{role} artifact identity contract is invalid")
    if by_role["neo4j_full"]["parameters"]:
        raise ValueError("neo4j_full must not declare parameters")
    if by_role["fuseki_risk"]["parameters"]:
        raise ValueError("fuseki_risk must not declare parameters")
    expected_bound = {
        "company_ids": {
            "type": "array[string]",
            "required": True,
            "max_items_from": "workload.max_bindings",
        }
    }
    if by_role["neo4j_bound"]["parameters"] != expected_bound:
        raise ValueError("neo4j_bound parameter contract is invalid")
    return artifacts


@dataclass(frozen=True)
class M15QueryContract:
    query_spec_path: Path
    body: Mapping[str, Any]
    query_contract_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **dict(self.body),
            "query_contract_sha256": self.query_contract_sha256,
        }


def compile_m15_query_contract(
    *,
    query_spec: str | Path,
    workload_bundle: M15WorkloadBundle | str | Path,
) -> M15QueryContract:
    """Bind one resolved query spec to exact artifacts in a verified bundle."""

    query_spec_candidate = Path(query_spec)
    if query_spec_candidate.is_symlink():
        raise ValueError("query_spec must be a regular non-symbolic-link file")
    query_spec_path = query_spec_candidate.resolve()
    if not query_spec_path.is_file():
        raise ValueError("query_spec must be a regular non-symbolic-link file")
    spec = M15ResolvedQuerySpec.from_json(query_spec_path)
    bundle = load_m15_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15WorkloadBundle)
        else workload_bundle
    )
    bound_artifacts: list[dict[str, Any]] = []
    for artifact in spec.artifacts:
        filename = str(artifact["filename"])
        try:
            path = bundle.path(filename)
        except KeyError as exc:
            raise ValueError(
                f"query artifact is not a declared workload member: {filename}"
            ) from exc
        artifact_id = str(artifact["artifact_id_template"]).replace(
            "{workload_id}", bundle.spec.workload_id
        )
        _safe_identifier(artifact_id, name="compiled artifact_id")
        digest = bundle.source_hashes.get(filename)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"bundle has no valid digest for query artifact: {filename}")
        bound_artifacts.append(
            {
                "role": artifact["role"],
                "backend_id": artifact["backend_id"],
                "language": artifact["language"],
                "filename": filename,
                "artifact_id": artifact_id,
                "sha256": digest,
                "parameters": dict(artifact["parameters"]),
            }
        )

    oracle_entries: list[dict[str, Any]] = []
    for role, filename, row_count in (
        (
            "source_answers",
            spec.source_oracle_filename,
            sum(len(rows) for rows in bundle.expected_source_rows.values()),
        ),
        ("final_answer", spec.final_oracle_filename, len(bundle.expected_rows)),
    ):
        digest = bundle.source_hashes.get(filename)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"bundle has no valid digest for oracle: {filename}")
        oracle_entries.append(
            {
                "role": role,
                "filename": filename,
                "sha256": digest,
                "row_count": row_count,
            }
        )

    body = {
        "schema_version": QUERY_CONTRACT_SCHEMA_VERSION,
        "query_spec_schema_version": QUERY_SPEC_SCHEMA_VERSION,
        "query_id": spec.query_id,
        "query_spec_sha256": _sha256_file(query_spec_path),
        "workload": {
            "workload_id": bundle.spec.workload_id,
            "bundle_schema_version": bundle.manifest["schema_version"],
            "generator_version": bundle.manifest["generator_version"],
            "spec_sha256": bundle.manifest["spec_sha256"],
        },
        "resolved_intent": spec.resolved_intent,
        "hard_constraints": [dict(item) for item in spec.hard_constraints],
        "semantic_operator_ids": list(spec.semantic_operator_ids),
        "output_fields": list(spec.output_fields),
        "artifacts": bound_artifacts,
        "oracles": oracle_entries,
        "automatic_retries": 0,
        "llm_calls": 0,
        "ontology_calls": 0,
        "evidence_class": "development_resolved_query_contract",
        "paper_result": False,
    }
    return M15QueryContract(
        query_spec_path=query_spec_path,
        body=body,
        query_contract_sha256=_content_hash(body),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-spec", required=True)
    parser.add_argument("--workload-bundle", required=True)
    args = parser.parse_args(argv)
    try:
        contract = compile_m15_query_contract(
            query_spec=args.query_spec,
            workload_bundle=args.workload_bundle,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {"status": "success", **contract.to_dict()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
