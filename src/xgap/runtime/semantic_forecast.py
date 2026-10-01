"""Offline empirical preparation for one exact A3 request, without fitting online."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import time

from xgap.runtime.observations import PlanObservationCollection
from xgap.runtime.planning import RemoteEstimate
from xgap.tools.backends import BackendOperation, _artifact_sha256


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Prepared observation requires original timestamps")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Prepared observation timestamp needs a timezone")
    return parsed.timestamp()


def context_identity(space, snapshot, environment_episode):
    if not isinstance(environment_episode, str) or not environment_episode.strip():
        raise ValueError("Forecast preparation requires an environment episode")
    if not hasattr(space, "memory_context"):
        raise ValueError("Prepared forecasts require the polynomial placement context")
    return digest({"schema": "exact-acquisition-context-v1", "episode": environment_episode,
        "placement": space.memory_context(), "requests": [r.to_dict() for r in space.observation_requests],
        "costs": {name: getattr(snapshot, name) for name in
            ("bandwidth_bytes_per_ms", "exchange_fixed_ms", "coordinator_row_ms")}})


@dataclass(frozen=True)
class ForecastTarget:
    environment_episode: str
    context_sha256: str
    request_sha256: str
    preparation_sha256: str
    cutoff_at: float
    historical_calls: int
    historical_acquisition_ms: float
    historical_reselection_ms: float
    preparation_cpu_ms: float

    def __post_init__(self):
        if not isinstance(self.environment_episode, str) or not self.environment_episode.strip():
            raise ValueError("Prepared forecast needs an environment episode")
        for sha in (self.context_sha256, self.request_sha256, self.preparation_sha256):
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise ValueError("Prepared forecast requires canonical SHA256 identities")
        if type(self.historical_calls) is not int or self.historical_calls <= 0:
            raise ValueError("Prepared forecast must retain its historical calls")
        for value in (self.cutoff_at, self.historical_acquisition_ms,
                      self.historical_reselection_ms, self.preparation_cpu_ms):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Prepared forecast time/cost must be finite and nonnegative")

    def validate_target(self, space, snapshot, request, environment_episode):
        if environment_episode != self.environment_episode:
            raise ValueError("Prepared forecast does not match the current environment episode")
        if (context_identity(space, snapshot, environment_episode) != self.context_sha256
                or digest(request.to_dict()) != self.request_sha256):
            raise ValueError("Prepared forecast does not match the nominated request/context")


@dataclass(frozen=True)
class AcquisitionPreparationSample:
    sample_id: str
    phase: str
    completed_at: float
    context_sha256: str
    source_receipt_sha256: str
    collection: PlanObservationCollection
    reselection_ms: float


def prepare_acquisition_policy(samples, *, space, snapshot, request, environment_episode,
                               cutoff_at, max_expected_extra_ms):
    """Keep every supplied prior sample; any invalid/failing sample rejects preparation.

    Phase/time and source digests are explicit experiment provenance, not a proof
    that an external caller's labels are truthful. Source receipts must be audited
    by the experiment intake. This function consumes no answers or backend service.
    """
    from xgap.runtime.semantic_acquisition import ProfileForecast, SemanticAcquisitionPolicy
    started = time.perf_counter()
    if (not isinstance(samples, tuple) or not samples
            or any(not isinstance(s, AcquisitionPreparationSample) for s in samples)
            or len({s.sample_id for s in samples}) != len(samples)):
        raise ValueError("Preparation requires unique, nonempty prior samples")
    if (type(cutoff_at) not in (int, float) or not math.isfinite(cutoff_at)
            or cutoff_at < 0 or cutoff_at > time.time()):
        raise ValueError("Preparation cutoff must be a finite timestamp")
    context = context_identity(space, snapshot, environment_episode)
    if request not in space.observation_requests or request.operation is not BackendOperation.PROFILE:
        raise ValueError("Forecast requires a registered profile request in this context")
    catalog = space.observation_catalogs[request.backend_id]
    artifact = catalog.query_artifacts[request.payload["query_id"]]
    expected_provenance = {"backend_id": request.backend_id, "operation": request.operation.value,
        "catalog_id": catalog.catalog_id, "catalog_version": catalog.version,
        "artifact_id": artifact.artifact_id, "artifact_sha256": _artifact_sha256(artifact)}
    records, outcomes, seen_observations = [], [], set()
    for sample in samples:
        if not isinstance(sample.sample_id, str) or not sample.sample_id.strip():
            raise ValueError("Preparation requires typed identified samples")
        if (sample.phase not in ("training", "preparation")
                or type(sample.completed_at) not in (int, float)
                or not math.isfinite(sample.completed_at) or not 0 <= sample.completed_at < cutoff_at):
            raise ValueError("Evaluation/current/future samples cannot prepare a forecast")
        if sample.context_sha256 != context:
            raise ValueError("Preparation sample belongs to another context")
        sha = sample.source_receipt_sha256
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Preparation requires an explicit source receipt SHA256")
        collection = sample.collection
        if (not isinstance(collection, PlanObservationCollection) or not collection.success
                or collection.requests != (request,) or collection.attempted_calls != 1
                or len(collection.snapshot.estimates) != 1):
            raise ValueError("Every sample must retain one successful matching request, without filtering failures")
        result = collection.tool_results[0]
        estimate = RemoteEstimate.from_tool_result(request.observation_key, result)
        if any(result.value.get(k) != v for k, v in expected_provenance.items()):
            raise ValueError("Sample response provenance disagrees with the registered profile request")
        observation = result.value["observation"]
        if (observation.get("success") is not True or observation.get("error") is not None
                or observation.get("backend_id") != request.backend_id
                or observation.get("artifact_id") != artifact.artifact_id):
            raise ValueError("Original observation failed or disagrees with the requested identity")
        start, end = (_timestamp(observation.get(k)) for k in ("started_at", "ended_at"))
        if not 0 <= start <= end <= sample.completed_at:
            raise ValueError("Original observation is not complete before the preparation cutoff")
        observation_identity = digest(result.to_dict())
        if observation_identity in seen_observations:
            raise ValueError("One original observation cannot become multiple preparation samples")
        seen_observations.add(observation_identity)
        if estimate != collection.snapshot.estimates[0] or estimate.backend_id != request.backend_id:
            raise ValueError("Sample estimate disagrees with the original observation")
        for value in (collection.elapsed_ms, sample.reselection_ms):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Preparation costs must be observed finite nonnegative times")
        outcomes.append(ProfileForecast(sample.sample_id, 1 / len(samples), estimate.elapsed_ms,
                                        estimate.row_count, estimate.row_width_bytes))
        records.append({"sample_id": sample.sample_id, "phase": sample.phase,
            "completed_at": sample.completed_at, "source_receipt_sha256": sha,
            "observation_sha256": observation_identity,
            "collection": collection.to_dict(), "reselection_ms": sample.reselection_ms})
    acquisition = math.fsum(s.collection.elapsed_ms for s in samples)
    reselection = math.fsum(s.reselection_ms for s in samples)
    receipt = {"schema": "empirical-exact-request-forecast-v1", "context_sha256": context,
        "request": request.to_dict(), "environment_episode": environment_episode,
        "cutoff_at": cutoff_at, "samples": records, "weights": "uniform_all_supplied_samples",
        "historical_calls": len(samples), "historical_acquisition_ms": acquisition,
        "historical_reselection_ms": reselection, "external_calls": 0,
        "calibration_claim": False, "family_transfer_claim": False}
    identity = digest(receipt)
    target = ForecastTarget(environment_episode, context, digest(request.to_dict()), identity,
        cutoff_at, len(samples), acquisition, reselection, (time.perf_counter()-started)*1000)
    policy = SemanticAcquisitionPolicy(tuple(outcomes), acquisition/len(samples), reselection/len(samples),
        max_expected_extra_ms, "prior exact-request empirical preparation", identity, target=target)
    return policy, {**receipt, "preparation_sha256": identity, "preparation_cpu_ms": target.preparation_cpu_ms}
