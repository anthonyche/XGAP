"""Common question entry; Interpretation and deterministic execution stay separate."""

from dataclasses import replace
import time

from xgap.agent.semantic_execution import run_frozen_semantic_query
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.semantic.interpretation import interpret_question
from xgap.semantic.program import SemanticGraphProgram


def run_question(request, provider, *, catalog_root, catalog_hash, sources,
                 backends, backend_clients, **execution_options):
    started = time.perf_counter()
    try:
        bundle = FrozenResolutionBundle.load(catalog_root, expected_bundle_hash=catalog_hash)
    except (OSError, ValueError) as error:
        return {"success": False, "status": "catalog_unavailable", "error": str(error),
                "interpretation": None, "backend_remote_calls": 0, "resolution_external_calls": 0,
                "interpretation_external_calls": 0, "input_tokens": 0, "output_tokens": 0,
                "end_to_end_ms": (time.perf_counter() - started) * 1000}
    request = replace(request, context={**request.context, "runtime": {
        "resolution_bundle": bundle.identity,
        "sources": {name: {"version": source.snapshot_version, "replicas": list(source.replica_backend_ids)}
                    for name, source in sources.items()}}})
    interpreted = interpret_question(request, provider)
    if interpreted["success"]:
        result = run_frozen_semantic_query(program=SemanticGraphProgram.from_dict(interpreted["program"]),
            question=request.question, operator_sources=interpreted["operator_sources"],
            catalog_root=catalog_root, catalog_hash=catalog_hash, sources=sources,
            backends=backends, backend_clients=backend_clients, **execution_options)
    else:
        result = {"success": False, "status": interpreted["status"], "error": interpreted["error"],
                  "backend_remote_calls": 0, "resolution_external_calls": 0,
                  "input_tokens": 0, "output_tokens": 0}
    return {**result, "interpretation": interpreted,
            "interpretation_token_usage_complete": not interpreted.get("usage_unavailable", False),
            "interpretation_external_calls": interpreted["external_calls"],
            "input_tokens": result["input_tokens"] + interpreted["input_tokens"],
            "output_tokens": result["output_tokens"] + interpreted["output_tokens"],
            "end_to_end_ms": (time.perf_counter() - started) * 1000}
