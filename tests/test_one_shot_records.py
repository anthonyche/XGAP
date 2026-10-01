"""New manifest/record adapter risks, reusing saved native evidence offline."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import socket

import pytest

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.experiments.one_shot_split import FIXTURE, split_inputs, load_split_provider
from xgap.experiments.one_shot_toy import load_one_shot_toy_provider
from xgap.experiments.one_shot_profile import SCHEMA, REQUEST_SCHEMA, FrozenOneShotProfile
from xgap.experiments.one_shot_records import run_record, evaluate_record, write_once, BackendReplay
from xgap.infrastructure.runtime import QueryArtifact


REPLAY = Path(__file__).parent / "fixtures/one_shot_record_replay"


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_profile(root, *, which="success"):
    root.mkdir()
    request, stats, inputs, _ = split_inputs()
    modes = {}
    for name in ("precision", "performance"):
        provider = (load_split_provider(mode=name, disable_thinking=True) if which=="success" else
            load_one_shot_toy_provider(mode=name,disable_thinking=True,wire_profile="envelope-schema-v1"))
        prompt = root/(name+".txt"); prompt.write_text(provider.system_prompt)
        c = provider.config
        modes[name] = {"policy":asdict(OneShotPolicy.for_mode(name)), "provider":{
            "provider_id":c.provider_id,"base_url":c.base_url,"model":c.model,"api_key_env":c.api_key_env,
            "wire_profile":"envelope-schema-v1","prompt":{"path":prompt.name,"sha256":sha(prompt)},
            "temperature":c.temperature,"top_p":c.top_p,"max_tokens":c.max_tokens,
            "timeout_seconds":c.timeout_seconds,"disable_thinking":True}}
    document = {"schema_version":SCHEMA,"profile_id":"split-evaluation-interface",
        "dataset":{"dataset_id":"one_shot_split_v1","version":"1"},
        "source_schema":request.context["source_schema"],
        "sources":{k:{"version":s.snapshot_version,"replicas":list(s.replica_backend_ids)} for k,s in inputs["sources"].items()},
        "backends":{b:{"semantic":asdict(s),"client":{"engine":b,"url":"http://127.0.0.1:1",
            "database":"toy" if b=="fuseki" else "neo4j","timeout_seconds":30,"auth":None}}
            for b,s in inputs["backends"].items()},
        "catalog":{"path":str(inputs["catalog_root"]),"bundle_hash":inputs["catalog_hash"]},
        "estimator":{"path":str((REPLAY/"estimator.json").resolve()),"sha256":sha(REPLAY/"estimator.json")},
        "modes":modes,"offline":{"scope":"existing frozen tiny artifacts, no current fit/build","elapsed_ms":None}}
    profile = root/"profile.json"; write_once(profile,document)
    q = {"schema_version":REQUEST_SCHEMA,"question_id":"SPLIT-NL-01","question":request.question,
        "population":"adapter-development","exposure":"development_exposed"}
    request_path = root/"request.json"; write_once(request_path,q)
    return dict(profile_path=profile,profile_sha256=sha(profile),request_path=request_path,
        request_sha256=sha(request_path)), document


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a,**k:pytest.fail("Unexpected network access"))
    return prepare_profile(tmp_path/"inputs")


def run(prepared, output, *, operation="replay", which="success", **changes):
    options = {**prepared[0],"mode":"performance","output":output,"operation":operation}
    if operation == "replay": options.update(replay_path=REPLAY/(which+".json"), replay_sha256=sha(REPLAY/(which+".json")))
    options.update(changes)
    return run_record(**options)


def test_both_profiles_preflight_with_identical_dataset_contract_and_no_calls(prepared,tmp_path):
    for mode,cap in (("precision",3),("performance",1)):
        receipt=run(prepared,tmp_path/mode,operation="preflight",mode=mode)
        assert receipt["success"],receipt
        assert receipt["policy"]["candidate_cap"]==cap
        assert receipt["backend_network_calls"]==receipt["model_network_calls"]==0
        assert not (tmp_path/mode/"intent.json").exists()
        request=json.loads((tmp_path/mode/"input.json").read_text())["request"]
        assert request["required_constraints"]==[] and "requested_output" not in request["context"]
        assert "population" not in request["context"] and "exposure" not in request["context"]


def test_exact_saved_answer_through_new_entry_and_post_seal_evaluation(prepared,tmp_path):
    root=tmp_path/"replay"
    receipt=run(prepared,root)
    assert receipt["success"],receipt
    assert receipt["execution_kind"]=="offline_replay"
    assert receipt["model_network_calls"]==receipt["backend_network_calls"]==0
    assert receipt["replay_backend_invocations"]==2 and receipt["final_plan_executions"]==1
    core=json.loads((root/"result.json").read_text())
    expected=json.loads((FIXTURE/"gold/expected_rows.json").read_text())
    assert core["answer_rows"]==expected
    assert core["estimator"]["model_sha256"]=="a2c547d33531e0043a496e98b421232e083badfb8988d1c3bdce1f47dac7872a"
    reference=tmp_path/"reference.json"
    write_once(reference,{"schema_version":"xgap-normalized-row-reference-v1","dataset":receipt["dataset"],
        "question_id":receipt["question_id"],"ordered":False,"rows":expected})
    score=evaluate_record(root/"receipt.json",receipt_sha256=sha(root/"receipt.json"),
        reference_path=reference,reference_sha256=sha(reference),output=tmp_path/"score.json")
    assert score["answer_em"]==score["answer_row_multiset_f1"]==1
    assert score["execution_kind"]=="offline_replay" and score["exposure"]=="development_exposed"
    with pytest.raises(FileExistsError):run(prepared,root)


def test_failed_interpretation_is_terminal_and_retained_for_scoring(prepared,tmp_path):
    root=tmp_path/"failure"
    historical=prepare_profile(tmp_path/"historical-inputs",which="failure")
    receipt=run(historical,root,which="failure")
    assert receipt["status"]=="no_admissible_interpretation" and not receipt["success"]
    assert receipt["final_plan_executions"]==receipt["replay_backend_invocations"]==0
    ref=tmp_path/"empty-gold.json"
    write_once(ref,{"schema_version":"xgap-normalized-row-reference-v1","dataset":receipt["dataset"],
        "question_id":receipt["question_id"],"ordered":False,"rows":[]})
    score=evaluate_record(root/"receipt.json",receipt_sha256=sha(root/"receipt.json"),reference_path=ref,
        reference_sha256=sha(ref),output=tmp_path/"failed-score.json")
    assert score["answer_em"]==score["answer_row_multiset_f1"]==0
    assert score["status"]=="no_admissible_interpretation"


@pytest.mark.parametrize("change",["snapshot","mode","file_hash"])
def test_profile_drift_is_rejected_before_any_model_or_backend_call(prepared,tmp_path,change):
    args,raw=prepared
    if change=="snapshot":raw["sources"]["profiles"]["version"]="stale"
    elif change=="mode":raw["modes"]["performance"]["policy"]["mode"]="precision"
    else:raw["estimator"]["sha256"]="0"*64
    path=args["profile_path"].with_name("drift.json");write_once(path,raw)
    receipt=run(prepared,tmp_path/"rejected",profile_path=path,profile_sha256=sha(path))
    assert not receipt["success"] and receipt["failure_phase"]=="preflight"
    assert receipt["model_network_calls"]==receipt["backend_network_calls"]==0
    assert not (tmp_path/"rejected"/"intent.json").exists()
    assert {"snapshot":"estimator/source identities", "mode":"Mode/policy identity", "file_hash":"file size/hash"}[change] in receipt["error"]


def test_replay_refuses_an_old_response_under_a_new_prompt_identity(prepared,tmp_path):
    receipt=run(prepared,tmp_path/"wrong-provider",which="failure")
    assert not receipt["success"] and receipt["failure_phase"]=="preflight"
    assert "model/prompt/config differs" in receipt["error"]
    assert receipt["model_network_calls"]==receipt["backend_network_calls"]==0


def test_changed_query_or_native_artifact_cannot_reuse_another_record(prepared,tmp_path):
    raw=json.loads(prepared[0]["request_path"].read_text());raw["question"]+=" Extra condition."
    path=tmp_path/"changed-request.json";write_once(path,raw)
    receipt=run(prepared,tmp_path/"changed",request_path=path,request_sha256=sha(path))
    assert not receipt["success"] and receipt["model_network_calls"]==0
    replay=json.loads((REPLAY/"success.json").read_text())
    item=replay["backend_records"][0]
    client=BackendReplay(item["backend_id"],[item])
    artifact=QueryArtifact.from_dict({**item["artifact"],"text":"SELECT ?x WHERE { ?x ?p ?o }"})
    with pytest.raises(ValueError,match="artifact differs"):client.execute(artifact)
    assert client.position==0


def test_failed_result_seal_preserves_known_live_call_costs(prepared,tmp_path,monkeypatch):
    import xgap.experiments.one_shot_records as records
    from xgap.experiments.external_toy_interpretation import BoundedExternalChatTransport
    saved=json.loads((REPLAY/"success.json").read_text())
    response=saved["interpretation"]["records"][0]["response"]
    monkeypatch.setenv("XGAP_EXTERNAL_LLM_API_KEY","unit-test-placeholder")
    monkeypatch.setattr(BoundedExternalChatTransport,"post_json",lambda *a,**k:{
        "model":"qwen3.8-27b","choices":[{"finish_reason":"stop","message":{"content":json.dumps(response["payload"])}}],
        "usage":{"prompt_tokens":12,"completion_tokens":9,"total_tokens":21}})
    monkeypatch.setattr(records,"native_clients",lambda specs:{b:BackendReplay(b,[r for r in saved["backend_records"]
        if r["backend_id"]==b]) for b in specs})
    original=records.write_once
    def fail_seal(path,value):
        if Path(path).name=="result.json":raise OSError("controlled seal failure")
        return original(path,value)
    monkeypatch.setattr(records,"write_once",fail_seal)
    receipt=run(prepared,tmp_path/"seal-failure",operation="execute")
    assert receipt["status"]=="record_failed" and receipt["failure_phase"]=="ordinary_entry"
    assert receipt["model_network_calls"]==1 and receipt["backend_network_calls"]==2
    assert receipt["input_tokens"]==12 and receipt["output_tokens"]==9
    assert receipt["final_plan_executions"]==1 and receipt["result"] is None
