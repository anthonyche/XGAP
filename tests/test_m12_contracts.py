from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import xgap.experiments.bundles as bundle_module
from xgap.experiments.artifacts import RunArtifactLayout, RUN_FILES
from xgap.experiments.bundles import (
    DatasetBundle,
    FragmentSupport,
    ModelBundle,
    QuestionRecord,
)
from xgap.experiments.contracts import (
    AblationConfig,
    BaselineConfig,
    BaselineId,
    ExecutionProtocol,
    ExperimentMetrics,
    ExperimentSpec,
    GPProtocol,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.semantic import OntologyGraph


def test_financial_risk_dataset_bundle_loads_and_hashes_stably() -> None:
    first = DatasetBundle.load("datasets/financial_risk_dev")
    second = DatasetBundle.load("datasets/financial_risk_dev")

    assert first.dataset_id == "financial_risk_dev"
    assert first.controlled
    assert len(first.questions) == 20
    assert first.bundle_hash == second.bundle_hash
    assert first.to_dict()["root"] not in first.to_hash_dict()
    assert set(first.fragment_support.values()) == set(FragmentSupport)
    assert len(first.gold_alignments or ()) == 3


def test_dataset_bundle_normalizes_yaml_null_optional_mappings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_loader = bundle_module.load_yaml_mapping

    def load_with_yaml_null(path: str | Path) -> dict[str, object]:
        loaded = original_loader(path)
        if Path(path).name == "dataset.yaml":
            loaded["backend_load"] = None
        return loaded

    monkeypatch.setattr(bundle_module, "load_yaml_mapping", load_with_yaml_null)

    bundle = DatasetBundle.load("datasets/financial_risk_dev")

    assert bundle.backend_load == {}


def test_dataset_bundle_rejects_non_mapping_backend_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_loader = bundle_module.load_yaml_mapping

    def load_with_invalid_backend_load(path: str | Path) -> dict[str, object]:
        loaded = original_loader(path)
        if Path(path).name == "dataset.yaml":
            loaded["backend_load"] = []
        return loaded

    monkeypatch.setattr(bundle_module, "load_yaml_mapping", load_with_invalid_backend_load)

    with pytest.raises(ValueError, match="dataset.backend_load must be a mapping"):
        DatasetBundle.load("datasets/financial_risk_dev")


def test_question_record_marks_missing_optional_gold_explicitly() -> None:
    record = QuestionRecord.from_dict(
        {
            "question_id": "external-q1",
            "text": "An external benchmark question",
            "split": "test",
            "source_benchmark_id": "external",
            "fragment_support": "xgap_supported",
            "gold_answers": None,
            "gold_logical_form": None,
        }
    )

    assert record.gold_answers is None
    assert record.gold_logical_form is None
    assert record.unavailable_fields == ("gold_answers", "gold_logical_form")


def test_dataset_bundle_allows_missing_optional_gold_alignment_file(tmp_path: Path) -> None:
    source = Path("datasets/financial_risk_dev")
    target = tmp_path / "bundle"
    shutil.copytree(source, target)
    metadata = (target / "dataset.yaml").read_text(encoding="utf-8")
    metadata = metadata.replace("  gold_alignments: gold_alignments.jsonl", "  gold_alignments: null")
    metadata = metadata.replace(
        "../../examples/financial_risk/load_neo4j.cypher",
        str(Path("examples/financial_risk/load_neo4j.cypher").resolve()),
    )
    metadata = metadata.replace(
        "../../examples/financial_risk/load_fuseki.ttl",
        str(Path("examples/financial_risk/load_fuseki.ttl").resolve()),
    )
    (target / "dataset.yaml").write_text(metadata, encoding="utf-8")

    bundle = DatasetBundle.load(target)

    assert bundle.gold_alignments is None
    assert "gold_alignments" in bundle.unavailable_artifacts


def test_ontology_validation_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="acyclic"):
        OntologyGraph(
            ontology_id="cycle",
            version="1",
            classes=("A", "B"),
            relations=(),
            properties=(),
            parents={"A": ("B",), "B": ("A",)},
            max_relaxation_hops=2,
        )


def test_model_bundle_validates_prompt_hash(tmp_path: Path) -> None:
    bundle = ModelBundle.load("models/mock_path_pattern_dev")
    assert bundle.config.provider == "mock"
    assert bundle.prompt.prompt_hash == bundle.config.prompt_hash

    shutil.copytree("models/mock_path_pattern_dev", tmp_path / "model")
    prompt_path = tmp_path / "model" / "prompt.json"
    prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
    prompt["system_prompt"] = "tampered"
    prompt_path.write_text(json.dumps(prompt), encoding="utf-8")
    with pytest.raises(ValueError, match="prompt_hash"):
        ModelBundle.load(tmp_path / "model")


def test_experiment_spec_gp_baseline_and_ablation_contracts() -> None:
    spec = ExperimentSpec.load("experiments/configs/financial_risk_xgap_dev.json")
    protocol = GPProtocol.from_dict(spec.gp_protocol.to_dict())

    assert protocol == spec.gp_protocol
    assert protocol.target == "log_execution_cost"
    assert protocol.freeze_hyperparameters_during_evaluation
    assert protocol.update_posterior_between_tasks
    assert not protocol.update_within_task
    assert spec.baseline.baseline_id is BaselineId.FULL_XGAP
    assert set(BaselineId) == {
        BaselineId.FULL_XGAP,
        BaselineId.RANDOM_FEASIBLE,
        BaselineId.MEAN_ONLY,
        BaselineId.NO_PRUNING,
        BaselineId.NO_ONLINE_UPDATE,
        BaselineId.SINGLE_BACKEND,
        BaselineId.EXHAUSTIVE_ORACLE,
        BaselineId.DIRECT_TEXT2GRAPHQUERY,
    }
    assert set(AblationConfig.__dataclass_fields__) == {
        "no_uncertainty",
        "no_pruning",
        "no_online_learning",
        "no_semantic_bound",
        "cost_only",
        "no_nash",
    }
    with pytest.raises(ValueError, match="epsilon"):
        replace(spec, epsilon=0.33)
    with pytest.raises(ValueError, match="Unknown ablation"):
        AblationConfig.from_dict({"future_switch": True})


def test_direct_text_baseline_has_a_strict_boundary() -> None:
    direct = BaselineConfig(
        BaselineId.DIRECT_TEXT2GRAPHQUERY,
        backend_id="neo4j",
        model_bundle_ref="models/mock_path_pattern_dev",
    )
    assert direct.to_dict()["id"] == "direct_text2graphquery"
    with pytest.raises(ValueError, match="backend_id"):
        BaselineConfig(BaselineId.DIRECT_TEXT2GRAPHQUERY)


def test_metrics_execution_protocol_and_hash_serialization() -> None:
    metrics = ExperimentMetrics.unavailable("not measured")
    parsed = ExperimentMetrics.from_dict(metrics.to_dict())
    protocol = ExecutionProtocol()

    assert parsed.to_dict() == metrics.to_dict()
    assert protocol.measured_repetitions == 5
    assert ExecutionProtocol.from_dict(protocol.to_dict()) == protocol
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


def test_run_layout_creates_frozen_tree_and_rejects_overwrite(tmp_path: Path) -> None:
    layout = RunArtifactLayout.create(tmp_path, "run-1")

    assert all((layout.root / path).exists() for path in RUN_FILES if path.endswith(".jsonl"))
    assert (layout.root / "plans/logical").is_dir()
    assert (layout.root / "results/normalized").is_dir()
    with pytest.raises(FileExistsError):
        RunArtifactLayout.create(tmp_path, "run-1")
