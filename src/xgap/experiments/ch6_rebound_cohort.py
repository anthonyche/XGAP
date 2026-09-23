"""Bind a fixed held-out semantic cohort to actual source/scale variants.

Selection uses template/workload/frame/ID only. Source-count changes must retain
the exact query and independent answer. Scale changes retain the query but may
change answers; full-source active-anchor eligibility is held fixed across scale.
No model, method, measured cost, or answer is used to select a case.
"""
from dataclasses import replace
import json
from pathlib import Path

from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.ch6_fact_index import pin, write
from xgap.experiments.ch6_sql_reference import evaluate
from xgap.experiments.controlled_state import publish_state, read_state
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.semantic.compact_lowering import lower_compact_query


def select_cases(bundles, *, per_frame=1):
    if type(per_frame) is not int or not 1 <= per_frame <= 100:
        raise ValueError('Explicit bounded per-frame sample required')
    cases=[];seen=set()
    for bundle in bundles:
        if (bundle['schema_version']!='xgap-ch6-heldout-cases-v1' or bundle['split']!='test'
                or bundle['method_outputs_used_for_selection'] is not False or bundle['dataset']!='D1'):
            raise ValueError('Source/scale study uses the frozen D1 held-out family')
        for c in bundle['cases']:
            if c['case_id'] in seen:raise ValueError('Duplicated base semantic case')
            seen.add(c['case_id'])
            if c['template']=='window_edge' and c['workload']=='W3':cases.append(c)
    chosen=[]
    for frame in ('uniform','active-anchor'):
        group=sorted((c for c in cases if c['stratum']==frame),key=lambda c:c['case_id'])
        if len(group)<per_frame:raise ValueError('Base cohort cannot supply the frozen sample')
        chosen.extend(group[:per_frame])
    return chosen


def publish(*,base_bundles,index_receipt,prepared_pin,factor,output,per_frame=1):
    if factor not in ('sources','graph_scale'):raise ValueError('Unknown deployment factor')
    bundles=[load(p) for p in base_bundles];chosen=select_cases(bundles,per_frame=per_frame)
    for bundle in bundles:
        parent_profile=load(bundle['profile'])
        parent_materialization=load(parent_profile['offline']['materialization'])
        if parent_materialization['index_receipt']['sha256']!=pin(index_receipt)['sha256']:
            raise ValueError('Base cohort belongs to a different original source index')
    prepared=load(prepared_pin)
    if not prepared.get('success'):raise ValueError('Actual prepared stores required')
    profile_pin=prepared['profile']
    profile=FrozenOneShotProfile.load(profile_pin['path'],expected_sha256=profile_pin['sha256'])
    doc,_,_,sources,backends,_,_=profile.materialize()
    if any(s['client']['engine']!='fuseki' for s in doc['backends'].values()):
        raise ValueError('Declared source/scale studies use common RDF')
    materialization=load(doc['offline']['materialization'])
    if materialization['index_receipt']['sha256']!=pin(index_receipt)['sha256']:
        raise ValueError('Variant was not materialized from the frozen source index')
    scale=materialization['scale'];source_count=materialization['source_count']
    level=source_count if factor=='sources' else float(scale)
    if factor=='sources' and (scale!='1' or level not in (2,4,8)):
        raise ValueError('Source sweep must keep original facts and admitted source counts')
    if factor=='graph_scale' and (source_count!=2 or scale not in ('.25','1','4')):
        raise ValueError('Scale sweep must keep two sources and admitted scale levels')
    snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    write(root/'preselection.json',dict(base_bundles=base_bundles,selected_case_ids=[c['case_id'] for c in chosen],
        factor=factor,level=level,per_frame=per_frame,method_outputs_used=False,answers_used_for_selection=False,
        rule='D1 test/window_edge/W3, case-ID order in each original full-source sampling frame'))
    cases=[]
    for base in chosen:
        cid=f'D1-{factor}-{level}-'+base['case_id'];directory=root/cid;directory.mkdir()
        request=load(base['request']);oracle=load(base['oracle']);old=load(base['controlled_state'])
        family,_,state=read_state(old,request['question']);family=replace(family,source_snapshot=snapshot)
        controlled=publish_state(request['question'],family,oracle['query'],
            clue_names=tuple(old['initial_clues']),semantic_choices=old['semantic_choices'])
        max_ops=0;used=set()
        for candidate in family.candidates:
            program,assignment=lower_compact_query(json.loads(candidate.query_json),doc['source_schema'],version='v2',optimize=True)
            max_ops=max(max_ops,len(program.operators));used.update(assignment.values())
        if max_ops>64:raise ValueError('Deployment variant exceeds the admitted operator bound')
        expected=evaluate(oracle['query'],index_receipt,scale=scale)
        parent_reference=load(base['reference']);norm=parent_reference['normalization']
        rows=normalize_rows(expected['rows'],norm)
        if factor=='sources' and rows!=normalize_rows(parent_reference['rows'],norm):
            raise ValueError('Source partition changed the fixed-query reference answer')
        request={**request,'question_id':cid,'population':'D1 fixed-semantic '+factor+' sweep; '+base['stratum']}
        reference={**parent_reference,'question_id':cid,'source_snapshot_sha256':snapshot,'rows':rows}
        references={k:write_once(directory/(k+'.json'),v) for k,v in dict(request=request,oracle=oracle,
            scope=load(base['scope']),controlled_state=controlled,reference=reference).items()}
        write(directory/'reference-evidence.json',expected)
        cases.append({**base,**references,'case_id':cid,'base_case_id':base['case_id'],'deployment':'rdf',
            'source_snapshot_sha256':snapshot,'contributing_sources':sorted(used),'max_operators':max_ops,
            'factor':factor,'level':level,'actual_N':state['initial_candidate_count'],'actual_u':state['initial_ambiguity'],
            'query_sha256':fingerprint(oracle['query'])})
    bundle=dict(schema_version='xgap-ch6-deployment-factor-v1',dataset='D1',split='test',input_track='controlled',
        factor=factor,level=level,cases=cases,profile=profile_pin,deployment='rdf',base_bundles=base_bundles,
        scale=scale,source_count=source_count,materialization=doc['offline']['materialization'],
        method_outputs_used_for_selection=False,template_splits=bundles[0]['template_splits'],
        preselection=pin(root/'preselection.json'),sampling_frame='fixed original full-source frame',
        backend_admission='required; materialization/compiler alone do not establish successful execution')
    result=write_once(root/'bundle.json',bundle)
    write(root/'receipt.json',dict(success=True,bundle=result,cases=len(cases),model_calls=0,backend_calls=0,formal_campaign_ready=False))
    return result
