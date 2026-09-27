"""A repair consumes only the frozen untouched suffix and inherits prior costs."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import run_ch6_small_continuation as recovery
from xgap.experiments.one_shot_records import write_once


def fixture(tmp_path, model_cap=1728):
    parent=tmp_path/'parent'; parent.mkdir()
    source='a'*40; units=[]; manifests=[]
    content=write_once(tmp_path/'input.json', {})
    for dataset in ('D1','D3','D2'):
        for deployment in ('native','rdf'):
            uid=dataset+'-'+deployment
            cells=[]
            for i in range(32 if deployment=='native' else 40):
                cell=dict(cell_id=uid+'-'+str(i),method='unified',request=content,reference=content,oracle=content)
                if uid=='D1-rdf' and i==9:cell['method']='aruqula-fedx'
                cells.append(cell)
            manifest=dict(cells=cells,design=dict(method_wall_seconds=1,startup_seconds=1,package_max_bytes=1000),
                          external_runtime=None)
            ref=write_once(tmp_path/(uid+'-manifest.json'),manifest)
            units.append(dict(unit_id=uid,dataset=dataset,deployment=deployment,manifest=ref))
            manifests.append(manifest)
    release=dict(schema_version='xgap-ch6-small-real-release-v1',automatic_retries=0,source_commit=source,
        units=units,output_root=str(parent),execution_dataset_order=['D1','D3','D2'],max_cells_per_source_session=8,
        budget=dict(model_calls_cap=model_cap,input_tokens_stop_threshold=6000000,output_tokens_stop_threshold=1000000,
                    total_wall_seconds=21600,package_max_bytes=10**9))
    ref=write_once(tmp_path/'release.json',release)
    write_once(parent/'identity.json',dict(identity=dict(release=ref,source_commit=source),started_unix=100))
    closure={k:True for k in recovery.CLOSED_FIELDS}
    closure['serving_copy_reclamation_complete']=True
    count=0
    for unit,manifest in zip(units,manifests):
        if count>=42:break
        root=parent/'units'/unit['unit_id']; root.mkdir(parents=True)
        identity=dict(manifest_sha256=unit['manifest']['sha256'],source_commit=source)
        write_once(root/'identity.json',dict(identity=identity,started_unix=100))
        inv=root/'invocations'/'0001';inv.mkdir(parents=True)
        write_once(inv/'receipt.json',dict(identity=identity,all_owned_closed=True,error=None,
            budget_status='study_harness_failure' if unit['deployment']=='rdf' else None,closures=[closure]))
        for cell in manifest['cells']:
            if count>=42:break
            path=root/'cells'/cell['cell_id'];path.mkdir(parents=True)
            outcome=dict(method=cell['method'],request_sha256=cell['request']['sha256'],
                model_calls=24 if count==41 else 1,input_tokens=10,output_tokens=2,success=count!=41,
                status='harness_observation_failure' if count==41 else 'answered')
            outpin=write_once(path/'receipt.json',outcome)
            score=write_once(path/'score.json',dict(receipt_sha256=outpin['sha256'],reference_sha256=content['sha256']))
            write_once(path/'terminal.json',dict(cell_id=cell['cell_id'],outcome=outpin,score=score))
            if cell['method']=='aruqula-fedx':
                (path/'external-services').mkdir()
                write_once(path/'external-services/closed.json',closure)
            count+=1
    return ref,release,parent


def fake_migration(monkeypatch):
    monkeypatch.setattr(recovery,'source_migration',lambda repo,old,new,allowed:dict(
        parent_commit=old,continuation_commit=new,allowed_runtime_paths=sorted(allowed),
        changed_paths=[],experimental_algorithm_unchanged=True))


def prepare(tmp_path,monkeypatch,model_cap=1728):
    ref,release,parent=fixture(tmp_path,model_cap=model_cap)
    fake_migration(monkeypatch)
    contract=recovery.prepare(parent_release=ref,output=tmp_path/'continuation',source_commit='b'*40,
        recovery_wall_seconds=19632,prior_allocation_seconds=1968,
        allowed_harness_changes=['scripts/run_ch6_small_continuation.py'])
    return ref,release,parent,contract


def test_exact_suffix_inherits_failures_costs_and_never_mutates_parent(tmp_path,monkeypatch):
    ref,release,parent=fixture(tmp_path)
    before={p:p.read_bytes() for p in parent.rglob('*') if p.is_file()}
    checked=recovery.inspect_parent(ref)
    assert checked['remaining_cells']==174 and checked['usage']['sealed_cells']==42
    assert checked['usage']['model_calls']==65 and checked['usage']['input_tokens']==420
    assert len(checked['units'][0]['pending_cells'])==0
    assert checked['units'][1]['pending_cells'][0]['cell_id']=='D1-rdf-10'
    fake_migration(monkeypatch)
    pin=recovery.prepare(parent_release=ref,output=tmp_path/'next',source_commit='b'*40,
        recovery_wall_seconds=19632,prior_allocation_seconds=1968,allowed_harness_changes=[])
    contract=recovery.reader()[0](pin)
    assert len(contract['units'])==5 and contract['prior_usage']==checked['usage']
    for original,new in zip([u for u in checked['units'] if u['pending_cells']],contract['units']):
        expected=deepcopy(original['manifest']);expected['cells']=original['pending_cells']
        assert recovery.reader()[0](new['manifest'])==expected
    assert 'supersedes' in contract['wall_policy'] and contract['recovery_wall_seconds']==19632
    assert all(p.read_bytes()==data for p,data in before.items())


@pytest.mark.parametrize('damage',['unsealed','unknown_usage','bad_pin','unclosed','out_of_order','unexpected'])
def test_rejects_unsafe_parent_recovery(tmp_path,damage):
    ref,release,parent=fixture(tmp_path)
    cell=parent/'units/D1-rdf/cells/D1-rdf-9'
    if damage=='unsealed':(cell/'terminal.json').unlink()
    elif damage=='bad_pin':(cell/'receipt.json').write_text('{}')
    elif damage=='unknown_usage':
        record=json.loads((cell/'receipt.json').read_text());record['input_tokens']=None
        (cell/'receipt.json').write_text(json.dumps(record))
        term=json.loads((cell/'terminal.json').read_text());term['outcome']=recovery.pin(cell/'receipt.json')
        score=json.loads((cell/'score.json').read_text());score['receipt_sha256']=term['outcome']['sha256']
        (cell/'score.json').write_text(json.dumps(score));term['score']=recovery.pin(cell/'score.json')
        (cell/'terminal.json').write_text(json.dumps(term))
    elif damage=='unclosed':
        f=cell/'external-services/closed.json';d=json.loads(f.read_text());d['observer_stopped']=False;f.write_text(json.dumps(d))
    elif damage=='out_of_order':
        (parent/'units/D1-native/cells/D1-native-0').rename(parent/'detached-cell')
    elif damage=='unexpected':(parent/'units/D1-native/cells/unknown').mkdir()
    with pytest.raises(ValueError):recovery.inspect_parent(ref)


def test_wall_budget_not_reset_and_old_output_never_reused(tmp_path,monkeypatch):
    ref,release,parent=fixture(tmp_path);fake_migration(monkeypatch)
    args=dict(parent_release=ref,output=tmp_path/'next',source_commit='b'*40,
        recovery_wall_seconds=21600,prior_allocation_seconds=1968,allowed_harness_changes=[])
    with pytest.raises(ValueError,match='original active wall'):recovery.prepare(**args)
    args.update(recovery_wall_seconds=19632,output=parent/'child')
    with pytest.raises(ValueError,match='disjoint'):recovery.prepare(**args)


def test_source_migration_rejects_algorithm_or_unapproved_runtime_edits(monkeypatch):
    monkeypatch.setattr(recovery.subprocess,'check_output',lambda *a,**k:'src/xgap/planning/runtime_work_estimator.py\n')
    with pytest.raises(ValueError,match='Non-harness'):recovery.source_migration('.', 'a','b',[])
    with pytest.raises(ValueError,match='allowlist'):recovery.source_migration('.', 'a','b',['src/xgap/planning/runtime_work_estimator.py'])
    monkeypatch.setattr(recovery.subprocess,'check_output',lambda *a,**k:'scripts/ch6_external_session.py\n')
    with pytest.raises(ValueError,match='Non-harness'):recovery.source_migration('.', 'a','b',[])
    assert recovery.source_migration('.', 'a','b',['scripts/ch6_external_session.py'])['experimental_algorithm_unchanged']


def test_real_archive_sealed_prefix_when_available():
    base=Path('/Users/anthonyche/xgap-data/outputs/xgap-small48-terminal-3890655-v1')
    if not base.exists():pytest.skip('Optional actual failure replay archive is not installed')
    ref=json.loads((base/'small48-fixed-f40dfa9-independent-v1/prepared.json').read_text())['release']
    checked=recovery.inspect_parent(ref,mapper=lambda p:base/Path(p).relative_to('/home/hxc859/xgap-ch6-artifacts'))
    assert checked['remaining_cells']==174
    assert checked['usage']==dict(model_calls=65,input_tokens=140424,output_tokens=21064,
        unknown_model_usage=False,sealed_cells=42,unsealed_cells=0)


def test_execute_only_suffix_and_cumulative_budget_includes_parent(tmp_path,monkeypatch):
    import run_bounded_joint_batch as batch
    from xgap.experiments import ch6_small_release
    ref,release,parent,contract_pin=prepare(tmp_path,monkeypatch)
    monkeypatch.setattr(batch,'source_commit',lambda:'b'*40)
    monkeypatch.setattr(ch6_small_release,'audit',lambda release:dict(success=True))
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fake-never-sent')
    seen=[]
    def run(**kwargs):
        manifest=recovery.reader()[0](dict(path=kwargs['manifest_path'],sha256=kwargs['manifest_sha256']))
        root=Path(kwargs['output']);root.mkdir(parents=True,exist_ok=True)
        attempts=0
        for cell in manifest['cells']:
            dest=root/'cells'/cell['cell_id']
            if dest.exists():continue
            assert kwargs['before_cell'](cell) is None
            dest.mkdir(parents=True);seen.append(cell['cell_id']);attempts+=1
            receipt=write_once(dest/'receipt.json',dict(model_calls=1,input_tokens=10,output_tokens=2))
            write_once(dest/'terminal.json',dict(outcome=receipt))
            if attempts>=kwargs['max_new_cells']:break
        return dict(status='returned',new_cells=attempts,receipt=None)
    monkeypatch.setattr(batch,'run',run)
    result=recovery.execute(contract_pin)
    assert result['status']=='all_unattempted_requests_processed'
    assert len(seen)==len(set(seen))==174 and seen[0]=='D1-rdf-10'
    assert result['cumulative_usage']['model_calls']==239
    assert result['cumulative_usage']['sealed_cells']==216
    assert result['parent_usage']['model_calls']==65 and result['new_usage']['model_calls']==174
    with pytest.raises(FileExistsError):recovery.execute(contract_pin)


def test_execute_rejects_tampered_subset_before_sources_start(tmp_path,monkeypatch):
    import run_bounded_joint_batch as batch
    from xgap.experiments import ch6_small_release
    ref,release,parent,contract_pin=prepare(tmp_path,monkeypatch)
    cfg=recovery.reader()[0](contract_pin)
    original=recovery.reader()[0](cfg['units'][0]['manifest'])
    original['cells'].reverse()
    path=Path(cfg['units'][0]['manifest']['path']);path.write_text(json.dumps(original))
    cfg['units'][0]['manifest']=recovery.pin(path)
    Path(contract_pin['path']).write_text(json.dumps(cfg));contract_pin=recovery.pin(contract_pin['path'])
    monkeypatch.setattr(batch,'source_commit',lambda:'b'*40)
    monkeypatch.setattr(ch6_small_release,'audit',lambda release:dict(success=True))
    with pytest.raises(ValueError,match='order or budgets'):recovery.execute(contract_pin)
    assert not Path(cfg['output_root']).exists()


def test_inherited_calls_stop_before_fresh_method_not_after_budget_reset(tmp_path,monkeypatch):
    import run_bounded_joint_batch as batch
    from xgap.experiments import ch6_small_release
    ref,release,parent,contract=prepare(tmp_path,monkeypatch,model_cap=65)
    monkeypatch.setattr(batch,'source_commit',lambda:'b'*40)
    monkeypatch.setattr(ch6_small_release,'audit',lambda release:dict(success=True))
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fake-never-sent')
    monkeypatch.setattr(batch,'run',lambda **kwargs:pytest.fail('No remaining call allowance'))
    result=recovery.execute(contract)
    assert result['status']=='model_call_budget'
    assert result['new_usage']['model_calls']==0 and result['cumulative_usage']['model_calls']==65


@pytest.mark.parametrize('last_cell_failure',['unknown_tokens','unsealed'])
def test_last_cell_cannot_report_complete_with_incomplete_accounting(tmp_path,monkeypatch,last_cell_failure):
    import run_bounded_joint_batch as batch
    from xgap.experiments import ch6_small_release
    ref,release,parent,contract_pin=prepare(tmp_path,monkeypatch)
    monkeypatch.setattr(batch,'source_commit',lambda:'b'*40)
    monkeypatch.setattr(ch6_small_release,'audit',lambda release:dict(success=True))
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fake-never-sent')
    seen=[]
    def run(**kwargs):
        manifest=recovery.reader()[0](dict(path=kwargs['manifest_path'],sha256=kwargs['manifest_sha256']))
        root=Path(kwargs['output']);root.mkdir(parents=True,exist_ok=True)
        attempts=0
        for cell in manifest['cells']:
            dest=root/'cells'/cell['cell_id']
            if dest.exists():continue
            assert kwargs['before_cell'](cell) is None
            dest.mkdir(parents=True);seen.append(cell['cell_id']);attempts+=1
            last=len(seen)==174
            receipt=write_once(dest/'receipt.json',dict(model_calls=1,
                input_tokens=None if last and last_cell_failure=='unknown_tokens' else 10,output_tokens=2))
            if not (last and last_cell_failure=='unsealed'):
                write_once(dest/'terminal.json',dict(outcome=receipt))
            if attempts>=kwargs['max_new_cells']:break
        # Simulate a successful enclosing runner return at the final position.
        return dict(status='returned',new_cells=attempts,receipt=None)
    monkeypatch.setattr(batch,'run',run)
    result=recovery.execute(contract_pin)
    assert len(seen)==174
    assert result['status']=='accounting_incomplete'
    if last_cell_failure=='unknown_tokens':
        assert result['new_usage']['sealed_cells']==174 and result['new_usage']['unknown_model_usage']
        assert result['cumulative_usage']['unknown_model_usage']
    else:
        assert result['new_usage']['sealed_cells']==173 and result['new_usage']['unsealed_cells']==1
        assert result['cumulative_usage']['sealed_cells']==215
    sealed=recovery.reader()[0](result['receipt'])
    assert sealed['status']=='accounting_incomplete'


def test_terminal_completion_requires_all_expected_new_seals(tmp_path,monkeypatch):
    import run_bounded_joint_batch as batch
    import run_ch6_formal_campaign as campaign
    from xgap.experiments import ch6_small_release
    ref,release,parent,contract_pin=prepare(tmp_path,monkeypatch)
    monkeypatch.setattr(batch,'source_commit',lambda:'b'*40)
    monkeypatch.setattr(ch6_small_release,'audit',lambda release:dict(success=True))
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fake-never-sent')
    real_usage=campaign.usage
    def incomplete_counts(root):
        result=real_usage(root)
        if result['sealed_cells']==174:result['sealed_cells']=173
        return result
    monkeypatch.setattr(campaign,'usage',incomplete_counts)
    def run(**kwargs):
        manifest=recovery.reader()[0](dict(path=kwargs['manifest_path'],sha256=kwargs['manifest_sha256']))
        root=Path(kwargs['output']);root.mkdir(parents=True,exist_ok=True);attempts=0
        for cell in manifest['cells']:
            dest=root/'cells'/cell['cell_id']
            if dest.exists():continue
            dest.mkdir(parents=True);attempts+=1
            receipt=write_once(dest/'receipt.json',dict(model_calls=1,input_tokens=10,output_tokens=2))
            write_once(dest/'terminal.json',dict(outcome=receipt))
            if attempts>=kwargs['max_new_cells']:break
        return dict(status='returned',new_cells=attempts,receipt=None)
    monkeypatch.setattr(batch,'run',run)
    result=recovery.execute(contract_pin)
    assert result['status']=='continuation_incomplete_membership'
    assert result['new_usage']['sealed_cells']==173
