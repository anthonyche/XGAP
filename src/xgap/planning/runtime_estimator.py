"""Offline-fitted, frozen cost prediction for the actual federated runtime DAG.

This small research estimator does not adapt M11 ``PhysicalState`` by inventing
placements. It extracts typed topology and source-size features directly from
``FederatedExecutionPlan`` and fits ridge regression to log latency offline.
No method in prediction invokes a backend, reads answers, profiles, or fits.

For N training records, d fixed features and total represented DAG size L,
feature extraction costs O(L), fit O(N*d*d + d**3), storage O(N*d + d*d), and
prediction O(V+E+d+N), including training-provenance serialization. N is capped
at 256. Numeric work uses finite double precision;
this is not a bit-complexity or query-execution bound. The empirical training
residual is descriptive uncertainty, not a calibrated interval or error bound.
The features distinguish topology/placement/source scale, not arbitrary query
selectivity. A new selectivity feature needs a new frozen feature schema.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind


MODEL_SCHEMA = "xgap-runtime-ridge-estimator-v1"
FEATURE_SCHEMA = "xgap-runtime-topology-source-features-v1"
MAX_TRAINING_SAMPLES = 256
_REMOTE = {RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY}
_BASE_FEATURES = (
    "plan.node_count", "plan.dependency_count", "plan.root_count",
    "plan.critical_remote_depth", "plan.max_parallelism",
    *(f"operator.{kind.value}.count" for kind in RuntimeNodeKind),
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _number(value: float, name: str, *, positive: bool = False) -> float:
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or value < 0 or (positive and value == 0)):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return float(value)


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a lowercase SHA-256")


@dataclass(frozen=True)
class SourceStatistics:
    """One offline, query-independent summary per backend's admitted source."""

    backend_id: str
    source_id: str
    snapshot_version: str
    total_rows: int | None
    mean_row_bytes: float | None
    provenance_ref: str

    def __post_init__(self) -> None:
        for name in ("backend_id", "source_id", "snapshot_version", "provenance_ref"):
            _text(getattr(self, name), name)
        if self.total_rows is not None and (type(self.total_rows) is not int or self.total_rows < 0):
            raise ValueError("total_rows must be a nonnegative integer or unknown")
        if self.mean_row_bytes is not None:
            _number(self.mean_row_bytes, "mean_row_bytes", positive=True)

    def to_dict(self) -> dict[str, Any]:
        return dict(vars(self))


@dataclass(frozen=True)
class FrozenSourceStatistics:
    statistics_id: str
    version: str
    entries: tuple[SourceStatistics, ...]

    def __post_init__(self) -> None:
        _text(self.statistics_id, "statistics_id")
        _text(self.version, "statistics version")
        if any(not isinstance(item, SourceStatistics) for item in self.entries):
            raise ValueError("source statistics require typed entries")
        entries = tuple(sorted(self.entries, key=lambda item: item.backend_id))
        if not entries or len({item.backend_id for item in entries}) != len(entries):
            raise ValueError("source statistics require unique backend entries")
        object.__setattr__(self, "entries", entries)

    def to_dict(self) -> dict[str, Any]:
        return {"statistics_id": self.statistics_id, "version": self.version,
                "entries": [item.to_dict() for item in self.entries]}

    @property
    def sha256(self) -> str:
        return _hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrozenSourceStatistics":
        return cls(data["statistics_id"], data["version"],
                   tuple(SourceStatistics(**item) for item in data["entries"]))


@dataclass(frozen=True)
class RuntimeFeatures:
    names: tuple[str, ...]
    values: tuple[float | None, ...]
    schema_sha256: str
    unknown_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": FEATURE_SCHEMA, "schema_sha256": self.schema_sha256,
                "names": list(self.names), "values": list(self.values),
                "unknown_fields": list(self.unknown_fields)}


def _feature_names(statistics: FrozenSourceStatistics) -> tuple[str, ...]:
    return _BASE_FEATURES + tuple(
        name for source in statistics.entries for name in (
            f"backend.{source.backend_id}.remote_count",
            f"backend.{source.backend_id}.queried_log_rows",
            f"backend.{source.backend_id}.queried_log_row_bytes"))


def extract_runtime_features(plan: FederatedExecutionPlan,
                             statistics: FrozenSourceStatistics) -> RuntimeFeatures:
    """Read only typed plan structure and the supplied frozen source statistics."""
    if not isinstance(plan, FederatedExecutionPlan):
        raise TypeError("prediction requires FederatedExecutionPlan")
    names = _feature_names(statistics)
    schema = _hash({"version": FEATURE_SCHEMA, "names": names})
    counts = Counter(node.kind for node in plan.nodes)
    dependents: dict[str, list[str]] = {node.node_id: [] for node in plan.nodes}
    by_id = {node.node_id: node for node in plan.nodes}
    indegree = {node.node_id: len(node.inputs) for node in plan.nodes}
    depth = dict.fromkeys(by_id, 0)
    ready = deque(node.node_id for node in plan.nodes if not node.inputs)
    for node in plan.nodes:
        for parent in node.inputs:
            dependents[parent].append(node.node_id)
    while ready:
        node_id = ready.popleft()
        node = by_id[node_id]
        depth[node_id] += int(node.kind in _REMOTE)
        for child in dependents[node_id]:
            depth[child] = max(depth[child], depth[node_id])
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    values: list[float | None] = [float(len(plan.nodes)),
        float(sum(len(node.inputs) for node in plan.nodes)), float(len(plan.roots)),
        float(max(depth[root] for root in plan.roots)), float(plan.max_parallelism)]
    values.extend(float(counts[kind]) for kind in RuntimeNodeKind)
    source_ids = {source.backend_id for source in statistics.entries}
    backend_counts: Counter[str] = Counter()
    unknown: list[str] = []
    source_versions = plan.metadata.get("source_snapshot_versions", {})
    if not isinstance(source_versions, Mapping):
        source_versions = {}
    for node in plan.nodes:
        if node.kind in _REMOTE:
            backend_id = node.parameters.get("backend_id")
            if not isinstance(backend_id, str) or not backend_id:
                unknown.append(f"node.{node.node_id}.backend_id")
            elif backend_id not in source_ids:
                unknown.append(f"backend.{backend_id}.source_statistics")
            else:
                backend_counts[backend_id] += 1
    for source in statistics.entries:
        count = backend_counts[source.backend_id]
        values.append(float(count))
        if count and source_versions.get(source.backend_id) != source.snapshot_version:
            unknown.append(f"backend.{source.backend_id}.source_snapshot_version_missing_or_mismatched")
        for suffix, raw in (("queried_log_rows", source.total_rows),
                            ("queried_log_row_bytes", source.mean_row_bytes)):
            if not count:
                values.append(0.0)  # Known: this source contributes no remote call.
            elif raw is None:
                values.append(None)
                unknown.append(f"backend.{source.backend_id}.{suffix}")
            else:
                values.append(count * math.log1p(raw))
    return RuntimeFeatures(names, tuple(values), schema, tuple(sorted(set(unknown))))


@dataclass(frozen=True)
class RuntimeTrainingSample:
    observation_id: str
    query_id: str
    plan: FederatedExecutionPlan
    observed_latency_ms: float
    measurement_sha256: str
    split_role: str = "training"

    def __post_init__(self) -> None:
        _text(self.observation_id, "observation_id")
        _text(self.query_id, "training query_id")
        _number(self.observed_latency_ms, "observed_latency_ms", positive=True)
        _digest(self.measurement_sha256, "measurement_sha256")
        if self.split_role != "training":
            raise ValueError("only separately declared training observations may be fitted")
        if not isinstance(self.plan, FederatedExecutionPlan):
            raise TypeError("training plan must be FederatedExecutionPlan")
        if self.plan.metadata.get("query_id", self.query_id) != self.query_id:
            raise ValueError("training query identity disagrees with runtime plan")


@dataclass(frozen=True)
class RuntimeCostPrediction:
    status: str
    estimated_ms: float | None
    empirical_log_rmse: float | None
    features: RuntimeFeatures
    out_of_training_range: tuple[str, ...]
    prediction_elapsed_ms: float
    provenance: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "estimated_ms": self.estimated_ms,
                "empirical_log_rmse": self.empirical_log_rmse,
                "uncertainty_kind": "training_log_residual_rmse_not_calibrated",
                "features": self.features.to_dict(),
                "out_of_training_range": list(self.out_of_training_range),
                "prediction_elapsed_ms": self.prediction_elapsed_ms,
                "online_cost_scope": "feature extraction, scoring and prediction provenance",
                "provenance": dict(self.provenance)}


@dataclass(frozen=True)
class FrozenRuntimeEstimator:
    model_version: str
    statistics: FrozenSourceStatistics
    feature_names: tuple[str, ...]
    feature_schema_sha256: str
    coefficients: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    training_min: tuple[float, ...]
    training_max: tuple[float, ...]
    empirical_log_rmse: float
    training_provenance_json: str

    def __post_init__(self) -> None:
        _text(self.model_version, "model_version")
        for name in ("feature_names", "coefficients", "means", "scales", "training_min", "training_max"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.feature_names != _feature_names(self.statistics):
            raise ValueError("frozen model feature names mismatch")
        expected = _hash({"version": FEATURE_SCHEMA, "names": self.feature_names})
        if self.feature_schema_sha256 != expected:
            raise ValueError("frozen model feature schema mismatch")
        dimension = len(self.feature_names)
        for name in ("means", "scales", "training_min", "training_max"):
            values = getattr(self, name)
            if len(values) != dimension:
                raise ValueError(f"invalid model {name} dimension")
        if len(self.coefficients) != dimension + 1:
            raise ValueError("invalid coefficient dimension")
        for value in (*self.coefficients, *self.means, *self.scales,
                      *self.training_min, *self.training_max):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("frozen model values must be finite numbers")
        if any(scale <= 0 for scale in self.scales):
            raise ValueError("model feature scales must be positive")
        if any(low > high for low, high in zip(self.training_min, self.training_max)):
            raise ValueError("model training feature ranges are invalid")
        _number(self.empirical_log_rmse, "empirical_log_rmse")
        provenance = json.loads(self.training_provenance_json)
        if (provenance.get("training_kind") not in {"toy_correctness", "measured_training"}
                or provenance.get("split_role") != "training"
                or provenance.get("source_statistics_sha256") != self.statistics.sha256
                or not 2 <= provenance.get("sample_count", 0) <= MAX_TRAINING_SAMPLES):
            raise ValueError("frozen model training provenance is invalid")
        if set(provenance["training_query_ids"]) & set(provenance["excluded_query_ids"]):
            raise ValueError("frozen model mixes training and excluded evaluation queries")

    def to_dict(self) -> dict[str, Any]:
        body = {"schema_version": MODEL_SCHEMA, "model_version": self.model_version,
                "statistics": self.statistics.to_dict(),
                "feature_schema_sha256": self.feature_schema_sha256,
                "feature_names": list(self.feature_names),
                "coefficients": list(self.coefficients), "means": list(self.means),
                "scales": list(self.scales), "training_min": list(self.training_min),
                "training_max": list(self.training_max),
                "empirical_log_rmse": self.empirical_log_rmse,
                "training_provenance": json.loads(self.training_provenance_json)}
        return {**body, "model_sha256": _hash(body)}

    @property
    def model_sha256(self) -> str:
        return self.to_dict()["model_sha256"]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrozenRuntimeEstimator":
        body = dict(data)
        claimed = body.pop("model_sha256", None)
        if body.get("schema_version") != MODEL_SCHEMA or claimed != _hash(body):
            raise ValueError("frozen estimator schema or content hash mismatch")
        reconstructed = cls(model_version=body["model_version"],
            statistics=FrozenSourceStatistics.from_dict(body["statistics"]),
            feature_names=tuple(body["feature_names"]),
            feature_schema_sha256=body["feature_schema_sha256"],
            coefficients=tuple(body["coefficients"]), means=tuple(body["means"]),
            scales=tuple(body["scales"]), training_min=tuple(body["training_min"]),
            training_max=tuple(body["training_max"]),
            empirical_log_rmse=body["empirical_log_rmse"],
            training_provenance_json=_json(body["training_provenance"]))
        if reconstructed.model_sha256 != claimed:
            raise ValueError("frozen estimator contains unrecognized or altered fields")
        return reconstructed

    def save(self, path: str | Path) -> None:
        """Explicit offline save; never replace an existing frozen artifact."""
        with Path(path).open("x", encoding="utf-8") as handle:
            handle.write(_json(self.to_dict()) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> "FrozenRuntimeEstimator":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def predict(self, plan: FederatedExecutionPlan) -> RuntimeCostPrediction:
        started = time.perf_counter()
        features = extract_runtime_features(plan, self.statistics)
        training = json.loads(self.training_provenance_json)
        provenance = {"model_version": self.model_version, "model_sha256": self.model_sha256,
            "training_id": training["training_id"], "training_kind": training["training_kind"],
            "training_samples_sha256": training["training_samples_sha256"],
            "source_statistics_sha256": self.statistics.sha256,
            "feature_schema_sha256": features.schema_sha256,
            "training_query_overlap": (plan.metadata["query_id"] in training["training_query_ids"]
                if isinstance(plan.metadata.get("query_id"), str) else None),
            "requested_source_snapshot_versions": plan.metadata.get("source_snapshot_versions"),
            "current_query_observation_calls": 0, "fit_calls": 0,
            "quality_bound": None}
        if features.unknown_fields:
            return RuntimeCostPrediction("unavailable_missing_features", None, None,
                features, (), (time.perf_counter() - started) * 1000, provenance)
        values = tuple(float(value) for value in features.values)
        outside = tuple(name for name, value, low, high in zip(
            features.names, values, self.training_min, self.training_max)
            if value < low - 1e-12 or value > high + 1e-12)
        log_cost = self.coefficients[0] + sum(weight * (value - mean) / scale
            for weight, value, mean, scale in zip(
                self.coefficients[1:], values, self.means, self.scales))
        if not math.isfinite(log_cost) or not -700 <= log_cost <= 700:
            status, estimate = "unavailable_numeric_range", None
        else:
            status, estimate = "estimated", math.exp(log_cost)
        return RuntimeCostPrediction(status, estimate, self.empirical_log_rmse,
            features, outside, (time.perf_counter() - started) * 1000, provenance)


def _solve_positive_definite(matrix: list[list[float]], target: list[float]) -> tuple[float, ...]:
    n = len(target)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("ridge system is numerically non-positive definite")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    intermediate = [0.0] * n
    for i in range(n):
        intermediate[i] = (target[i] - sum(lower[i][j] * intermediate[j]
                                          for j in range(i))) / lower[i][i]
    solution = [0.0] * n
    for i in reversed(range(n)):
        solution[i] = (intermediate[i] - sum(lower[j][i] * solution[j]
                                           for j in range(i + 1, n))) / lower[i][i]
    return tuple(solution)


def fit_runtime_estimator(samples: Sequence[RuntimeTrainingSample], *,
        statistics: FrozenSourceStatistics, training_id: str, model_version: str,
        training_kind: str, excluded_query_ids: Sequence[str], collection_ref: str,
        collection_elapsed_ms: float | None, collection_remote_calls: int | None,
        ridge: float = 1e-3) -> FrozenRuntimeEstimator:
    """Fit only explicitly supplied independent training records, once offline.

    Excluded IDs must include the caller's complete intended evaluation population.
    Hashes bind supplied evidence; they do not independently prove split honesty.
    Toy measurements can verify the API but never constitute real-data training.
    """
    started = time.perf_counter()
    _text(training_id, "training_id")
    _text(collection_ref, "collection_ref")
    _number(ridge, "ridge", positive=True)
    if training_kind not in {"toy_correctness", "measured_training"}:
        raise ValueError("training_kind must state toy_correctness or measured_training")
    if collection_elapsed_ms is not None:
        _number(collection_elapsed_ms, "collection_elapsed_ms")
    if collection_remote_calls is not None and (type(collection_remote_calls) is not int
                                               or collection_remote_calls < 0):
        raise ValueError("collection_remote_calls must be nonnegative or unknown")
    if not 2 <= len(samples) <= MAX_TRAINING_SAMPLES:
        raise ValueError(f"training needs 2..{MAX_TRAINING_SAMPLES} independently recorded samples")
    for query_id in excluded_query_ids:
        _text(query_id, "excluded_query_id")
    excluded = tuple(sorted(set(excluded_query_ids)))
    if len({sample.observation_id for sample in samples}) != len(samples):
        raise ValueError("training observation IDs must be unique")
    if {sample.query_id for sample in samples} & set(excluded):
        raise ValueError("training records overlap excluded evaluation queries")
    features = [extract_runtime_features(sample.plan, statistics) for sample in samples]
    if any(feature.unknown_fields for feature in features):
        raise ValueError("cannot train with unknown runtime/source features")
    rows = [tuple(float(value) for value in feature.values) for feature in features]
    dimension, count = len(rows[0]), len(rows)
    means = tuple(sum(row[j] for row in rows) / count for j in range(dimension))
    scales = tuple(max(1e-12, math.sqrt(sum((row[j] - means[j]) ** 2
                     for row in rows) / count)) for j in range(dimension))
    # Constant columns use unit scale; no artificial huge out-of-range effects.
    scales = tuple(1.0 if scale <= 1e-12 else scale for scale in scales)
    design = [[1.0, *((value - mean) / scale for value, mean, scale
                     in zip(row, means, scales))] for row in rows]
    targets = [math.log(sample.observed_latency_ms) for sample in samples]
    width = dimension + 1
    matrix = [[sum(row[i] * row[j] for row in design)
               + (ridge if i == j and i > 0 else 0.0)
               for j in range(width)] for i in range(width)]
    right = [sum(row[i] * target for row, target in zip(design, targets))
             for i in range(width)]
    coefficients = _solve_positive_definite(matrix, right)
    rmse = math.sqrt(sum((target - sum(w * x for w, x in zip(coefficients, row))) ** 2
                         for row, target in zip(design, targets)) / count)
    evidence = [{"observation_id": sample.observation_id, "query_id": sample.query_id,
        "measurement_sha256": sample.measurement_sha256, "plan_sha256": _hash(sample.plan.to_dict()),
        "features": feature.to_dict(), "observed_latency_ms": sample.observed_latency_ms,
        "split_role": sample.split_role} for sample, feature in zip(samples, features)]
    provenance = {"training_id": training_id, "training_kind": training_kind,
        "split_role": "training", "sample_count": count,
        "training_samples_sha256": _hash(evidence),
        "training_query_ids": sorted({sample.query_id for sample in samples}),
        "training_observation_ids": [sample.observation_id for sample in samples],
        "measurement_sha256s": [sample.measurement_sha256 for sample in samples],
        "excluded_query_ids": list(excluded), "collection_ref": collection_ref,
        "source_statistics_sha256": statistics.sha256, "ridge": ridge,
        "offline_cost": {"collection_elapsed_ms": collection_elapsed_ms,
            "collection_remote_calls": collection_remote_calls,
            "fit_elapsed_ms": (time.perf_counter() - started) * 1000,
            "cost_scope": "one-time collection plus offline fit; exclude from per-query prediction"},
        "independence_boundary": "caller-declared training split; hashes bind evidence, not independence",
        "uncertainty_boundary": "in-sample log residual only; no calibrated coverage or uniform error bound"}
    return FrozenRuntimeEstimator(model_version, statistics, features[0].names,
        features[0].schema_sha256, coefficients, means, scales,
        tuple(min(row[j] for row in rows) for j in range(dimension)),
        tuple(max(row[j] for row in rows) for j in range(dimension)), rmse, _json(provenance))
