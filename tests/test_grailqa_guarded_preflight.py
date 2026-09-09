"""Offline runner lifecycle tests; synthetic outcomes make no quality claim."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import runpy
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import xgap.experiments.grailqa_guarded_preflight as runner
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_candidate_grounding import LEGACY_GROUNDING_POLICY, STRICT_GROUNDING_POLICY
from xgap.experiments.cwru_vllm import CWRUVLLMContract, RUN_ENVIRONMENT_SCHEMA_VERSION
from xgap.experiments.grailqa_guarded_provider import QueryEventJournal
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider


ROOT = Path(__file__).resolve().parents[1]
SPEC = Path("experiments/specs/grailqa_semantic_preflight_output_contract_v1_cwru_qwen3_32b.json")
CWRU_FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e2_cwru_vllm.py"))


def _json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _freeze(path: Path, data) -> None:
    data["freeze_hash"] = content_hash({key: value for key, value in data.items() if key != "freeze_hash"})
    _json(path, data)


def test_new_spec_changes_only_identity_and_explicit_grounding_policy():
    from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec

    old = GrailQAPreflightSpec.load(ROOT / SPEC)
    new = GrailQAPreflightSpec.load(ROOT / "experiments/specs/grailqa_semantic_preflight_canonical_grounding_v1_cwru_qwen3_32b.json")
    changed = {key for key in old.data.keys() | new.data.keys() if old.data.get(key) != new.data.get(key)}
    assert changed == {"experiment_id", "run_id_prefix", "freeze_hash", "candidate_grounding_policy"}
    assert new.data["candidate_grounding_policy"] == STRICT_GROUNDING_POLICY
    assert new.data["full_150_run_permitted"] is False


@pytest.fixture
def case(monkeypatch, tmp_path):
    # Only temporary copies are edited; the new real model bundle and deployment
    # contract are loaded by the actual runner, without a model or service.
    repo = (tmp_path / "repo").resolve()
    spec_data = json.loads((ROOT / SPEC).read_text())
    spec_data["question_ids"] = spec_data["question_ids"][:15]
    spec_data["selection"] = {"size": 15, "policy": "synthetic_test_only", "model_outcomes_used": False}
    spec_path = repo / "experiments/specs/synthetic_guarded_preflight.json"
    _freeze(spec_path, spec_data)
    for relative in (spec_data["model_bundle_root"],):
        shutil.copytree(ROOT / relative, repo / relative)
    contract_path = repo / spec_data["deployment_contract"]
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / spec_data["deployment_contract"], contract_path)
    pilot = repo / spec_data["pilot_root"]
    pilot.mkdir(parents=True)
    questions = [{"question_id": qid, "text": "Synthetic fixture question"} for qid in spec_data["question_ids"]]
    (pilot / "inference_questions.jsonl").write_text(
        "".join(json.dumps(question) + "\n" for question in reversed(questions)), encoding="utf-8"
    )
    environment_path = repo / "runtime-environment.json"
    environment = {"schema_version": RUN_ENVIRONMENT_SCHEMA_VERSION, "secrets_persisted": False}
    _json(environment_path, environment)
    output = repo / "runs/guarded-development"
    revision = "a" * 40
    snapshot = (tmp_path / "tokenizer/snapshots" / revision).resolve()
    snapshot.mkdir(parents=True)
    monkeypatch.setenv("XGAP_LLM_API_KEY", "offline-guarded-runner-fixture")
    monkeypatch.delenv("XGAP_LLM_MODEL", raising=False)
    monkeypatch.delenv("XGAP_LLM_BASE_URL", raising=False)
    readiness = Mock(return_value={
        "ready": True,
        "catalog_root": str(repo / spec_data["catalog_root"]),
        "reachability_root": str(repo / spec_data["reachability_root"]),
    })
    environment_validation = Mock(return_value={
        "schema_version": "synthetic-environment-binding", "success": True,
        "remote_serving_parity_verified": False, "paper_result": False,
    })
    counter = SimpleNamespace(
        identity={"schema_version": "synthetic-tokenizer", "snapshot_revision": revision,
                  "remote_serving_parity_verified": False},
        count_payload_tokens=Mock(return_value=100),
    )
    tokenizer = Mock(return_value=counter)
    model_load = Mock(wraps=ModelBundle.load)
    contract_load = Mock(wraps=CWRUVLLMContract.load)
    monkeypatch.setattr(runner, "ModelBundle", SimpleNamespace(load=model_load))
    monkeypatch.setattr(runner, "CWRUVLLMContract", SimpleNamespace(load=contract_load))
    monkeypatch.setattr(runner, "preflight_readiness", readiness)
    monkeypatch.setattr(runner, "validate_guarded_environment", environment_validation)
    monkeypatch.setattr(runner, "LocalPinnedChatTokenizer", tokenizer)
    monkeypatch.setattr(runner, "GrailQAInferenceCatalogV2", SimpleNamespace(load=Mock(return_value=SimpleNamespace(
        catalog_hash="c" * 64, ontology=SimpleNamespace(max_relaxation_hops=2),
    ))))
    monkeypatch.setattr(runner, "DirectionalOntologyDeviation", Mock(return_value=object()))
    state = SimpleNamespace(
        repo=repo, output=output, spec=spec_data, spec_path=spec_path, questions=questions,
        readiness=readiness, environment_validation=environment_validation,
        tokenizer=tokenizer, counter=counter, model_load=model_load, contract_load=contract_load,
        environment_path=environment_path, providers=[], inference_order=[], completed=[],
        manifest_snapshots=[], fatal_index=None, transport_calls=[],
    )

    class InspectingJournal(QueryEventJournal):
        def append(self, event):
            if event.get("event") == "query_inference_completed":
                saved = _rows(output / "query_states.jsonl")
                assert saved[-1]["question"]["question_id"] == event["question_id"]
                assert content_hash(saved[-1]) == event["state_sha256"]
                state.completed.append(event["question_id"])
            super().append(event)

    monkeypatch.setattr(runner, "QueryEventJournal", InspectingJournal)

    class OfflineTransport:
        def post_json(self, **kwargs):
            # A model attempt is permitted only after the real journal has
            # durably published its corresponding token check.
            check_event, attempt_event = _rows(output / "query_events.jsonl")[-2:]
            assert check_event["event"] == "token_check"
            assert attempt_event["event"] == "transport_attempt"
            assert check_event["question_id"] == attempt_event["question_id"]
            assert check_event["check"]["payload_sha256"] == attempt_event["payload_sha256"] == content_hash(kwargs["payload"])
            state.transport_calls.append(copy.deepcopy(kwargs))
            return CWRU_FIXTURES["_provider_response"]()

    def build_provider(model, *, transport_override, **kwargs):
        assert isinstance(transport_override, runner.LoopbackInferenceTransport)
        return build_openai_compatible_provider(model, OfflineTransport(), **kwargs)

    state.base_factory = Mock(side_effect=build_provider)
    monkeypatch.setattr(runner, "build_openai_compatible_provider", state.base_factory)

    def infer(**kwargs):
        index = len(state.inference_order)
        question, provider = kwargs["question"], kwargs["provider"]
        qid = question["question_id"]
        assert qid == questions[index]["question_id"]
        assert len(_rows(output / "query_states.jsonl")) == index
        assert not (output / "metrics.json").exists()
        state.manifest_snapshots.append((output / "run_manifest.json").read_bytes())
        assert state.manifest_snapshots[-1] == state.manifest_snapshots[0]
        assert kwargs["response_parser"] is parse_normalized_planner_response
        assert (kwargs["retrieval_k"], kwargs["candidate_cap"], kwargs["prompt_candidates_per_slot"]) == (20, 3, 4)
        assert provider.token_check_records == ()
        assert provider.last_invocation is None
        state.inference_order.append(qid)
        state.providers.append(provider)
        if state.fatal_index == index:
            raise RuntimeError("synthetic-sensitive-failure-text")
        result = None
        if index in {0, 2}:
            request = CWRU_FIXTURES["_planner_request"]()
            request = replace(request, metadata={**request.metadata, "task_id": qid})
            result = provider.generate(request, None)
        return {
            "question": question, "retrieval": {"question_id": qid, "synthetic": True},
            "request_records": list(result.request_records) if result else [],
            "response_record": result.response_record if result else None,
            "api_call_completed": bool(result and result.api_call_completed),
            "candidates": [], "semantic_scores": [],
            "failure": {"question_id": qid, "category": "synthetic_no_valid_candidate"},
        }

    def evaluate(states, loaded_spec, actual_repo, actual_readiness, **kwargs):
        assert len(states) == len(_rows(output / "query_states.jsonl")) == 15
        assert len(state.completed) == 15
        assert _rows(output / "query_events.jsonl")[-1]["event"] == "inference_complete"
        assert actual_repo == repo
        assert loaded_spec.data == spec_data
        assert actual_readiness == readiness.return_value
        policy = spec_data.get("candidate_grounding_policy", LEGACY_GROUNDING_POLICY)
        assert kwargs == ({"grounding_policy": policy} if policy != LEGACY_GROUNDING_POLICY else {})
        return {
            "candidates": [], "components": [], "semantic": [],
            "failures": [item["failure"] for item in states],
            "metrics": {"question_count": 15, "candidate_bearing_query_count": 0},
            **({"rejected_candidates": []} if policy != LEGACY_GROUNDING_POLICY else {}),
        }

    state.infer = Mock(side_effect=infer)
    state.evaluate = Mock(side_effect=evaluate)
    monkeypatch.setattr(runner, "_infer_one", state.infer)
    monkeypatch.setattr(runner, "_evaluate_preflight", state.evaluate)
    state.kwargs = {
        "spec_path": spec_path, "repo_root": repo, "output_root": output,
        "run_environment_path": environment_path, "tokenizer_snapshot": snapshot,
        "tokenizer_revision": revision, "expected_runner_commit": "b" * 40,
        "execute_development_spec_sha256": spec_data["freeze_hash"],
        "allow_unverified_serving_tokenizer": True,
    }
    return state


def test_explicit_policy_is_bound_before_sends_and_reaches_inference_evaluation(case):
    case.spec["candidate_grounding_policy"] = STRICT_GROUNDING_POLICY
    _freeze(case.spec_path, case.spec)
    runner.run_guarded_preflight(**{**case.kwargs, "execute_development_spec_sha256": case.spec["freeze_hash"]})
    assert all(call.kwargs["grounding_policy"] == STRICT_GROUNDING_POLICY for call in case.infer.call_args_list)
    for name in ("run_manifest.json", "run_status.json"):
        result = json.loads((case.output / name).read_text())
        assert result["candidate_grounding_policy"] == STRICT_GROUNDING_POLICY
        assert result["schema_version"] == "grailqa-guarded-canonical-grounding-preflight-v1"
        assert result["paper_result"] is False
    assert (case.output / "rejected_candidates.jsonl").read_text() == ""
    assert len(case.transport_calls) == 2  # Unchanged fixture sends; no grounding repair.


@pytest.mark.parametrize("value", [None, "typo", {}, True])
def test_unknown_frozen_grounding_policy_is_not_silently_ignored(case, value):
    case.spec["candidate_grounding_policy"] = value
    _freeze(case.spec_path, case.spec)
    with pytest.raises(ValueError, match="grounding policy"):
        runner.run_guarded_preflight(**{**case.kwargs, "execute_development_spec_sha256": case.spec["freeze_hash"]})
    case.base_factory.assert_not_called()
    case.tokenizer.assert_not_called()
    case.readiness.assert_not_called()
    assert not case.output.exists()


def test_runner_completes_protocol_with_zero_valid_candidates_and_sequential_evidence(case) -> None:
    result = runner.run_guarded_preflight(**case.kwargs)

    assert result == {
        "status": "completed", "output_root": str(case.output), "paper_result": False,
        "metrics": {"question_count": 15, "candidate_bearing_query_count": 0},
    }
    assert case.inference_order == case.spec["question_ids"] == case.completed
    assert len({id(provider) for provider in case.providers}) == 15
    case.model_load.assert_called_once()
    case.contract_load.assert_called_once()
    case.base_factory.assert_called_once()
    case.tokenizer.assert_called_once()
    case.environment_validation.assert_called_once()
    case.evaluate.assert_called_once()
    assert case.readiness.call_args.kwargs == {"require_credentials": True}
    checks = _rows(case.output / "token_checks.jsonl")
    diagnostics = _rows(case.output / "guard_diagnostics.jsonl")
    assert [row["question_id"] for row in checks] == [case.spec["question_ids"][i] for i in (0, 2)]
    assert [row["question_id"] for row in diagnostics] == case.spec["question_ids"]
    assert diagnostics[1]["token_check_count"] == diagnostics[1]["actual_attempted_provider_calls"] == 0
    assert diagnostics[1]["provider_invoked"] is False
    assert diagnostics[1]["details"] == {}
    assert len(case.transport_calls) == len(_rows(case.output / "llm_requests.jsonl")) == 2
    assert len(_rows(case.output / "llm_responses.jsonl")) == 2
    assert len(_rows(case.output / "failures.jsonl")) == 15
    manifest = json.loads((case.output / "run_manifest.json").read_text())
    status = json.loads((case.output / "run_status.json").read_text())
    assert (case.output / "run_manifest.json").read_bytes() == case.manifest_snapshots[0]
    assert manifest["schema_version"] == "grailqa-guarded-development-preflight-v2"
    assert manifest["maximum_provider_calls"] == 30
    assert manifest["maximum_schema_repair_calls_per_query"] == 1
    assert manifest["claim_boundary"]["completion_means_protocol_completed_not_semantic_success"] is True
    assert manifest["claim_boundary"]["remote_serving_parity_verified"] is False
    assert manifest["automatic_retries"] == 0
    assert status["status"] == "completed" and status["paper_result"] is False
    assert status["actual_attempted_provider_calls"] == status["token_check_count"] == 2
    assert _rows(case.output / "query_events.jsonl")[-1]["event"] == "run_completed"
    for name in ("validated_candidates", "component_match", "semantic_scores"):
        assert _rows(case.output / f"{name}.jsonl") == []


def test_fatal_query_preserves_completed_prefix_without_evaluation_or_false_call_total(case) -> None:
    case.fatal_index = 2
    with pytest.raises(RuntimeError, match="synthetic-sensitive"):
        runner.run_guarded_preflight(**case.kwargs)

    case.evaluate.assert_not_called()
    assert [row["question"]["question_id"] for row in _rows(case.output / "query_states.jsonl")] == case.spec["question_ids"][:2]
    events = _rows(case.output / "query_events.jsonl")
    assert [row["question_id"] for row in events if row["event"] == "query_inference_completed"] == case.spec["question_ids"][:2]
    assert events[-1] == {"event": "query_started", "question_id": case.spec["question_ids"][2], "query_index": 3}
    assert len(case.transport_calls) == 1
    status = json.loads((case.output / "run_status.json").read_text())
    assert status["status"] == "incomplete"
    assert status["completed_inference_query_count"] == 2
    assert status["actual_attempted_provider_calls"] is None
    assert status["call_accounting_complete"] is False
    assert status["error_type"] == "RuntimeError"
    assert status["automatic_resume"] is False and status["paper_result"] is False
    assert "synthetic-sensitive" not in json.dumps(status)
    assert (case.output / "run_manifest.json").read_bytes() == case.manifest_snapshots[0]
    assert not (case.output / "metrics.json").exists()
    assert not (case.output / "token_checks.jsonl").exists()


@pytest.mark.parametrize("reason", ["parity", "wrong-freeze", "readiness"])
def test_startup_refusal_precedes_provider_and_tokenizer_construction(case, reason) -> None:
    kwargs = dict(case.kwargs)
    if reason == "parity":
        kwargs.pop("allow_unverified_serving_tokenizer")
    elif reason == "wrong-freeze":
        kwargs["execute_development_spec_sha256"] = "0" * 64
    else:
        case.readiness.return_value["ready"] = False
    with pytest.raises(ValueError):
        runner.run_guarded_preflight(**kwargs)
    case.base_factory.assert_not_called()
    case.model_load.assert_not_called()
    case.tokenizer.assert_not_called()
    case.infer.assert_not_called()
    assert not case.output.exists()
    assert case.transport_calls == []


@pytest.mark.parametrize("field", ["backend_execution", "gold_exposed_to_inference", "full_150_run_permitted"])
def test_development_boundary_flags_fail_closed_before_startup(case, field) -> None:
    changed = copy.deepcopy(case.spec)
    changed[field] = True
    _freeze(case.spec_path, changed)
    kwargs = {**case.kwargs, "execute_development_spec_sha256": changed["freeze_hash"]}
    with pytest.raises(ValueError, match="development preflight"):
        runner.run_guarded_preflight(**kwargs)
    case.base_factory.assert_not_called()
    case.tokenizer.assert_not_called()
    assert not case.output.exists()


@pytest.mark.parametrize("corruption", ["json", "binding", "symlink"])
def test_invalid_environment_stops_before_tokenizer_or_any_send(case, corruption) -> None:
    if corruption == "json":
        case.environment_path.write_text("not-json")
    elif corruption == "binding":
        case.environment_validation.side_effect = ValueError("synthetic_runtime_binding_mismatch")
    else:
        target = case.environment_path.with_name("symlink-target.json")
        case.environment_path.rename(target)
        case.environment_path.symlink_to(target)
    with pytest.raises(ValueError):
        runner.run_guarded_preflight(**case.kwargs)
    case.tokenizer.assert_not_called()
    case.infer.assert_not_called()
    assert not case.output.exists()
    assert case.transport_calls == []


@pytest.mark.parametrize("target", ["existing", "protected-data", "protected-source", "symlink", "ancestor-symlink"])
def test_output_is_exclusive_and_cannot_alias_or_enter_inputs(case, target) -> None:
    if target == "existing":
        output = case.output
        output.mkdir(parents=True)
        (output / "keep.txt").write_text("pre-existing evidence")
    elif target == "protected-data":
        output = case.repo / "datasets/forbidden-output"
    elif target == "protected-source":
        output = case.repo / "scripts/forbidden-output"
    else:
        real_parent = case.repo.parent / "real-output-parent"
        real_parent.mkdir()
        alias = case.repo.parent / "output-alias"
        alias.symlink_to(real_parent, target_is_directory=True)
        output = alias if target == "symlink" else alias / "new-run"
    before = case.spec_path.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        runner.run_guarded_preflight(**{**case.kwargs, "output_root": output})
    case.base_factory.assert_not_called()
    case.tokenizer.assert_not_called()
    assert case.spec_path.read_bytes() == before
    if target == "existing":
        assert sorted(path.name for path in output.iterdir()) == ["keep.txt"]
        assert (output / "keep.txt").read_text() == "pre-existing evidence"
    elif target in {"protected-data", "protected-source", "ancestor-symlink"}:
        assert not output.exists()


@pytest.mark.parametrize("acknowledge", [False, True])
def test_cli_passes_explicit_development_acknowledgement_and_reports_status(case, capsys, acknowledge) -> None:
    names = {"spec_path": "spec"}
    argv = [
        part for key, value in case.kwargs.items() if key != "allow_unverified_serving_tokenizer"
        for part in ("--" + names.get(key, key.replace("_", "-")), str(value))
    ]
    if acknowledge:
        argv.append("--allow-unverified-serving-tokenizer")
    assert runner.main(argv) == (0 if acknowledge else 1)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == ("completed" if acknowledge else "incomplete")
    assert result["paper_result"] is False
    if acknowledge:
        assert result["metrics"]["candidate_bearing_query_count"] == 0
    else:
        assert result["error_type"] == "ValueError"
        case.tokenizer.assert_not_called()
        case.base_factory.assert_not_called()
        assert not case.output.exists()
