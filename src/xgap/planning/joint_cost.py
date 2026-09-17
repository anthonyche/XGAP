"""Frozen comparable costs for information actions and federated execution.

Work units express preferences/relative ranking, not observed wall time. A
compatible offline estimator is reused when available; otherwise the explicitly
labelled structural fallback preserves a nonzero execution objective.
"""
from dataclasses import asdict, dataclass
import math

from xgap.runtime.contracts import RuntimeNodeKind as R


@dataclass(frozen=True)
class JointCostProfile:
    profile_id: str = 'bounded-joint-work-v1'
    clarification_call: float = 1.0
    disclosed_field: float = 0.25
    model_call: float = 1.0
    model_token: float = 0.001
    estimated_ms_per_unit: float = 100.0
    remote_call: float = 1.0
    coordinator_node: float = 0.02

    def __post_init__(self):
        if not self.profile_id:
            raise ValueError('Frozen cost profile needs an identity')
        for key, value in asdict(self).items():
            if key != 'profile_id' and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError('Costs must be finite nonnegative numbers')
        if self.estimated_ms_per_unit <= 0 or self.remote_call <= 0:
            raise ValueError('Execution normalization and fallback remote cost must be positive')

    def information(self, slots):
        return self.clarification_call + self.disclosed_field * len(slots)

    def execution(self, plan, estimator=None):
        unavailable = None
        if estimator is not None:
            try:
                prediction = estimator.predict(plan)
            except (ValueError, KeyError) as error:
                prediction = None
                unavailable = dict(error_type=type(error).__name__, reason=str(error))
            if prediction is not None and prediction.status == 'estimated' and prediction.estimated_ms is not None:
                value = prediction.estimated_ms / self.estimated_ms_per_unit
                if not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid frozen execution prediction')
                return value, dict(basis='frozen_estimator', prediction=prediction.to_dict(),
                                   unit='declared_work_units', calibrated=False)
            if prediction is not None:
                unavailable = prediction.to_dict()
        remote = sum(n.kind in (R.REMOTE_QUERY, R.REMOTE_BIND_QUERY) for n in plan.nodes)
        score = self.remote_call * remote + self.coordinator_node * (len(plan.nodes) - remote)
        return score, dict(basis='structural_fallback', unit='declared_work_units',
                           calibrated=False, missing='No compatible numerical execution prediction',
                           unavailable_prediction=unavailable,
                           remote_calls=remote, coordinator_nodes=len(plan.nodes)-remote)

    def to_dict(self):
        return {**asdict(self), 'unit': 'declared_work_units', 'measured_latency': False}
