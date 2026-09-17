"""The package monitor must be an object, and integration faults stop the group."""
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

from xgap.experiments.one_shot_records import write_once
import run_family_policy_group as runner


def test_monitor_protocol_and_abort_after_first_framework_failure(tmp_path,monkeypatch):
    design=json.loads((Path(__file__).resolve().parents[1]/'experiments/protocols/family_policy_study_v1.json').read_text())
    p=write_once(tmp_path/'input.json',{});closed=[];called=[]
    class Session:
        def __init__(self,root,**kw):
            self.root=root;root.mkdir();self.profile=p;self.observer=SimpleNamespace(generation=0);self.owned=[]
        def start(self):return self
        def close(self):
            closed.append(True);return dict(owned_groups_drained=True,owned_processes_terminal=True,observer_stopped=True)
    def trial(**kw):
        assert isinstance(kw['package_monitor'],runner.StudyBudget)
        assert kw['package_monitor'].sample([]) is None
        called.append(kw)
        return dict(receipt=p,success=False,status='guard_monitor_failed',source_observations={'requests':0},
            timing={'total_online_ms':1},model_calls=0,can_continue_session=False)
    monkeypatch.setattr(runner,'NativeStoreSession',Session)
    monkeypatch.setattr(runner,'run_nl_trial',trial)
    monkeypatch.setattr(runner,'score_trial',lambda *_a,**kw:{'answer_em':0})
    # Scoring's durable artifact belongs to the scoring tool, emulated here.
    def score(*_a,**kw):write_once(kw['output'],{});return {'answer_em':0}
    monkeypatch.setattr(runner,'score_trial',score)
    monkeypatch.setattr(runner.subprocess,'check_output',lambda args,**kw:'' if 'status' in args else 'commit')
    cells=[dict(cell_id=str(i),round='first',group_index=i//6,method_position=i%6,label='search_exact',
        method='xgap-nl-family-exact',question_id=str(i//6),request=p,family=p,oracle=p,reference=p) for i in range(112)]
    release=write_once(tmp_path/'release.json',dict(schema_version='xgap-family-policy-study-release-v1',design=design,cells=cells,prepared=p))
    runner.run(release['path'],release['sha256'],tmp_path/'run')
    assert len(called)==len(closed)==1
    report=json.loads((tmp_path/'run/group-first-0/receipt.json').read_text())
    assert report['budget_status']=='harness_integration_failure'
    assert len(list((tmp_path/'run/cells').iterdir()))==1
