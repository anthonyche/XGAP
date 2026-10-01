"""Separate offline preparation and NL-only request for a necessary federation.

No gold, prepared semantic program or native target is read by request/preparation.
"""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.toy_semantic import toy_backends
from xgap.experiments.one_shot_toy import load_one_shot_toy_provider
from xgap.experiments.hashing import content_hash
from xgap.llm.candidate_interpretation import OpenAICompatibleCandidateInterpretationProvider
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics, _hash
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.planning.runtime_work_estimator import FrozenWorkEstimator, load_frozen_estimator
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationRequest


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/one_shot_split_v1"
QUERY_ID = "SPLIT-NL-01"
PROFILE = "xgap-one-shot-split-nl-v1"


def load_split_provider(*, mode="performance", disable_thinking=False):
    base = load_one_shot_toy_provider(mode=mode, wire_profile="envelope-schema-v1",
        disable_thinking=disable_thinking)
    appendix = (FIXTURE.parents[1] / "prompts/interpretation/nl_only_identity_v1.txt").read_text()
    prompt = base.system_prompt + "\n" + appendix
    config = replace(base.config, provider_id=base.provider_id + ":nl-only-identity-v1",
        prompt_hash=content_hash(prompt))
    return OpenAICompatibleCandidateInterpretationProvider(config, prompt, base.token_guard, base.transport)


def split_inputs(*, fixture=FIXTURE, mode="performance"):
    """Read frozen deployment inputs. Gold files are outside this dependency path."""
    fixture = Path(fixture)
    manifest = json.loads((fixture / "manifest.json").read_text())
    for name, digest in manifest["inference_files"].items():
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError("Invalid frozen split input path")
        if hashlib.sha256((fixture / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen split input hash mismatch: " + name)
    statistics = FrozenSourceStatistics.from_dict(json.loads((fixture / "statistics.json").read_text()))
    pin = json.loads((fixture / "catalog/manifest.json").read_text())
    bundle = FrozenResolutionBundle.load(fixture / "catalog", expected_bundle_hash=pin["bundle_hash"])
    schema = json.loads((fixture / "source_schema.json").read_text())
    sources = {s.source_id: LogicalSource(s.source_id, s.snapshot_version, (s.backend_id,))
               for s in statistics.entries}
    policy = OneShotPolicy.for_mode(mode)
    # Original natural language plus reusable source schemas; no operator ID or
    # structured hard/output constraint is supplied to the model.
    request = InterpretationRequest((fixture / "question.txt").read_text().strip(), {
        "query_id": QUERY_ID, "source_schema": schema, "one_shot_profile": policy.to_dict(),
        "runtime": {"resolution_bundle": bundle.identity, "sources": {
            name: {"version": s.snapshot_version, "replicas": list(s.replica_backend_ids)}
            for name, s in sources.items()}}})
    backends = toy_backends(json.loads((fixture / "mapping.json").read_text()))
    ns = schema["shared_identity_namespace"]
    backends["fuseki"] = replace(backends["fuseki"], rdf_node_classes=(ns + "Entity",))
    return request, statistics, {"catalog_root": fixture / "catalog", "catalog_hash": bundle.bundle_hash,
        "sources": sources, "backends": backends}, manifest


def prepare_split_deployment(trained_path, output, *, fixture=FIXTURE):
    """Explicit offline freeze only; caller invokes before online request handling."""
    _, statistics, _, manifest = split_inputs(fixture=fixture)
    parent = load_frozen_estimator(trained_path)
    if not isinstance(parent, FrozenWorkEstimator):
        raise ValueError("Split preparation requires the original trained v2 artifact")
    if QUERY_ID in parent.to_dict()["training_provenance"]["training_query_ids"]:
        raise ValueError("Current split request was used as a training query")
    deployment = FrozenWorkDeployment(PROFILE + ":deployment", parent, statistics,
        "fixture-manifest#sha256=" + _hash(manifest))
    deployment.save(output)
    return deployment
