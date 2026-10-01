"""Version public wording and proved source contracts without resampling cases.

Preparation/audit may compare private files to prove an unchanged intent. Their
query and nonce never supply public text and never leave this offline verifier.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.ch6_entry_gate import locate, load
from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_formal_protocol import load_pin, METHODS
from xgap.experiments.ch6_heldout import QUESTION_VERSION, public_edge_role_text
from xgap.experiments.compact_constraints_profile import (
    PROOF_PROFILE, publish_compact_constraints_profile, load_public_compact_constraints)
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.intent_scope import ScopePolicy

SCHEMA='xgap-ch6-small-public-contract-migration-v1'
PROVIDER='frozen_compact_model_public_contract_v1'
CASE_FIELDS=('request','oracle','reference','scope','controlled_state')


def same_pin(a,b):
    return isinstance(a,dict) and isinstance(b,dict) and all(a.get(k)==b.get(k) for k in ('path','sha256'))


def _absolute(value,root):
    if isinstance(value,list):return [_absolute(v,root) for v in value]
    if isinstance(value,dict):
        return {k:os.path.abspath(Path(root)/v) if k=='path' and isinstance(v,str) else _absolute(v,root)
                for k,v in value.items()}
    return value


def revised_request(original,case,domain,scope):
    """All five methods receive these same public words; identity stays stable."""
    return {**original,'question':original['question']+' '+public_edge_role_text(CORES[domain],case['template'],scope)}


def verify_migration(pin,*,reader=load_pin,pin_mirrors=()):
    doc=reader(pin)
    if (doc.get('schema_version')!=SCHEMA or doc.get('question_version')!=QUESTION_VERSION
            or doc.get('provider')!=PROVIDER or doc.get('methods')!=list(METHODS)):
        raise ValueError('Explicit shared public-input migration required')
    parent=reader(doc['parent_selection'])
    parents={(c['dataset'],c['deployment']):c for c in parent['cohorts']}
    if len(parents)!=6 or len(doc['cohorts'])!=6:raise ValueError('All six original cohorts are required')
    seen=set();count=0
    for cohort in doc['cohorts']:
        key=(cohort['dataset'],cohort['deployment'])
        if key in seen or key not in parents:raise ValueError('Duplicate or unknown migration cohort')
        seen.add(key);old=parents[key]
        for field in ('prepared','profile','bundle','backend_admission'):
            if not same_pin(cohort['parent_'+field],old[field]):raise ValueError('Original deployment/admission changed')
        old_profile=reader(old['profile']);new_profile=reader(cohort['entry_profile'])
        check=deepcopy(new_profile);constraints_pin=check['offline'].pop('compact_public_constraints',None)
        check['profile_id']=check['profile_id'].removesuffix(':'+PROOF_PROFILE)
        if (constraints_pin is None or check!=_absolute(old_profile,Path(old['profile']['path']).parent)
                or new_profile['profile_id']!=old_profile['profile_id']+':'+PROOF_PROFILE):
            raise ValueError('Derived profile changes more than the proved public contract')
        # Verify the contract and its source proof against the derived profile.
        load_public_compact_constraints(new_profile,
            profile_root=Path(cohort['entry_profile']['path']).parent,pin_mirrors=pin_mirrors)
        originals={c['case_id']:c for c in old['cases']}
        if [c['case_id'] for c in cohort['cases']]!=old['case_ids']:raise ValueError('Selected case order or membership changed')
        for case in cohort['cases']:
            previous=originals[case['case_id']];scope=ScopePolicy.from_dict(reader(previous['scope']))
            for field in CASE_FIELDS:
                if not same_pin(case['original_'+field],previous[field]):raise ValueError('Original case pin changed')
            for field in ('reference','scope','controlled_state'):
                if case[field]!=previous[field]:raise ValueError('Reference, scope or controlled query changed')
            original=reader(case['original_request']);new=reader(case['request'])
            if new!=revised_request(original,previous,key[0],scope):raise ValueError('Public wording migration exceeds static edge-role addendum')
            private=reader(case['original_oracle']);revised=reader(case['oracle'])
            if (private['question_sha256']!=fingerprint(original['question']) or
                    revised!={**private,'question_sha256':fingerprint(new['question'])}):
                raise ValueError('Private query/nonce changed beyond question binding')
            count+=1
    if count!=48:raise ValueError('Exactly the original 48 questions are required')
    return doc


def migration_cohort(pin,*,prepared_pin,entry_profile_pin,reader=load_pin,pin_mirrors=()):
    doc=verify_migration(pin,reader=reader,pin_mirrors=pin_mirrors)
    matches=[c for c in doc['cohorts'] if same_pin(c['parent_prepared'],prepared_pin)
             and same_pin(c['entry_profile'],entry_profile_pin)]
    if len(matches)!=1:raise ValueError('Migration must match exactly one original prepared deployment')
    return matches[0]


def original_cells(cells,cohort):
    """Restore ONLY public request pins for checking prior backend admission."""
    by_request={(c['request']['path'],c['request']['sha256']):c for c in cohort['cases']}
    result=[]
    for cell in cells:
        case=by_request.get((cell['request']['path'],cell['request']['sha256']))
        if case is None or not same_pin(case['reference'],cell['reference']):
            raise ValueError('Method input differs from the frozen shared migration')
        for field in ('oracle','scope'):
            if field in cell and not same_pin(cell[field],case[field]):raise ValueError('Method private/scope pin differs')
        result.append({**cell,'request':case['original_request']})
    return result


def verify_selection(selection,migration,*,reader=load_pin):
    """No changes to W/frame/source/selection metadata or historical admissions."""
    original=reader(migration['parent_selection'])
    expected=deepcopy(original)
    expected['entry_migration']=selection['entry_migration'];expected['question_version']=QUESTION_VERSION
    for cohort,change in zip(expected['cohorts'],migration['cohorts']):
        if (cohort['dataset'],cohort['deployment'])!=(change['dataset'],change['deployment']):
            raise ValueError('Migration cohort order changed')
        cohort['entry_profile']=change['entry_profile']
        for case,row in zip(cohort['cases'],change['cases']):
            case.update(request=row['request'],oracle=row['oracle'])
    if selection!=expected:raise ValueError('Public migration changed frozen selection or deployment metadata')


def prepare(*,selection_pin,output,pin_mirrors=(),proof_mirrors=()):
    parent=load(selection_pin,pin_mirrors)
    if parent.get('unique_query_intent_cases')!=48 or 'entry_migration' in parent:
        raise ValueError('Original frozen 48-case selection required')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    changed=deepcopy(parent);cohorts=[]
    for old,new in zip(parent['cohorts'],changed['cohorts']):
        name=old['dataset']+'-'+old['deployment'];folder=root/name;folder.mkdir()
        profile=publish_compact_constraints_profile(parent_path=locate(old['profile'],pin_mirrors),
            parent_sha256=old['profile']['sha256'],output=folder/'profile',pin_mirrors=proof_mirrors)
        new['entry_profile']=profile;rows=[]
        for previous,case in zip(old['cases'],new['cases']):
            original=load(previous['request'],pin_mirrors)
            scope=ScopePolicy.from_dict(load(previous['scope'],pin_mirrors))
            revised=revised_request(original,previous,old['dataset'],scope)
            private=load(previous['oracle'],pin_mirrors)
            if private['question_sha256']!=fingerprint(original['question']):raise ValueError('Original question binding changed')
            case_root=folder/previous['case_id'];case_root.mkdir()
            case['request']=write_once(case_root/'request.json',revised)
            case['oracle']=write_once(case_root/'private-user.json',{**private,'question_sha256':fingerprint(revised['question'])})
            os.chmod(case_root/'private-user.json',0o600)
            rows.append(dict(case_id=case['case_id'],**{f'original_{k}':previous[k] for k in CASE_FIELDS},
                             **{k:case[k] for k in CASE_FIELDS}))
        cohorts.append(dict(dataset=old['dataset'],deployment=old['deployment'],
            **{f'parent_{k}':old[k] for k in ('prepared','profile','bundle','backend_admission')},
            entry_profile=profile,cases=rows))
    migration=dict(schema_version=SCHEMA,question_version=QUESTION_VERSION,provider=PROVIDER,
        parent_selection=selection_pin,methods=list(METHODS),cohorts=cohorts,
        method_results_read=0,reference_answers_read=0,model_calls=0,backend_calls=0,
        private_access='Offline equality check only; query and nonce copied unchanged; never construct public wording',
        prior_backend_admission='Reused unchanged source/query/reference; no claim of new NL backend execution')
    pin=write_once(root/'migration.json',migration)
    reader=lambda p:load(p,pin_mirrors)
    verify_migration(pin,reader=reader,pin_mirrors=proof_mirrors)
    changed.update(entry_migration=pin,question_version=QUESTION_VERSION)
    result=write_once(root/'selection.json',changed)
    write_once(root/'receipt.json',dict(success=True,selection=result,migration=pin,unique_cases=48,
        supported_requests=216,model_calls=0,backend_calls=0,submitted_jobs=0))
    return dict(selection=result,migration=pin,model_calls=0,backend_calls=0,submitted_jobs=0)
