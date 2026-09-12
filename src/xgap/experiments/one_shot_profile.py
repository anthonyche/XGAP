"""Caller-pinned dataset/endpoint contracts; file reads only, no preparation."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.compilers.rdf_encoding import RdfEdgeEncoding, RdfResourceTripleEncoding
from xgap.experiments.external_toy_interpretation import BoundedExternalChatTransport
from xgap.experiments.one_shot_toy import OneShotChatRequestGuard
from xgap.experiments.hashing import content_hash
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.candidate_interpretation import (CandidateInterpretationProviderConfig,
    OpenAICompatibleCandidateInterpretationProvider, candidate_interpretation_schema, WIRE_PROFILES)
from xgap.llm.compact_interpretation import (CompactInterpretationProviderConfig,
    OpenAICompatibleCompactInterpretationProvider, WIRE_PROFILE as COMPACT_WIRE)
from xgap.semantic.compact_query import compact_schema
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationRequest


SCHEMA = "xgap-frozen-one-shot-profile-v1"
REQUEST_SCHEMA = "xgap-one-shot-evaluation-request-v1"
MAX_BYTES = 16 * 1024 * 1024


def _fields(raw, required, optional=()):
    if not isinstance(raw, dict) or set(raw)-set(required)-set(optional) or not set(required)<=set(raw):
        raise ValueError("Invalid frozen contract fields")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty contract text")
    return value


def _env(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Credential references must be environment-variable names")
    return value


def _url(value):
    parsed = urlsplit(_text(value))
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("Endpoint must be HTTP(S) without inline credentials/query/fragment")
    parsed.port
    return value.rstrip("/")


def read_pinned(path, sha256):
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("An exact SHA-256 is required")
    with Path(path).open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("Frozen file size/hash mismatch")
    return data


def _file(root, ref):
    _fields(ref, ("path", "sha256"))
    return read_pinned(root / _text(ref["path"]), ref["sha256"])


def _backend(raw, backend_id):
    _fields(raw, ("resource_namespace",), ("backend_id", "identity_property", "backend_mapping",
        "rdf_edge_encoding", "rdf_node_classes", "profile", "rdf_resource_encoding"))
    values = dict(raw)
    if values.pop("backend_id", backend_id) != backend_id:
        raise ValueError("Semantic backend identity mismatch")
    for name, kind in (("rdf_edge_encoding", RdfEdgeEncoding), ("rdf_resource_encoding", RdfResourceTripleEncoding)):
        if values.get(name) is not None:
            values[name] = kind(**values[name])
    if values.get("profile") is not None:
        values["profile"] = BackendCapabilityProfile.from_dict(values["profile"])
    if "rdf_node_classes" in values:
        values["rdf_node_classes"] = tuple(values["rdf_node_classes"])
    return SemanticBackend(backend_id, **values)


def _client_spec(raw):
    _fields(raw, ("engine", "url", "database", "timeout_seconds", "auth"))
    if raw["engine"] not in {"neo4j", "fuseki"}:
        raise ValueError("No native client registered for this engine")
    _url(raw["url"])
    if not isinstance(raw["database"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", raw["database"]):
        raise ValueError("Invalid endpoint database name")
    timeout = raw["timeout_seconds"]
    if type(timeout) not in (float, int) or not 0 < timeout <= 120:
        raise ValueError("Native timeout must be in (0,120]")
    if raw["auth"] is not None:
        if raw["engine"] != "neo4j":
            raise ValueError("This Fuseki adapter has no credential contract")
        _fields(raw["auth"], ("user_env", "password_env"))
        for value in raw["auth"].values(): _env(value)
    return dict(raw)


def _provider(root, raw, policy):
    _fields(raw, ("provider_id", "base_url", "model", "api_key_env", "wire_profile", "prompt",
        "temperature", "top_p", "max_tokens", "timeout_seconds", "disable_thinking"))
    prompt = _file(root, raw["prompt"]).decode("utf-8")
    if type(raw["disable_thinking"]) is not bool or not 0 < raw["timeout_seconds"] <= 120:
        raise ValueError("Provider timeout/thinking contract invalid")
    if raw['wire_profile'] == COMPACT_WIRE:
        output, schema_options = 'json_schema', {}
        schema = compact_schema(policy.candidate_cap)
        config_type, provider_type = CompactInterpretationProviderConfig, OpenAICompatibleCompactInterpretationProvider
    else:
        output, schema_profile = WIRE_PROFILES[raw["wire_profile"]]
        schema_options = {'schema_profile': schema_profile}
        schema = candidate_interpretation_schema(policy.candidate_cap, schema_profile=schema_profile)
        config_type, provider_type = CandidateInterpretationProviderConfig, OpenAICompatibleCandidateInterpretationProvider
    config = config_type(provider_id=_text(raw["provider_id"]),
        base_url=_url(raw["base_url"]), api_key_env=_env(raw["api_key_env"]), model=_text(raw["model"]),
        temperature=raw["temperature"], top_p=raw["top_p"], max_tokens=raw["max_tokens"],
        candidate_cap=policy.candidate_cap, timeout_seconds=raw["timeout_seconds"],
        structured_output_mode=output, structured_schema=schema, **schema_options,
        prompt_hash=content_hash(prompt), max_repair_calls=0,
        extra_parameters={"chat_template_kwargs":{"enable_thinking":False}} if raw["disable_thinking"] else {})
    # The existing transport/guard are dataset-independent despite their legacy
    # module names; neither helper reads a toy request or any fixture.
    return provider_type(config, prompt,
        OneShotChatRequestGuard(config.model, output_limit=config.max_tokens), BoundedExternalChatTransport())


@dataclass(frozen=True)
class FrozenOneShotProfile:
    root: Path
    sha256: str
    document_json: str

    @classmethod
    def load(cls, path, *, expected_sha256):
        data = read_pinned(path, expected_sha256)
        profile = cls(Path(path).resolve().parent, expected_sha256, data.decode("utf-8"))
        profile.materialize()  # Validate every mode/source before any external action.
        return profile

    def materialize(self):
        raw = json.loads(self.document_json)
        _fields(raw, ("schema_version", "profile_id", "dataset", "source_schema", "sources", "backends",
            "catalog", "estimator", "modes", "offline"))
        if raw["schema_version"] != SCHEMA:
            raise ValueError("Unsupported frozen profile")
        _text(raw["profile_id"])
        _fields(raw["dataset"], ("dataset_id", "version"))
        for value in raw["dataset"].values(): _text(value)
        if not isinstance(raw["source_schema"], dict) or not isinstance(raw["offline"], dict):
            raise ValueError("Dataset schema/offline provenance must be objects")
        _fields(raw["catalog"], ("path", "bundle_hash"))
        catalog_root = self.root / _text(raw["catalog"]["path"])
        bundle = FrozenResolutionBundle.load(catalog_root, expected_bundle_hash=raw["catalog"]["bundle_hash"])
        estimator = frozen_estimator_from_dict(json.loads(_file(self.root, raw["estimator"])))
        if not isinstance(raw["sources"], dict) or not 1 <= len(raw["sources"]) <= 64:
            raise ValueError("Profile requires 1..64 declared sources")
        if not isinstance(raw["backends"], dict) or not 1 <= len(raw["backends"]) <= 64:
            raise ValueError("Profile requires 1..64 backend configurations")
        sources, backends, clients, identities = {}, {}, {}, {}
        for key, spec in raw["backends"].items():
            _text(key); _fields(spec, ("semantic", "client"))
            backends[key], clients[key] = _backend(spec["semantic"], key), _client_spec(spec["client"])
        for key, spec in raw["sources"].items():
            _fields(spec, ("version", "replicas")); _text(key); _text(spec["version"])
            if not isinstance(spec["replicas"], list) or not spec["replicas"]:
                raise ValueError("Logical sources require an explicit replica list")
            source = LogicalSource(key, spec["version"], tuple(spec["replicas"]))
            for backend in source.replica_backend_ids:
                if backend not in backends or backend in identities:
                    raise ValueError("Each backend must declare exactly one known logical source")
                identities[backend] = (key, source.snapshot_version)
            if len({backends[b].resource_namespace for b in source.replica_backend_ids}) != 1:
                raise ValueError("Replica identity namespace mismatch")
            sources[key] = source
        if (set(identities) != set(backends) or identities != {
                s.backend_id:(s.source_id,s.snapshot_version) for s in estimator.statistics.entries}):
            raise ValueError("Frozen estimator/source identities mismatch before interpretation")
        if not isinstance(raw["modes"], dict) or set(raw["modes"]) != {"precision", "performance"}:
            raise ValueError("Both one-shot modes must be frozen explicitly")
        modes = {}
        for name, spec in raw["modes"].items():
            _fields(spec, ("policy", "provider"))
            policy = OneShotPolicy(**spec["policy"])
            if policy.mode != name: raise ValueError("Mode/policy identity mismatch")
            modes[name] = (policy, _provider(self.root, spec["provider"], policy))
        return raw, estimator, bundle, sources, backends, clients, modes

    def request(self, raw, mode, materialized=None):
        _fields(raw, ("schema_version", "question_id", "question", "population", "exposure"),
            ("required_constraints", "requested_output"))
        if raw["schema_version"] != REQUEST_SCHEMA: raise ValueError("Unsupported request schema")
        for key in ("question_id", "question", "population", "exposure"): _text(raw[key])
        doc, _, bundle, sources, _, _, modes = materialized or self.materialize()
        policy, _ = modes[mode]
        context = {"query_id":raw["question_id"], "source_schema":doc["source_schema"],
            "one_shot_profile":policy.to_dict(), "runtime":{"resolution_bundle":bundle.identity,
                "sources":{key:{"version":s.snapshot_version,"replicas":list(s.replica_backend_ids)} for key,s in sources.items()}}}
        if "requested_output" in raw: context["requested_output"] = raw["requested_output"]
        return InterpretationRequest(raw["question"], context, tuple(raw.get("required_constraints", ())))


def native_clients(specs):
    """Instantiate existing plugins from pinned endpoints; no health or query calls."""
    import os
    result = {}
    for backend, spec in specs.items():
        neo = spec["engine"] == "neo4j"
        descriptor = BackendDescriptor(backend, spec["engine"], "cypher" if neo else "sparql",
            "property_graph" if neo else "rdf", runtime={"timeout_seconds":spec["timeout_seconds"]})
        client = Neo4jClient(descriptor) if neo else FusekiClient(descriptor)
        if neo:
            client.http_url, client.database = spec["url"].rstrip("/"), spec["database"]
            client.user = client.password = ""
            if spec["auth"] is not None:
                auth = spec["auth"]
                if any(not os.environ.get(name) for name in auth.values()):
                    raise ValueError("Required native credential environment variable is unset")
                client.user, client.password = os.environ[auth["user_env"]], os.environ[auth["password_env"]]
        else:
            client.base_url, client.dataset = spec["url"].rstrip("/"), spec["database"]
        result[backend] = client
    return result
