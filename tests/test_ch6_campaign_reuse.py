"""Budgeted session reuse, no databases or model calls."""
import json

import pytest

import run_ch6_formal_campaign as campaign
from xgap.experiments.one_shot_records import write_once


def test_prefix_reserves_every_method_without_reordering_or_overdraft():
    cells=[dict(method=m) for m in ('internal','external','internal')]
    reservations={m:dict(model_calls=c,input_tokens=10*c,output_tokens=2*c,wall_seconds=5)
                  for m,c in (('internal',1),('external',4))}
    budget=dict(model_calls_cap=6,input_tokens_cap=60,output_tokens_cap=12)
    spent=dict(model_calls=1,input_tokens=10,output_tokens=2)
    assert campaign.affordable_prefix(cells,spent,reservations,budget,remaining_seconds=100,limit=3)==(2,'campaign_model_budget')
    assert campaign.affordable_prefix(cells,spent,reservations,budget,remaining_seconds=11,limit=3,startup_seconds=2)==(1,'campaign_wall_budget')
    reservations['internal']['model_calls']=-1
    with pytest.raises(ValueError,match='reservations'):
        campaign.affordable_prefix(cells,spent,reservations,budget,remaining_seconds=100,limit=3)


def test_one_guarded_invocation_reuses_session_and_never_retries_unsealed(tmp_path,monkeypatch):
    manifest=write_once(tmp_path/'manifest.json',dict(cells=[dict(cell_id=str(i),method='internal') for i in range(3)],
        design=dict(startup_seconds=2,method_wall_seconds=5,package_max_bytes=100000)))
    release=dict(output_root=str(tmp_path/'results'),source_commit='fixture',
        budget=dict(total_wall_seconds=1000,model_calls_cap=10,input_tokens_cap=100,output_tokens_cap=100,package_max_bytes=1000000),
        per_method_reservations=dict(internal=dict(model_calls=1,input_tokens=10,output_tokens=10,wall_seconds=10)),
        units=[dict(unit_id='same-snapshot',manifest=manifest)])
    rp=write_once(tmp_path/'release.json',release);calls=[]
    monkeypatch.setattr(campaign,'audit_release',lambda _:dict(success=True))
    monkeypatch.setattr(campaign,'source_commit',lambda:'fixture')
    def run(**args):
        calls.append(args['max_new_cells'])
        for i in range(args['max_new_cells']):
            path=args['output']/'cells'/str(i);path.mkdir(parents=True)
            outcome=write_once(path/'outcome.json',dict(model_calls=0,input_tokens=0,output_tokens=0))
            write_once(path/'terminal.json',dict(outcome=outcome))
        return dict(status='returned',new_cells=args['max_new_cells'])
    monkeypatch.setattr(campaign,'run',run)
    campaign.dispatch(release_path=rp['path'],release_sha256=rp['sha256'],execute=True,max_new_cells=3)
    assert calls==[3]
    # An interrupted last request must not disappear from global accounting,
    # including when there are no further unattempted cells in this unit.
    (tmp_path/'results/units/same-snapshot/cells/2/terminal.json').unlink()
    campaign.dispatch(release_path=rp['path'],release_sha256=rp['sha256'],execute=True,max_new_cells=3)
    record=json.loads((tmp_path/'results/campaign-invocations/00002.json').read_text())
    assert record['status']=='unsealed_cell_requires_accounting' and calls==[3]
