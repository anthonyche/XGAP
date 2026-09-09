"""Explicit, journaled GrailQA development preflight with per-send token checks.

This entrypoint does not replace an existing preflight or paper runner. A
separately selected mode checks each payload against the serving tokenization
endpoint before inference. That observation is not global service attestation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.cwru_vllm import CWRUVLLMContract, load_run_environment
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_guarded_environment import validate_guarded_environment
from xgap.experiments.grailqa_guarded_provider import (
    GuardedSemanticPilotProvider, QueryEventJournal,
)
from xgap.experiments.grailqa_loopback_inference import LoopbackInferenceTransport
from xgap.experiments.grailqa_preflight import (
    GrailQAPreflightSpec, _evaluate_preflight, build_preflight_run_manifest,
    preflight_readiness,
)
from xgap.experiments.grailqa_request_tokens import _check_output, _questions
from xgap.experiments.grailqa_server_tokenization import ServerTokenizationGuard
from xgap.experiments.grailqa_semantic_pilot import _infer_one
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.experiments.semantic import DirectionalOntologyDeviation, SemanticDeviationConfig
from xgap.llm.token_budget import ChatTokenBudgetGuard, LocalPinnedChatTokenizer


SCHEMA_VERSION = "grailqa-guarded-development-preflight-v2"
TOKENIZER_PROBE_TIMEOUT_SECONDS = 60.0
CLAIM_BOUNDARY = {
    "development_preflight_only": True,
    "backend_execution": False,
    "full_150_run_authorized": False,
    "paper_result": False,
    "remote_serving_parity_verified": False,
    "server_tokenization_equality_is_payload_scoped_not_process_attestation": True,
    "execution_acknowledgement_is_not_authority_receipt": True,
    "completion_means_protocol_completed_not_semantic_success": True,
    "completion_requires_successful_cli_and_status_without_failure_marker": True,
    "local_token_refusals_reported_separately_from_legacy_failure_taxonomy": True,
    "reference_content_opened_only_after_all_inference": True,
}


def _safe_failure_reason(error: BaseException) -> str:
    # Environment checks deliberately use fixed identifiers. Expose those for
    # diagnostics, never arbitrary exception/provider text or observed values.
    binding = re.fullmatch(r"Guarded environment check failed: ([a-z0-9_]+)\.", str(error))
    if binding:
        return "environment_" + binding.group(1)
    return {
        "Serving tokenizer parity is unverified; explicit development-only acknowledgement is required.": "serving_parity_acknowledgement_missing",
        "Choose exactly one explicit serving-tokenization mode.": "serving_tokenization_mode_ambiguous",
        "Execution acknowledgement does not match this frozen spec.": "development_spec_acknowledgement_mismatch",
        "Only a non-backend, gold-free development preflight is supported.": "development_scope_mismatch",
        "Preflight readiness failed before any provider call.": "preflight_readiness_failed",
        "A regular, job-owned run environment record is required.": "run_environment_unavailable",
    }.get(str(error), "incomplete_see_error_type_and_partial_records")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    serialized = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    with QueryEventJournal(path) as journal:
        for value in values:
            journal.append(value)


def _validate_output(
    output: Path, *, repo: Path, spec: GrailQAPreflightSpec,
    readiness: Mapping[str, Any], snapshot: Path, environment_path: Path,
) -> None:
    # Do not follow a writable-output alias into an old run or input tree.
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("Output and its ancestors must not be symlinks.")
    report = {
        "inputs": {
            "repo_root": str(repo), "spec": str(spec.path),
            "tokenizer_snapshot": str(snapshot),
            **{key: str((repo / str(spec.data[key])).resolve()) for key in (
                "pilot_root", "catalog_root", "reachability_root", "model_bundle_root",
                "deployment_contract",
            )},
        },
        "readiness": readiness,
    }
    _check_output(output, report)
    if output.resolve() == environment_path.resolve() or any(
        output.resolve().is_relative_to(repo / name)
        for name in (".git", "scripts", "prompts")
    ):
        raise ValueError("Output must be outside read-only input and source paths.")


def run_guarded_preflight(
    *, spec_path: str | Path, repo_root: str | Path, output_root: str | Path,
    run_environment_path: str | Path, tokenizer_snapshot: str | Path,
    tokenizer_revision: str, expected_runner_commit: str,
    execute_development_spec_sha256: str,
    allow_unverified_serving_tokenizer: bool = False,
    verify_server_tokenization: bool = False,
) -> dict[str, Any]:
    """Execute only an explicitly selected, bounded development specification.

    Missing binding/inputs fail before the first provider call. Once a new run
    directory is owned, durable query/check/invocation records retain partial
    progress. Fatal accounting or persistence errors stop without automatic
    retry/resume. Ordinary query failures remain outcomes, not dropped rows.
    """
    if type(allow_unverified_serving_tokenizer) is not bool or type(verify_server_tokenization) is not bool \
            or (allow_unverified_serving_tokenizer and verify_server_tokenization):
        raise ValueError("Choose exactly one explicit serving-tokenization mode.")
    if not allow_unverified_serving_tokenizer and not verify_server_tokenization:
        raise ValueError(
            "Serving tokenizer parity is unverified; explicit development-only "
            "acknowledgement is required."
        )
    tokenizer_mode = (
        "per_request_server_tokenization" if verify_server_tokenization
        else "explicit_development_unverified"
    )
    repo = Path(repo_root).resolve()
    spec = GrailQAPreflightSpec.load(repo / spec_path)
    if execute_development_spec_sha256 != spec.data["freeze_hash"]:
        raise ValueError("Execution acknowledgement does not match this frozen spec.")
    if any(spec.data.get(key) is not False for key in (
        "backend_execution", "gold_exposed_to_inference", "full_150_run_permitted",
    )):
        raise ValueError("Only a non-backend, gold-free development preflight is supported.")

    output = (repo / output_root).absolute()
    environment_path = (repo / run_environment_path).absolute()
    snapshot = Path(tokenizer_snapshot).expanduser().absolute()
    readiness = preflight_readiness(spec, repo, require_credentials=True)
    _validate_output(
        output, repo=repo, spec=spec, readiness=readiness, snapshot=snapshot,
        environment_path=environment_path,
    )
    if readiness.get("ready") is not True:
        raise ValueError("Preflight readiness failed before any provider call.")
    if environment_path.is_symlink() or not environment_path.is_file():
        raise ValueError("A regular, job-owned run environment record is required.")
    model = ModelBundle.load(repo / str(spec.data["model_bundle_root"]))
    contract = CWRUVLLMContract.load(repo / str(spec.data["deployment_contract"]))
    base_provider = build_openai_compatible_provider(
        model, transport_override=LoopbackInferenceTransport(),
        response_parser=parse_normalized_planner_response,
    )
    environment = load_run_environment(environment_path)
    binding = validate_guarded_environment(
        environment, spec=spec, model=model, contract=contract,
        provider_config=base_provider.config, tokenizer_snapshot=snapshot,
        tokenizer_revision=tokenizer_revision, repo_root=repo,
        expected_runner_commit=expected_runner_commit,
    )
    tokenizer_started = time.perf_counter()
    counter = LocalPinnedChatTokenizer(snapshot, tokenizer_revision)
    guard = ChatTokenBudgetGuard(
        counter, input_limit=model.config.token_limits["input"],
        output_limit=model.config.token_limits["output"],
        context_limit=contract.data["serving"]["max_model_len"], expected_model=contract.model,
    )
    tokenizer_initialization_seconds = time.perf_counter() - tokenizer_started
    catalog = GrailQAInferenceCatalogV2.load(readiness["catalog_root"])
    questions_by_id = _questions(repo / str(spec.data["pilot_root"]) / "inference_questions.jsonl")
    questions = [questions_by_id[qid] for qid in spec.question_ids]
    semantic = DirectionalOntologyDeviation(
        catalog.ontology,
        SemanticDeviationConfig(
            max_relaxation_hops=catalog.ontology.max_relaxation_hops,
            epsilon_values=tuple(float(value) for value in spec.data["epsilon_values"]),
        ),
    )

    # All output files below are created exclusively inside a newly owned root.
    # No old result is edited and no automatic continuation consumes this root.
    output.mkdir(parents=True, exist_ok=False)
    states: list[Mapping[str, Any]] = []
    checks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc).isoformat()
    inference_started = time.perf_counter()
    try:
        _write_json(output / "readiness.json", readiness)
        _write_json(output / "environment_binding.json", binding)
        _write_json(output / "tokenizer_identity.json", counter.identity)
        manifest = build_preflight_run_manifest(
            output=output, spec=spec, catalog_hash=catalog.catalog_hash, model=model,
            effective_model=base_provider.config.model, question_count=len(questions),
            execution_environment=environment, readiness=readiness,
        )
        manifest.update(
            schema_version=SCHEMA_VERSION, started_at=started_at,
            runner_commit=expected_runner_commit, claim_boundary=dict(CLAIM_BOUNDARY),
            environment_binding_sha256=content_hash(binding),
            tokenizer_identity_record_sha256=content_hash(counter.identity),
            execution_acknowledgement_spec_sha256=execute_development_spec_sha256,
            serving_tokenizer_mode=tokenizer_mode,
            automatic_retries=0, maximum_provider_calls=2 * len(questions),
            maximum_tokenizer_probe_calls=2 * len(questions) if verify_server_tokenization else 0,
            maximum_total_external_calls=(4 if verify_server_tokenization else 2) * len(questions),
            tokenizer_probe_timeout_seconds=TOKENIZER_PROBE_TIMEOUT_SECONDS if verify_server_tokenization else None,
            maximum_schema_repair_calls_per_query=1, paper_result=False,
            tokenizer_initialization_seconds=tokenizer_initialization_seconds,
            cost_boundary={
                "total_external_attempted_calls_scope": "per_query_inference_plus_tokenizer_probes_only",
                "service_startup_health_checks_included": False,
                "llm_latency_includes_token_checks": True,
                "llm_latency_includes_check_journaling": True,
                "llm_latency_includes_server_tokenization_probes": verify_server_tokenization,
                "server_tokenization_probe_costs_reported_separately_do_not_add_twice": True,
                "inference_wall_includes_all_query_journaling": True,
                "tokenizer_initialization_reported_separately": True,
                "backend_execution": False,
            },
        )
        _write_json(output / "run_manifest.json", manifest)
        with QueryEventJournal(output / "query_events.jsonl") as journal, \
                QueryEventJournal(output / "query_states.jsonl") as state_journal:
            for index, question in enumerate(questions, start=1):
                qid = str(question["question_id"])
                journal.append({"event": "query_started", "question_id": qid, "query_index": index})
                query_guard = guard
                if verify_server_tokenization:
                    query_guard = ServerTokenizationGuard(
                        guard, counter, journal, qid,
                        base_url=base_provider.config.base_url,
                        api_key=os.environ.get(base_provider.config.api_key_env, ""),
                        timeout_seconds=TOKENIZER_PROBE_TIMEOUT_SECONDS,
                        context_limit=contract.data["serving"]["max_model_len"],
                        maximum_calls=2,
                    )
                # Retrieval misses never inherit the previous query's checks.
                provider = GuardedSemanticPilotProvider(
                    model, query_guard, journal, qid, base_provider=base_provider,
                )
                state = _infer_one(
                    question=question, catalog=catalog, provider=provider, semantic=semantic,
                    retrieval_k=int(spec.data["retrieval_k"]),
                    candidate_cap=int(spec.data["candidate_cap"]),
                    prompt_candidates_per_slot=int(spec.data["prompt_candidates_per_slot"]),
                    response_parser=parse_normalized_planner_response,
                )
                if str(state["question"]["question_id"]) != qid:
                    raise ValueError("Inference state belongs to a different question.")
                invocation = provider.last_invocation
                actual_calls = (
                    invocation.generation_calls + invocation.repair_calls if invocation else 0
                )
                query_checks = [{"question_id": qid, **row} for row in provider.token_check_records]
                probe_diagnostic = query_guard.diagnostics if verify_server_tokenization else {
                    "tokenizer_probe_attempted_calls": 0,
                    "tokenizer_probe_completed_results": 0,
                    "tokenizer_probe_error_count": 0,
                    "tokenizer_probe_latency_seconds": 0.0,
                    "tokenizer_probe_receipts": [],
                    "remote_serving_parity_verified": False,
                }
                failed_checks = [row for row in query_checks if row["passed"] is False]
                diagnostic = {
                    "question_id": qid, "provider_invoked": invocation is not None,
                    "actual_attempted_provider_calls": actual_calls,
                    "token_check_count": len(query_checks),
                    "guard_refusal": bool(failed_checks),
                    "local_token_refusal": any(
                        not str(row["reason"]).startswith("server_tokenization_") for row in failed_checks
                    ),
                    "server_tokenization_refusal": any(
                        str(row["reason"]).startswith("server_tokenization_") for row in failed_checks
                    ),
                    "server_tokenization": probe_diagnostic,
                    "details": provider.guard_diagnostics,
                }
                state_journal.append(state)
                journal.append({
                    "event": "query_inference_completed", "question_id": qid,
                    "query_index": index, "state_sha256": content_hash(state),
                    "diagnostic": diagnostic,
                })
                states.append(state)
                checks.extend(query_checks)
                diagnostics.append(diagnostic)
            inference_wall_seconds = time.perf_counter() - inference_started
            journal.append({"event": "inference_complete", "question_count": len(states)})
            # Frozen reference content is evaluation-only, never a prompt input.
            evaluated = _evaluate_preflight(states, spec, repo, readiness)
            _write_jsonl(output / "retrieval.jsonl", (state["retrieval"] for state in states))
            _write_jsonl(output / "llm_requests.jsonl", (
                row for state in states for row in state.get("request_records", ())
            ))
            _write_jsonl(output / "llm_responses.jsonl", (
                state["response_record"] for state in states if state.get("response_record")
            ))
            for name, key in (
                ("validated_candidates", "candidates"), ("component_match", "components"),
                ("semantic_scores", "semantic"), ("failures", "failures"),
            ):
                _write_jsonl(output / f"{name}.jsonl", evaluated[key])
            _write_json(output / "metrics.json", evaluated["metrics"])
            _write_jsonl(output / "token_checks.jsonl", checks)
            _write_jsonl(output / "guard_diagnostics.jsonl", diagnostics)
            _write_jsonl(output / "server_tokenization_checks.jsonl", (
                row for diagnostic in diagnostics
                for row in diagnostic["server_tokenization"]["tokenizer_probe_receipts"]
            ))
            # This marks inference/evaluation lifecycle completion, not final
            # status publication. Readers also require a successful CLI exit,
            # completed run_status.json, and absence of run_failure.json.
            journal.append({"event": "run_completed", "question_count": len(states)})
        status = {
            "schema_version": SCHEMA_VERSION, "status": "completed",
            "started_at": started_at, "ended_at": datetime.now(timezone.utc).isoformat(),
            "question_count": len(states),
            "actual_attempted_provider_calls": sum(row["actual_attempted_provider_calls"] for row in diagnostics),
            "local_token_refusal_query_count": sum(row["local_token_refusal"] for row in diagnostics),
            "guard_refusal_query_count": sum(row["guard_refusal"] for row in diagnostics),
            "server_tokenization_refusal_query_count": sum(row["server_tokenization_refusal"] for row in diagnostics),
            "serving_tokenizer_mode": tokenizer_mode,
            **{key: sum(row["server_tokenization"][key] for row in diagnostics) for key in (
                "tokenizer_probe_attempted_calls", "tokenizer_probe_completed_results",
                "tokenizer_probe_error_count", "tokenizer_probe_latency_seconds",
            )},
            "total_external_attempted_calls": sum(
                row["actual_attempted_provider_calls"] + row["server_tokenization"]["tokenizer_probe_attempted_calls"]
                for row in diagnostics
            ),
            "token_check_count": len(checks),
            "inference_wall_seconds": inference_wall_seconds,
            "tokenizer_initialization_seconds": tokenizer_initialization_seconds,
            "claim_boundary": dict(CLAIM_BOUNDARY), "paper_result": False,
        }
        _write_json(output / "run_status.json", status)
    except BaseException as error:
        # A crash can follow a send but precede its final receipt. Do not invent
        # zero or a complete total from only the already completed query prefix.
        failure = {
            "schema_version": SCHEMA_VERSION, "status": "incomplete",
            "started_at": started_at, "ended_at": datetime.now(timezone.utc).isoformat(),
            "completed_inference_query_count": len(states),
            "actual_attempted_provider_calls": None,
            "tokenizer_probe_attempted_calls": None, "total_external_attempted_calls": None,
            "call_accounting_complete": False, "error_type": type(error).__name__,
            "reason": _safe_failure_reason(error),
            "automatic_resume": False, "claim_boundary": dict(CLAIM_BOUNDARY),
            "paper_result": False,
        }
        try:
            _write_json(output / "run_status.json", failure)
        except (OSError, ValueError):
            pass  # The partial journal is evidence, not a successful status.
        # A failed completed-status write may already have created that file,
        # even with apparently complete JSON bytes. Never overwrite it or retry
        # a send: publish an independent failure marker where possible. A disk
        # failure that also prevents this marker leaves the outcome unknown.
        try:
            _write_json(output / "run_failure.json", failure)
        except (OSError, ValueError):
            pass
        raise
    return {"status": "completed", "output_root": str(output), "metrics": evaluated["metrics"], "paper_result": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "spec", "repo-root", "output-root", "run-environment-path", "tokenizer-snapshot",
        "tokenizer-revision", "expected-runner-commit", "execute-development-spec-sha256",
    ):
        parser.add_argument(
            f"--{name}", required=True,
            help=("Exact canonical freeze_hash field of the development spec, not its file-byte SHA-256."
                  if name == "execute-development-spec-sha256" else None),
        )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--allow-unverified-serving-tokenizer", action="store_true",
        help="Acknowledge development-only, unverified serving tokenizer parity; not an execution-authority receipt.",
    )
    modes.add_argument(
        "--verify-server-tokenization", action="store_true",
        help="Compare every locally fitting request's ordered token IDs with loopback /tokenize before inference; extra calls are charged separately, not an execution-authority receipt.",
    )
    args = parser.parse_args(argv)
    try:
        result = run_guarded_preflight(
            spec_path=args.spec, repo_root=args.repo_root, output_root=args.output_root,
            run_environment_path=args.run_environment_path,
            tokenizer_snapshot=args.tokenizer_snapshot, tokenizer_revision=args.tokenizer_revision,
            expected_runner_commit=args.expected_runner_commit,
            execute_development_spec_sha256=args.execute_development_spec_sha256,
            allow_unverified_serving_tokenizer=args.allow_unverified_serving_tokenizer,
            verify_server_tokenization=args.verify_server_tokenization,
        )
    except (Exception, KeyboardInterrupt) as error:
        # Never echo an exception containing arbitrary provider response text.
        print(json.dumps({
            "status": "incomplete", "error_type": type(error).__name__,
            "reason": _safe_failure_reason(error), "paper_result": False,
        }))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
