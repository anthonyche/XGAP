"""Ordinary NL -> bounded interpretation/estimated planning -> one final answer.

The core entry accepts a frozen fitted estimator; it never acquires execution
observations or fits on the incoming question. Evaluation gold is not an input.
"""

from dataclasses import replace
import math
import time

from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.compilers.errors import CompilerError
from xgap.planning.runtime_estimator import FrozenRuntimeEstimator
from xgap.planning.runtime_work_estimator import FrozenWorkEstimator
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.tool import FederatedExecutionTool
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
from xgap.tools.contracts import ToolContext, ToolStatus


def _source_mismatch(plan, estimator):
    known = {entry.backend_id: entry for entry in estimator.statistics.entries}
    return [backend_id for backend_id, identity in plan.metadata["source_identities"].items()
            if backend_id not in known or (known[backend_id].source_id,
                known[backend_id].snapshot_version) != (identity["source_id"], identity["snapshot_version"])]


def _frontier(items):
    # Only the cheapest estimated physical plan per admitted interpretation is
    # relevant to this two-dimensional proxy frontier (K <= 8).
    return [item["candidate_id"] for item in items if not any(
        other["estimated_ms"] <= item["estimated_ms"]
        and other["ranking_quality_proxy"] >= item["ranking_quality_proxy"]
        and (other["estimated_ms"] < item["estimated_ms"]
             or other["ranking_quality_proxy"] > item["ranking_quality_proxy"])
        for other in items)]


def run_one_shot_question(request, provider, *, policy: OneShotPolicy,
                          estimator: FrozenRuntimeEstimator | FrozenWorkEstimator | FrozenWorkDeployment | FrozenInstanceWorkDeployment, catalog_root, catalog_hash,
                          sources, backends, backend_clients):
    started = time.perf_counter()
    report = {"schema_version": "xgap-one-shot-answer-v1", "success": False,
        "status": "not_started", "error": None, "answer_rows": None,
        "answer_quality_verified": False, "interpretation": None,
        "candidates": [], "selection": None, "execution": None,
        "backend_remote_calls": 0, "observation_calls": 0, "final_plan_executions": 0,
        "resolution_external_calls": 0, "interpretation_external_calls": 0,
        "input_tokens": 0, "output_tokens": 0, "interpretation_token_usage_complete": True,
        "automatic_retries": 0, "catalog_load_ms": 0.0, "grounding_ms": 0.0,
        "planning_ms": 0.0, "execution_ms": 0.0}

    def finish():
        report["end_to_end_ms"] = (time.perf_counter() - started) * 1000
        report["cost_boundary"] = {
            "online": "this request: frozen bundle load, interpretation, grounding, planning, final execution",
            "offline": "catalog/index/statistics construction and estimator collection/fit, reported separately",
            "post_return_persistence_included": False, "backend_wire_bytes": None}
        return report

    if not isinstance(policy, OneShotPolicy) or not isinstance(estimator, (FrozenRuntimeEstimator, FrozenWorkEstimator, FrozenWorkDeployment, FrozenInstanceWorkDeployment)):
        report.update(status="configuration_unavailable",
                      error="One-shot requires a typed policy and a prepared frozen runtime estimator")
        return finish()
    report["policy"] = policy.to_dict()
    provider_config = getattr(provider, "config", None)
    if provider_config is not None and getattr(provider_config, "candidate_cap", None) != policy.candidate_cap:
        report.update(status="configuration_unavailable",
                      error="Provider's pinned wire candidate cap must match the one-shot policy before dispatch")
        return finish()
    estimator_artifact = estimator.to_dict()
    report["estimator"] = {key: estimator_artifact[key] for key in (
        "model_version", "model_sha256", "feature_schema_sha256", "training_provenance")}
    if "deployment_provenance" in estimator_artifact:
        report["estimator"]["deployment_provenance"] = estimator_artifact["deployment_provenance"]
    load_at = time.perf_counter()
    try:
        bundle = FrozenResolutionBundle.load(catalog_root, expected_bundle_hash=catalog_hash)
    except (OSError, ValueError) as error:
        report.update(status="catalog_unavailable", error=str(error))
        return finish()
    finally:
        report["catalog_load_ms"] = (time.perf_counter() - load_at) * 1000
    report["resolution_bundle"] = bundle.identity
    request = replace(request, context={**request.context, "one_shot_profile": policy.to_dict(),
        "runtime": {"resolution_bundle": bundle.identity, "sources": {
            name: {"version": source.snapshot_version, "replicas": list(source.replica_backend_ids)}
            for name, source in sources.items()}}})
    interpreted = interpret_candidate_question(request, provider, candidate_cap=policy.candidate_cap)
    report.update(interpretation=interpreted,
        interpretation_external_calls=interpreted["external_calls"], input_tokens=interpreted["input_tokens"],
        output_tokens=interpreted["output_tokens"],
        interpretation_token_usage_complete=not interpreted.get("usage_unavailable", False))
    report["interpretation_usage_known_lower_bounds"] = {
        key: interpreted[key] for key in ("external_calls", "input_tokens", "output_tokens")}
    report["interpretation_call_count_complete"] = interpreted.get("external_call_count_complete", True)
    if not report["interpretation_token_usage_complete"]:
        report.update(input_tokens=None, output_tokens=None)
    if not report["interpretation_call_count_complete"]:
        report["interpretation_external_calls"] = None
    if not interpreted["success"]:
        report.update(status=interpreted["status"], error=interpreted["error"])
        return finish()
    winners, choices = [], {}
    for interpretation in interpreted["candidates"]:
        if interpretation["status"] != "admitted":
            continue  # Its complete rejection record remains in Interpretation.
        candidate_id = interpretation["candidate_id"]
        detail = {"candidate_id": candidate_id, "status": "not_planned", "plans": []}
        report["candidates"].append(detail)
        grounding_at = time.perf_counter()
        try:
            program = SemanticGraphProgram.from_dict(interpretation["program"])
            if len(program.operators) > policy.max_operators:
                raise ValueError("Interpretation exceeds the supported operator bound")
            bound, trace = ground_interpretation(program, interpretation["operator_sources"],
                bundle, request.question, max_holes=policy.max_holes,
                max_candidates_per_hole=policy.max_candidates_per_hole, use_ontology=policy.use_ontology)
            detail["grounding"] = trace
            detail["bound_program"] = bound.program.to_dict()
            detail["bindings"] = dict(bound.bindings)
        except (ValueError, KeyError, TypeError) as error:
            detail.update(status="grounding_failed", error=str(error), grounding=getattr(error, "trace", None))
            continue
        finally:
            report["grounding_ms"] += (time.perf_counter() - grounding_at) * 1000
        planning_at = time.perf_counter()
        try:
            candidates, domain = prepare_one_shot_domain(bound.program,
                operator_sources=bound.operator_sources, sources=sources, backends=backends, policy=policy)
            detail["domain"] = domain
            estimated = []
            for candidate in candidates:
                plan = replace(candidate.plan, metadata={**candidate.plan.metadata,
                    "query_id": request.context.get("query_id")})
                candidate = replace(candidate, plan=plan)
                record = {"strategy_id": candidate.strategy_id, "plan_id": plan.plan_id}
                detail["plans"].append(record)
                mismatch = _source_mismatch(plan, estimator)
                if mismatch:
                    record.update(status="estimator_source_mismatch", backends=mismatch)
                    continue
                prediction = estimator.predict(plan).to_dict()
                record["prediction"] = prediction
                record["status"] = prediction["status"]
                cost = prediction["estimated_ms"]
                if prediction["status"] != "estimated" or cost is None:
                    continue
                if not math.isfinite(cost) or cost < 0:
                    raise ValueError("Estimator returned an invalid finite cost")
                estimated.append((cost, candidate.strategy_id, candidate, record))
            if not estimated:
                detail.update(status="no_estimated_plan", error="No admitted strategy has a compatible estimate")
                continue
            cost, _, best, best_record = min(estimated, key=lambda item: item[:2])
            quality = interpretation["quality_proxy"]
            proxy = policy.unknown_quality_proxy if quality is None else quality
            winner = {"candidate_id": candidate_id, "strategy_id": best.strategy_id,
                "plan_id": best.plan.plan_id, "estimated_ms": cost, "quality_proxy": quality,
                "ranking_quality_proxy": proxy, "quality_fallback_used": quality is None,
                "quality_proxy_calibrated": False,
                "objective_ms": cost + policy.quality_penalty_ms * (1 - proxy)}
            detail.update(status="planned", estimated_best=winner)
            winners.append(winner)
            choices[candidate_id] = (best, detail, best_record)
        except (ValueError, KeyError, TypeError, CompilerError) as error:
            detail.update(status="planning_failed", error=str(error))
        finally:
            report["planning_ms"] += (time.perf_counter() - planning_at) * 1000
    if not winners:
        report.update(status="no_executable_interpretation", error="No interpretation has a grounded estimated plan")
        return finish()
    decision_at = time.perf_counter()
    winner = min(winners, key=lambda item: (item["objective_ms"], item["estimated_ms"], item["candidate_id"]))
    selected, detail, _ = choices[winner["candidate_id"]]
    report["selection"] = {**winner, "interpretation_options": winners,
        "proxy_frontier": _frontier(winners), "frontier_is_actual_quality": False,
        "algorithm": "estimated_argmin_per_interpretation_then_quality_cost_argmin_v1",
        "optimality_scope": "estimated compatible admitted neighborhood; no global physical or answer guarantee",
        "selection_uses_execution_observations": False}
    report["selected_plan"] = selected.plan.to_dict()
    report["selected_grounding"] = detail["grounding"]
    report["planning_ms"] += (time.perf_counter() - decision_at) * 1000
    used = set(selected.plan.metadata["source_identities"])
    missing = sorted(used - set(backend_clients))
    if missing:
        report.update(status="backend_unavailable", error=f"Missing clients for selected plan: {missing}")
        return finish()
    registry = BackendPluginRegistry()
    for backend_id in sorted(used):
        registry.register(NativeBackendPlugin(backend_id, backend_clients[backend_id]))
    execute_at = time.perf_counter()
    report["final_plan_executions"] = 1
    try:
        result = FederatedExecutionTool(FederatedScheduler(BackendInvokeTool(registry))).invoke(
            {"plan": selected.plan.to_dict()}, ToolContext("one-shot:" + selected.plan.plan_id, 1, "final"))
        report.update(execution=result.to_dict(), backend_remote_calls=int(result.metrics.get("remote_calls", 0)),
                      success=result.status is ToolStatus.SUCCESS, error=result.error)
        if report["success"]:
            report.update(status="answered", answer_rows=result.value["final_rows"],
                answer_semantics="selected_predicted_interpretation", approximation={
                    "interpretation_is_prediction": True, "candidate_coverage_bounded": True,
                    "result_rows_truncated": False, "grounding": detail["grounding"]})
        else:
            report["status"] = "execution_failed"
    except Exception as error:
        # No retry/fallback. Unknown calls must not be represented by free work.
        report.update(success=False, answer_rows=None, status="execution_failed",
                      error=f"Execution boundary raised {type(error).__name__}",
                      backend_remote_calls=None, execution_accounting_complete=False)
    finally:
        report["execution_ms"] = (time.perf_counter() - execute_at) * 1000
    return finish()
