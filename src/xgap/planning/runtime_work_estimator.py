"""Frozen nonnegative workload costs; v1 artifacts keep their original meaning.

Features associate compiled work with its backend, without parsing native text or
reading answers. Work units are coarse source/DAG proxies, not cardinalities.
Fixed-sweep coordinate descent is offline O(SNd); prediction is O(V+E+B+d+N).
See docs/decisions/runtime_work_estimator_v2.md for assumptions and limitations.
"""

from collections import deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics as numeric_statistics
import time

from xgap.planning.runtime_estimator import (
    FrozenRuntimeEstimator, FrozenSourceStatistics, RuntimeCostPrediction,
    RuntimeFeatures, RuntimeTrainingSample, MAX_TRAINING_SAMPLES,
    _hash, _json, _number, _text, extract_runtime_features,
)
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R
from xgap.runtime.retrieval_budget import budget_from_artifact


MODEL_SCHEMA = "xgap-runtime-nonnegative-work-estimator-v2"
FEATURE_SCHEMA = "xgap-runtime-backend-work-features-v2"
REMOTE = {R.REMOTE_QUERY, R.REMOTE_BIND_QUERY}
FAMILIES = ("match", "path")
MODES = ("full", "bind")
MEASURES = ("calls", "record_units", "column_units", "logical_byte_units", "binding_units")


def feature_names(statistics):
    return ("plan.nodes", "plan.dependencies", "plan.critical_remote_depth",
        "plan.inverse_parallelism", *(f"kind.{kind.value}.count" for kind in R),
        *(f"kind.{kind.value}.input_units" for kind in R if kind not in REMOTE),
        *(f"backend.{source.backend_id}.{family}.{mode}.{measure}"
          for source in statistics.entries for family in FAMILIES for mode in MODES
          for measure in MEASURES))


def _support_feature(name):
    return name.endswith(".calls") or (name.startswith("kind.") and name.endswith(".count"))


@dataclass(frozen=True)
class WorkFeatures(RuntimeFeatures):
    def to_dict(self):
        return {**super().to_dict(), "schema_version": FEATURE_SCHEMA,
            "work_units_scope": "logical source records times compiled shape / DAG input units; not result cardinalities",
            "selectivity_estimated": False}


def extract_work_features(plan, statistics):
    if not isinstance(plan, FederatedExecutionPlan):
        raise TypeError("work prediction requires FederatedExecutionPlan")
    # Reuse the existing typed source/snapshot and remote-topology checks only.
    base = extract_runtime_features(plan, statistics)
    unknown = list(base.unknown_fields)
    old = dict(zip(base.names, base.values))
    names = feature_names(statistics)
    features = dict.fromkeys(names, 0.0)
    features.update({"plan.nodes": float(len(plan.nodes)),
        "plan.dependencies": float(sum(len(n.inputs) for n in plan.nodes)),
        "plan.critical_remote_depth": old["plan.critical_remote_depth"],
        "plan.inverse_parallelism": 1.0 / plan.max_parallelism})
    sources = {s.backend_id: s for s in statistics.entries}
    nodes = {n.node_id: n for n in plan.nodes}
    remaining = {n.node_id: len(n.inputs) for n in plan.nodes}
    children = {n.node_id: [] for n in plan.nodes}
    for node in plan.nodes:
        for parent in node.inputs:
            children[parent].append(node.node_id)
    ready = deque(sorted(k for k, degree in remaining.items() if degree == 0))
    work = {}
    while ready:
        node = nodes[ready.popleft()]
        incoming = sum(work[parent] for parent in node.inputs)
        features[f"kind.{node.kind.value}.count"] += 1.0
        output = incoming
        if node.kind in REMOTE:
            backend = node.parameters.get("backend_id")
            source = sources.get(backend)
            raw_artifact = node.parameters.get("artifact", {})
            descriptor = raw_artifact.get("parameters", {}) if isinstance(raw_artifact, dict) else {}
            compiler = descriptor.get("compiler") if isinstance(descriptor, dict) else None
            family = ("match" if compiler == "semantic_node_match_v1" else
                      "path" if compiler in {"bounded_native_paths_v1", "resource_triple_paths_v1", "semantic_edge_match_v1"} else None)
            columns = descriptor.get("output_columns") if isinstance(descriptor, dict) else None
            if (source is None or source.total_rows is None or source.mean_row_bytes is None or family is None
                    or not isinstance(columns, list) or not columns
                    or any(not isinstance(c, str) for c in columns)):
                unknown.append(f"node.{node.node_id}.compiled_workload_descriptor_or_source")
                output = 0.0  # Entire prediction is unavailable, never a free estimate.
            else:
                try:
                    span = 1
                    if family == "path":
                        lengths = descriptor.get("branch_edge_counts")
                        if lengths is None:
                            lengths = [descriptor.get("path_selection", {}).get("max_edges")]
                        if (not isinstance(lengths, list) or not lengths or
                                any(type(v) is not int or v < 0 for v in lengths)):
                            raise ValueError("missing finite path span")
                        span = sum(max(1, v) for v in lengths)
                    mode = "bind" if node.kind is R.REMOTE_BIND_QUERY else "full"
                    records = float(source.total_rows) * span
                    if mode == "bind":
                        limit = node.parameters.get("max_bindings")
                        if type(limit) is not int or limit <= 0:
                            raise ValueError("missing bind bound")
                        records = min(records, incoming, float(limit))
                    prefix = f"backend.{backend}.{family}.{mode}"
                    budget = budget_from_artifact(raw_artifact)
                    received = min(records, float(budget["fetch_rows"])) if budget else records
                    features[prefix + ".calls"] += 1.0
                    features[prefix + ".record_units"] += records
                    features[prefix + ".column_units"] += records * len(columns)
                    features[prefix + ".logical_byte_units"] += received * source.mean_row_bytes
                    features[prefix + ".binding_units"] += incoming if mode == "bind" else 0.0
                    # LIMIT bounds returned work, not the black-box scan/sort.
                    # Keep native record/column proxies; only bound transfer and
                    # the downstream input work, with the same executable cap.
                    output = min(records, float(budget["rows"])) if budget else records
                except (ValueError, TypeError, OverflowError):
                    unknown.append(f"node.{node.node_id}.finite_workload_descriptor")
                    output = 0.0
        else:
            features[f"kind.{node.kind.value}.input_units"] += incoming
        work[node.node_id] = output
        for child in children[node.node_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    for name, value in features.items():
        if not math.isfinite(value) or value < 0:
            unknown.append(name + ".finite_work_units")
            features[name] = None
    return WorkFeatures(names, tuple(features[n] for n in names),
        _hash({"version": FEATURE_SCHEMA, "names": names}), tuple(sorted(set(unknown))))


@dataclass(frozen=True)
class FrozenWorkEstimator:
    model_version: str
    statistics: FrozenSourceStatistics
    feature_names: tuple
    feature_schema_sha256: str
    coefficients: tuple
    scales: tuple
    training_min: tuple
    training_max: tuple
    empirical_log_rmse: float
    training_provenance_json: str

    def __post_init__(self):
        _text(self.model_version, "model_version")
        for field in ("feature_names", "coefficients", "scales", "training_min", "training_max"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        if self.feature_names != feature_names(self.statistics):
            raise ValueError("work model feature names mismatch")
        if self.feature_schema_sha256 != _hash({"version": FEATURE_SCHEMA, "names": self.feature_names}):
            raise ValueError("work model feature schema mismatch")
        d = len(self.feature_names)
        if len(self.coefficients) != d + 1 or any(len(getattr(self, f)) != d for f in
                ("scales", "training_min", "training_max")):
            raise ValueError("invalid work model dimension")
        for v in (*self.coefficients, *self.training_min, *self.training_max):
            _number(v, "nonnegative work model value")
        for v in self.scales:
            _number(v, "scale", positive=True)
        if any(low > high for low, high in zip(self.training_min, self.training_max)):
            raise ValueError("invalid work model feature ranges")
        _number(self.empirical_log_rmse, "empirical_log_rmse")
        p = json.loads(self.training_provenance_json)
        if (p.get("training_kind") not in {"toy_correctness", "measured_training"}
                or p.get("split_role") != "training" or not 2 <= p.get("sample_count", 0) <= MAX_TRAINING_SAMPLES
                or p.get("source_statistics_sha256") != self.statistics.sha256
                or p.get("algorithm") != "fixed_sweep_nonnegative_relative_ridge_v1"
                or type(p.get("fit_sweeps")) is not int or not 1 <= p["fit_sweeps"] <= 256):
            raise ValueError("invalid work model training provenance")
        if set(p["training_query_ids"]) & set(p["excluded_query_ids"]):
            raise ValueError("work model mixes training and excluded queries")
        if "training_statistics_profile" in p:
            assignments = p.get("sample_source_statistics", {})
            artifacts = p.get("training_statistics_artifacts", {})
            if (p["training_statistics_profile"] != "per-sample-frozen-statistics-v1"
                    or set(assignments) != set(p["training_observation_ids"])
                    or set(artifacts) != set(assignments.values())):
                raise ValueError("Invalid per-sample training statistics provenance")
            for digest, raw in artifacts.items():
                stat = FrozenSourceStatistics.from_dict(raw)
                if stat.sha256 != digest or feature_names(stat) != self.feature_names:
                    raise ValueError("Training statistics artifact differs from its hash/schema")

    def to_dict(self):
        body = {"schema_version": MODEL_SCHEMA, "model_version": self.model_version,
            "statistics": self.statistics.to_dict(), "feature_names": list(self.feature_names),
            "feature_schema_sha256": self.feature_schema_sha256,
            **{k: list(getattr(self, k)) for k in ("coefficients", "scales", "training_min", "training_max")},
            "empirical_log_rmse": self.empirical_log_rmse,
            "training_provenance": json.loads(self.training_provenance_json)}
        return {**body, "model_sha256": _hash(body)}

    @property
    def model_sha256(self):
        return self.to_dict()["model_sha256"]

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as f:
            f.write(_json(self.to_dict()) + "\n")

    @classmethod
    def from_dict(cls, data):
        body = dict(data)
        sha = body.pop("model_sha256", None)
        if body.get("schema_version") != MODEL_SCHEMA or _hash(body) != sha:
            raise ValueError("work estimator schema or content hash mismatch")
        body.pop("schema_version")
        body["statistics"] = FrozenSourceStatistics.from_dict(body["statistics"])
        body["training_provenance_json"] = _json(body.pop("training_provenance"))
        result = cls(**body)
        if result.model_sha256 != sha:
            raise ValueError("work model reconstructed content differs")
        return result

    def predict(self, plan):
        return self._predict_with_statistics(plan, self.statistics)

    def _predict_with_statistics(self, plan, statistics):
        """Shared scorer; explicit offline deployment owns alternative statistics."""
        started = time.perf_counter()
        f = extract_work_features(plan, statistics)
        return self._predict_features(plan, statistics, f, started=started)

    def _predict_features(self, plan, statistics, f, *, started=None):
        """Score an explicitly projected vector in the original frozen basis."""
        started = time.perf_counter() if started is None else started
        if f.names != self.feature_names or f.schema_sha256 != self.feature_schema_sha256:
            raise ValueError('Prediction feature basis differs from the frozen model')
        p = json.loads(self.training_provenance_json)
        provenance = {"model_version": self.model_version, "model_sha256": self.model_sha256,
            "training_id": p["training_id"], "training_kind": p["training_kind"],
            "training_samples_sha256": p["training_samples_sha256"],
            "source_statistics_sha256": statistics.sha256, "feature_schema_sha256": f.schema_sha256,
            "training_query_overlap": (plan.metadata["query_id"] in p["training_query_ids"]
                if isinstance(plan.metadata.get("query_id"), str) else None),
            "current_query_observation_calls": 0, "fit_calls": 0, "quality_bound": None,
            "monotonicity_scope": "componentwise represented work only; not actual runtime",
            "extrapolation_policy": "unseen categories unavailable; nonnegative numeric extrapolation uncalibrated"}
        if any(n.kind in REMOTE and n.parameters["artifact"]["parameters"].get("compiler") == "semantic_edge_match_v1"
               for n in plan.nodes):
            provenance["workload_lowering_extension"] = {
                "profile": "edge_match_as_one_edge_path_v1", "calibrated": False,
                "weights_changed": False, "feature_dimensions_changed": False}
        if plan.metadata.get("retrieval_budget") is not None:
            provenance["retrieval_work_extension"] = {
                "profile": "bounded-edge-relations-v1", "calibrated": False,
                "weights_changed": False, "native_scan_discounted": False,
                "scope": "compiled returned-row cap bounds transfer and downstream work proxies"}
        outside = ()
        status, estimate, residual = "unavailable_missing_features", None, None
        if not f.unknown_fields:
            outside = tuple(n for n, v, low, high in zip(f.names, f.values, self.training_min, self.training_max)
                if v < low - 1e-12 or v > high + 1e-12)
            unsupported = [n for n, v, high in zip(f.names, f.values, self.training_max)
                           if _support_feature(n) and v > 0 and high == 0]
            provenance["unseen_work_categories"] = unsupported
            if unsupported:
                status = "unavailable_unseen_work"
            else:
                estimate = self.coefficients[0] + sum(w * (v / scale) for w, v, scale in
                    zip(self.coefficients[1:], f.values, self.scales))
                status, residual = "estimated", self.empirical_log_rmse
                if not math.isfinite(estimate) or estimate <= 0:
                    status, estimate, residual = "unavailable_numeric_range", None, None
        return RuntimeCostPrediction(status, estimate, residual, f, outside,
            (time.perf_counter() - started) * 1000, provenance)


def fit_work_estimator(samples, *, statistics, training_id, model_version, training_kind,
        excluded_query_ids, collection_ref, collection_elapsed_ms, collection_remote_calls,
        ridge=1e-4, fit_sweeps=128, sample_statistics=None):
    """Fixed budget offline fitting; no backend, inference, answer, or held-out labels."""
    started = time.perf_counter()
    for value, name in ((training_id, "training_id"), (model_version, "model_version"), (collection_ref, "collection_ref")):
        _text(value, name)
    _number(ridge, "ridge", positive=True)
    if training_kind not in {"toy_correctness", "measured_training"}:
        raise ValueError("explicit training_kind required")
    if type(fit_sweeps) is not int or not 1 <= fit_sweeps <= 256:
        raise ValueError("fit_sweeps must be in 1..256")
    if not 2 <= len(samples) <= MAX_TRAINING_SAMPLES or any(not isinstance(s, RuntimeTrainingSample) for s in samples):
        raise ValueError("work fit requires 2..256 typed independent training samples")
    excluded = tuple(sorted(set(excluded_query_ids)))
    for q in excluded:
        _text(q, "excluded_query_id")
    if len({s.observation_id for s in samples}) != len(samples):
        raise ValueError("training observation IDs must be unique")
    if {s.query_id for s in samples} & set(excluded):
        raise ValueError("training records overlap excluded evaluation queries")
    if collection_elapsed_ms is not None:
        _number(collection_elapsed_ms, "collection_elapsed_ms")
    if collection_remote_calls is not None and (type(collection_remote_calls) is not int or collection_remote_calls < 0):
        raise ValueError("collection calls must be nonnegative or unknown")
    if sample_statistics is None:
        training_statistics = {s.observation_id: statistics for s in samples}
    else:
        if (not isinstance(sample_statistics, dict)
                or set(sample_statistics) != {s.observation_id for s in samples}
                or any(not isinstance(v, FrozenSourceStatistics) or feature_names(v) != feature_names(statistics)
                       for v in sample_statistics.values())):
            raise ValueError("Per-sample statistics must exactly cover samples with the same feature schema")
        training_statistics = sample_statistics
        for sample in samples:
            stat = training_statistics[sample.observation_id]
            by_backend = {s.backend_id: s for s in stat.entries}
            identities = sample.plan.metadata.get("source_identities", {})
            used = {n.parameters.get("backend_id") for n in sample.plan.nodes if n.kind in REMOTE}
            if any(b not in by_backend or identities.get(b) != {
                    "source_id": by_backend[b].source_id, "snapshot_version": by_backend[b].snapshot_version}
                    for b in used):
                raise ValueError("Per-sample statistics disagree with the plan's source identities")
    fs = [extract_work_features(s.plan, training_statistics[s.observation_id]) for s in samples]
    if any(f.unknown_fields for f in fs):
        raise ValueError("cannot fit unknown workload features")
    rows = [f.values for f in fs]
    dimension = len(rows[0])
    scales = tuple(max(1.0, max(r[j] for r in rows)) for j in range(dimension))
    label_scale = numeric_statistics.median(s.observed_latency_ms for s in samples)
    targets = [s.observed_latency_ms / label_scale for s in samples]
    design = [[1.0 / t, *(v / scale / t for v, scale in zip(row, scales))]
              for row, t in zip(rows, targets)]
    # Coefficients predict latency / median label. Optimize relative squared error
    # plus ridge without normal equations, centering, negative weights or log cost.
    columns = list(zip(*design))
    weights = [0.0] * (dimension + 1)
    residual = [1.0] * len(samples)
    norms = [sum(v*v for v in c) + ridge for c in columns]
    for _ in range(fit_sweeps):
        for j, column in enumerate(columns):
            updated = max(0.0, (sum(v*r for v, r in zip(column, residual))
                               + weights[j] * (norms[j] - ridge)) / norms[j])
            delta = updated - weights[j]
            if delta:
                residual = [r - delta*v for r, v in zip(residual, column)]
                weights[j] = updated
    coefficients = tuple(w * label_scale for w in weights)
    fitted = [coefficients[0] + sum(w*v/scale for w, v, scale in zip(coefficients[1:], row, scales)) for row in rows]
    log_rmse = math.sqrt(sum(math.log(pred / s.observed_latency_ms)**2 for pred, s in zip(fitted, samples)) / len(samples))
    evidence = [{"observation_id": s.observation_id, "query_id": s.query_id,
        "measurement_sha256": s.measurement_sha256, "plan_sha256": _hash(s.plan.to_dict()),
        "features": f.to_dict(), "observed_latency_ms": s.observed_latency_ms,
        "split_role": s.split_role} for s, f in zip(samples, fs)]
    if sample_statistics is not None:
        for record in evidence:
            record["source_statistics_sha256"] = training_statistics[record["observation_id"]].sha256
    p = {"training_id": training_id, "training_kind": training_kind, "split_role": "training",
        "sample_count": len(samples), "training_query_ids": sorted({s.query_id for s in samples}),
        "training_observation_ids": [s.observation_id for s in samples],
        "measurement_sha256s": [s.measurement_sha256 for s in samples], "excluded_query_ids": list(excluded),
        "collection_ref": collection_ref, "source_statistics_sha256": statistics.sha256,
        "training_samples_sha256": _hash(evidence), "algorithm": "fixed_sweep_nonnegative_relative_ridge_v1",
        "fit_sweeps": fit_sweeps, "ridge": ridge, "label_scale_ms": label_scale,
        "training_relative_rmse": math.sqrt(sum(r*r for r in residual) / len(samples)),
        "offline_cost": {"collection_elapsed_ms": collection_elapsed_ms,
            "collection_remote_calls": collection_remote_calls, "fit_elapsed_ms": (time.perf_counter()-started)*1000,
            "cost_scope": "one-time independent collection and fit"},
        "independence_boundary": "caller-declared split; hashes bind records, not independence",
        "uncertainty_boundary": "training residuals only; no calibrated generalization or error guarantee"}
    if sample_statistics is not None:
        p["training_statistics_profile"] = "per-sample-frozen-statistics-v1"
        p["sample_source_statistics"] = {s.observation_id: training_statistics[s.observation_id].sha256 for s in samples}
        p["training_statistics_artifacts"] = {v.sha256: v.to_dict() for v in training_statistics.values()}
        p["primary_statistics_scope"] = "default serving contract; training samples retain their own snapshots"
    return FrozenWorkEstimator(model_version, statistics, fs[0].names, fs[0].schema_sha256,
        coefficients, scales, tuple(min(r[j] for r in rows) for j in range(dimension)),
        tuple(max(r[j] for r in rows) for j in range(dimension)), log_rmse, _json(p))


def frozen_estimator_from_dict(data):
    from xgap.planning.runtime_work_deployment import DEPLOYMENT_SCHEMA, FrozenWorkDeployment
    from xgap.planning.runtime_instance_work import INSTANCE_SCHEMA, FrozenInstanceWorkDeployment
    if data.get("schema_version") == INSTANCE_SCHEMA:
        return FrozenInstanceWorkDeployment.from_dict(data)
    if data.get("schema_version") == DEPLOYMENT_SCHEMA:
        return FrozenWorkDeployment.from_dict(data)
    if data.get("schema_version") == MODEL_SCHEMA:
        return FrozenWorkEstimator.from_dict(data)
    return FrozenRuntimeEstimator.from_dict(data)


def load_frozen_estimator(path):
    return frozen_estimator_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
