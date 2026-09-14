"""Opt-in ordinary question route for the trusted-skeleton strong-plan profile."""
from dataclasses import dataclass, field, replace
import time

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingState, PracticalMode
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.semantic.interpretation import interpret_question
from xgap.semantic.program import SemanticGraphProgram


@dataclass(frozen=True)
class PracticalQuestionOptions:
    initial_state: BindingState
    mode: PracticalMode = field(default_factory=PracticalMode)
    actions: tuple = ()
    resolution_tools: object = None
    predictions: object = None
    limits: StrongSearchLimits = field(default_factory=StrongSearchLimits)
    physical_profile: OneShotPolicy = field(default_factory=OneShotPolicy)
    resolution_bundle: FrozenResolutionBundle | None = None


def run_practical_question(request, provider, *, options, catalog_root, catalog_hash,
                           sources, backends, backend_clients, estimator=None):
    if not isinstance(options, PracticalQuestionOptions):
        raise ValueError("Practical question entry needs typed options")
    started = time.perf_counter()
    base = {"success": False, "answer_rows": None, "final_plan_executions": 0,
            "backend_remote_calls": 0, "interpretation": None,
            "mode": options.mode.mode, "optimality_certified": False}
    def finish(result):
        return {**result, "end_to_end_ms": (time.perf_counter() - started) * 1000}
    try:
        if options.resolution_bundle is None:
            bundle = FrozenResolutionBundle.load(catalog_root, expected_bundle_hash=catalog_hash)
        else:
            bundle = options.resolution_bundle
            if not isinstance(bundle,FrozenResolutionBundle) or bundle.bundle_hash != catalog_hash:
                raise ValueError('Prepared resolution snapshot differs from the requested bundle')
    except (OSError, ValueError) as error:
        return finish({**base, "status": "catalog_unavailable", "error": str(error)})
    interpreted = interpret_question(request, provider)
    base["interpretation"] = interpreted
    if not interpreted["success"]:
        return finish({**base, "status": interpreted["status"], "error": interpreted["error"]})
    if interpreted.get("usage_unavailable", False):
        return finish({**base, "status": "interpretation_usage_unknown"})
    used = ResourceUsage(interpreted["external_calls"], interpreted["input_tokens"] + interpreted["output_tokens"], 0)
    if not used.fits(options.limits.resources):
        return finish({**base, "status": "interpretation_budget_exhausted"})
    remaining = ResourceUsage(*(getattr(options.limits.resources, k) - getattr(used, k)
                               for k in ("model_calls", "tokens", "remote_calls")))
    try:
        result = run_practical_semantic_query(SemanticGraphProgram.from_dict(interpreted["program"]),
            initial_state=options.initial_state, mode=options.mode, actions=options.actions,
            predictions=options.predictions, resolution_tools=options.resolution_tools,
            limits=replace(options.limits, resources=remaining), physical_profile=options.physical_profile,
            operator_sources=interpreted["operator_sources"], binding_values=bundle.bindings,
            sources=sources, backends=backends, backend_clients=backend_clients, estimator=estimator)
    except (ValueError, KeyError, TypeError) as error:
        result = {**base, "status": "practical_admission_failed", "error": str(error)}
    return finish({**result, "interpretation": interpreted, "resolution_bundle": bundle.identity,
        "interpretation_external_calls": used.model_calls,
        "model_calls": None if result.get("model_calls") is None and 'model_calls' in result else used.model_calls + result.get("model_calls", 0),
        "tokens": None if result.get("tokens") is None and 'tokens' in result else used.tokens + result.get("tokens", 0)})
