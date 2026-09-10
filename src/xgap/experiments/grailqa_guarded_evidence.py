"""Fail-closed, read-only reconstruction of a complete guarded development18 run.

All source, catalog and tokenizer inputs are explicit and locally available.
No inference, tokenizer endpoint, scheduler or backend is called. Output is a
development evidence receipt, never authorization for full150 or paper claims.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract, load_run_environment
from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_guarded_accounting import reconstruct_guarded_ledger
from xgap.experiments.grailqa_guarded_evaluation import reconstruct_guarded_evaluation
from xgap.experiments.grailqa_guarded_preflight import CLAIM_BOUNDARY
from xgap.experiments.grailqa_guarded_run_inputs import (
    bind_environment_records, bind_outer_run, bind_producer_inputs, digest, finite_time,
    read_json, read_rows, regular, snapshot, timestamp,
)
from xgap.experiments.grailqa_inline_evidence import _require, _same
from xgap.experiments.grailqa_local_catalog import _query_entity_ids, validate_local_catalog
from xgap.experiments.grailqa_preflight import (
    GrailQAPreflightSpec, QUERY_LOCAL_ARTIFACT_PROFILE, _validate_artifact_profile,
)
from xgap.experiments.grailqa_reachability import (
    audit_reachability, load_catalog_universe, prompt_reachability_gate,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.relation_endpoints import RELATION_ENDPOINT_CONTRACT_VERSION
from xgap.experiments.semantic import DirectionalOntologyDeviation, SemanticDeviationConfig
from xgap.llm.token_budget import LocalPinnedChatTokenizer


RESULT_ROOT = Path("results/grailqa-guarded-preflight")
SCHEMA = "grailqa-guarded-contract-feedback-preflight-v1"


def _selected(rows, ids, label):
    indexed = {str(row["question_id"]): row for row in rows}
    _same(len(indexed), len(rows), "unique " + label + " IDs")
    _require(all(qid in indexed for qid in ids), "complete " + label + " population")
    return [indexed[qid] for qid in ids]


def _pilot_file(pilot: Path, manifest: Mapping[str, Any], name: str):
    path = regular(pilot / name)
    _same(manifest["artifacts"][name], {"bytes": path.stat().st_size, "sha256": digest(path)}, "frozen pilot artifact: " + name)
    return read_rows(path)


def _readiness(*, spec, model, catalog, root, summary, rows, require_credentials):
    profile = _validate_artifact_profile(
        profile=QUERY_LOCAL_ARTIFACT_PROFILE, catalog=catalog, summary=summary,
        reachability_rows=rows, reachability_rows_sha256=digest(root / "reachability.jsonl"), spec=spec,
    )
    _same(summary["catalog_hash"], catalog.catalog_hash, "reachability catalog binding")
    gate = prompt_reachability_gate(summary, minimum_joint_ratio=float(spec.data["minimum_joint_prompt_reachability"]))
    _same(gate["passed"], True, "frozen development readiness gate")
    checks = [
        {"name": name, "status": "pass", "detail": detail} for name, detail in (
            ("artifact_profile", QUERY_LOCAL_ARTIFACT_PROFILE), ("catalog_v2", catalog.catalog_hash),
            ("reachability_artifact", summary["audit_hash"]), ("reachability_rows", f"{len(rows)} rows"),
            ("artifact_profile_contract", profile), ("prompt_reachability_gate", gate),
            ("model_bundle", model.bundle_hash),
        )
    ]
    if require_credentials:
        checks.append({"name": "provider_credential", "status": "pass",
                       "detail": f"{model.config.api_key_env} is set (value not inspected or persisted)"})
    return {
        "schema_version": "m13e3b5-preflight-readiness-v3", "ready": True,
        "artifact_profile": QUERY_LOCAL_ARTIFACT_PROFILE, "artifact_profile_contract": profile,
        "catalog_root": str(catalog.root), "reachability_root": str(root),
        "reachability_summary_path": str(root / "audit_summary.json"),
        "reachability_rows_path": str(root / "reachability.jsonl"), "reachability_audit_hash": summary["audit_hash"],
        "relation_endpoint_contract_version": RELATION_ENDPOINT_CONTRACT_VERSION,
        "prompt_candidates_per_slot": spec.data["prompt_candidates_per_slot"],
        "catalog_coverage": summary["summary"]["catalog"], "retrieval_coverage": summary["summary"]["retrieval"],
        "prompt_reachability": summary["summary"]["deployed_prompt"], "gate": gate, "checks": checks,
    }


def _manifest(*, actual, spec, model, catalog, readiness, environment, binding, identity, commit):
    finite_time(actual["tokenizer_initialization_seconds"])
    _require(timestamp(actual["started_at"]) <= timestamp(actual["created_at"]), "manifest creation after recorded start")
    expected = {
        "schema_version": SCHEMA, "run_id": RESULT_ROOT.name, "created_at": actual["created_at"],
        "started_at": actual["started_at"], "spec_sha256": digest(spec.path), "spec_freeze_hash": spec.data["freeze_hash"],
        "catalog_hash": catalog.catalog_hash, "provider": model.config.provider, "model": model.config.exact_model_snapshot,
        "model_bundle_hash": model.bundle_hash, "prompt_hash": model.prompt.prompt_hash, "question_count": 18,
        "backend_execution": False, "secrets_persisted": False,
        "inference_artifacts": {"profile": readiness["artifact_profile"], **{key: readiness[key] for key in (
            "catalog_root", "reachability_root", "reachability_summary_path", "reachability_rows_path",
            "reachability_audit_hash", "prompt_candidates_per_slot", "relation_endpoint_contract_version",
        )}},
        "execution_environment": environment, "runner_commit": commit, "claim_boundary": dict(CLAIM_BOUNDARY),
        "environment_binding_sha256": content_hash(binding), "tokenizer_identity_record_sha256": content_hash(identity),
        "execution_acknowledgement_spec_sha256": spec.data["freeze_hash"],
        "serving_tokenizer_mode": "per_request_server_tokenization", "automatic_retries": 0,
        "maximum_provider_calls": 36, "maximum_tokenizer_probe_calls": 36, "maximum_total_external_calls": 72,
        "tokenizer_probe_timeout_seconds": 60.0, "maximum_schema_repair_calls_per_query": 1,
        "paper_result": False, "tokenizer_initialization_seconds": actual["tokenizer_initialization_seconds"],
        "cost_boundary": {
            "total_external_attempted_calls_scope": "per_query_inference_plus_tokenizer_probes_only",
            "service_startup_health_checks_included": False, "llm_latency_includes_token_checks": True,
            "llm_latency_includes_check_journaling": True, "llm_latency_includes_server_tokenization_probes": True,
            "server_tokenization_probe_costs_reported_separately_do_not_add_twice": True,
            "inference_wall_includes_all_query_journaling": True, "tokenizer_initialization_reported_separately": True,
            "backend_execution": False,
        },
        "candidate_grounding_policy": SEMANTIC_GROUNDING_POLICY, "candidate_repair_policy": TYPED_GROUNDING_ONCE,
        "maximum_combined_repair_calls_per_query": 1, "candidate_repair_trigger": "no_typed_prompt_grounded_candidate",
    }
    _same(actual, expected, "complete frozen guarded manifest")


def audit_guarded_development_run(
    *, run_root: str | Path, repo_root: str | Path, spec_path: str | Path,
    expected_commit: str, expected_spec_freeze_hash: str, catalog_root: str | Path,
    expected_catalog_hash: str, expected_catalog_manifest_sha256: str,
    reachability_root: str | Path, tokenizer_snapshot: str | Path, tokenizer_revision: str,
) -> dict[str, Any]:
    """Admit a complete development observation, or raise on missing evidence."""
    root, repo, catalog_path, reach_root = (Path(p).absolute() for p in (run_root, repo_root, catalog_root, reachability_root))
    for value, length in ((expected_commit, 40), (tokenizer_revision, 40), (expected_spec_freeze_hash, 64),
                          (expected_catalog_hash, 64), (expected_catalog_manifest_sha256, 64)):
        _require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None, "explicit exact input digest")
    before = snapshot(root)
    _require(not any(Path(name).name == "run_failure.json" for name in before), "no run failure marker")
    outer_status = bind_outer_run(root, before)
    result = root / RESULT_ROOT
    spec = GrailQAPreflightSpec.load(regular(repo / spec_path))
    _same(spec.data["freeze_hash"], expected_spec_freeze_hash, "explicit frozen development spec")
    _same(len(spec.question_ids), 18, "exact development18 size")
    _same([spec.data[k] for k in ("backend_execution", "gold_exposed_to_inference", "full_150_run_permitted")], [False] * 3, "development scope")
    _same(spec.data["candidate_grounding_policy"], SEMANTIC_GROUNDING_POLICY, "semantic grounding spec")
    _same(spec.data["candidate_repair_policy"], TYPED_GROUNDING_ONCE, "bounded repair spec")
    _same([spec.data[k] for k in ("candidate_cap", "retrieval_k", "prompt_candidates_per_slot", "relation_slot_bound")], [3, 20, 4, 3], "frozen development bounds")
    pilot = repo / spec.data["pilot_root"]
    source_paths = ["src/xgap", "scripts/server/run_grailqa_guarded_preflight.sh", "scripts/slurm/cwru_xgap_vllm.sbatch",
                    spec.path.relative_to(repo).as_posix(), spec.data["model_bundle_root"], spec.data["deployment_contract"],
                    (pilot / "artifact_manifest.json").relative_to(repo).as_posix()]
    source_before = bind_producer_inputs(repo, expected_commit, source_paths)
    pilot_manifest = read_json(pilot / "artifact_manifest.json")
    questions = _selected(_pilot_file(pilot, pilot_manifest, "inference_questions.jsonl"), spec.question_ids, "inference questions")
    model = ModelBundle.load(repo / spec.data["model_bundle_root"])
    contract = CWRUVLLMContract.load(repo / spec.data["deployment_contract"])
    _same(model.config.max_repair_calls, 1, "one total repair")
    _same(model.config.token_limits, {"input": 8192, "output": 4096}, "frozen token reservations")
    _same(contract.data["serving"]["max_model_len"], 12288, "frozen context window")
    catalog_before = snapshot(catalog_path)
    _same(digest(catalog_path / "manifest.json"), expected_catalog_manifest_sha256, "explicit catalog manifest including SQLite identity")
    catalog = GrailQAInferenceCatalogV2.load(catalog_path)
    _same(catalog.catalog_hash, expected_catalog_hash, "preserved catalog identity")
    validate_local_catalog(catalog_path)
    cm = catalog.manifest
    _same(cm["local_catalog_schema_version"], "m13e3b-grailqa-local-catalog-v1", "preserved v1 catalog policy")
    _same(sorted(cm["question_ids"]), sorted(spec.question_ids), "catalog exact question set")
    q_by_id = {q["question_id"]: q for q in questions}
    _same(cm["question_text_sha256"], content_hash([{"question_id": qid, "text": q_by_id[qid]["text"]} for qid in cm["question_ids"]]), "catalog question text binding")
    _same(cm["catalog_hash"], content_hash({
        "schema_version": cm["local_catalog_schema_version"],
        "source_manifest_sha256": cm["sources"]["freebase_archival_parquet"]["source_manifest_sha256"],
        "question_text_sha256": cm["question_text_sha256"],
        "content_file_hashes": {k: v for k, v in cm["file_hashes"].items() if k != "catalog.sqlite3"},
    }), "canonical catalog identity")
    for name in cm["file_hashes"]:
        _require(name in catalog_before, "catalog file remains inside explicit tree")
    identity = read_json(result / "tokenizer_identity.json")
    counter = LocalPinnedChatTokenizer(Path(tokenizer_snapshot).absolute(), tokenizer_revision)
    _same(counter.identity, identity, "actual pinned local tokenizer files/template/libraries")
    environment = load_run_environment(regular(root / "cwru_environment.json"))
    # Load duplicate-key-safe JSON too; the environment loader enforces its own
    # existing credential-free contract, while this reader enforces JSON identity.
    _same(environment, read_json(root / "cwru_environment.json"), "unambiguous environment JSON")
    binding = read_json(result / "environment_binding.json")
    deployment = bind_environment_records(environment=environment, binding=binding,
        launch=read_json(root / "guarded_launch_binding.json"), spec=spec, model=model, contract=contract,
        repo=repo, commit=expected_commit, revision=tokenizer_revision, tokenizer_identity=identity)
    smoke = read_json(root / "vllm_structured_smoke.json")
    _same(smoke["schema_valid"], True, "retained startup schema smoke")
    _same(smoke["secrets_persisted"], False, "startup smoke credential boundary")
    states, events = read_rows(result / "query_states.jsonl"), read_rows(result / "query_events.jsonl")
    ledger = reconstruct_guarded_ledger(
        states=states, events=events, questions=questions, model=model, catalog=catalog,
        semantic=DirectionalOntologyDeviation(catalog.ontology, SemanticDeviationConfig(
            max_relaxation_hops=catalog.ontology.max_relaxation_hops,
            epsilon_values=tuple(float(e) for e in spec.data["epsilon_values"]))),
        counter=counter, retrieval_k=20, prompt_limit=4, context_limit=12288,
    )
    for name, expected in ledger["copies"].items():
        _same(read_rows(result / (name + ".jsonl")), expected, "reconstructed ledger extraction: " + name)
    # No oracle content is opened or supplied to any inference reconstruction
    # above. Frozen references/workload are first loaded here, for evaluation.
    references = _selected(_pilot_file(pilot, pilot_manifest, "reference_interpretations.jsonl"), spec.question_ids, "references")
    workload = _selected(_pilot_file(pilot, pilot_manifest, "workload_stats.jsonl"), spec.question_ids, "workload")
    reach_before = snapshot(reach_root)
    summary, reach_rows = read_json(reach_root / "audit_summary.json"), read_rows(reach_root / "reachability.jsonl")
    coverage = audit_reachability(
        references=references, retrieval_rows=ledger["copies"]["retrieval"], catalog=load_catalog_universe(catalog_path),
        workload_by_id={r["question_id"]: r for r in workload}, catalog_entities_by_question=_query_entity_ids(catalog_path),
        prompt_limit=4,
    )
    for row in coverage["rows"]:
        if row["first_unreachable_stage"] == "reference_not_in_catalog":
            row["first_unreachable_stage"] = "reference_not_in_local_catalog"
    _same(sorted(reach_rows, key=lambda r: r["question_id"]), sorted(coverage["rows"], key=lambda r: r["question_id"]), "independent reference reachability rows")
    _same(summary["summary"], coverage["summary"], "independent availability/retrieval/prompt coverage")
    readiness = _readiness(spec=spec, model=model, catalog=catalog, root=reach_root, summary=summary, rows=reach_rows, require_credentials=True)
    _same(read_json(result / "readiness.json"), readiness, "inner readiness reconstruction")
    _same(read_json(root / "preflight_readiness.json"), _readiness(spec=spec, model=model, catalog=catalog, root=reach_root,
        summary=summary, rows=reach_rows, require_credentials=False), "prelaunch credential-free readiness reconstruction")
    manifest = read_json(result / "run_manifest.json")
    _manifest(actual=manifest, spec=spec, model=model, catalog=catalog, readiness=readiness,
              environment=environment, binding=binding, identity=identity, commit=expected_commit)
    evaluated = reconstruct_guarded_evaluation(states=states, references={r["question_id"]: r for r in references},
        reachability={r["question_id"]: r for r in coverage["rows"]}, coverage=coverage["summary"], epsilon_values=spec.data["epsilon_values"])
    for name, expected in evaluated.items():
        _same(read_json(result / "metrics.json") if name == "metrics" else read_rows(result / (name + ".jsonl")),
              expected, "independently reconstructed evaluation: " + name)
    status = read_json(result / "run_status.json")
    finite_time(status["inference_wall_seconds"])
    _require(sum(s[k] for s in states for k in (
        "retrieval_latency_seconds", "llm_latency_seconds", "deterministic_latency_seconds"))
        <= status["inference_wall_seconds"] + 1e-6, "serial stage time fits recorded inference wall")
    _same(status, {
        "schema_version": SCHEMA, "status": "completed", "started_at": manifest["started_at"], "ended_at": status["ended_at"],
        "question_count": 18, **ledger["totals"], "serving_tokenizer_mode": "per_request_server_tokenization",
        "inference_wall_seconds": status["inference_wall_seconds"], "tokenizer_initialization_seconds": manifest["tokenizer_initialization_seconds"],
        "claim_boundary": dict(CLAIM_BOUNDARY), "paper_result": False,
        "candidate_grounding_policy": SEMANTIC_GROUNDING_POLICY, "candidate_repair_policy": TYPED_GROUNDING_ONCE,
    }, "independent terminal status and totals")
    _require(timestamp(environment["captured_at"]) <= timestamp(status["started_at"])
             <= timestamp(status["ended_at"]) <= timestamp(outer_status["completed_at"]), "recorded outer/inner lifecycle order")
    _same(snapshot(root), before, "run files unchanged throughout audit")
    _same(snapshot(catalog_path), catalog_before, "catalog unchanged throughout audit")
    _same(snapshot(reach_root), reach_before, "reachability inputs unchanged throughout audit")
    _same(bind_producer_inputs(repo, expected_commit, source_paths), source_before, "source inputs unchanged throughout audit")
    for name in ("inference_questions.jsonl", "reference_interpretations.jsonl", "workload_stats.jsonl"):
        _pilot_file(pilot, pilot_manifest, name)
    _same(counter.identity, identity, "tokenizer identity unchanged throughout audit")
    _same(LocalPinnedChatTokenizer(Path(tokenizer_snapshot).absolute(), tokenizer_revision).identity,
          identity, "tokenizer files/template/libraries rechecked at audit end")
    report = {
        "schema_version": "grailqa-guarded-development-evidence-v1", "whole_run_admitted": True,
        "question_count": 18, "inputs": {"run_root": str(root), "runner_commit": expected_commit,
            "spec_freeze_hash": expected_spec_freeze_hash, "catalog_hash": expected_catalog_hash,
            "catalog_manifest_sha256": expected_catalog_manifest_sha256, "tokenizer_identity_sha256": content_hash(identity)},
        "source_files": source_before["files"], "run_files": before, "deployment": deployment,
        "queries": ledger["queries"], "totals": ledger["totals"], "metrics": evaluated["metrics"],
        "claim_boundary": {**CLAIM_BOUNDARY, "external_calls": 0, "semantic_metrics_recomputed": True,
            "token_counts_recomputed": True, "original_timings_are_recorded_observations": True,
            "scheduler_status_independently_queried": False, "server_identity_verified": False,
            "raw_external_failure_causes_independently_verified": False,
            "source_freebase_rescanned": False, "reference_content_opened_after_inference_reconstruction": True},
    }
    report["audit_sha256"] = content_hash(report)
    return deepcopy(report)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-root", "repo-root", "spec-path", "expected-commit", "expected-spec-freeze-hash",
                 "catalog-root", "expected-catalog-hash", "expected-catalog-manifest-sha256",
                 "reachability-root", "tokenizer-snapshot", "tokenizer-revision"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit_guarded_development_run(**vars(args))
    except Exception as error:
        # Retained evidence may contain provider text. Never echo arbitrary
        # exceptions or partially admitted metrics on the public failure path.
        print(json.dumps({"schema_version": "grailqa-guarded-development-evidence-v1",
              "whole_run_admitted": False, "error_type": type(error).__name__, "paper_result": False}))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
