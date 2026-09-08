"""M13-E1 guarded 18-query GrailQA live preflight runner."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import load_run_environment
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_local_catalog import validate_local_catalog
from xgap.experiments.grailqa_reachability import prompt_reachability_gate
from xgap.experiments.grailqa_semantic_pilot import (
    LiveSemanticPilotProvider,
    _infer_one,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import (
    STAGE_AWARE_FAILURE_TAXONOMY,
    classify_first_failure,
    component_match_report,
    parse_normalized_planner_response,
    semantic_deviation_distribution,
)
from xgap.experiments.relation_endpoints import RELATION_ENDPOINT_CONTRACT_VERSION
from xgap.experiments.semantic import DirectionalOntologyDeviation, SemanticDeviationConfig


PREFLIGHT_SCHEMA_VERSION = "m13e1-grailqa-semantic-preflight-v2"
QUERY_INDEPENDENT_ARTIFACT_PROFILE = "query_independent_catalog_v2"
QUERY_LOCAL_ARTIFACT_PROFILE = "query_local_e3b4"
QUERY_LOCAL_CATALOG_SCHEMA_VERSION = "m13e3b-grailqa-local-catalog-v1"
QUERY_LOCAL_REACHABILITY_SCHEMA_VERSION = "m13e3b4-grailqa-local-reachability-v2"
_ARTIFACT_PROFILES = frozenset(
    {QUERY_INDEPENDENT_ARTIFACT_PROFILE, QUERY_LOCAL_ARTIFACT_PROFILE}
)


def select_preflight_ids(
    reachability_rows: Sequence[Mapping[str, Any]],
    workload_by_id: Mapping[str, Mapping[str, Any]],
    *,
    size: int = 18,
    seed: int = 13031,
) -> tuple[str, ...]:
    """Outcome-independent seeded stratification over frozen workload/reachability."""

    if not 15 <= size <= 20:
        raise ValueError("Preflight size must be within [15, 20].")
    rows_by_q: dict[int, list[Mapping[str, Any]]] = {}
    for row in reachability_rows:
        question_id = str(row["question_id"])
        workload = workload_by_id[question_id]
        rows_by_q.setdefault(int(workload["Q"]), []).append(row)
    total = sum(len(values) for values in rows_by_q.values())
    raw_quotas = {q: size * len(values) / total for q, values in rows_by_q.items()}
    quotas = {q: int(value) for q, value in raw_quotas.items()}
    for q in sorted(
        rows_by_q,
        key=lambda key: (-(raw_quotas[key] - quotas[key]), key),
    )[: size - sum(quotas.values())]:
        quotas[q] += 1
    selected: list[str] = []
    for q in sorted(rows_by_q):
        buckets: dict[tuple[int, str, int], list[str]] = {}
        for row in rows_by_q[q]:
            question_id = str(row["question_id"])
            workload = workload_by_id[question_id]
            relations = tuple(str(item) for item in workload.get("relations", ()))
            domain = relations[0].split(".", 1)[0] if relations else "unknown"
            deployed = _mapping(row["deployed_prompt"], "deployed_prompt")
            reachability_score = sum(
                bool(_mapping(deployed[kind], kind)["reachable"])
                for kind in ("entity", "relation", "type")
            )
            key = (int(workload["path_length"]), domain, reachability_score)
            buckets.setdefault(key, []).append(question_id)
        for key, values in buckets.items():
            values.sort(
                key=lambda question_id: hashlib.sha256(
                    f"{seed}:{q}:{key}:{question_id}".encode("ascii")
                ).hexdigest()
            )
        keys = sorted(
            buckets,
            key=lambda key: hashlib.sha256(f"{seed}:{q}:{key}".encode("ascii")).hexdigest(),
        )
        q_selected: list[str] = []
        while len(q_selected) < quotas[q]:
            progressed = False
            for key in keys:
                if buckets[key] and len(q_selected) < quotas[q]:
                    q_selected.append(buckets[key].pop(0))
                    progressed = True
            if not progressed:
                raise ValueError("Insufficient records for requested preflight quota.")
        selected.extend(q_selected)
    return tuple(selected)


@dataclass(frozen=True)
class GrailQAPreflightSpec:
    path: Path
    data: Mapping[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "GrailQAPreflightSpec":
        spec_path = Path(path).resolve()
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping) or data.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
            raise ValueError("Unsupported GrailQA semantic preflight v2 spec.")
        expected = str(data.get("freeze_hash", ""))
        payload = {key: value for key, value in data.items() if key != "freeze_hash"}
        if content_hash(payload) != expected:
            raise ValueError("Preflight v2 freeze_hash does not match canonical content.")
        ids = tuple(str(item) for item in data.get("question_ids", ()))
        if not 15 <= len(ids) <= 20 or len(ids) != len(set(ids)):
            raise ValueError("Preflight must contain 15-20 unique frozen question IDs.")
        return cls(spec_path, dict(data))

    @property
    def question_ids(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.data["question_ids"])


def _artifact_paths(
    spec: GrailQAPreflightSpec, repo: Path
) -> tuple[str, Path, Path, Path, Path]:
    profile = os.environ.get(
        "XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE",
        QUERY_INDEPENDENT_ARTIFACT_PROFILE,
    )
    catalog_root = _environment_path(
        "XGAP_GRAILQA_CATALOG_V2", repo / str(spec.data["catalog_root"]), repo
    )
    reachability_root = _environment_path(
        "XGAP_GRAILQA_REACHABILITY_V2",
        repo / str(spec.data["reachability_root"]),
        repo,
    )
    default_summary = reachability_root / (
        "audit_summary.json"
        if profile == QUERY_LOCAL_ARTIFACT_PROFILE
        else "summary.json"
    )
    summary_path = _environment_path(
        "XGAP_GRAILQA_REACHABILITY_SUMMARY", default_summary, repo
    )
    rows_path = _environment_path(
        "XGAP_GRAILQA_REACHABILITY_ROWS",
        reachability_root / "reachability.jsonl",
        repo,
    )
    return profile, catalog_root, reachability_root, summary_path, rows_path


def _environment_path(name: str, default: Path, repo: Path) -> Path:
    raw = os.environ.get(name)
    path = default if raw is None else Path(raw).expanduser()
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _validated_artifact_profile_name(profile: str) -> str:
    if profile not in _ARTIFACT_PROFILES:
        raise ValueError(f"Unsupported preflight artifact profile: {profile}.")
    return profile


def _validate_exact_question_set(
    values: Sequence[object], expected: Sequence[str], *, name: str
) -> tuple[str, ...]:
    ids = tuple(str(item) for item in values)
    if not all(ids):
        raise ValueError(f"{name} requires nonempty question IDs.")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name} contains duplicate question IDs.")
    missing = sorted(set(expected) - set(ids))
    unexpected = sorted(set(ids) - set(expected))
    if missing or unexpected:
        raise ValueError(
            f"{name} does not match the frozen preflight question set: "
            f"missing={missing}, unexpected={unexpected}."
        )
    return ids


def _validate_artifact_profile(
    *,
    profile: str,
    catalog: GrailQAInferenceCatalogV2,
    summary: Mapping[str, Any],
    reachability_rows: Sequence[Mapping[str, Any]],
    reachability_rows_sha256: str,
    spec: GrailQAPreflightSpec,
) -> dict[str, Any]:
    if profile not in _ARTIFACT_PROFILES:
        raise ValueError(f"Unsupported preflight artifact profile: {profile}.")
    row_ids = tuple(str(item.get("question_id", "")) for item in reachability_rows)
    if not all(row_ids) or len(row_ids) != len(set(row_ids)):
        raise ValueError("Reachability rows require unique nonempty question IDs.")

    manifest = catalog.manifest
    if profile == QUERY_INDEPENDENT_ARTIFACT_PROFILE:
        missing = sorted(set(spec.question_ids) - set(row_ids))
        if missing:
            raise ValueError(
                f"Reachability rows are missing frozen preflight IDs: {missing}."
            )
        if manifest.get("requires_query_entity_filter") is True:
            raise ValueError(
                "A query-local catalog requires the explicit query_local_e3b4 profile."
            )
        return {
            "profile": profile,
            "question_count": len(row_ids),
            "question_contract": "frozen_preflight_ids_are_a_subset",
        }

    if manifest.get("local_catalog_schema_version") != QUERY_LOCAL_CATALOG_SCHEMA_VERSION:
        raise ValueError("Query-local catalog schema does not match M13-E3B.")
    if manifest.get("requires_query_entity_filter") is not True:
        raise ValueError("Query-local catalog must enforce per-question entity filtering.")
    if manifest.get("gold_used_for_construction") is not False:
        raise ValueError("Query-local catalog must attest gold_used_for_construction=false.")
    local_validation = validate_local_catalog(catalog.root)
    _validate_exact_question_set(
        tuple(manifest.get("question_ids", ())),
        spec.question_ids,
        name="Query-local catalog",
    )
    _validate_exact_question_set(
        row_ids,
        spec.question_ids,
        name="Query-local reachability rows",
    )
    if summary.get("schema_version") != QUERY_LOCAL_REACHABILITY_SCHEMA_VERSION:
        raise ValueError("Query-local reachability schema does not match M13-E3B.4.")
    if int(summary.get("question_count", -1)) != len(spec.question_ids):
        raise ValueError("Query-local reachability question count must be exactly 18.")
    prompt_limit = int(summary.get("prompt_limit", -1))
    if prompt_limit != int(spec.data["prompt_candidates_per_slot"]):
        raise ValueError("Query-local prompt bound does not match the frozen preflight spec.")
    endpoint = _mapping(
        summary.get("relation_endpoint_grounding"),
        "relation_endpoint_grounding",
    )
    if endpoint.get("contract_version") != RELATION_ENDPOINT_CONTRACT_VERSION:
        raise ValueError("Query-local endpoint-grounding contract version does not match.")
    for row in reachability_rows:
        row_endpoint = _mapping(
            row.get("relation_endpoint_grounding"),
            "reachability relation_endpoint_grounding",
        )
        if row_endpoint.get("contract_version") != RELATION_ENDPOINT_CONTRACT_VERSION:
            raise ValueError(
                "Every query-local reachability row must use the frozen endpoint contract."
            )
    expected_audit_hash = str(summary.get("audit_hash", ""))
    audit_payload = {key: value for key, value in summary.items() if key != "audit_hash"}
    if not expected_audit_hash or content_hash(audit_payload) != expected_audit_hash:
        raise ValueError("Query-local reachability audit hash does not match its content.")
    artifact_hashes = _mapping(summary.get("artifact_hashes"), "artifact_hashes")
    if artifact_hashes.get("reachability.jsonl") != reachability_rows_sha256:
        raise ValueError("Query-local reachability rows hash does not match the audit.")
    return {
        "profile": profile,
        "question_count": len(row_ids),
        "question_contract": "exact_frozen_preflight_id_set_order_independent",
        "prompt_candidates_per_slot": prompt_limit,
        "relation_endpoint_contract_version": RELATION_ENDPOINT_CONTRACT_VERSION,
        "audit_hash": expected_audit_hash,
        "local_catalog_validation": local_validation,
    }


def preflight_readiness(
    spec: GrailQAPreflightSpec,
    repo_root: str | Path,
    *,
    require_credentials: bool,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    checks: list[dict[str, Any]] = []

    def check(name: str, action: Any) -> Any:
        try:
            detail = action()
            checks.append({"name": name, "status": "pass", "detail": detail})
            return detail
        except Exception as error:  # noqa: BLE001 - readiness reports every boundary.
            checks.append({"name": name, "status": "fail", "detail": str(error)})
            return None

    profile, catalog_root, reachability_root, summary_path, rows_path = _artifact_paths(
        spec, repo
    )
    check(
        "artifact_profile",
        lambda: _validated_artifact_profile_name(profile),
    )
    catalog: GrailQAInferenceCatalogV2 | None = None
    try:
        catalog = GrailQAInferenceCatalogV2.load(catalog_root)
        checks.append(
            {"name": "catalog_v2", "status": "pass", "detail": catalog.catalog_hash}
        )
    except Exception as error:  # noqa: BLE001
        checks.append({"name": "catalog_v2", "status": "fail", "detail": str(error)})
    summary: Mapping[str, Any] | None = None
    try:
        loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(loaded_summary, Mapping):
            raise ValueError("Reachability summary must be an object.")
        summary = loaded_summary
        checks.append(
            {
                "name": "reachability_artifact",
                "status": "pass",
                "detail": str(summary.get("audit_hash", "hash unavailable")),
            }
        )
    except Exception as error:  # noqa: BLE001
        checks.append(
            {"name": "reachability_artifact", "status": "fail", "detail": str(error)}
        )
    reachability_rows: list[dict[str, Any]] | None = None
    try:
        reachability_rows = _read_jsonl(rows_path)
        if not reachability_rows:
            raise ValueError("Reachability rows must not be empty.")
        checks.append(
            {
                "name": "reachability_rows",
                "status": "pass",
                "detail": f"{len(reachability_rows)} rows",
            }
        )
    except Exception as error:  # noqa: BLE001
        checks.append(
            {"name": "reachability_rows", "status": "fail", "detail": str(error)}
        )
    profile_contract = None
    if catalog is not None and summary is not None and reachability_rows is not None:
        profile_contract = check(
            "artifact_profile_contract",
            lambda: _validate_artifact_profile(
                profile=profile,
                catalog=catalog,
                summary=summary,
                reachability_rows=reachability_rows or (),
                reachability_rows_sha256=_sha256_file(rows_path),
                spec=spec,
            ),
        )
    else:
        checks.append(
            {
                "name": "artifact_profile_contract",
                "status": "fail",
                "detail": "Catalog, summary, and reachability rows must pass first.",
            }
        )
    gate = None
    if catalog is not None and summary is not None:
        def validate_reachability() -> Mapping[str, Any]:
            if summary.get("catalog_hash") != catalog.catalog_hash:
                raise ValueError("Reachability catalog hash does not match catalog v2.")
            result = prompt_reachability_gate(
                summary,
                minimum_joint_ratio=float(spec.data["minimum_joint_prompt_reachability"]),
            )
            if not result["passed"]:
                raise ValueError(str(result["reason"]))
            return result

        gate = check("prompt_reachability_gate", validate_reachability)
    else:
        checks.append(
            {
                "name": "prompt_reachability_gate",
                "status": "fail",
                "detail": "Catalog and reachability artifacts must pass first.",
            }
        )
    model: ModelBundle | None = None
    try:
        model = ModelBundle.load(repo / str(spec.data["model_bundle_root"]))
        if model.bundle_hash != spec.data.get("model_bundle_hash"):
            raise ValueError("Model bundle hash does not match the frozen preflight spec.")
        checks.append(
            {"name": "model_bundle", "status": "pass", "detail": model.bundle_hash}
        )
    except Exception as error:  # noqa: BLE001
        checks.append({"name": "model_bundle", "status": "fail", "detail": str(error)})
    if require_credentials:
        def credential() -> str:
            if model is None:
                raise ValueError("Model bundle did not load.")
            name = str(model.config.api_key_env)
            if not os.environ.get(name):
                raise ValueError(f"{name} is unset.")
            return f"{name} is set (value not inspected or persisted)"

        check("provider_credential", credential)
    ready = all(item["status"] == "pass" for item in checks)
    coverage = summary.get("summary", {}) if isinstance(summary, Mapping) else {}
    return {
        "schema_version": "m13e3b5-preflight-readiness-v3",
        "ready": ready,
        "artifact_profile": profile,
        "artifact_profile_contract": profile_contract,
        "catalog_root": str(catalog_root),
        "reachability_root": str(reachability_root),
        "reachability_summary_path": str(summary_path),
        "reachability_rows_path": str(rows_path),
        "reachability_audit_hash": (
            str(summary.get("audit_hash"))
            if isinstance(summary, Mapping) and summary.get("audit_hash")
            else None
        ),
        "relation_endpoint_contract_version": (
            RELATION_ENDPOINT_CONTRACT_VERSION
            if profile == QUERY_LOCAL_ARTIFACT_PROFILE
            else None
        ),
        "prompt_candidates_per_slot": int(spec.data["prompt_candidates_per_slot"]),
        "catalog_coverage": coverage.get("catalog"),
        "retrieval_coverage": coverage.get("retrieval"),
        "prompt_reachability": coverage.get("deployed_prompt"),
        "gate": gate,
        "checks": checks,
    }


def run_preflight(
    *, spec_path: str | Path, repo_root: str | Path, output_root: str | Path
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    spec = GrailQAPreflightSpec.load(spec_path)
    readiness = preflight_readiness(spec, repo, require_credentials=True)
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "readiness.json", readiness)
    if not readiness["ready"]:
        raise RuntimeError("Preflight readiness failed before any provider call.")
    catalog = GrailQAInferenceCatalogV2.load(readiness["catalog_root"])
    model = ModelBundle.load(repo / str(spec.data["model_bundle_root"]))
    provider = LiveSemanticPilotProvider(
        model, response_parser=parse_normalized_planner_response
    )
    question_rows = {
        str(item["question_id"]): item
        for item in _read_jsonl(repo / str(spec.data["pilot_root"]) / "inference_questions.jsonl")
    }
    questions = [question_rows[question_id] for question_id in spec.question_ids]
    semantic = DirectionalOntologyDeviation(
        catalog.ontology,
        SemanticDeviationConfig(
            max_relaxation_hops=catalog.ontology.max_relaxation_hops,
            epsilon_values=tuple(float(item) for item in spec.data["epsilon_values"]),
        ),
    )
    states = [
        _infer_one(
            question=question,
            catalog=catalog,  # type: ignore[arg-type] - compatible retrieval/prompt protocol.
            provider=provider,
            semantic=semantic,
            retrieval_k=int(spec.data["retrieval_k"]),
            candidate_cap=int(spec.data["candidate_cap"]),
            prompt_candidates_per_slot=int(spec.data["prompt_candidates_per_slot"]),
            response_parser=parse_normalized_planner_response,
        )
        for question in questions
    ]
    evaluated = _evaluate_preflight(states, spec, repo, readiness)
    execution_environment = None
    environment_path = os.environ.get("XGAP_RUN_ENVIRONMENT_FILE")
    if environment_path:
        execution_environment = load_run_environment(environment_path)
    manifest = build_preflight_run_manifest(
        output=output,
        spec=spec,
        catalog_hash=catalog.catalog_hash,
        model=model,
        effective_model=provider.model_name,
        question_count=len(questions),
        execution_environment=execution_environment,
        readiness=readiness,
    )
    _write_json(output / "run_manifest.json", manifest)
    _write_jsonl(output / "retrieval.jsonl", (state["retrieval"] for state in states))
    _write_jsonl(
        output / "llm_requests.jsonl",
        (row for state in states for row in state.get("request_records", ())),
    )
    _write_jsonl(
        output / "llm_responses.jsonl",
        (state["response_record"] for state in states if state.get("response_record")),
    )
    _write_jsonl(output / "validated_candidates.jsonl", evaluated["candidates"])
    _write_jsonl(output / "component_match.jsonl", evaluated["components"])
    _write_jsonl(output / "semantic_scores.jsonl", evaluated["semantic"])
    _write_jsonl(output / "failures.jsonl", evaluated["failures"])
    _write_json(output / "metrics.json", evaluated["metrics"])
    return {"output_root": str(output), "metrics": evaluated["metrics"]}


def build_preflight_run_manifest(
    *,
    output: Path,
    spec: GrailQAPreflightSpec,
    catalog_hash: str,
    model: ModelBundle,
    effective_model: str,
    question_count: int,
    execution_environment: Mapping[str, Any] | None,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the live manifest, optionally including a CWRU environment record."""

    manifest = {
        "schema_version": "m13e3b5-preflight-run-manifest-v3",
        "run_id": output.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "spec_sha256": hashlib.sha256(spec.path.read_bytes()).hexdigest(),
        "spec_freeze_hash": spec.data["freeze_hash"],
        "catalog_hash": catalog_hash,
        "provider": model.config.provider,
        "model": effective_model,
        "model_bundle_hash": model.bundle_hash,
        "prompt_hash": model.prompt.prompt_hash,
        "question_count": question_count,
        "backend_execution": False,
        "secrets_persisted": False,
    }
    if readiness is not None:
        manifest["inference_artifacts"] = {
            "profile": readiness.get("artifact_profile"),
            "catalog_root": readiness.get("catalog_root"),
            "reachability_root": readiness.get("reachability_root"),
            "reachability_summary_path": readiness.get(
                "reachability_summary_path"
            ),
            "reachability_rows_path": readiness.get("reachability_rows_path"),
            "reachability_audit_hash": readiness.get("reachability_audit_hash"),
            "prompt_candidates_per_slot": readiness.get(
                "prompt_candidates_per_slot"
            ),
            "relation_endpoint_contract_version": readiness.get(
                "relation_endpoint_contract_version"
            ),
        }
    if execution_environment is not None:
        manifest["execution_environment"] = dict(execution_environment)
    return manifest


def _evaluate_preflight(
    states: Sequence[Mapping[str, Any]],
    spec: GrailQAPreflightSpec,
    repo: Path,
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    pilot = repo / str(spec.data["pilot_root"])
    references = {
        str(item["question_id"]): item
        for item in _read_jsonl(pilot / "reference_interpretations.jsonl")
    }
    reachability = {
        str(item["question_id"]): item
        for item in _read_jsonl(Path(str(readiness["reachability_rows_path"])))
    }
    candidate_rows: list[dict[str, Any]] = []
    component_rows: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    by_question_match: dict[str, bool] = {}
    for state in states:
        question_id = str(state["question"]["question_id"])
        reference = references[question_id]["pattern_query"]
        matches = False
        for candidate in state.get("candidates", ()):
            row = dict(candidate)
            report = component_match_report(row["pattern_query"], reference)
            row["normalized_reference_match"] = report["matches"][
                "full_normalized_interpretation"
            ]
            matches = matches or bool(row["normalized_reference_match"])
            candidate_rows.append(row)
            component_rows.append(
                {
                    "question_id": question_id,
                    "candidate_id": row["candidate_id"],
                    **report,
                }
            )
        by_question_match[question_id] = matches
        semantic_rows.extend(state.get("semantic_scores", ()))
        old_failure = state.get("failure")
        category = classify_first_failure(
            reachability_row=reachability.get(question_id),
            malformed_output=bool(old_failure and old_failure.get("category") == "malformed_output"),
            generated_candidates=len(state.get("candidates", ())),
            type_check_ok=not bool(old_failure and old_failure.get("category") == "type_check_failure"),
            grounding_ok=not bool(
                old_failure
                and old_failure.get("category")
                in {"entity_grounding_failure", "relation_grounding_failure"}
            ),
            semantic_admissible=any(
                bool(item.get("semantic_admissible")) for item in state.get("candidates", ())
            ),
            selected_candidate=bool(state.get("candidates")),
            equivalent=matches,
        )
        if category is not None:
            failure_row: dict[str, Any] = {
                "schema_version": "m13e1-stage-aware-failure-v1",
                "question_id": question_id,
                "category": category,
            }
            # Retain producer diagnostics without changing the frozen taxonomy.
            if old_failure is not None:
                failure_row["original_inference_failure"] = dict(old_failure)
            failures.append(failure_row)
    match_fields = tuple(component_rows[0]["matches"]) if component_rows else ()
    component_accuracy = {
        key: sum(bool(item["matches"][key]) for item in component_rows) / len(component_rows)
        for key in match_fields
    }
    epsilons = tuple(float(item) for item in spec.data["epsilon_values"])
    metrics = {
        "schema_version": "m13e1-preflight-metrics-v2",
        "query_count": len(states),
        "catalog_availability": readiness.get("catalog_coverage"),
        "prompt_reachability": readiness.get("prompt_reachability"),
        "provider_success_rate": (
            sum(bool(state.get("api_call_completed")) for state in states) / len(states)
            if states
            else None
        ),
        "structured_valid_rate": (
            sum(bool(state.get("candidates")) for state in states) / len(states) if states else None
        ),
        "candidate_recall": (
            sum(by_question_match.values()) / len(states) if states else None
        ),
        "jointly_reachable_subset": _jointly_reachable_subset_metrics(
            states, by_question_match, reachability
        ),
        "component_accuracy": component_accuracy,
        "full_normalized_interpretation_accuracy": component_accuracy.get(
            "full_normalized_interpretation"
        ),
        "c_sem": semantic_deviation_distribution(candidate_rows),
        "feasible_coverage": {
            str(epsilon): (
                sum(
                    any(
                        item.get("semantic_deviation") is not None
                        and float(item["semantic_deviation"]) <= epsilon
                        for item in state.get("candidates", ())
                    )
                    for state in states
                )
                / len(states)
                if states
                else None
            )
            for epsilon in epsilons
        },
        "failure_taxonomy": {
            name: Counter(item["category"] for item in failures).get(name, 0)
            for name in STAGE_AWARE_FAILURE_TAXONOMY
        },
    }
    return {
        "candidates": candidate_rows,
        "components": component_rows,
        "semantic": semantic_rows,
        "failures": failures,
        "metrics": metrics,
    }


def _jointly_reachable_subset_metrics(
    states: Sequence[Mapping[str, Any]],
    by_question_match: Mapping[str, bool],
    reachability: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    jointly_reachable_ids = {
        question_id
        for question_id, row in reachability.items()
        if bool(
            _mapping(
                _mapping(row.get("deployed_prompt"), "deployed_prompt").get("joint"),
                "joint",
            ).get("reachable")
        )
    }
    subset = [
        state
        for state in states
        if str(_mapping(state.get("question"), "question").get("question_id"))
        in jointly_reachable_ids
    ]
    count = len(subset)
    total = len(states)
    matched = sum(
        bool(
            by_question_match.get(
                str(_mapping(state.get("question"), "question").get("question_id"))
            )
        )
        for state in subset
    )
    return {
        "schema_version": "m13e3b5-jointly-reachable-subset-v1",
        "question_count": count,
        "unreachable_question_count": total - count,
        "prompt_reachability_ceiling": count / total if total else None,
        "provider_success_rate": (
            sum(bool(state.get("api_call_completed")) for state in subset) / count
            if count
            else None
        ),
        "structured_valid_rate": (
            sum(bool(state.get("candidates")) for state in subset) / count
            if count
            else None
        ),
        "candidate_recall": matched / count if count else None,
        "matched_question_count": matched,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Any) -> None:
    path.write_text(
        "".join(json.dumps(dict(value), sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument(
        "--spec", default="experiments/specs/grailqa_semantic_preflight_v2.json"
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output")
    parser.add_argument("--require-credentials", action="store_true")
    args = parser.parse_args(argv)
    spec = GrailQAPreflightSpec.load(args.spec)
    if args.command == "check":
        report = preflight_readiness(
            spec, args.repo_root, require_credentials=args.require_credentials
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ready"] else 2
    output = args.output or (
        "runs/grailqa-semantic-preflight-v2-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    result = run_preflight(
        spec_path=args.spec, repo_root=args.repo_root, output_root=output
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
