"""Direct NL-to-native-query system baseline for M12-D."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.backends import registry
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.experiments.bundles import DatasetBundle, ModelBundle
from xgap.experiments.contracts import BaselineId, ExperimentSpec
from xgap.experiments.cost_calibration import aggregate_latencies
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import (
    OntologyArtifactLoader,
    OntologyContextRetriever,
    PromptSchemaViewBuilder,
    RetrievalLimits,
    assert_no_gold_leakage,
)
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.llm.openai_compatible import (
    OpenAICompatibleTransport,
    UrllibOpenAICompatibleTransport,
    redact_secrets,
)


@dataclass(frozen=True)
class DirectQueryGeneration:
    backend_id: str
    language: str
    query: str
    request_payload: Mapping[str, Any]
    raw_response: Mapping[str, Any]
    latency_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    @property
    def request_hash(self) -> str:
        return content_hash(self.request_payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "m12d-direct-generation-v1",
            "backend_id": self.backend_id,
            "language": self.language,
            "query": self.query,
            "request_payload": redact_secrets(self.request_payload),
            "request_hash": self.request_hash,
            "raw_response": redact_secrets(self.raw_response),
            "latency_seconds": self.latency_seconds,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            },
        }


@dataclass(frozen=True)
class DirectBaselineRunResult:
    run_root: Path
    status: str
    row_count: int | None
    result_status: str


def build_direct_request(
    *,
    question: str,
    backend_id: str,
    language: str,
    model: ModelBundle,
    prompt: Mapping[str, Any],
    schema: Mapping[str, Any],
    bounded_context: Mapping[str, Any],
) -> dict[str, Any]:
    expected_language = "cypher" if backend_id == "neo4j" else "sparql"
    if language.lower() != expected_language:
        raise ValueError(f"Backend '{backend_id}' requires {expected_language}.")
    user = {
        "question": question,
        "backend_id": backend_id,
        "language": expected_language,
        "bounded_schema_context": dict(bounded_context),
        "structured_output_schema": dict(schema),
        "requirements": {
            "exactly_one_native_query": True,
            "path_pattern_query_forbidden": True,
            "gold_query_forbidden": True,
        },
    }
    assert_no_gold_leakage(user)
    payload: dict[str, Any] = {
        "model": model.config.exact_model_snapshot,
        "messages": [
            {"role": "system", "content": str(prompt["system_prompt"])},
            {
                "role": "user",
                "content": json.dumps(user, sort_keys=True, ensure_ascii=True),
            },
        ],
        "temperature": model.config.temperature,
        "top_p": model.config.top_p,
        "max_tokens": int(model.config.token_limits["output"]),
        "response_format": {"type": "json_object"},
        **dict(model.config.extra_parameters),
    }
    if model.config.seed is not None:
        payload["seed"] = model.config.seed
    return payload


def generate_direct_query(
    *,
    question: str,
    backend_id: str,
    language: str,
    model: ModelBundle,
    prompt: Mapping[str, Any],
    schema: Mapping[str, Any],
    bounded_context: Mapping[str, Any],
    transport: OpenAICompatibleTransport | None = None,
) -> DirectQueryGeneration:
    payload = build_direct_request(
        question=question,
        backend_id=backend_id,
        language=language,
        model=model,
        prompt=prompt,
        schema=schema,
        bounded_context=bounded_context,
    )
    api_key_env = str(model.config.api_key_env)
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"Required API key environment variable '{api_key_env}' is unset.")
    endpoint = str(model.config.base_url).rstrip("/") + "/chat/completions"
    client = transport or UrllibOpenAICompatibleTransport(user_agent="xgap-m12d-direct/1")
    started = time.perf_counter()
    raw = client.post_json(
        url=endpoint,
        api_key=api_key,
        payload=payload,
        timeout_seconds=model.config.timeout_seconds,
    )
    latency = time.perf_counter() - started
    structured = _structured_content(raw)
    expected_language = "cypher" if backend_id == "neo4j" else "sparql"
    if set(structured) != {"language", "query"}:
        raise ValueError("Direct baseline response requires exactly language and query.")
    if str(structured["language"]).lower() != expected_language:
        raise ValueError("Direct baseline response language does not match the backend.")
    query = str(structured["query"]).strip()
    if not query:
        raise ValueError("Direct baseline native query must be non-empty.")
    if any(token in structured for token in ("pattern_query", "candidates")):
        raise ValueError("Direct baseline cannot return XGAP interpretations.")
    usage = raw.get("usage", {}) if isinstance(raw.get("usage"), Mapping) else {}
    return DirectQueryGeneration(
        backend_id=backend_id,
        language=expected_language,
        query=query,
        request_payload=payload,
        raw_response=raw,
        latency_seconds=latency,
        input_tokens=_optional_int(usage.get("prompt_tokens", usage.get("input_tokens"))),
        output_tokens=_optional_int(
            usage.get("completion_tokens", usage.get("output_tokens"))
        ),
        total_tokens=_optional_int(usage.get("total_tokens")),
    )


def run_direct_baseline(
    config_path: str | Path,
    *,
    output_root_override: str | Path | None = None,
    transport_override: OpenAICompatibleTransport | None = None,
    client_override: BackendClient | None = None,
) -> DirectBaselineRunResult:
    repo_root = _repo_root()
    spec = ExperimentSpec.load(_resolve(config_path, repo_root))
    if spec.baseline.baseline_id is not BaselineId.DIRECT_TEXT2GRAPHQUERY:
        raise ValueError("Direct baseline runner requires direct_text2graphquery.")
    backend_id = str(spec.baseline.backend_id)
    dataset = DatasetBundle.load(_resolve(spec.dataset_bundle_ref, repo_root))
    model = ModelBundle.load(_resolve(spec.model_bundle_ref, repo_root))
    if model.config.provider == "mock" and transport_override is None:
        raise ValueError("Direct baseline requires a live provider or injected transport.")
    question = dataset.question(spec.question_ids[0])
    if len(spec.question_ids) != 1:
        raise ValueError("The direct baseline runner executes one task per run.")
    loader = OntologyArtifactLoader.from_dataset(dataset)
    view = PromptSchemaViewBuilder(
        loader,
        OntologyContextRetriever(loader, RetrievalLimits()),
    ).build(
        task_id=f"{spec.run_id}-task-1",
        question=question.text,
        backend_ids=(backend_id,),
    )
    prompt = _load_json(_resolve(str(spec.orchestration["direct_prompt"]), repo_root))
    schema = _load_json(_resolve(str(spec.orchestration["direct_schema"]), repo_root))
    registry.load_descriptors(_resolve(spec.descriptor_dir, repo_root))
    descriptor = registry.get(backend_id)
    generation = generate_direct_query(
        question=question.text,
        backend_id=backend_id,
        language=descriptor.language,
        model=model,
        prompt=prompt,
        schema=schema,
        bounded_context=view.to_dict(),
        transport=transport_override,
    )
    artifact = QueryArtifact(
        artifact_id=f"{spec.run_id}-direct-query",
        language=generation.language,
        text=generation.query,
        kind="native",
    )
    client = client_override or _live_client(backend_id, descriptor)
    reports: list[ExecutionReport] = []
    for _ in range(spec.execution_protocol.warmup_runs):
        client.execute(artifact)
    for _ in range(spec.execution_protocol.measured_repetitions):
        reports.append(client.execute(artifact))
    successful = tuple(
        item
        for item in reports
        if item.success and item.elapsed_ms is not None and item.elapsed_ms > 0
    )
    aggregate = (
        aggregate_latencies(
            [float(item.elapsed_ms) for item in successful if item.elapsed_ms is not None],
            spec.execution_protocol.aggregation_statistic,
        )
        if len(successful) == spec.execution_protocol.measured_repetitions
        else None
    )
    representative = successful[-1] if successful else reports[-1]
    output_root = (
        Path(output_root_override)
        if output_root_override is not None
        else _resolve(spec.output_root, repo_root)
    )
    run_root = output_root / spec.run_id
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"Direct baseline run will not be overwritten: {run_root}")
    (run_root / "results" / "normalized").mkdir(parents=True, exist_ok=True)
    (run_root / "queries").mkdir(parents=True, exist_ok=True)
    _write_json(run_root / "experiment_spec.json", spec.to_dict())
    _write_json(run_root / "direct_request.json", generation.to_dict())
    _write_json(
        run_root / "direct_response.json",
        {"raw_response": redact_secrets(generation.raw_response)},
    )
    (run_root / "queries" / f"direct.{ 'cypher' if generation.language == 'cypher' else 'rq'}").write_text(
        generation.query + "\n", encoding="utf-8"
    )
    result_status = representative.result_status
    _write_json(
        run_root / "results" / "normalized" / "result.json",
        {
            "schema_version": "m12d-direct-result-v1",
            "result_status": result_status,
            "row_count": representative.row_count if representative.success else None,
            "rows": representative.rows,
            "aggregated_latency_ms": aggregate,
            "reports": [item.to_dict() for item in reports],
            "answer_correctness": {
                "status": "not_available",
                "reason": "Execution success or nonempty rows do not establish correctness.",
            },
        },
    )
    status = "complete" if aggregate is not None else "complete_with_execution_error"
    _write_json(
        run_root / "run_summary.json",
        {
            "schema_version": "m12d-direct-summary-v1",
            "run_id": spec.run_id,
            "status": status,
            "method": BaselineId.DIRECT_TEXT2GRAPHQUERY.value,
            "backend_id": backend_id,
            "result_status": result_status,
            "row_count": representative.row_count if representative.success else None,
            "llm_latency_seconds": generation.latency_seconds,
            "backend_latency_ms": aggregate,
        },
    )
    from xgap.experiments.readiness import (
        capture_environment_manifest,
        configured_backend_images,
    )

    _write_json(
        run_root / "server_environment.json",
        capture_environment_manifest(
            repo_root,
            images=configured_backend_images(
                repo_root / "services" / "docker-compose.yml"
            ),
        ),
    )
    return DirectBaselineRunResult(
        run_root,
        status,
        representative.row_count if representative.success else None,
        result_status,
    )


def _live_client(backend_id: str, descriptor: Any) -> BackendClient:
    if os.environ.get("XGAP_RUN_BACKENDS") != "1":
        raise RuntimeError("Direct baseline execution requires XGAP_RUN_BACKENDS=1.")
    if backend_id == "neo4j":
        return Neo4jClient(descriptor)
    if backend_id == "fuseki":
        return FusekiClient(descriptor)
    raise NotImplementedError(f"No direct native client for '{backend_id}'.")


def _structured_content(response: Mapping[str, Any]) -> dict[str, Any]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Direct provider response has no message content.") from error
    if isinstance(content, Mapping):
        return dict(content)
    data = json.loads(str(content))
    if not isinstance(data, Mapping):
        raise ValueError("Direct provider structured response must be an object.")
    return dict(data)


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else repo_root / value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run direct text-to-graph-query baseline.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root")
    args = parser.parse_args()
    result = run_direct_baseline(args.config, output_root_override=args.output_root)
    print(f"Direct baseline status: {result.status}")
    print(f"Result status: {result.result_status}")
    print(f"row_count: {result.row_count}")
    print(f"Artifacts: {result.run_root}")
    return 0 if result.status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
