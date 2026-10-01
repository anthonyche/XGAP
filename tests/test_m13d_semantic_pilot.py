from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_catalog import GrailQAInferenceCatalog
from xgap.experiments.grailqa_semantic_pilot import (
    FakeSemanticPilotProvider,
    GrailQASemanticPilotSpec,
    OUTPUT_FILES,
    build_inference_request,
    canonical_interpretation,
    reference_supported,
    run_semantic_pilot,
    strict_inference_leakage_audit,
    validate_frozen_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "experiments/specs/grailqa_semantic_pilot_v1.json"

pytestmark = pytest.mark.skipif(
    not (
        (REPO_ROOT / "datasets/grailqa_pilot_v1/dataset.yaml").is_file()
        and (REPO_ROOT / "datasets/grailqa_inference_catalog_v1/entities.jsonl").is_file()
    ),
    reason="external GrailQA pilot and inference-catalog artifacts are not installed",
)


@pytest.fixture(scope="session")
def spec() -> GrailQASemanticPilotSpec:
    return GrailQASemanticPilotSpec.load(SPEC_PATH)


@pytest.fixture(scope="session")
def catalog(spec: GrailQASemanticPilotSpec) -> GrailQAInferenceCatalog:
    value, _ = validate_frozen_artifacts(spec, REPO_ROOT)
    return value


@pytest.fixture(scope="session")
def full_fake_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    output = tmp_path_factory.mktemp("m13d-full-fake")
    result = run_semantic_pilot(
        spec_path=SPEC_PATH,
        output_root=output,
        repo_root=REPO_ROOT,
        dry_run=True,
        resume=False,
    )
    return output, result


def test_inference_catalog_is_reproducible_and_query_independent(
    catalog: GrailQAInferenceCatalog,
) -> None:
    assert catalog.catalog_hash == catalog.recomputed_catalog_hash
    assert catalog.catalog_hash == "b547bf391a2dadf6c5affd205689da325bd4bce31b179b3d0a1f3c6bc4c4d416"
    assert catalog.manifest["counts"] == {
        "entities": 14951,
        "properties": 5531,
        "relations": 13747,
        "reverse_property_entries": 9908,
        "types": 10656,
    }
    assert catalog.manifest["construction"]["gold_inputs"] is False
    assert catalog.manifest["construction"]["query_dependent_inputs"] is False


def test_retrieval_is_deterministic_and_persists_identity(
    catalog: GrailQAInferenceCatalog,
) -> None:
    first = catalog.retrieve("q1", "Which films did Christopher Nolan direct?", top_k=20)
    second = catalog.retrieve("q1", "Which films did Christopher Nolan direct?", top_k=20)
    assert first.to_dict() == second.to_dict()
    assert first.catalog_hash == catalog.catalog_hash
    assert first.question_hash
    assert [item.rank for item in first.relations] == list(range(1, 21))
    assert first.config["llm_used"] is False
    assert first.config["input_fields"] == ["question"]


@pytest.mark.parametrize(
    "field",
    [
        "gold_logical_form",
        "gold_entity_annotation",
        "gold_relation_annotation",
        "gold_answers",
        "reference_interpretation",
        "canonical_gold_plan",
        "Q",
        "A",
    ],
)
def test_gold_leakage_is_rejected_before_provider_use(field: str) -> None:
    with pytest.raises(ValueError, match="Evaluation-only field leaked"):
        strict_inference_leakage_audit(
            {"question_id": "q1", "text": "safe question", field: "injected"}
        )


def test_request_serialization_contains_only_inference_safe_context(
    catalog: GrailQAInferenceCatalog,
) -> None:
    question = {
        "schema_version": "m13d-grailqa-inference-question-v1",
        "question_id": "q1",
        "text": "Which films did Christopher Nolan direct?",
        "split": "dev",
        "source_benchmark_id": "fixture:q1",
    }
    retrieval = catalog.retrieve("q1", question["text"], top_k=20)
    view = catalog.prompt_view(retrieval)
    request = build_inference_request(question, retrieval, view, 3)
    serialized = json.dumps(request.to_dict(), sort_keys=True).casefold()
    assert "gold_logical_form" not in serialized
    assert "reference_interpretation" not in serialized
    assert request.metadata["prompt_schema_view"]["query_slots"]


def test_frozen_spec_and_artifact_hashes(spec: GrailQASemanticPilotSpec) -> None:
    assert len(spec.question_ids) == 150
    assert spec.file_sha256 == "736237ec3293a1b3a86e94e7f2592b36179a6edf97635e07c306ba4c91a9ca48"
    assert spec.freeze_hash == "5aeb1813813ca0c0835e30fa9c92644cf51a25b14480b6aa8b3d7e6938304e28"
    assert spec.data["m_values"] == [1, 3]
    assert spec.data["candidate_cap"] == 3
    validate_frozen_artifacts(spec, REPO_ROOT)




def test_server_artifact_fetch_script_verifies_installed_bundle() -> None:
    script = REPO_ROOT / "scripts/server/fetch_grailqa_m13d_artifacts.sh"
    syntax = subprocess.run(
        ("bash", "-n", str(script)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
    verify = subprocess.run(
        ("bash", str(script), "--verify-only"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "already installed and match" in verify.stdout


def test_server_storage_script_creates_idempotent_data_symlink(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts/server/prepare_xgap_data_storage.sh"
    home = tmp_path / "home" / "tester"
    data_root = tmp_path / "data" / "tester" / "xgap-artifacts"
    link = home / "xgap-data"
    home.mkdir(parents=True)
    environment = {
        **os.environ,
        "HOME": str(home),
        "USER": "tester",
        "XGAP_SERVER_DATA_ROOT": str(data_root),
        "XGAP_DATA_LINK": str(link),
    }

    syntax = subprocess.run(
        ("bash", "-n", str(script)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    for _ in range(2):
        result = subprocess.run(
            ("bash", str(script)),
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    assert link.is_symlink()
    assert os.readlink(link) == str(data_root)
    assert (link / "grailqa-m13d-v1").is_dir()
    assert f"physical_root={data_root}" in result.stdout


def test_reference_equivalence_is_structural_and_variable_insensitive() -> None:
    pattern = {
        "path_var": "p",
        "source": {"var": "x", "label": "film.film", "properties": {}},
        "expr": {
            "kind": "rel",
            "edge": {
                "var": "e",
                "label": "film.film.directed_by",
                "direction": "OUT",
                "properties": {},
            },
        },
        "target": {"var": "y", "label": "people.person", "properties": {}},
        "selector": {"kind": "ALL", "k": None},
        "restrictor": "SIMPLE",
        "condition": None,
        "max_depth": None,
    }
    renamed = json.loads(json.dumps(pattern))
    renamed["path_var"] = "other"
    renamed["source"]["var"] = "answer"
    renamed["expr"]["edge"]["var"] = "edge_1"
    assert canonical_interpretation(pattern) == canonical_interpretation(renamed)
    assert reference_supported(pattern, renamed)
    renamed["expr"]["edge"]["direction"] = "IN"
    assert not reference_supported(pattern, renamed)


def test_full_150_fake_run_writes_contract_and_reuses_candidates(
    full_fake_run: tuple[Path, dict[str, Any]],
) -> None:
    output, result = full_fake_run
    assert result["query_count"] == 150
    assert result["metrics"]["measurement_status"] == "orchestration_only_no_accuracy_claim"
    assert result["metrics"]["generation"]["completed_requests"] == 150
    assert result["metrics"]["generation"]["failed_requests"] == 0
    assert result["metrics"]["generation"]["repair_count"] == 0
    assert result["metrics"]["q_stratified"]["13"]["count"] == 83
    assert result["metrics"]["q_stratified"]["19"]["count"] == 56
    assert result["metrics"]["q_stratified"]["25"]["count"] == 11
    assert all((output / name).exists() for name in OUTPUT_FILES)
    request_rows = _jsonl(output / "llm_requests.jsonl")
    ranking_rows = _jsonl(output / "rankings.jsonl")
    candidate_rows = _jsonl(output / "validated_candidates.jsonl")
    assert len(request_rows) == 150
    assert len(ranking_rows) == 150
    assert len(candidate_rows) == 450
    assert all(len(row["rankings_by_epsilon"]) == 6 for row in ranking_rows)
    assert all(row["candidate_generation_reused"] for row in ranking_rows)
    assert "DASHSCOPE_API_KEY" not in (output / "llm_requests.jsonl").read_text()
    assert "# GrailQA Semantic Pilot Result Summary" in result["summary"]


def test_post_inference_retrieval_metrics_cover_all_k(
    full_fake_run: tuple[Path, dict[str, Any]],
) -> None:
    _, result = full_fake_run
    for kind in ("entity", "relation", "type"):
        assert set(result["metrics"]["retrieval"][kind]) == {
            "recall@1",
            "recall@5",
            "recall@10",
            "recall@20",
        }


def test_resume_does_not_repeat_successful_provider_calls(
    tmp_path: Path,
    spec: GrailQASemanticPilotSpec,
) -> None:
    model = ModelBundle.load(REPO_ROOT / spec.data["model_bundle_root"])

    calls = [0]

    class CountingProvider(FakeSemanticPilotProvider):
        def generate(self, request: Any, prompt_view: Any) -> Any:
            calls[0] += 1
            return super().generate(request, prompt_view)

    provider = CountingProvider(model)
    output = tmp_path / "resume"
    first = run_semantic_pilot(
        spec_path=SPEC_PATH,
        output_root=output,
        repo_root=REPO_ROOT,
        dry_run=True,
        resume=False,
        max_queries=2,
        provider_override=provider,
    )
    assert first["processed_this_invocation"] == 2
    assert calls[0] == 2
    second = run_semantic_pilot(
        spec_path=SPEC_PATH,
        output_root=output,
        repo_root=REPO_ROOT,
        dry_run=True,
        resume=True,
        max_queries=2,
        provider_override=provider,
    )
    assert second["processed_this_invocation"] == 0
    assert second["skipped_on_resume"] == 2
    assert calls[0] == 2


def test_readiness_script_reports_ready_without_persisting_secret(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "PYTHON": sys.executable,
        "PYTHONPATH": "src",
        "DASHSCOPE_API_KEY": "test-only-not-a-real-key",
        "XGAP_ALLOW_DIRTY": "1",
        "XGAP_GRAILQA_READINESS_OUTPUT": str(tmp_path / "readiness"),
    }
    result = subprocess.run(
        ("bash", "scripts/check_grailqa_semantic_pilot_ready.sh"),
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report_text = (tmp_path / "readiness/readiness.json").read_text()
    assert "test-only-not-a-real-key" not in report_text
    assert json.loads(report_text)["ready"] is True


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]
