"""New lineage boundary only; preserve failures and dispatch no old cell."""
from copy import deepcopy
import json

import pytest

from release_contribution_campaign import ident, inherit_results
from prepare_rdf_tdb import stream_pin
from xgap.experiments.campaign_schedule import dispatch_one_group
from xgap.experiments.one_shot_records import write_once


def journal(tmp_path):
    root=tmp_path/'old';ledger=root/'cells';ledger.mkdir(parents=True)
    cells=[{'cell_id':f'natural_language-00-{i//2:03}-{i%2}','block':0,'group_index':i//2,
        'method':('xgap-precision','fedx')[i%2],'question_id':f'q{i//2}','track':'natural_language'} for i in range(4)]
    raw={'schema_version':'xgap-balanced-campaign-schedule-v1','cells':cells,'source_budget':{'calls':64},'profile':{'version':'old'}}
    old=write_once(tmp_path/'old-schedule.json',raw)
    new=write_once(tmp_path/'new-schedule.json',{**raw,'profile':{'version':'new'}})
    write_once(ledger/'schedule.json',ident(old));write_once(root/'campaign.json',{'schedule':old})
    for cell in cells[:2]:
        path=ledger/cell['cell_id'];path.mkdir()
        outcome=write_once(path/'outcome.json',{**cell,'status':'no_admissible_interpretation','success':False})
        write_once(path/'intent.json',{'cell':cell,'attempts':1})
        write_once(path/'terminal.json',{'cell_id':cell['cell_id'],'status':'outcome_sealed','outcome':outcome})
    return root,old,new,raw


def test_all_prior_failures_stay_and_only_next_group_dispatches(tmp_path):
    root,old,new,raw=journal(tmp_path);target=tmp_path/'new'
    originals={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    pin=inherit_results(old_root=root,old_schedule=old,new_schedule=new,new_root=target,expected_count=2)
    lineage=json.loads(open(pin['path']).read())
    assert lineage['inherited_count']==2 and lineage['next_group_index']==1 and lineage['methods_rerun']==0
    for cell in raw['cells'][:2]:
        record=json.loads((target/'cells'/cell['cell_id']/'terminal.json').read_text())
        assert record['executed_in_this_campaign'] is False
        assert record['status']=='inherited_prior_outcome' and record['language_version_at_execution']=='v1'
        assert json.loads(open(record['outcome']['path']).read())['success'] is False
    calls=[]
    def execute(cell,output):
        calls.append(cell['cell_id']);output.mkdir()
        return write_once(output/'receipt.json',{**cell,'success':False})
    result=dispatch_one_group(schedule_path=new['path'],schedule_sha256=new['sha256'],ledger=target/'cells',
        ready=lambda cell:{'ready':True},execute=execute)
    assert calls==[c['cell_id'] for c in raw['cells'][2:]]
    assert len([r for r in result if r['status']=='already_sealed'])==2
    assert {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}==originals


def test_budget_drift_and_nonprefix_fail_before_new_journal(tmp_path):
    root,old,new,raw=journal(tmp_path);target=tmp_path/'new'
    drift=deepcopy(raw);drift['source_budget']['calls']=65
    drift_pin=write_once(tmp_path/'drift.json',drift)
    with pytest.raises(ValueError,match='budgets'):
        inherit_results(old_root=root,old_schedule=old,new_schedule=drift_pin,new_root=target,expected_count=2)
    assert not target.exists()
    with pytest.raises(ValueError,match='complete expected prefix'):
        inherit_results(old_root=root,old_schedule=old,new_schedule=new,new_root=target,expected_count=1)
    assert not target.exists()
