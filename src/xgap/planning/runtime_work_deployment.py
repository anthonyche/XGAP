"""Explicit offline deployment of frozen weights to new frozen source statistics.

The trained artifact is embedded unchanged. Deployment is not fitting, calibration
or proof of transfer quality. This profile requires the same backend feature names.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import time

from xgap.planning.runtime_estimator import FrozenSourceStatistics, _hash, _json, _text
from xgap.planning.runtime_work_estimator import FrozenWorkEstimator, feature_names
from xgap.runtime.contracts import RuntimeNodeKind as R


DEPLOYMENT_SCHEMA = "xgap-frozen-work-deployment-v1"


@dataclass(frozen=True)
class FrozenWorkDeployment:
    model_version: str
    trained_model: FrozenWorkEstimator
    statistics: FrozenSourceStatistics
    preparation_ref: str

    def __post_init__(self):
        _text(self.model_version, "deployment version")
        _text(self.preparation_ref, "offline preparation reference")
        if not isinstance(self.trained_model, FrozenWorkEstimator):
            raise TypeError("deployment requires one original frozen v2 model, not nested deployment")
        if not isinstance(self.statistics, FrozenSourceStatistics):
            raise TypeError("deployment requires frozen source statistics")
        if feature_names(self.statistics) != self.trained_model.feature_names:
            raise ValueError("deployment must preserve backend workload feature schema")

    @property
    def feature_schema_sha256(self):
        return self.trained_model.feature_schema_sha256

    @property
    def model_sha256(self):
        return self.to_dict()["model_sha256"]

    def to_dict(self):
        trained = self.trained_model.to_dict()
        body = {"schema_version": DEPLOYMENT_SCHEMA, "model_version": self.model_version,
            "feature_schema_sha256": self.feature_schema_sha256,
            "trained_model": trained, "statistics": self.statistics.to_dict(),
            "preparation_ref": self.preparation_ref,
            "training_provenance": trained["training_provenance"],
            "deployment_provenance": {
                "parent_model_sha256": trained["model_sha256"],
                "training_source_statistics_sha256": self.trained_model.statistics.sha256,
                "serving_source_statistics_sha256": self.statistics.sha256,
                "weights_changed": False, "fit_calls": 0, "collection_calls": 0,
                "transfer_calibrated": False, "quality_bound": None}}
        return {**body, "model_sha256": _hash(body)}

    @classmethod
    def from_dict(cls, data):
        body = dict(data)
        sha = body.pop("model_sha256", None)
        if body.get("schema_version") != DEPLOYMENT_SCHEMA or _hash(body) != sha:
            raise ValueError("deployment schema or hash mismatch")
        result = cls(body["model_version"], FrozenWorkEstimator.from_dict(body["trained_model"]),
            FrozenSourceStatistics.from_dict(body["statistics"]), body["preparation_ref"])
        if result.to_dict() != data:
            raise ValueError("deployment provenance or reconstructed identity mismatch")
        return result

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as handle:
            handle.write(_json(self.to_dict()) + "\n")

    def predict(self, plan):
        started = time.perf_counter()
        prediction = self.trained_model._predict_with_statistics(plan, self.statistics)
        identities = plan.metadata.get("source_identities", {})
        known = {s.backend_id: s for s in self.statistics.entries}
        unknown = list(prediction.features.unknown_fields)
        for node in plan.nodes:
            if node.kind not in (R.REMOTE_QUERY, R.REMOTE_BIND_QUERY):
                continue
            backend = node.parameters.get("backend_id")
            identity = identities.get(backend) if isinstance(identities, dict) else None
            source = known.get(backend)
            if source is None or identity != {"source_id": source.source_id,
                    "snapshot_version": source.snapshot_version}:
                unknown.append(f"backend.{backend}.deployment_source_identity_mismatch")
        provenance = {**prediction.provenance,
            **self.to_dict()["deployment_provenance"],
            "model_version": self.model_version, "model_sha256": self.model_sha256,
            "preparation_ref": self.preparation_ref,
            "uncertainty_scope": "parent training residual only; serving domain transfer uncalibrated"}
        changes = {"provenance": provenance, "prediction_elapsed_ms": (time.perf_counter()-started)*1000}
        if unknown:
            changes.update(status="unavailable_missing_features", estimated_ms=None, empirical_log_rmse=None,
                features=replace(prediction.features, unknown_fields=tuple(sorted(set(unknown)))))
        return replace(prediction, **changes)
