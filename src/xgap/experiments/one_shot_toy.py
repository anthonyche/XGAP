"""One original tiny question through the ordinary one-shot entry.

Default operation is local preflight. Explicit execution makes at most one model
request, uses already loaded backend clients, and never starts/loads services or
fits an estimator. All exports are exclusive; a failure is locally replayable.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.question import run_question
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.external_toy_interpretation import (
    ExternalChatRequestGuard, REQUEST_BYTES, RESPONSE_BYTES, load_external_toy_provider,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, interpretation_inputs
from xgap.experiments.toy_live_interpretation import PROMPT_PATH
from xgap.experiments.toy_output_contract import apply_request_profile
from xgap.experiments.toy_semantic import toy_backends
from xgap.llm.candidate_interpretation import (
    OpenAICompatibleCandidateInterpretationProvider, candidate_interpretation_schema,
)
from xgap.planning.runtime_estimator import FrozenRuntimeEstimator
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationFailure, InterpretationRequest
from xgap.semantic.interpretation_candidates import SCHEMA, interpret_candidate_question
from xgap.semantic.interpretation_replay import (
    RecordingInterpretationProvider, ReplayInterpretationProvider, SCHEMA as RECORDING_SCHEMA,
)


PROFILE = "xgap-one-shot-toy-development-v2"
MODEL = "qwen3.8-27b"
BASE_URL = "http://112.95.75.67:9018/v1"
# Original request text only. Reading the old cases file before inference would
# expose its gold fields, so that file is opened only by post-seal evaluation.
REQUEST_QUESTIONS = {
    "B01": "在 toy graph 中查找 Alice knows 的 people，年龄至少 30，返回人员和边。",
    "B04": "在 toy graph 的 people 中，返回 Alice 的身份和年龄，并要求年龄至少30。",
}


@dataclass(frozen=True)
class OneShotChatRequestGuard(ExternalChatRequestGuard):
    """Same full-request byte check, with explicit 6144-token output allowance."""

    def __post_init__(self):
        if not isinstance(self.expected_model, str) or not self.expected_model.strip():
            raise ValueError("An exact model alias is required")
        if (type(self.request_byte_limit) is not int or not 0 < self.request_byte_limit <= REQUEST_BYTES
                or type(self.output_limit) is not int or not 0 < self.output_limit <= 6144):
            raise ValueError("One-shot development request/output reservation exceeds its profile")


def one_shot_toy_prompt():
    base = PROMPT_PATH.with_name("semantic_program_v3.txt").read_text(encoding="utf-8")
    marker = "The program has program_id, operators, roots, holes, metadata."
    if marker not in base:
        raise ValueError("The explicit-output toy prompt has changed its reusable operator contract")
    body = base[base.index(marker):]
    body = body.replace("question mentions a clarification; the caller's separate clarification tool\n"
                        "owns that decision. Do not replace an ambiguous original mention yourself.",
                        "question is ambiguous; subsequent frozen-catalog grounding owns the identity\n"
                        "prediction. Do not replace an ambiguous original mention yourself.")
    return (f"Interpret the question as one to candidate_cap bounded alternative semantic programs.\n"
        f"Return only {{schema_version: \"{SCHEMA}\", candidates: [...]}} as valid JSON.\n"
        "Each candidate has candidate_id, quality_proxy, program and operator_sources.\n"
        "Candidate IDs are unique. quality_proxy is an uncalibrated preference in [0,1],\n"
        "or null when unknown; it is not an accuracy probability. Return fewer than the\n"
        "cap when extra interpretations are not justified. Do not duplicate candidates.\n"
        "Interpret every candidate independently using the following same contract.\n"
        "Never produce native queries, physical plans, answers or invented/resolved entity IDs.\n"
        "Never alter a required hard constraint. Respect context.one_shot_profile budgets.\n"
        "Follow the typed response schema exactly. constraints and required_capabilities\n"
        "are siblings of parameters, never fields inside parameters. In path_pattern,\n"
        "target, selector, restrictor, condition and max_depth are siblings of expr.\n"
        "A rel expr contains only kind and edge. Misnested or extra fields are rejected\n"
        "without repair; do not duplicate fields at multiple levels.\n\n" + body)


def load_one_shot_toy_provider(*, mode="precision", base_url=BASE_URL, model=MODEL,
                               api_key_env="XGAP_EXTERNAL_LLM_API_KEY", disable_thinking=False,
                               output_tokens=None):
    policy = OneShotPolicy.for_mode(mode)
    legacy = load_external_toy_provider(base_url=base_url, model=model, api_key_env=api_key_env,
        disable_thinking=disable_thinking, request_profile="explicit-output-v1")
    output = output_tokens if output_tokens is not None else (6144 if mode == "precision" else 4096)
    guard = OneShotChatRequestGuard(model, output_limit=output)
    prompt = one_shot_toy_prompt()
    config = replace(legacy.config, provider_id=PROFILE + ":" + mode + ":" + model,
        max_tokens=output, candidate_cap=policy.candidate_cap,
        structured_schema=candidate_interpretation_schema(policy.candidate_cap), prompt_hash=content_hash(prompt))
    return OpenAICompatibleCandidateInterpretationProvider(config, prompt, guard, legacy.transport)


def one_shot_toy_inputs(query_id="B01", mode="precision"):
    if query_id not in ("B01", "B04"):
        raise ValueError("This single-question development gate supports only original B01 or B04")
    request, _ = interpretation_inputs({"id": query_id, "nl": REQUEST_QUESTIONS[query_id]})
    request = apply_request_profile(request, "explicit-output-v1")
    graph = json.loads((DEFAULT_FIXTURE / "graph.json").read_text())
    mapping = json.loads((DEFAULT_FIXTURE / "mapping.json").read_text())
    version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
    pin = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    root = BUNDLE_FIXTURE / pin["root"]
    bundle = FrozenResolutionBundle.load(root, expected_bundle_hash=pin["bundle_hash"])
    policy = OneShotPolicy.for_mode(mode)
    sources = {"toy": LogicalSource("toy", version, ("neo4j", "fuseki"))}
    request = replace(request, context={**request.context, "query_id": query_id,
        "one_shot_profile": policy.to_dict(), "runtime": {"resolution_bundle": bundle.identity,
            "sources": {"toy": {"version": version, "replicas": ["neo4j", "fuseki"]}}}})
    return request, {"policy": policy, "catalog_root": root, "catalog_hash": pin["bundle_hash"],
                     "sources": sources, "backends": toy_backends(mapping)}


def _write_once(path, record):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _file_record(path):
    data = Path(path).read_bytes()
    return {"file": Path(path).name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def one_shot_toy_preflight(provider, *, estimator_path, query_id="B01", mode="precision"):
    """Read the frozen estimator and inputs; no client, model, fit, or builder call."""
    request, inputs = one_shot_toy_inputs(query_id, mode)
    data = Path(estimator_path).read_bytes()
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Frozen toy estimator exceeds 8 MiB")
    estimator = FrozenRuntimeEstimator.from_dict(json.loads(data))
    version = inputs["sources"]["toy"].snapshot_version
    entries = estimator.statistics.entries
    if (set(item.backend_id for item in entries) != {"neo4j", "fuseki"}
            or any((item.source_id, item.snapshot_version) != ("toy", version) for item in entries)):
        raise ValueError("Estimator statistics do not identify the exact original tiny graph and two backends")
    if query_id in estimator.to_dict()["training_provenance"]["training_query_ids"]:
        raise ValueError("Current question cannot occur in the estimator training IDs")
    if (provider.config.candidate_cap != inputs["policy"].candidate_cap
            or provider.config.prompt_hash != content_hash(one_shot_toy_prompt())):
        raise ValueError("Provider prompt/candidate cap differs from the requested one-shot mode")
    check = provider.token_guard.check(provider.build_request_payload(request), call_kind="generation")
    report = {"schema_version": PROFILE, "success": check["passed"], "operation": "preflight",
        "query_id": query_id, "mode": mode, "external_calls": 0, "backend_calls": 0,
        "paper_result": False, "gold_used_for_inference": False, "config": provider.config.safe_dict(),
        "request": request.to_dict(), "request_budget": check, "policy": inputs["policy"].to_dict(),
        "estimator_file": {"file": Path(estimator_path).name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "path": str(Path(estimator_path).resolve())},
        "estimator_model_sha256": estimator.model_sha256, "training_provenance": estimator.to_dict()["training_provenance"],
        "source_snapshot_version": version, "resolution_bundle": request.context["runtime"]["resolution_bundle"],
        "live_endpoint_verified": False, "loaded_backend_facts_verified": False,
        "exact_input_tokens_verified": False, "context_fit_verified": False,
        "response_byte_limit": RESPONSE_BYTES, "maximum_model_requests": 1,
        "timeout_semantics": "120-second socket timeout; not a hard end-to-end wall deadline"}
    return report, request, inputs, estimator


class _DurableRecordingProvider(RecordingInterpretationProvider):
    def __init__(self, provider, path):
        super().__init__(provider)
        self.config, self.path = provider.config, path

    def interpret(self, request):
        if self.records:
            raise InterpretationFailure("request_budget", "The single model request is already consumed")
        try:
            return super().interpret(request)
        finally:
            try:
                _write_once(self.path, {"schema_version": RECORDING_SCHEMA,
                    "provider_id": self.provider_id, "records": self.records})
            except (OSError, ValueError, TypeError) as error:
                record = self.records[0] if self.records else {}
                outcome = record.get("response", record.get("failure", {}))
                usage = outcome.get("usage", {})
                provenance = outcome.get("provenance", {})
                raise InterpretationFailure("recording_failed", "Cannot durably preserve the one model outcome",
                    usage=usage, provenance={"usage_reported": provenance.get("usage_reported", bool(usage)),
                        "external_call_count_complete": "external_calls" in usage
                            and provenance.get("external_call_count_complete") is not False,
                        "recording_error_type": type(error).__name__}) from error


def run_one_shot_toy(*, estimator_path, output, query_id="B01", mode="precision", execute=False,
                     backend_clients=None, provider=None, evaluate=False, **provider_options):
    """Exactly one ordinary query when execute=True; only preflight otherwise."""
    if type(execute) is not bool or type(evaluate) is not bool:
        raise ValueError("Execution/evaluation flags must be explicit booleans")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    receipt = {"schema_version": PROFILE, "success": False, "operation": "execute" if execute else "preflight",
        "query_id": query_id, "mode": mode, "external_calls": 0, "backend_calls": 0,
        "execution_success": None, "answer_exact": None,
        "paper_result": False, "automatic_retries": 0, "files": []}
    try:
        provider = provider or load_one_shot_toy_provider(mode=mode, **provider_options)
        preflight, request, inputs, estimator = one_shot_toy_preflight(provider,
            estimator_path=estimator_path, query_id=query_id, mode=mode)
        _write_once(root / "preflight.json", preflight)
        if not preflight["success"]:
            receipt["status"] = "preflight_failed"
        elif not execute:
            receipt.update(success=True, status="preflight_passed")
        elif backend_clients is None or set(backend_clients) != {"neo4j", "fuseki"}:
            receipt["status"] = "prepared_backend_clients_required"
        else:
            _write_once(root / "request_intent.json", {"request": request.to_dict(),
                "policy": inputs["policy"].to_dict(), "estimator_model_sha256": estimator.model_sha256,
                "maximum_model_requests": 1, "maximum_final_plan_executions": 1,
                "backend_state": "caller-owned, already loaded original tiny fixture"})
            recorder = _DurableRecordingProvider(provider, root / "interpretation.json")
            result = run_question(request, recorder, one_shot_policy=inputs["policy"], estimator=estimator,
                catalog_root=inputs["catalog_root"], catalog_hash=inputs["catalog_hash"],
                sources=inputs["sources"], backends=inputs["backends"], backend_clients=backend_clients)
            _write_once(root / "result.json", result)  # Seal before optional independent gold access.
            receipt.update(success=result["success"], status=result["status"],
                execution_success=result["success"] if result["final_plan_executions"] else None,
                external_calls=result["interpretation_external_calls"], backend_calls=result["backend_remote_calls"],
                final_plan_executions=result["final_plan_executions"], input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"], online_end_to_end_ms=result["end_to_end_ms"])
            if evaluate:
                from xgap.experiments.toy_binding import load_binding_cases
                case = next(item for item in load_binding_cases() if item["id"] == query_id)
                canonical = lambda rows: sorted(json.dumps(row, sort_keys=True, allow_nan=False) for row in rows)
                exact = result["success"] and canonical(result["answer_rows"]) == canonical(case["expected_rows"])
                _write_once(root / "evaluation.json", {"query_id": query_id, "scope": "independent original tiny gold",
                    "execution_completed": result["success"], "answer_exact": exact,
                    "inference_result_sealed_sha256": _file_record(root / "result.json")["sha256"],
                    "paper_result": False})
                receipt["answer_exact"] = exact
    except Exception as error:
        receipt.update(success=False, status="harness_failed", error_type=type(error).__name__, error=str(error))
        if (root / "request_intent.json").exists() and not (root / "result.json").exists():
            receipt.update(external_calls=None, backend_calls=None)
    finally:
        receipt["files"] = [_file_record(path) for path in sorted(root.glob("*.json"))]
        receipt["harness_elapsed_ms"] = (time.perf_counter() - started) * 1000
        _write_once(root / "receipt.json", receipt)
    return receipt


def replay_one_shot_interpretation(recording_path, *, output):
    """Replay provider admission only; never retry a model or execute a backend."""
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    replay = ReplayInterpretationProvider.from_path(recording_path)
    if len(replay.records) != 1:
        raise ValueError("Single-question replay requires exactly one recorded model outcome")
    raw = replay.records[0]["request"]
    request = InterpretationRequest(raw["question"], raw["context"], tuple(raw["required_constraints"]), raw["max_response_bytes"])
    result = interpret_candidate_question(request, replay,
        candidate_cap=request.context["one_shot_profile"]["candidate_cap"])
    replay.assert_consumed()
    _write_once(root / "result.json", result)
    receipt = {"schema_version": PROFILE, "operation": "interpretation_replay", "success": True,
        "replayed_status": result["status"], "external_calls": 0, "backend_calls": 0,
        "automatic_retries": 0, "paper_result": False, "original_recording": _file_record(recording_path),
        "files": [_file_record(root / "result.json")]}
    _write_once(root / "receipt.json", receipt)
    return receipt


def main(argv=None):
    import argparse
    from xgap.backends.fuseki_client import FusekiClient
    from xgap.backends.neo4j_client import Neo4jClient
    from xgap.infrastructure.descriptors import BackendDescriptor

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--estimator")
    parser.add_argument("--query-id", choices=("B01", "B04"), default="B01")
    parser.add_argument("--mode", choices=("precision", "performance"), default="precision")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--execute", action="store_true")
    operation.add_argument("--replay", metavar="RECORDING_JSON")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--api-key-env", default="XGAP_EXTERNAL_LLM_API_KEY")
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--output-tokens", type=int, choices=(4096, 6144))
    parser.add_argument("--neo4j-url", help="Already loaded loopback tiny Neo4j root URL")
    parser.add_argument("--fuseki-url", help="Already loaded loopback Fuseki root URL, dataset /toy")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args(argv)
    if args.replay:
        receipt = replay_one_shot_interpretation(args.replay, output=args.output)
    else:
        if not args.estimator:
            parser.error("--estimator is required; no online fitting or synthetic fallback")
        clients = None
        if args.execute:
            for url in (args.neo4j_url, args.fuseki_url):
                parsed = urllib.parse.urlsplit(url or "")
                if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                        or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
                    parser.error("Execution requires both already loaded loopback root URLs")
            neo = Neo4jClient(BackendDescriptor("neo4j", "neo4j", "cypher", "property_graph", runtime={"timeout_seconds": 35}))
            rdf = FusekiClient(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf", runtime={"timeout_seconds": 35}))
            neo.http_url, neo.database = args.neo4j_url.rstrip("/"), "neo4j"
            rdf.base_url, rdf.dataset = args.fuseki_url.rstrip("/"), "toy"
            clients = {"neo4j": neo, "fuseki": rdf}
        receipt = run_one_shot_toy(estimator_path=args.estimator, output=args.output,
            query_id=args.query_id, mode=args.mode, execute=args.execute, backend_clients=clients,
            evaluate=args.evaluate, base_url=args.base_url, model=args.model, api_key_env=args.api_key_env,
            disable_thinking=args.disable_thinking, output_tokens=args.output_tokens)
    print(json.dumps({key: receipt.get(key) for key in ("success", "operation", "status", "external_calls", "backend_calls")}))
    return 0 if receipt["success"] else 1
