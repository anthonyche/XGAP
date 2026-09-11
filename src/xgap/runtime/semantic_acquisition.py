"""Finite predictive rollout for stop versus one nominated profile request."""

from dataclasses import asdict, dataclass, replace
import math

from xgap.runtime.planning import FederatedPlanSelector, RemoteEstimate
from xgap.runtime.semantic_refresh import SemanticRefreshPolicy


def _nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class ProfileForecast:
    outcome_id: str
    probability: float
    elapsed_ms: float
    row_count: int
    row_width_bytes: float

    def __post_init__(self):
        if not isinstance(self.outcome_id, str) or not self.outcome_id.strip():
            raise ValueError("Forecast outcome needs an identity")
        _nonnegative(self.probability, "Forecast probability")
        if self.probability == 0:
            raise ValueError("Only positive-probability forecast outcomes are admitted")
        RemoteEstimate("forecast", "forecast", self.elapsed_ms, self.row_count,
            self.row_width_bytes, "validation", "validation")


@dataclass(frozen=True)
class SemanticAcquisitionPolicy:
    outcomes: tuple[ProfileForecast, ...]
    expected_acquisition_ms: float
    expected_reselection_ms: float
    max_expected_extra_ms: float
    source: str
    version: str

    def __post_init__(self):
        if (not isinstance(self.outcomes, tuple) or not self.outcomes
                or any(not isinstance(o, ProfileForecast) for o in self.outcomes)):
            raise ValueError("Acquisition requires explicit typed finite outcomes")
        if len({o.outcome_id for o in self.outcomes}) != len(self.outcomes):
            raise ValueError("Forecast outcome identities must be unique")
        if not math.isclose(math.fsum(o.probability for o in self.outcomes), 1.0, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("Forecast probabilities must sum to one")
        for field in ("expected_acquisition_ms", "expected_reselection_ms", "max_expected_extra_ms"):
            _nonnegative(getattr(self, field), field)
        _nonnegative(self.expected_acquisition_ms + self.expected_reselection_ms, "Expected extra cost")
        if any(not isinstance(v, str) or not v.strip() for v in (self.source, self.version)):
            raise ValueError("Forecast source and version must be explicit")

    def to_dict(self):
        return {**asdict(self), "scope": "stop_vs_one_nominated_request",
            "request_rule": SemanticRefreshPolicy().to_dict()["request_rule"],
            "max_acquisition_calls": 1, "max_reselections": 1,
            "hard_wall_time_bound": False, "forecast_calibration_claim": False,
            "global_action_optimality_claim": False}

    def decide(self, space, snapshot, initial):
        request = SemanticRefreshPolicy().choose_request(space, initial.plan, snapshot)
        original = snapshot.by_key[request.observation_key]
        response_space = replace(space, baseline=initial)
        selector = FederatedPlanSelector()
        scenarios = []
        mass = math.fsum(o.probability for o in self.outcomes)
        for outcome in self.outcomes:
            version = snapshot.version + "/forecast:" + self.version + ":" + outcome.outcome_id
            estimate = replace(original, elapsed_ms=outcome.elapsed_ms, row_count=outcome.row_count,
                row_width_bytes=outcome.row_width_bytes, source=self.source, version=version)
            predicted = snapshot.with_estimates((estimate,), version=version)
            response, selection = response_space.select(predicted)
            baseline = selector.estimate(initial.plan, predicted).predicted_latency_ms
            upper = selection["certificate"]["upper_bound_ms"]
            lower = selection["certificate"]["lower_bound_ms"]
            if upper > baseline:
                raise ValueError("Forecast response must preserve the initial-plan baseline")
            scenarios.append({"outcome_id": outcome.outcome_id, "probability": outcome.probability / mass,
                "estimate": estimate.to_dict(), "baseline_cost_ms": baseline,
                "response_cost_ms": upper, "response_plan_id": response.plan.plan_id,
                "selection": selection,
                "response_gap_ms": upper - lower if lower is not None else None})
        stop_cost = math.fsum(s["probability"] * s["baseline_cost_ms"] for s in scenarios)
        response_cost = math.fsum(s["probability"] * s["response_cost_ms"] for s in scenarios)
        extra = self.expected_acquisition_ms + self.expected_reselection_ms
        # Sum paired savings before subtracting the action cost. Subtracting
        # two large weighted totals can turn an exact zero-gain tie positive.
        saving = math.fsum(s["probability"] * (s["baseline_cost_ms"] - s["response_cost_ms"])
            for s in scenarios)
        gain = saving - extra
        gap = (math.fsum(s["probability"] * s["response_gap_ms"] for s in scenarios)
            if all(s["response_gap_ms"] is not None for s in scenarios) else None)
        gain_upper = gain + gap if gap is not None else None
        feasible = extra <= self.max_expected_extra_ms
        acquire = feasible and gain > 0
        reason = ("positive_expected_net_gain" if acquire else "expected_budget_exceeded" if not feasible else
                  "optimal_response_cannot_pay" if gain_upper is not None and gain_upper <= 0 else
                  "specified_response_has_no_expected_gain")
        for value in (stop_cost, response_cost, extra, gain):
            if not math.isfinite(value):
                raise ValueError("Forecast cost arithmetic must remain finite")
        return {"action": "acquire" if acquire else "stop", "reason": reason,
            "request": request.to_dict(), "scenarios": scenarios,
            "initial_plan_id": initial.plan.plan_id,
            "expected_stop_execution_ms": stop_cost, "expected_response_execution_ms": response_cost,
            "expected_extra_ms": extra, "expected_execution_saving_ms": saving, "expected_net_gain_ms": gain,
            "optimal_net_gain_upper_ms": gain_upper,
            "decision_regret_bound_ms": (gap if acquire else max(0.0, gain_upper)) if gap is not None else None,
            "expected_policy_total_ms": extra + response_cost if acquire else stop_cost,
            "forecast_budget_feasible": feasible, "scenario_selection_runs": len(scenarios),
            "certificate_scope": "conditional discrete forecast; stop or one nominated request",
            "actual_latency_bound": False}

    def matches_support(self, estimate):
        return any((estimate["elapsed_ms"], estimate["row_count"], estimate["row_width_bytes"])
            == (o.elapsed_ms, o.row_count, o.row_width_bytes) for o in self.outcomes)
