from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_ch6_small_release import fixture
from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.ch6_small_migration import (
    CASE_FIELDS,PROVIDER,SCHEMA,prepare,verify_migration,verify_selection,original_cells)
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.compact_constraints_profile import PROOF_PROFILE
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.intent_scope import ScopePolicy
from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import make_family
from xgap.experiments.controlled_state import publish_state


def migrate_fixture(tmp_path,monkeypatch):
    import xgap.experiments.ch6_small_migration as migration
    parent=fixture(tmp_path)
    profile=write_once(tmp_path/'source-profile.json',dict(profile_id='frozen',offline={},source_schema={'public':'schema'}))
    for cohort in parent['cohorts']:
        cohort['profile']=profile
        cohort['prepared']=write_once(tmp_path/f"{cohort['dataset']}-{cohort['deployment']}-prepared-v2.json",
                                     dict(success=True,profile=profile))
        for case in cohort['cases']:
            cid=case['case_id'];case['template']='window_edge'
            case['request']=write_once(tmp_path/f'{cid}-public-v1.json',dict(question_id=cid,question='List matching edges.'))
            case['scope']=write_once(tmp_path/f'{cid}-scope.json',ScopePolicy('public-family',(),language_version='v2').to_dict())
            case['oracle']=write_once(tmp_path/f'{cid}-private-v1.json',dict(query={'hidden':'sentinel-never-in-public'},nonce='a'*64,
                question_sha256=fingerprint('List matching edges.')))
            query,_,family=make_family(CORES[cohort['dataset']],'window_edge',['node:1','node:2'],
                                      1000,case['workload'],'snapshot',cid)
            case['controlled_state']=write_once(tmp_path/f'{cid}-state-v2.json',
                publish_state('List matching edges.',family,query,semantic_choices=[
                    dict(name=s.name,type='coordinate',slots=[s.name]) for s in family.slots]))
        cohort['bundle']=write_once(tmp_path/f"{cohort['dataset']}-{cohort['deployment']}-bundle-v2.json",
                                   dict(profile=profile,cases=cohort['cases']))
    selection=write_once(tmp_path/'parent-selection.json',parent)
    def publish(*,parent_path,parent_sha256,output,pin_mirrors):
        root=Path(output);root.mkdir(parents=True)
        doc=load_pin(dict(path=str(parent_path),sha256=parent_sha256))
        doc['profile_id']+=':'+PROOF_PROFILE
        doc['offline']['compact_public_constraints']=write_once(root/'constraints.json',dict(public='proof'))
        return write_once(root/'profile.json',doc)
    monkeypatch.setattr(migration,'publish_compact_constraints_profile',publish)
    monkeypatch.setattr(migration,'load_public_compact_constraints',lambda *a,**k:object())
    result=prepare(selection_pin=selection,output=tmp_path/'migration')
    return result


def test_migration_preserves_all_private_intents_case_membership_and_public_sharing(tmp_path,monkeypatch):
    result=migrate_fixture(tmp_path,monkeypatch)
    doc=verify_migration(result['migration']);selection=load_pin(result['selection'])
    verify_selection(selection,doc)
    assert len(doc['cohorts'])==6 and sum(len(c['cases']) for c in doc['cohorts'])==48
    assert result['model_calls']==result['backend_calls']==result['submitted_jobs']==0
    for cohort in doc['cohorts']:
        for case in cohort['cases']:
            request=load_pin(case['request']);old=load_pin(case['original_request'])
            assert request['question_id']==old['question_id']==case['case_id']
            assert 'sentinel' not in json.dumps(request)
            newprivate=load_pin(case['oracle']);oldprivate=load_pin(case['original_oracle'])
            assert newprivate['query']==oldprivate['query'] and newprivate['nonce']==oldprivate['nonce']
            assert newprivate['question_sha256']==fingerprint(request['question'])
            cells=[dict(cell_id=case['case_id']+'-'+m,method=m,request=case['request'],reference=case['reference'])
                   for m in ('XGAP','NP','SH','GR','TS')]
            mapped=original_cells(cells,cohort)
            assert all(c['request']==case['original_request'] for c in mapped)
            assert all(c['reference']==case['reference'] for c in mapped)


@pytest.mark.parametrize('change',['query','nonce','wording','profile'])
def test_migration_rejects_meaning_or_source_changes_even_with_new_valid_pins(tmp_path,monkeypatch,change):
    result=migrate_fixture(tmp_path,monkeypatch);doc=load_pin(result['migration'])
    cohort=doc['cohorts'][0];case=cohort['cases'][0]
    if change in ('query','nonce'):
        private=load_pin(case['oracle']);private[change]='changed'
        case['oracle']=write_once(tmp_path/'tampered-private.json',private)
    elif change=='wording':
        public=load_pin(case['request']);public['question']+=' Use a different condition.'
        case['request']=write_once(tmp_path/'tampered-request.json',public)
    else:
        profile=load_pin(cohort['entry_profile']);profile['source_schema']['public']='other'
        cohort['entry_profile']=write_once(tmp_path/'tampered-profile.json',profile)
    changed=write_once(tmp_path/'tampered-migration.json',doc)
    with pytest.raises(ValueError):verify_migration(changed)


def test_migration_rejects_reference_change_and_selection_reweighting(tmp_path,monkeypatch):
    result=migrate_fixture(tmp_path,monkeypatch);doc=verify_migration(result['migration'])
    selection=load_pin(result['selection']);selection['cohorts'][0]['cases'][0]['workload']='W4'
    with pytest.raises(ValueError,match='selection'):verify_selection(selection,doc)
    case=doc['cohorts'][0]['cases'][0]
    with pytest.raises(ValueError,match='Method input'):
        original_cells([dict(request=case['request'],reference=case['oracle'])],doc['cohorts'][0])


def test_migrated_release_has_216_requests_all_methods_share_new_words(tmp_path,monkeypatch):
    from dataclasses import asdict
    import prepare_ch6_small_release as publisher
    import release_ch6_five_method_batch as batch_publisher
    import run_bounded_joint_batch as batch
    import xgap.experiments.ch6_backend_eligibility as eligibility
    from xgap.agent.live_probe import LiveProbePolicy
    from xgap.experiments.unified_contract import configuration
    result=migrate_fixture(tmp_path,monkeypatch)
    # Exercise the actual question/state identity guard, not a stubbed config.
    from prepare_ch6_execution_units import case_configuration
    first=load_pin(result['selection'])['cohorts'][0]['cases'][0]
    with pytest.raises(ValueError,match='Controlled state identity'):
        case_configuration(first)
    monkeypatch.setattr(publisher,'source_commit',lambda:'a'*40)
    monkeypatch.setattr(batch_publisher,'source_commit',lambda:'a'*40)
    monkeypatch.setattr(batch_publisher,'validate',lambda manifest:None)
    monkeypatch.setattr(batch,'validate',lambda manifest:None)
    monkeypatch.setattr(eligibility,'eligible',lambda *a,**k:True)
    monkeypatch.setattr(eligibility,'check_design',lambda *a,**k:None)
    policy=write_once(tmp_path/'probe.json',asdict(LiveProbePolicy(policy_id='test',basis='Frozen toy priors')))
    spec=write_once(tmp_path/'spec.json',dict(schema_version='xgap-ch6-small-release-input-v1',selection=result['selection'],
        live_probe_policy=policy,output_root=str(tmp_path/'runs'),budget=dict(total_wall_seconds=14400,
        package_max_bytes=1000000,free_disk_reserve_bytes=1,model_calls_cap=1728,
        input_tokens_stop_threshold=1000000,output_tokens_stop_threshold=500000)))
    published=publisher.prepare(spec['path'],spec['sha256'],tmp_path/'release')
    assert published['audit_passed'],published['failed_checks']
    release=load_pin(published['release']);rows=[]
    for unit in release['units']:
        manifest=load_pin(unit['manifest']);rows+=manifest['cells']
        assert manifest['entry_migration']==result['migration']
        for cell in manifest['cells']:
            if cell['method']=='aruqula-fedx':assert 'oracle' not in cell and 'config' not in cell
            else:assert load_pin(cell['config'])['provider']==PROVIDER
        by_case={}
        for cell in manifest['cells']:
            cid=unit['cell_cases'][cell['cell_id']]
            by_case.setdefault(cid,[]).append(cell['request'])
        assert all(all(p==pins[0] for p in pins) for pins in by_case.values())
    assert len(rows)==216
