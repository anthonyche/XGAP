"""Actual offline runner/catalog fixtures, never measured model-quality evidence."""

from copy import deepcopy
import json
from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import xgap.experiments.grailqa_guarded_evidence as reader
import xgap.experiments.grailqa_guarded_preflight as runner
import xgap.experiments.grailqa_guarded_environment as environment_module
import xgap.experiments.grailqa_local_catalog as local
import xgap.experiments.grailqa_server_tokenization as server_tokens
from xgap.experiments.cwru_vllm import collect_run_environment, finalize_run
from xgap.experiments.grailqa_guarded_run_inputs import digest, read_json, read_rows, snapshot
from xgap.experiments.grailqa_inline_evidence import InlineEvidenceError
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError


ROOT = Path(__file__).resolve().parents[1]
INLINE = runpy.run_path(str(ROOT / "tests/test_inline_grounding.py"))
LOCAL = runpy.run_path(str(ROOT / "tests/test_m13e3b_local_catalog.py"))
SPEC_PATH = "experiments/specs/grailqa_semantic_preflight_inline_grounding_v1_cwru_qwen3_32b.json"
REVISION = "b" * 40


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def freeze(data, key):
    data[key] = content_hash({k: v for k, v in data.items() if k != key})


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    home = tmp_path_factory.mktemp("guarded-actual-runner").resolve()
    repo = home / "repo"
    repo.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        for name in ("XGAP_LLM_MODEL", "XGAP_LLM_BASE_URL", "GIT_DIR", "GIT_WORK_TREE"):
            patch.delenv(name, raising=False)
        patch.setenv("XGAP_LLM_API_KEY", "offline-d200-key")
        patch.setenv("XGAP_RESOLVED_MODEL_REVISION", REVISION)
        patch.setenv("SLURM_JOB_ID", "98765")
        patch.setattr(environment_module.socket, "gethostname", lambda: "test-node")
        spec_data = read_json(ROOT / SPEC_PATH)
        for name in ("src/xgap", spec_data["model_bundle_root"]):
            shutil.copytree(ROOT / name, repo / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("scripts/server/run_grailqa_guarded_preflight.sh", "scripts/slurm/cwru_xgap_vllm.sbatch"):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, repo / name)
        contract_data = read_json(ROOT / spec_data["deployment_contract"])
        contract_data["shared_paths"]["hf_home"] = str(home / "hf-cache")
        freeze(contract_data, "contract_hash")
        write_json(repo / spec_data["deployment_contract"], contract_data)
        spec_data["deployment_contract_hash"] = contract_data["contract_hash"]
        freeze(spec_data, "freeze_hash")
        write_json(repo / SPEC_PATH, spec_data)
        ids = spec_data["question_ids"]
        pilot = repo / spec_data["pilot_root"]
        questions = [{"question_id": qid, "text": "Where was Alice born?"} for qid in ids]
        write_rows(pilot / "inference_questions.jsonl", reversed(questions))
        # Actual catalog construction from the existing tiny archival adapter;
        # references do not exist during inference-side candidate selection.
        seed_dir = home / "seed"
        seed_dir.mkdir()
        seed = LOCAL["_build_fixture"](seed_dir, patch)
        catalog_path = home / "catalog18"
        local.build_local_catalog(
            inference_questions_path=pilot / "inference_questions.jsonl", question_ids=ids,
            workload_name="synthetic-test-only", artifact_id="d200-offline-catalog",
            freebase_parquet_root=seed["parquet_root"], source_manifest_path=seed["source_manifest"],
            normalized_ontology_path=seed["ontology"], reverse_properties_path=seed["reverse"],
            output_root=catalog_path, staging_root=home / "staging",
        )
        good = INLINE["wire"](INLINE["FIXTURES"]["case"].__wrapped__().raw)
        substitutions = {"type.source": "people.person", "type.target": "location.location",
                         "r.connected": "people.person.place_of_birth", "m.visible": "m.alice"}
        def substitute(value):
            if isinstance(value, dict):
                return {k: substitute(v) for k, v in value.items()}
            if isinstance(value, list):
                return [substitute(v) for v in value]
            return substitutions.get(value, value) if isinstance(value, str) else value
        good = substitute(good)
        good["query_slots"].extend({"slot_id": f"relation-hop-{hop}",
                                    "query_anchor_id": "people.person.place_of_birth"} for hop in (2, 3))
        bad = deepcopy(good)
        bad["candidates"][0]["pattern_query"]["source"].pop("label_slot")
        reference = INLINE["expand"](good)["candidates"][0]["pattern_query"]
        references = [{"question_id": qid, "pattern_query": deepcopy(reference)} for qid in ids]
        references[12]["pattern_query"]["expr"]["edge"]["direction"] = "IN"
        write_rows(pilot / "reference_interpretations.jsonl", references)
        write_rows(pilot / "workload_stats.jsonl", [{"question_id": qid, "Q": 13, "path_length": 1} for qid in ids])
        write_json(pilot / "artifact_manifest.json", {"artifacts": {
            name: {"bytes": (pilot / name).stat().st_size, "sha256": digest(pilot / name)}
            for name in ("inference_questions.jsonl", "reference_interpretations.jsonl", "workload_stats.jsonl")}})
        local.run_local_reachability_audit(
            catalog_root=catalog_path, inference_questions_path=pilot / "inference_questions.jsonl", question_ids=ids,
            reference_interpretations_path=pilot / "reference_interpretations.jsonl", workload_stats_path=pilot / "workload_stats.jsonl",
            output_root=catalog_path, top_k=20, prompt_limit=4,
        )
        for name, value in {
            "XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE": "query_local_e3b4",
            "XGAP_GRAILQA_CATALOG_V2": str(catalog_path), "XGAP_GRAILQA_REACHABILITY_V2": str(catalog_path),
            "XGAP_GRAILQA_REACHABILITY_SUMMARY": str(catalog_path / "audit_summary.json"),
            "XGAP_GRAILQA_REACHABILITY_ROWS": str(catalog_path / "reachability.jsonl"),
        }.items():
            patch.setenv(name, value)
        for args in (("init", "-q"), ("add", "."),
                     ("-c", "user.name=Offline test", "-c", "user.email=offline@example.invalid", "commit", "-qm", "synthetic source inputs")):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        tokenizer_path = home / "hf-cache/hub/models--Qwen--Qwen3-32B/snapshots" / REVISION
        tokenizer_path.mkdir(parents=True)
        identity = {"schema_version": "synthetic-tokenizer-test-only", "snapshot_path": str(tokenizer_path),
                    "snapshot_revision": REVISION, "remote_serving_parity_verified": False}
        def payload_case(payload):
            qid = json.loads(payload["messages"][1]["content"])["task_id"]
            return ids.index(qid), len(payload["messages"]) > 2
        class Counter:
            def __init__(self, path, revision):
                assert path == tokenizer_path and revision == REVISION
                self.identity = deepcopy(identity)
            def payload_token_ids(self, payload):
                case_index, repair = payload_case(payload)
                count = 9000 if case_index == 4 or (case_index == 5 and repair) else (110 if repair else 100)
                return list(range(count))
            def count_payload_tokens(self, payload):
                return len(self.payload_token_ids(payload))
        counter = Counter(tokenizer_path, REVISION)
        patch.setattr(runner, "LocalPinnedChatTokenizer", Counter)
        sent, probed = [], []
        class TokenTransport:
            def post_json(self, **kw):
                index, _ = payload_case(kw["payload"])
                probed.append(index)
                if index == 9:
                    raise server_tokens.ServerTokenizationEndpointError("http_error")
                tokens = counter.payload_token_ids(kw["payload"])
                if index == 8:
                    tokens = [999] + tokens[1:]
                return {"tokens": tokens, "count": len(tokens), "max_model_len": 12288}
        patch.setattr(server_tokens, "LoopbackTokenizationTransport", TokenTransport)
        def send(**kw):
            index, repair = payload_case(kw["payload"])
            sent.append((index, repair))
            if index == 6 or (index == 7 and repair):
                raise ProviderTransportError(LiveFailureCategory.TIMEOUT, "synthetic timeout")
            wire = deepcopy(bad if index == 2 or (index in (1, 5, 7) and not repair) else good)
            if index == 3:
                wire = {"invalid": True}
            if index == 10:
                sibling = deepcopy(wire["candidates"][0])
                sibling["candidate_id"] = "bad-sibling"
                sibling["pattern_query"]["source"]["label"] = "type.unavailable"
                wire["candidates"].append(sibling)
            if index == 11:
                wire["candidates"][0]["pattern_query"]["expr"]["edge"]["direction"] = "IN"
            return INLINE["response"](wire)
        patch.setattr(runner, "build_openai_compatible_provider", lambda model, **kw:
            build_openai_compatible_provider(model, SimpleNamespace(post_json=send), response_parser=kw["response_parser"]))
        import xgap.experiments.cwru_vllm as cwru
        patch.setattr(cwru, "_runtime_versions", lambda: contract_data["runtime"])
        patch.setattr(cwru, "_gpu_metadata", lambda: {"status": "available", "model": "synthetic H100"})
        environment = collect_run_environment(repo_root=repo, spec_path=SPEC_PATH, contract_path=repo / spec_data["deployment_contract"])
        run = home / "recorded-run"
        run.mkdir()
        write_json(run / "cwru_environment.json", environment)
        spec = reader.GrailQAPreflightSpec.load(repo / SPEC_PATH)
        write_json(run / "preflight_readiness.json", runner.preflight_readiness(spec, repo, require_credentials=False))
        write_json(run / "guarded_launch_binding.json", {
            "schema_version": "grailqa-guarded-launch-binding-v1", "runner_commit": commit,
            "spec_freeze_hash": spec_data["freeze_hash"], "slurm_job_id": "98765", "question_count": 18,
            "serving_python": str(Path(contract_data["shared_paths"]["vllm_env"]) / "bin/python"),
            "contract_hash": contract_data["contract_hash"], "paper_result": False, "automatic_retries": 0,
            "author_receipt_created": False, "candidate_grounding_policy": spec_data["candidate_grounding_policy"],
            "candidate_repair_policy": spec_data["candidate_repair_policy"],
        })
        write_json(run / "vllm_structured_smoke.json", {"schema_valid": True, "secrets_persisted": False})
        produced = runner.run_guarded_preflight(
            spec_path=SPEC_PATH, repo_root=repo, output_root=run / reader.RESULT_ROOT,
            run_environment_path=run / "cwru_environment.json", tokenizer_snapshot=tokenizer_path,
            tokenizer_revision=REVISION, expected_runner_commit=commit,
            execute_development_spec_sha256=spec_data["freeze_hash"], verify_server_tokenization=True,
        )
        (run / "job.log").write_text("synthetic retained launch log\n")
        finalize_run(run, 0)
        with (run / "job.log").open("a") as log:
            log.write("synthetic finalizer tail\n")
        assert len(read_rows(run / reader.RESULT_ROOT / "query_states.jsonl")) == 18
        assert produced["metrics"]["structured_valid_rate"] > 0
    return SimpleNamespace(home=home, repo=repo, run=run, Counter=Counter, sent=sent, probed=probed,
        kwargs={"repo_root": repo, "spec_path": SPEC_PATH, "expected_commit": commit,
            "expected_spec_freeze_hash": spec_data["freeze_hash"], "catalog_root": catalog_path,
            "expected_catalog_hash": read_json(catalog_path / "manifest.json")["catalog_hash"],
            "expected_catalog_manifest_sha256": digest(catalog_path / "manifest.json"),
            "reachability_root": catalog_path, "tokenizer_snapshot": tokenizer_path, "tokenizer_revision": REVISION})


@pytest.fixture
def case(recorded, tmp_path, monkeypatch):
    run = (tmp_path / "run").resolve()
    shutil.copytree(recorded.run, run)
    monkeypatch.setattr(reader, "LocalPinnedChatTokenizer", recorded.Counter)
    import xgap.experiments.grailqa_semantic_pilot as producer
    import xgap.experiments.grailqa_preflight as evaluator
    forbidden = lambda *a, **kw: pytest.fail("audit invoked producer or external transport")
    monkeypatch.setattr(producer, "_infer_one", forbidden)
    monkeypatch.setattr(producer, "_infer_one_impl", forbidden)
    monkeypatch.setattr(evaluator, "_evaluate_preflight", forbidden)
    monkeypatch.setattr(runner, "run_guarded_preflight", forbidden)
    monkeypatch.setattr(server_tokens.LoopbackTokenizationTransport, "post_json", forbidden)
    return SimpleNamespace(recorded=recorded, run=run, result=run / reader.RESULT_ROOT,
                           kwargs={**recorded.kwargs, "run_root": run})


def test_complete_actual_runner_is_independently_reconstructed(case):
    before = snapshot(case.run)
    result = reader.audit_guarded_development_run(**case.kwargs)
    assert result["whole_run_admitted"] is True
    assert result["question_count"] == 18
    assert result["totals"]["actual_attempted_provider_calls"] == len(case.recorded.sent)
    assert result["totals"]["tokenizer_probe_attempted_calls"] == len(case.recorded.probed)
    assert result["metrics"] == read_json(case.result / "metrics.json")
    assert result["metrics"]["candidate_recall"] < result["metrics"]["structured_valid_rate"]
    assert result["claim_boundary"]["external_calls"] == 0
    assert result["claim_boundary"]["paper_result"] is False
    assert snapshot(case.run) == before


def test_references_are_first_opened_after_all_inference_reconstruction(case, monkeypatch):
    done = []
    original = reader.reconstruct_guarded_ledger
    def ledger(**kwargs):
        assert not done
        result = original(**kwargs)
        done.append(True)
        return result
    monkeypatch.setattr(reader, "reconstruct_guarded_ledger", ledger)
    original_read = reader._pilot_file
    def read(pilot, manifest, name):
        if name in {"reference_interpretations.jsonl", "workload_stats.jsonl"}:
            assert done == [True]
        return original_read(pilot, manifest, name)
    monkeypatch.setattr(reader, "_pilot_file", read)
    assert reader.audit_guarded_development_run(**case.kwargs)["whole_run_admitted"]


def reseal(case, states=None, events=None):
    if states is not None:
        write_rows(case.result / "query_states.jsonl", states)
        if events is None:
            events = read_rows(case.result / "query_events.jsonl")
        by_id = {s["question"]["question_id"]: s for s in states}
        for event in events:
            if event["event"] == "query_inference_completed" and event["question_id"] in by_id:
                event["state_sha256"] = content_hash(by_id[event["question_id"]])
    if events is not None:
        write_rows(case.result / "query_events.jsonl", events)
    finalize_run(case.run, 0)


@pytest.mark.parametrize("defect", [
    "metric-recall", "metric-denominator", "semantic-score", "component-match", "candidate-capability",
    "candidate-score", "candidate-grounding", "candidate-unknown-field", "question-text", "state-unknown-field",
    "missing-question", "reordered-questions", "unknown-event", "missing-completion", "duplicate-inference-end",
    "cross-query-probe", "late-probe", "token-count", "request-copy", "feedback-copy", "diagnostic-copy",
    "server-receipt-copy", "inner-call-total", "inner-time", "outer-exit-bool", "failure-marker",
    "maximum-calls", "tokenizer-mode", "model-dtype-coordinated", "missing-deployment-check",
    "wrong-launch-job", "catalog-pin", "tokenizer-identity", "truncated-journal", "duplicate-json-key",
    "missing-file", "symlink-file", "job-log-prefix",
])
def test_coordinated_corruption_fails_after_inventory_is_resealed(case, defect):
    states = read_rows(case.result / "query_states.jsonl")
    events = read_rows(case.result / "query_events.jsonl")
    if defect.startswith("metric-"):
        value = read_json(case.result / "metrics.json")
        value["candidate_recall" if defect == "metric-recall" else "query_count"] = 1.0 if defect == "metric-recall" else 9
        write_json(case.result / "metrics.json", value)
    elif defect in {"semantic-score", "component-match", "candidate-capability"}:
        name = {"semantic-score": "semantic_scores", "component-match": "component_match", "candidate-capability": "candidate_capabilities"}[defect]
        rows = read_rows(case.result / (name + ".jsonl"))
        rows[0]["invented"] = True
        write_rows(case.result / (name + ".jsonl"), rows)
    elif defect in {"candidate-score", "candidate-grounding", "candidate-unknown-field"}:
        row = states[0]["candidates"][0]
        row[{"candidate-score": "semantic_deviation", "candidate-grounding": "grounded", "candidate-unknown-field": "invented"}[defect]] = 999
        reseal(case, states=states)
    elif defect in {"question-text", "state-unknown-field", "missing-question", "reordered-questions"}:
        if defect == "question-text":
            states[0]["question"]["text"] = "new inference context"
        elif defect == "state-unknown-field":
            states[0]["backend_execution_verified"] = True
        elif defect == "missing-question":
            states.pop()
        else:
            states.reverse()
        reseal(case, states=states)
    elif defect in {"unknown-event", "missing-completion", "duplicate-inference-end", "cross-query-probe", "late-probe", "token-count"}:
        if defect == "unknown-event":
            events.insert(1, {"event": "invisible_retry", "question_id": states[0]["question"]["question_id"]})
        elif defect == "missing-completion":
            events.pop()
        elif defect == "duplicate-inference-end":
            events.insert(-1, deepcopy(events[-2]))
        elif defect == "cross-query-probe":
            next(e for e in events if e["event"] == "tokenizer_probe_attempt")["question_id"] = states[1]["question"]["question_id"]
        elif defect == "late-probe":
            probe = next(e for e in events if e["event"] == "tokenizer_probe_result")
            events.remove(probe)
            events.insert(events.index(next(e for e in events if e["event"] == "transport_attempt")), probe)
        else:
            next(e for e in events if e["event"] == "token_check")["check"]["input_tokens"] += 1
        reseal(case, events=events)
    elif defect in {"request-copy", "feedback-copy", "diagnostic-copy", "server-receipt-copy"}:
        name = {"request-copy": "llm_requests", "feedback-copy": "candidate_feedback",
                "diagnostic-copy": "guard_diagnostics", "server-receipt-copy": "server_tokenization_checks"}[defect]
        rows = read_rows(case.result / (name + ".jsonl"))
        rows.pop()
        write_rows(case.result / (name + ".jsonl"), rows)
    elif defect in {"inner-call-total", "inner-time"}:
        status = read_json(case.result / "run_status.json")
        status["actual_attempted_provider_calls" if defect == "inner-call-total" else "inference_wall_seconds"] = 0
        write_json(case.result / "run_status.json", status)
    elif defect in {"maximum-calls", "tokenizer-mode"}:
        manifest = read_json(case.result / "run_manifest.json")
        manifest["maximum_provider_calls" if defect == "maximum-calls" else "serving_tokenizer_mode"] = 100 if defect == "maximum-calls" else "explicit_development_unverified"
        write_json(case.result / "run_manifest.json", manifest)
    elif defect in {"model-dtype-coordinated", "missing-deployment-check"}:
        environment = read_json(case.run / "cwru_environment.json")
        binding = read_json(case.result / "environment_binding.json")
        manifest = read_json(case.result / "run_manifest.json")
        if defect == "model-dtype-coordinated":
            environment["model"]["dtype"] = "float16"
        else:
            binding["checks"].pop()
        write_json(case.run / "cwru_environment.json", environment)
        binding["environment_sha256"] = content_hash(environment)
        freeze(binding, "binding_sha256")
        write_json(case.result / "environment_binding.json", binding)
        manifest.update(execution_environment=environment, environment_binding_sha256=content_hash(binding))
        write_json(case.result / "run_manifest.json", manifest)
    elif defect == "wrong-launch-job":
        value = read_json(case.run / "guarded_launch_binding.json")
        value["slurm_job_id"] = "123456"
        write_json(case.run / "guarded_launch_binding.json", value)
    elif defect == "catalog-pin":
        case.kwargs["expected_catalog_manifest_sha256"] = "0" * 64
    elif defect == "tokenizer-identity":
        value = read_json(case.result / "tokenizer_identity.json")
        value["snapshot_revision"] = "c" * 40
        write_json(case.result / "tokenizer_identity.json", value)
    elif defect == "truncated-journal":
        path = case.result / "query_events.jsonl"
        path.write_text(path.read_text().rstrip("\n"))
    elif defect == "duplicate-json-key":
        path = case.result / "metrics.json"
        path.write_text('{"query_count":18,' + path.read_text().lstrip()[1:])
    elif defect == "missing-file":
        (case.result / "server_tokenization_checks.jsonl").unlink()
    elif defect == "symlink-file":
        path = case.result / "metrics.json"
        target = case.run.parent / "outside.json"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    elif defect == "failure-marker":
        write_json(case.result / "run_failure.json", {"status": "incomplete"})
    # Refresh all file digests, so substantive tests must reconstruct contents.
    finalize_run(case.run, 0)
    if defect == "outer-exit-bool":
        status = read_json(case.run / "run_status.json")
        status["exit_code"] = False
        write_json(case.run / "run_status.json", status)
    if defect == "job-log-prefix":
        (case.run / "job.log").write_text("a corrupted original prefix\n")
    with pytest.raises((InlineEvidenceError, ValueError, FileNotFoundError, KeyError)):
        reader.audit_guarded_development_run(**case.kwargs)


def test_missing_real_tokenizer_cannot_admit_or_print_partial_metrics(case, monkeypatch, capsys):
    def unavailable(*a, **kw):
        raise ValueError("synthetic-sensitive-text")
    monkeypatch.setattr(reader, "LocalPinnedChatTokenizer", unavailable)
    args = [part for key, value in case.kwargs.items() for part in ("--" + key.replace("_", "-"), str(value))]
    assert reader.main(args) == 1
    output = capsys.readouterr().out
    assert "synthetic-sensitive-text" not in output
    assert json.loads(output)["whole_run_admitted"] is False
    assert "metrics" not in output


def test_explicit_source_files_are_checked_without_switching_checkout(case, monkeypatch):
    import xgap.experiments.grailqa_guarded_run_inputs as inputs
    before = subprocess.check_output(["git", "-C", str(case.recorded.repo), "rev-parse", "HEAD"])
    calls = []
    original = inputs.subprocess.run
    def run(args, **kwargs):
        calls.append(args)
        return original(args, **kwargs)
    monkeypatch.setattr(inputs.subprocess, "run", run)
    assert reader.audit_guarded_development_run(**case.kwargs)["whole_run_admitted"]
    assert calls and all(command[3] == "ls-tree" for command in calls)
    assert subprocess.check_output(["git", "-C", str(case.recorded.repo), "rev-parse", "HEAD"]) == before


def test_all_failed_queries_keep_denominator_and_no_candidate_accuracy(recorded):
    from xgap.experiments.grailqa_guarded_evaluation import reconstruct_guarded_evaluation
    states = read_rows(recorded.run / reader.RESULT_ROOT / "query_states.jsonl")
    failed = states[6]
    assert failed["candidates"] == [] and failed["api_call_completed"] is False
    failures = []
    for original in states:
        state = deepcopy(failed)
        state["question"] = original["question"]
        state["failure"]["question_id"] = state["question"]["question_id"]
        failures.append(state)
    pilot = recorded.repo / "datasets/grailqa_pilot_v1"
    references = {r["question_id"]: r for r in read_rows(pilot / "reference_interpretations.jsonl")}
    reachability = {r["question_id"]: r for r in read_rows(recorded.kwargs["reachability_root"] / "reachability.jsonl")}
    coverage = read_json(recorded.kwargs["reachability_root"] / "audit_summary.json")["summary"]
    result = reconstruct_guarded_evaluation(states=failures, references=references, reachability=reachability,
        coverage=coverage, epsilon_values=(0, 0.1, 0.25, 0.5, 0.75, 1))
    metrics = result["metrics"]
    assert metrics["query_count"] == len(result["failures"]) == 18
    assert metrics["candidate_recall"] == metrics["structured_valid_rate"] == metrics["provider_success_rate"] == 0.0
    assert metrics["full_normalized_interpretation_accuracy"] is None
    assert metrics["validated_grounded_candidate_count"] == metrics["generated_candidate_count"] == 0


def test_actual_retrieval_miss_has_a_complete_zero_call_ledger(tmp_path):
    from xgap.experiments.grailqa_guarded_accounting import reconstruct_guarded_ledger
    from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
    from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
    from xgap.experiments.grailqa_semantic_pilot import _infer_one
    from xgap.experiments.bundles import ModelBundle
    from xgap.experiments.grailqa_server_tokenization import EQUALITY_SCOPE
    fixture = INLINE["FIXTURES"]["case"].__wrapped__()
    catalog = SimpleNamespace(retrieve=lambda *a, **kw: SimpleNamespace(types=(), relations=(), to_dict=lambda: {}))
    question = {"question_id": "q1", "text": "fixture question"}
    state = _infer_one(question=question, catalog=catalog, provider=object(), semantic=fixture.semantic,
        retrieval_k=20, candidate_cap=3, grounding_policy=SEMANTIC_GROUNDING_POLICY)
    state["candidate_repair_policy"] = TYPED_GROUNDING_ONCE
    probes = {"tokenizer_probe_attempted_calls": 0, "tokenizer_probe_completed_results": 0,
        "tokenizer_probe_error_count": 0, "tokenizer_probe_latency_seconds": 0.0, "tokenizer_probe_receipts": [],
        "preprocessing_equality_scope": EQUALITY_SCOPE, "remote_serving_parity_verified": False,
        "journal_failed": False, "journal_failure_phase": None}
    diagnostic = {"question_id": "q1", "provider_invoked": False, "actual_attempted_provider_calls": 0,
        "token_check_count": 0, "guard_refusal": False, "local_token_refusal": False,
        "server_tokenization_refusal": False, "server_tokenization": probes, "details": {}}
    events = [{"event": "query_started", "question_id": "q1", "query_index": 1},
        {"event": "query_inference_completed", "question_id": "q1", "query_index": 1,
         "state_sha256": content_hash(state), "diagnostic": diagnostic},
        {"event": "inference_complete", "question_count": 1}, {"event": "run_completed", "question_count": 1}]
    counter = SimpleNamespace(identity={"synthetic": True}, payload_token_ids=lambda _: pytest.fail("counted absent payload"))
    result = reconstruct_guarded_ledger(states=[state], events=events, questions=[question],
        model=ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_grailqa_inline_v1"), catalog=catalog,
        semantic=fixture.semantic, counter=counter, retrieval_k=20, prompt_limit=4, context_limit=12288)
    assert result["totals"]["total_external_attempted_calls"] == 0
    assert result["copies"]["guard_diagnostics"] == [diagnostic]


def test_changed_source_bytes_cannot_keep_the_original_commit_receipt(tmp_path):
    from xgap.experiments.grailqa_guarded_run_inputs import bind_producer_inputs
    repo = tmp_path.resolve()
    (repo / "source.py").write_text("meaning = 1\n")
    for args in (("init", "-q"), ("add", "source.py"),
                 ("-c", "user.name=Offline test", "-c", "user.email=offline@example.invalid", "commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert bind_producer_inputs(repo, commit, ["source.py"])["files"]["source.py"] == digest(repo / "source.py")
    (repo / "source.py").write_text("meaning = 2\n")
    with pytest.raises(InlineEvidenceError, match="producer Git blob"):
        bind_producer_inputs(repo, commit, ["source.py"])
