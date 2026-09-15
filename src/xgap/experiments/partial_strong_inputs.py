"""Derive pinned predicate-hole inputs without reading query answers or running tools."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from xgap.agent.practical_planning import program_identity
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_methods import PRACTICAL_METHODS, STRONG_METHODS
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_study import SCHEMA_V2
from xgap.experiments.resolved_strong_inputs import closed_template, SPLITS
from xgap.semantic.binding import bind_semantic_query
from xgap.semantic.program import SemanticGraphProgram, hard_constraints_sha256

SLOT='relation'
SCOPE='authored trusted predicate-hole query with supplied source assignments; not unaided NL or source discovery'


def _pin(raw, root):
    return {'path':str((root/raw['path']).resolve()),'sha256':raw['sha256']}


def partial_template(program, question, rule, *, template_id):
    """Only exact edge-label occurrences change; repeated uses share one slot."""
    if set(rule)!={'predicate','phrases'} or not isinstance(rule['predicate'],str):
        raise ValueError('Explicit family predicate and phrase rule required')
    template=deepcopy(closed_template(program,question,template_id=template_id))
    changed=[]
    for op in template['operators']:
        edge=op['parameters'].get('edge')
        if op['kind']=='match' and isinstance(edge,dict) and edge.get('label')==rule['predicate']:
            edge['label']={'$hole':SLOT};changed.append(op['operator_id'])
            if len(changed)==1:op['hole_ids']=[SLOT]
    if not changed:raise ValueError('Declared predicate has no edge-label occurrence')
    template['holes']=[{'hole_id':SLOT,'kind':'predicate','phrases':rule['phrases'],'required':True}]
    template['metadata']['input_scope']=SCOPE
    return template,changed


def publish_partial_cohort(*,cohort_path,cohort_sha256,policy_path,policy_sha256,output,
        rdf_mapping_path=None,rdf_mapping_sha256=None):
    started=time.perf_counter();origin=Path(cohort_path).resolve().parent
    cohort=json.loads(read_pinned(cohort_path,cohort_sha256))
    rows=cohort.get('groups',[])
    if (cohort.get('schema_version')!='xgap-resolved-strong-cohort-v1' or not 1<=len(rows)<=128 or
            cohort['instance_count']!=len(rows) or len({r['question_id'] for r in rows})!=len(rows) or
            dict(Counter(r['split'] for r in rows))!=cohort['split_counts'] or
            set(cohort['split_counts'])-set(SPLITS)):
        raise ValueError('An intact bounded resolved cohort with declared splits is required')
    policy=json.loads(read_pinned(policy_path,policy_sha256));policy_root=Path(policy_path).resolve().parent
    if (set(policy)!={'schema_version','policy_id','scope','family_rules','candidate_ids','model_provider','modes'} or
            policy['schema_version']!='xgap-partial-strong-input-policy-v1' or
            set(r['family'] for r in rows)-set(policy['family_rules'])):
        raise ValueError('Explicit candidate policy and a rule for every family are required')
    candidates=policy['candidate_ids']
    if not isinstance(candidates,list) or not 2<=len(candidates)<=8 or len(set(candidates))!=len(candidates):
        raise ValueError('Two to eight distinct frozen predicate candidates are required')
    modes=policy['modes']
    if (set(modes)!={'exact','performance'} or modes['exact']['semantic']['allowed_unvalidated']!=[] or
            modes['performance']['semantic']['allowed_unvalidated']!=[SLOT] or
            any(set(m['actions'])!={'relation-model','relation-authority'} for m in modes.values()) or
            modes['exact']['actions']!=modes['performance']['actions']):
        raise ValueError('Candidate modes require matched actions and explicit slot permissions')
    provider=deepcopy(policy['model_provider']);provider['prompt']=_pin(provider['prompt'],policy_root)
    rdf=rdf_mapping_path is not None
    if rdf!=(rdf_mapping_sha256 is not None):raise ValueError('RDF mapping path and hash must be supplied together')
    mapping={'path':str(Path(rdf_mapping_path).resolve()),'sha256':rdf_mapping_sha256} if rdf else None
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    groups={s:[] for s in SPLITS};published=[];dependency_reads=0
    for i,row in enumerate(rows):
        previous=_pin(row['profile'],origin);previous_root=Path(previous['path']).parent
        old=json.loads(read_pinned(previous['path'],previous['sha256']))
        if old['dataset']!=cohort['dataset']:raise ValueError('Per-question dataset differs from cohort')
        request_pin=_pin(row['request'],origin);request=json.loads(read_pinned(request_pin['path'],request_pin['sha256']))
        if (request.get('schema_version')!='xgap-practical-request-v1' or
                any(request.get(k)!={} for k in ('trusted_bindings','predictions','clarifications'))):
            raise ValueError('Derivation requires the resolved request, without preexisting binding inputs')
        semantic_pin=_pin(row['authored_semantics_as_explicit_input'],origin)
        semantic=json.loads(read_pinned(semantic_pin['path'],semantic_pin['sha256']))
        if semantic['family']!=row['family'] or request['question_id']!=row['question_id']:
            raise ValueError('Question/family identity differs')
        program=SemanticGraphProgram.from_dict(semantic['program']);rule=policy['family_rules'][row['family']]
        template,occurrences=partial_template(program,request['question'],rule,template_id=f'partial-finbench-{i:03}')
        directory=root/f'group-{i:03}';directory.mkdir()
        intake_pin=write_once(directory/'intake.json',template)
        common={k:deepcopy(old[k]) for k in ('dataset','catalog','estimator','sources','backends')}
        refs=[common['catalog']]+([common['estimator']] if common['estimator'] is not None else [])
        refs += [s['equality_key_bounds'] for s in common['sources'].values() if 'equality_key_bounds' in s]
        for ref in refs:ref['path']=str((previous_root/ref['path']).resolve())
        for spec in common['backends'].values():spec['client']['url']='http://127.0.0.1:1'
        annotation={'kind':'clarification','slot':SLOT,'candidate_ids':candidates,
            'source_id':'finbench-authored-semantic-annotation','version':semantic_pin['sha256'],'failed_outcomes':[]}
        doc={**common,'schema_version':'xgap-frozen-practical-profile-v1','profile_id':f'{policy["policy_id"]}:{i:03}',
            'intake':_pin(intake_pin,directory),'operator_sources':semantic['operator_sources'],
            'acquisitions':{'relation-model':{'kind':'model','slot':SLOT,'candidate_ids':candidates,'provider':provider},
                'relation-authority':annotation},'modes':modes,
            'offline':{'input_scope':SCOPE,'derived_from':previous,'authored_semantics_as_explicit_input':semantic_pin,
                'policy':{'path':str(Path(policy_path).resolve()),'sha256':policy_sha256},
                'source_assignment_scope':'supplied authored input, equally available to methods; no source-discovery claim',
                'formal_campaign_ready':False,'catalog_builds':0,'fit_calls':0,'initial_predictions_supplied':False}}
        if rdf:doc['external_frontend']={'policy':'fixed_action_order_v1','mapping':mapping}
        profile_pin=write_once(directory/'profile.json',doc)
        profile,cfg=FrozenPracticalProfile.load_materialized(profile_pin['path'],expected_sha256=profile_pin['sha256'])
        dependency_reads+=1
        intended=[c for c in candidates if cfg[2].bindings[c].value==rule['predicate']]
        if len(intended)!=1:raise ValueError('Exactly one declared predicate binding must restore authored meaning')
        raw={**request,'trusted_bindings':{},'predictions':{},'clarifications':{}}
        q=profile.prepare(raw,request_sha256=request_pin['sha256'],request_root=directory,mode='exact',materialized=cfg)
        resolution={'program_id':q.program.program_id,'hard_constraints_sha256':hard_constraints_sha256(q.program),
            'hard_constraints_preserved':True,'candidate_sets':[{'hole_id':SLOT,'candidate_ids':intended,'authoritative':True}]}
        restored=bind_semantic_query(q.program,resolution,binding_values=cfg[2].bindings,operator_sources=doc['operator_sources'])
        if ([o.to_dict() for o in restored.program.operators]!=[o.to_dict() for o in program.operators] or
                restored.program.roots!=program.roots or restored.operator_sources!=semantic['operator_sources']):
            raise ValueError('Partial input changes more than the declared relation binding')
        answer=write_once(directory/'authority.json',{'schema_version':'xgap-clarification-bindings-v1',
            'program_sha256':program_identity(q.program),'source_id':annotation['source_id'],'version':annotation['version'],
            'bindings':{SLOT:intended[0]}})
        raw['clarifications']={'relation-authority':_pin(answer,directory)}
        request_out=write_once(directory/'request.json',raw)
        for mode in modes:profile.prepare(raw,request_sha256=request_out['sha256'],request_root=directory,mode=mode,materialized=cfg)
        group={'request':request_out,'profile':profile_pin,'reference':_pin(row['reference'],origin)}  # Never open reference.
        groups[row['split']].append(group)
        published.append({**{k:row[k] for k in ('question_id','family','split')},**group,
            'intake':intake_pin,'authority':answer,'changed_operator_ids':occurrences,
            'original_request':request_pin,'authored_semantics_as_explicit_input':semantic_pin})
    methods=list(PRACTICAL_METHODS if rdf else STRONG_METHODS)
    studies={s:write_once(root/f'{s}-study-input.json',{'schema_version':SCHEMA_V2,
        'study_id':f'{policy["policy_id"]}:{s}','methods':methods,'groups':gs}) for s,gs in groups.items() if gs}
    return write_once(root/'manifest.json',{'schema_version':'xgap-partial-strong-cohort-v1','input_scope':SCOPE,
        'dataset':cohort['dataset'],'instance_count':len(published),'split_counts':cohort['split_counts'],
        'original_resolved_cohort':{'path':str(Path(cohort_path).resolve()),'sha256':cohort_sha256},
        'policy':{'path':str(Path(policy_path).resolve()),'sha256':policy_sha256},'groups':published,'study_inputs':studies,
        'reference_contents_read':False,'model_calls':0,'backend_calls':0,'planning_runs':0,'catalog_builds':0,'fit_calls':0,
        'catalog_admission_count':dependency_reads,'offline_preparation_ms':(time.perf_counter()-started)*1000,
        'automatic_retries':0,'formal_campaign_ready':False,'paper_result':False,
        'release_status':'candidate; development feasibility, information-cost basis and paper profile discussion remain'})
