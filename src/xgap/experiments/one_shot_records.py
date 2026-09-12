"""Single-request execution records and strict offline replay; no benchmark loop."""

from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from xgap.agent.question import run_question
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned, native_clients
from xgap.experiments.one_shot_toy import _DurableRecordingProvider
from xgap.experiments.row_normalization import normalize_rows
from xgap.infrastructure.runtime import QueryArtifact, ExecutionReport
from xgap.semantic.interpretation_replay import ReplayInterpretationProvider


RUN_SCHEMA = "xgap-one-shot-evaluation-record-v1"
REPLAY_SCHEMA = "xgap-one-shot-complete-replay-v1"


def write_once(path, value):
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())
    return {"path":str(Path(path).resolve()), "sha256":hashlib.sha256(data).hexdigest(), "bytes":len(data)}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class BackendReplay:
    def __init__(self, backend_id, records):
        self.backend_id, self.records, self.position = backend_id, list(records), 0

    def execute(self, artifact):
        if self.position == len(self.records):
            raise ValueError("No backend replay call remains")
        record = self.records[self.position]
        if _canonical(artifact.to_dict()) != _canonical(record["artifact"]):
            raise ValueError("Backend replay artifact differs; another plan's rows cannot be reused")
        self.position += 1
        original = ExecutionReport.from_dict(record["execution"])
        if original.backend_id != self.backend_id or original.artifact_id != artifact.artifact_id:
            raise ValueError("Backend replay response identity mismatch")
        # Historical timing is retained as provenance, not this run's measurement.
        return replace(original, elapsed_ms=0.0, metadata={"execution_kind":"offline_replay",
            "historical_elapsed_ms":original.elapsed_ms, "network_calls":0})


class CapturingClient:
    def __init__(self, client, root, records, lock):
        self.client, self.backend_id, self.root = client, client.backend_id, root
        self.records, self.lock = records, lock

    def execute(self, artifact):
        with self.lock:
            index = len(self.records)
            record = {"backend_id":self.backend_id,"artifact":artifact.to_dict(),"status":"started"}
            self.records.append(record)
        write_once(self.root/f"backend-{index:04}-intent.json", record)
        try:
            result = self.client.execute(artifact)
            record.update(status="returned", execution=result.to_dict())
            write_once(self.root/f"backend-{index:04}-result.json", record)
            return result
        except BaseException:
            record.update(status="indeterminate", error="Backend call or durable recording failed")
            # Core/receipt retain unknown calls. Do not retry the action or write.
            raise


def replay_from_saved_result(interpretation, result):
    """Offline migration of old full-query records; bind calls need original ledgers."""
    records = []
    outcomes = {n["node_id"]:n for n in (result.get("execution") or {}).get("value", {}).get("node_results", [])}
    for node in result.get("selected_plan", {}).get("nodes", []):
        if node["kind"] == "remote_bind_query":
            raise ValueError("Bound native replay requires the actual captured bound query")
        if node["kind"] != "remote_query" or node["node_id"] not in outcomes:
            continue
        outcome = outcomes[node["node_id"]]
        artifact = QueryArtifact.from_dict(node["parameters"]["artifact"])
        backend = node["parameters"]["backend_id"]
        execution = ExecutionReport(backend, artifact.artifact_id, artifact.language,
            outcome["status"] == "success", outcome["rows"], outcome["elapsed_ms"], outcome.get("error"))
        records.append({"backend_id":backend,"artifact":artifact.to_dict(),"execution":execution.to_dict()})
    return {"schema_version":REPLAY_SCHEMA,"interpretation":interpretation,"backend_records":records,
        "provenance":{"kind":"offline_conversion_of_saved_full_query_results",
            "live_timing_reproduction":False}}


def run_record(*, profile_path, profile_sha256, request_path, request_sha256, mode, output,
               operation="preflight", replay_path=None, replay_sha256=None):
    if operation not in {"preflight", "execute", "replay"}:
        raise ValueError("Explicit operation must be preflight, execute or replay")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    receipt = {"schema_version":RUN_SCHEMA,"operation":operation,"execution_kind":
        "offline_replay" if operation=="replay" else "live" if operation=="execute" else "preflight",
        "success":False,"status":"preparing","mode":mode,"profile_sha256":profile_sha256,
        "request_sha256":request_sha256,"model_network_calls":0,"backend_network_calls":0,
        "training_calls":0,"fit_calls":0,"current_query_probe_calls":0,"automatic_retries":0,
        "final_plan_executions":0,"input_tokens":0,"output_tokens":0,"result":None,
        "paper_result":False,"backend_snapshot_verified_by_runner":False}
    phase, captured, core, replay_clients = "preflight", [], None, {}
    try:
        profile = FrozenOneShotProfile.load(profile_path, expected_sha256=profile_sha256)
        materialized = profile.materialize()
        raw, estimator, _, sources, backends, client_specs, modes = materialized
        request_raw = json.loads(read_pinned(request_path, request_sha256))
        request = profile.request(request_raw, mode, materialized)
        policy, provider = modes[mode]
        budget = provider.token_guard.check(provider.build_request_payload(request), call_kind="generation")
        if not budget["passed"]: raise ValueError("Frozen request exceeds its provider budget")
        receipt.update(dataset=raw["dataset"], profile_id=raw["profile_id"], question_id=request_raw["question_id"],
            population=request_raw["population"], exposure=request_raw["exposure"],
            policy=policy.to_dict(), provider=provider.config.safe_dict(), offline=raw["offline"],
            estimator_sha256=estimator.model_sha256)
        write_once(root/"input.json", {"request":request.to_dict(),"profile_sha256":profile.sha256,
            "question_metadata":{k:request_raw[k] for k in ("population","exposure")},
            "provider":provider.config.safe_dict(),"budget":budget,"policy":policy.to_dict()})
        if operation == "preflight":
            receipt.update(success=True,status="preflight_passed")
            return receipt
        if operation == "replay":
            replay = json.loads(read_pinned(replay_path, replay_sha256))
            if replay.get("schema_version") != REPLAY_SCHEMA:
                raise ValueError("Unsupported complete replay")
            original_records = replay.get("interpretation", {}).get("records", [])
            if len(original_records) != 1:
                raise ValueError("One-shot replay requires one original provider record")
            outcome = original_records[0].get("response", original_records[0].get("failure", {}))
            if outcome.get("provenance", {}).get("config") != provider.config.safe_dict():
                raise ValueError("Replay model/prompt/config differs from the frozen provider profile")
            provider = ReplayInterpretationProvider(replay["interpretation"])
            provider.config = None  # Replay has no wire dispatch; original profile was preflighted above.
            replay_clients = {b:BackendReplay(b,[r for r in replay["backend_records"] if r["backend_id"]==b]) for b in backends}
            if any(r["backend_id"] not in backends for r in replay["backend_records"]):
                raise ValueError("Replay contains an unknown backend")
            clients = replay_clients
            receipt["replay_sha256"] = replay_sha256
        else:
            if not os.environ.get(provider.config.api_key_env):
                raise ValueError("The configured model credential environment variable is unset")
            clients = native_clients(client_specs)
        recorder = _DurableRecordingProvider(provider, root/"interpretation.json")
        # Live config must remain visible to the core wire-cap admission.
        recorder.config = getattr(provider, "config", None)
        lock = threading.Lock()
        clients = {b:CapturingClient(c,root,captured,lock) for b,c in clients.items()}
        receipt["preparation_ms"] = (time.perf_counter()-started)*1000
        write_once(root/"intent.json", {"operation":operation,"profile_sha256":profile.sha256,
            "request_sha256":request_sha256,"maximum_final_executions":1,"automatic_retries":0})
        phase = "ordinary_entry"
        core = run_question(request, recorder, one_shot_policy=policy, estimator=estimator,
            catalog_root=profile.root/raw["catalog"]["path"], catalog_hash=raw["catalog"]["bundle_hash"],
            sources=sources, backends=backends, backend_clients=clients)
        receipt.update(success=core["success"], status=core["status"], final_plan_executions=core["final_plan_executions"],
            model_network_calls=0 if operation=="replay" else core["interpretation_external_calls"],
            backend_network_calls=0 if operation=="replay" else core["backend_remote_calls"],
            input_tokens=core["input_tokens"],output_tokens=core["output_tokens"],
            core_end_to_end_ms=core["end_to_end_ms"], planning_ms=core["planning_ms"],
            execution_ms=core["execution_ms"], current_query_probe_calls=core["observation_calls"],
            replay_backend_invocations=len(captured) if operation=="replay" else 0)
        receipt["result"] = write_once(root/"result.json", core)
        phase = "post_seal"
        if operation == "replay":
            provider.assert_consumed()
            if any(c.position!=len(c.records) for c in replay_clients.values()):
                raise ValueError("Unconsumed backend replay; execution differs from the recorded path")
            receipt["timing_scope"] = "local replay only; not live inference/query latency"
        else:
            receipt["timing_scope"] = "current live core, including per-call durable backend capture"
        write_once(root/"backend_ledger.json", captured)
    except Exception as error:
        receipt.update(success=False,status="record_failed",failure_phase=phase,
            error_type=type(error).__name__,error=str(error))
        if phase == "ordinary_entry" and core is None and operation != "replay":
            receipt.update(model_network_calls=None,backend_network_calls=None,
                input_tokens=None,output_tokens=None,final_plan_executions=None)
    finally:
        receipt["wrapper_elapsed_ms_before_receipt"] = (time.perf_counter()-started)*1000
        receipt["cost_boundary"] = "profile/request reads, intent and core/result persistence included; receipt write and evaluation separate"
        write_once(root/"receipt.json", receipt)
    return receipt


def evaluate_record(receipt_path, *, receipt_sha256, reference_path, reference_sha256, output):
    """Post-seal normalized JSON row scoring. Never called by inference/preflight."""
    receipt = json.loads(read_pinned(receipt_path, receipt_sha256))
    if receipt.get("schema_version") != RUN_SCHEMA or receipt.get("operation") == "preflight":
        raise ValueError("An execution/replay terminal receipt is required")
    result = receipt.get("result")
    core = json.loads(read_pinned(result["path"], result["sha256"])) if result else None
    reference = json.loads(read_pinned(reference_path, reference_sha256))
    if (reference.get("schema_version") != "xgap-normalized-row-reference-v1"
            or reference.get("question_id") != receipt.get("question_id")
            or reference.get("dataset") != receipt.get("dataset")
            or type(reference.get("ordered")) is not bool
            or not isinstance(reference.get("rows"), list)):
        raise ValueError("Reference identity/normalized-row contract mismatch")
    success = bool(receipt["success"] and core and core["success"])
    normalization = reference.get('normalization')
    expected_rows = normalize_rows(reference['rows'], normalization) if normalization is not None else reference['rows']
    expected = [_canonical(row) for row in expected_rows]
    comparison_error = None
    try:
        actual_rows = core['answer_rows'] if success else []
        if normalization is not None: actual_rows = normalize_rows(actual_rows, normalization)
        actual = [_canonical(row) for row in actual_rows]
    except (ValueError, TypeError) as error:
        if normalization is None: raise  # Preserve the existing legacy contract.
        comparison_error, actual = str(error), []
    bag_a, bag_e = Counter(actual), Counter(expected)
    overlap = sum((bag_a & bag_e).values())
    comparable = success and comparison_error is None
    exact = comparable and (actual==expected if reference["ordered"] else bag_a==bag_e)
    score = {"schema_version":"xgap-one-shot-row-evaluation-v1", "dataset":receipt["dataset"],
        "question_id":receipt["question_id"],"mode":receipt["mode"],"execution_kind":receipt["execution_kind"],
        "population":receipt["population"],"exposure":receipt["exposure"],"execution_success":success,
        "answer_em":float(exact),"answer_row_multiset_f1":(2*overlap/(len(actual)+len(expected))
            if actual or expected else 1.0) if comparable else 0.0,
        "status":receipt["status"],"receipt_sha256":receipt_sha256,"reference_sha256":reference_sha256,
        "equivalence_scope":"explicitly normalized JSON rows; multiset F1, order-aware EM when declared",
        "paper_result":False}
    if normalization is not None:
        score.update(normalization=normalization, comparison_error=comparison_error,
            equivalence_scope='declared value normalization; original row order and multiplicity retained')
    write_once(output, score)
    return score
