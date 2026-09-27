"""Two immutable attempts compose into one suffix with witnessed accounting."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

import run_ch6_small_continuation as first
import run_ch6_small_chain_continuation as chain
from test_ch6_small_continuation import fixture as original_fixture, fake_migration
from xgap.experiments.one_shot_records import write_once


def rewrite(path,value):
    path=Path(path);path.write_text(json.dumps(value));return first.pin(path)


def fixture(tmp_path,monkeypatch):
    parent_pin,release,parent=original_fixture(tmp_path)
    fake_migration(monkeypatch)
    monkeypatch.setattr(chain,'migration',lambda repo,old,new:dict(parent_commit=old,continuation_commit=new,changed_paths=[]))
    # Extend the older accounting fixture with the actual unified worker pins.
    for unit in release['units']:
        manifest=first.reader()[0](unit['manifest'])
        for cell in manifest['cells']:cell.update(scope=cell['oracle'],config=cell['oracle'])
        unit['manifest']=rewrite(unit['manifest']['path'],manifest)
        identity=parent/'units'/unit['unit_id']/'identity.json'
        if identity.exists():
            d=json.loads(identity.read_text());d['identity']['manifest_sha256']=unit['manifest']['sha256'];rewrite(identity,d)
    parent_pin=rewrite(parent_pin['path'],release)
    identity=json.loads((parent/'identity.json').read_text());identity['identity']['release']=parent_pin
    rewrite(parent/'identity.json',identity)
    contract=first.prepare(parent_release=parent_pin,output=tmp_path/'first',source_commit='b'*40,
        recovery_wall_seconds=19632,prior_allocation_seconds=1968,allowed_harness_changes=[])
    cfg=first.reader()[0](contract);root=Path(cfg['output_root']);root.mkdir()
    write_once(root/'identity.json',dict(contract=contract,source_commit='b'*40,started_unix=200))
    closed={k:True for k in first.CLOSED_FIELDS};closed['serving_copy_reclamation_complete']=True
    total=0;last=None
    for unit in cfg['units']:
        if total==135:break
        manifest=first.reader()[0](unit['manifest']);u=root/'units'/unit['unit_id'];u.mkdir(parents=True)
        ident=dict(source_commit='b'*40,manifest_sha256=unit['manifest']['sha256'])
        write_once(u/'identity.json',dict(identity=ident,started_unix=200))
        inv=u/'invocations/0001';inv.mkdir(parents=True)
        write_once(inv/'receipt.json',dict(identity=ident,all_owned_closed=True,error=None,closures=[closed]))
        for cell in manifest['cells']:
            if total==135:break
            p=u/'cells'/cell['cell_id'];p.mkdir(parents=True);total+=1
            outcome=dict(method=cell['method'],request_sha256=cell['request']['sha256'],question_id=cell['cell_id'],
                profile_sha256='d'*64,track='unified',dataset={'dataset_id':'toy','version':'v1'},
                model_calls=1,input_tokens=10,output_tokens=2,success=True,status='answered')
            if total==135:
                execution=p/'execution';worker=execution/'worker';worker.mkdir(parents=True)
                usage=dict(model_calls=1,input_tokens=2649,output_tokens=427)
                core=worker/'core.json.gz';core.write_bytes(gzip.compress(json.dumps(usage).encode()))
                core_pin=first.pin(core)
                child=dict(outcome,**dict(success=False,status='execution_failed'))
                child.update(usage);child.update(schema_version='xgap-nl-method-worker-v1',scope_sha256=cell['scope']['sha256'],
                    oracle_sha256=cell['oracle']['sha256'],joint_config_sha256=cell['config']['sha256'],core=core_pin)
                child_pin=write_once(worker/'receipt.json',child)
                interpretation=write_once(worker/'interpretation.json',dict(records=[dict(response=dict(
                    usage=dict(external_calls=1,input_tokens=2649,output_tokens=427),provenance=dict(usage_reported=True)))]))
                outcome.update(model_calls=None,input_tokens=None,output_tokens=None,success=False,status='upstream_source_failure',
                    error_type='RuntimeError',error='Source accounting not settled',guard_status='completed',
                    quiescence=dict(complete=True),partial_worker_files=[child_pin,core_pin,interpretation])
                last=p
            out=write_once(p/'outcome.json',outcome)
            score=write_once(p/'score.json',dict(receipt_sha256=out['sha256'],reference_sha256=cell['reference']['sha256']))
            write_once(p/'terminal.json',dict(cell_id=cell['cell_id'],outcome=out,score=score))
            if cell['method']=='aruqula-fedx':
                (p/'external-services').mkdir();write_once(p/'external-services/closed.json',closed)
    usage=dict(model_calls=134,input_tokens=1340,output_tokens=268,sealed_cells=135,unsealed_cells=0,unknown_model_usage=True)
    cumulative=dict(usage)
    for k in (*first.USAGE_FIELDS,'sealed_cells'):cumulative[k]+=cfg['prior_usage'][k]
    write_once(root/'receipt.json',dict(contract=contract,error=None,status='accounting_incomplete',elapsed_seconds=12000.5,
        parent_usage=cfg['prior_usage'],new_usage=usage,cumulative_usage=cumulative))
    return parent_pin,contract,last


def update_last_outcome(last,transform):
    terminal=json.loads((last/'terminal.json').read_text());outcome=first.reader()[0](terminal['outcome'])
    transform(outcome)
    terminal['outcome']=rewrite(terminal['outcome']['path'],outcome)
    score=first.reader()[0](terminal['score']);score['receipt_sha256']=terminal['outcome']['sha256']
    terminal['score']=rewrite(terminal['score']['path'],score);rewrite(last/'terminal.json',terminal)


def test_witnessed_usage_and_exact_39_suffix_preserve_all_ancestors(tmp_path,monkeypatch):
    parent,contract,last=fixture(tmp_path,monkeypatch)
    before={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    checked=chain.inspect_chain(parent,contract)
    assert checked['remaining_cells']==39 and checked['inherited_usage']['sealed_cells']==177
    assert checked['inherited_usage']['model_calls']==200
    assert checked['inherited_usage']['input_tokens']==420+1340+2649
    assert checked['inherited_usage']['unknown_model_usage'] is False
    assert checked['corrections'][0]['old_status']=='upstream_source_failure'
    pin=chain.prepare(parent_release=parent,first_contract=contract,output=tmp_path/'second',source_commit='c'*40,
        prior_allocations_seconds=[1968,12002])
    cfg=first.reader()[0](pin)
    assert cfg['recovery_wall_seconds']==7630 and cfg['remaining_cells']==39
    assert first.reader()[0](cfg['reconciliation'])['original_outcomes_preserved']
    assert all(p.read_bytes()==data for p,data in before.items())


@pytest.mark.parametrize('durations,wall', [([1,12002],None),([1968,12000],None),([1968,12002],21600),([1968,22000],None)])
def test_cumulative_allocation_cannot_be_reset(tmp_path,monkeypatch,durations,wall):
    parent,contract,last=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='allocation|accounting'):
        chain.prepare(parent_release=parent,first_contract=contract,output=tmp_path/'second',source_commit='c'*40,
            prior_allocations_seconds=durations,recovery_wall_seconds=wall)
    assert not (tmp_path/'second').exists()


@pytest.mark.parametrize('damage',['other_unknown','child_identity','core_disagrees','provider_unknown','provider_incomplete','unsealed','duplicate'])
def test_uncertain_or_changed_evidence_never_reconciles(tmp_path,monkeypatch,damage):
    parent,contract,last=fixture(tmp_path,monkeypatch)
    if damage=='unsealed':(last/'terminal.json').unlink()
    elif damage=='duplicate':(last.parent/'extra-unrecorded').mkdir()
    else:
        def change(out):
            if damage=='other_unknown':out['error']='Different failure';return
            if damage=='child_identity':name='receipt.json'
            elif damage=='core_disagrees':name='core.json.gz'
            else:name='interpretation.json'
            target=next(p for p in out['partial_worker_files'] if p['path'].endswith('/worker/'+name))
            path=Path(target['path'])
            if name=='core.json.gz':
                path.write_bytes(gzip.compress(json.dumps(dict(model_calls=9,input_tokens=9,output_tokens=9)).encode()))
                child_path=path.parent/'receipt.json';child=json.loads(child_path.read_text());child['core']=first.pin(path)
                child_pin=rewrite(child_path,child)
                out['partial_worker_files']=[child_pin if p['path']==str(child_path) else p for p in out['partial_worker_files']]
            else:
                d=json.loads(path.read_text())
                if damage=='child_identity':d['question_id']='different-user-question'
                elif damage=='provider_unknown':d['records'][0]['response']['provenance']['usage_reported']=False
                else:d['records'][0]['response']['provenance']['external_call_count_complete']=False
                rewrite(path,d)
            out['partial_worker_files']=[first.pin(path) if p['path']==str(path) else p for p in out['partial_worker_files']]
        update_last_outcome(last,change)
    with pytest.raises((ValueError,FileNotFoundError)):chain.inspect_chain(parent,contract)


def test_modified_frozen_subset_is_rejected(tmp_path,monkeypatch):
    parent,contract,last=fixture(tmp_path,monkeypatch)
    cfg=first.reader()[0](contract);target=cfg['units'][0]['manifest']['path'];real=first.reader
    def reader(mapper=None):
        load,resolve=real(mapper)
        def altered(pin):
            doc=load(pin)
            if pin['path']==target:doc['cells'].reverse()
            return doc
        return altered,resolve
    monkeypatch.setattr(first,'reader',reader)
    with pytest.raises(ValueError,match='ordering'):chain.inspect_chain(parent,contract)


def test_actual_archives_reconcile_only_durable_missing_counter():
    old=Path('/Users/anthonyche/xgap-data/outputs/xgap-small48-terminal-3890655-v1')
    new=Path('/Users/anthonyche/xgap-data/outputs/xgap-small48-terminal-3891655-v1')
    if not old.exists() or not new.exists():pytest.skip('Optional archived failure evidence unavailable')
    parent=json.loads((old/'small48-fixed-f40dfa9-independent-v1/prepared.json').read_text())['release']
    contract=json.loads((new/'small48-continue-2a8e16e-v1/continuation/results/identity.json').read_text())['contract']
    def mapper(p):
        rel=Path(p).relative_to('/home/hxc859/xgap-ch6-artifacts')
        return (new if rel.parts[0].startswith('small48-continue-') else old)/rel
    checked=chain.inspect_chain(parent,contract,mapper=mapper)
    assert checked['inherited_usage']==dict(model_calls=468,input_tokens=868493,output_tokens=103775,
        sealed_cells=177,unsealed_cells=0,unknown_model_usage=False)
    assert checked['remaining_cells']==39 and len(checked['corrections'])==1


@pytest.mark.parametrize('last_failure',[None,'unknown_tokens','unsealed'])
def test_execution_inherits_ancestors_and_runs_no_old_cell(tmp_path,monkeypatch,last_failure):
    import run_bounded_joint_batch as batch
    from xgap.experiments import ch6_small_release
    parent,contract,last=fixture(tmp_path,monkeypatch)
    ref=chain.prepare(parent_release=parent,first_contract=contract,output=tmp_path/'second',source_commit='c'*40,
        prior_allocations_seconds=[1968,12002])
    monkeypatch.setattr(batch,'source_commit',lambda:'c'*40)
    monkeypatch.setattr(ch6_small_release,'audit',lambda release:dict(success=True))
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fixture-no-network')
    seen=[]
    def run(**kwargs):
        manifest=first.reader()[0](dict(path=kwargs['manifest_path'],sha256=kwargs['manifest_sha256']))
        root=Path(kwargs['output']);root.mkdir(parents=True,exist_ok=True);count=0
        for cell in manifest['cells']:
            path=root/'cells'/cell['cell_id']
            if path.exists():continue
            assert kwargs['before_cell'](cell) is None
            path.mkdir(parents=True);seen.append(cell['cell_id']);count+=1
            last_new=len(seen)==39
            pin=write_once(path/'outcome.json',dict(model_calls=1,
                input_tokens=None if last_new and last_failure=='unknown_tokens' else 10,output_tokens=2))
            if not (last_new and last_failure=='unsealed'):
                write_once(path/'terminal.json',dict(outcome=pin))
            if count>=kwargs['max_new_cells']:break
        return dict(status='returned',new_cells=count,receipt=None)
    monkeypatch.setattr(batch,'run',run)
    result=chain.execute(ref)
    assert len(set(seen))==39
    if last_failure is None:
        assert result['status']=='all_unattempted_requests_processed'
        assert result['new_usage']['sealed_cells']==39 and result['cumulative_usage']['sealed_cells']==216
        assert result['cumulative_usage']['model_calls']==239
    else:
        assert result['status']=='accounting_incomplete'
        assert result['new_usage']['unknown_model_usage'] or result['new_usage']['unsealed_cells']==1
    assert last.name not in seen
    with pytest.raises(FileExistsError):chain.execute(ref)
