from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

from xgap.agent.live_probe import LiveProbePolicy
from xgap.experiments.ch6_small_release import validate_membership
from xgap.experiments.ch6_small_sample import SCHEMA as SELECTION_SCHEMA,EXPOSURE
from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration


def fixture(tmp_path):
    profile=write_once(tmp_path/'profile.json',{})
    prepared=write_once(tmp_path/'prepared.json',dict(success=True,profile=profile))
    gate=write_once(tmp_path/'gate.json',{})
    external=write_once(tmp_path/'external.json',dict(model_budget=dict(max_calls=64)))
    cohorts=[]
    design=dict(package_max_bytes=4096,method_wall_seconds=300,startup_seconds=300)
    for d in ('D1','D2','D3'):
        for p in ('native','rdf'):
            cases=[]
            for w in ('W1','W2','W3','W4'):
                for frame in ('uniform','active-anchor'):
                    cid=f'{d}-{p}-{frame}-{w}'
                    request=write_once(tmp_path/f'{cid}-request.json',dict(question_id=cid))
                    reference=write_once(tmp_path/f'{cid}-reference.json',dict(question_id=cid))
                    cases.append(dict(case_id=cid,workload=w,stratum=frame,request=request,
                        reference=reference,scope=profile,oracle=profile,controlled_state=profile))
            bundle=write_once(tmp_path/f'{d}-{p}-bundle.json',dict(profile=profile,cases=cases))
            cohorts.append(dict(dataset=d,deployment=p,cases=cases,case_ids=[c['case_id'] for c in cases],
                prepared=prepared,profile=profile,backend_admission=gate,bundle=bundle,
                design=design,external_runtime=external if p=='rdf' else None))
    return dict(schema_version=SELECTION_SCHEMA,unique_query_intent_cases=48,cohorts=cohorts)


def test_preparation_publishes_exact_216_selected_nl_requests(tmp_path,monkeypatch):
    import prepare_ch6_small_release as prepare
    import release_ch6_five_method_batch as publisher
    import run_bounded_joint_batch as batch
    import run_ch6_small_study as runner
    import xgap.experiments.ch6_backend_eligibility as eligibility
    monkeypatch.setattr(prepare,'case_configuration',lambda *a,**k:configuration())
    monkeypatch.setattr(prepare,'source_commit',lambda:'a'*40)
    monkeypatch.setattr(publisher,'source_commit',lambda:'a'*40)
    monkeypatch.setattr(publisher,'validate',lambda manifest:None)
    monkeypatch.setattr(batch,'validate',lambda manifest:None)
    monkeypatch.setattr(eligibility,'eligible',lambda *a,**k:True)
    monkeypatch.setattr(eligibility,'check_design',lambda *a,**k:None)
    selection=fixture(tmp_path)
    pin=write_once(tmp_path/'selection.json',selection)
    policy=write_once(tmp_path/'policy.json',asdict(LiveProbePolicy(policy_id='test',basis='Frozen declared fixture priors')))
    spec=write_once(tmp_path/'spec.json',dict(schema_version='xgap-ch6-small-release-input-v1',
        selection=pin,live_probe_policy=policy,output_root=str(tmp_path/'runs'),budget=dict(
        total_wall_seconds=14400,package_max_bytes=1000000,free_disk_reserve_bytes=1,
        model_calls_cap=1728,input_tokens_stop_threshold=1000000,output_tokens_stop_threshold=500000)))
    result=prepare.prepare(spec['path'],spec['sha256'],tmp_path/'release')
    assert result['audit_passed'],result['failed_checks']
    release=json.loads(Path(result['release']['path']).read_text())
    manifests=[json.loads(Path(u['manifest']['path']).read_text()) for u in release['units']]
    assert sum(len(m['cells']) for m in manifests)==216
    assert all('controlled_state' not in cell for m in manifests for cell in m['cells'])
    assert all(m['prepared']==c['prepared'] for m,c in zip(manifests,selection['cohorts']))
    # Dry run must perform no execution and use the new subset audit.
    monkeypatch.setattr(runner,'run',lambda **kw:pytest.fail('A dry run executed a cell'))
    dry=runner.dispatch(result['release']['path'],result['release']['sha256'])
    assert dry['ready'] and dry['model_calls']==dry['backend_calls']==0
    # Dropping a selected method request is rejected, not hidden in a reduced denominator.
    incomplete=deepcopy(manifests);incomplete[0]['cells'].pop()
    with pytest.raises(ValueError,match='Missing selected'):
        validate_membership(selection,release['units'],incomplete)
    assert release['exposure']==EXPOSURE and not release['heldout_claim']
