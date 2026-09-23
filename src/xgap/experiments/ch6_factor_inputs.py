"""Actual bounded N/u families, with correlation disclosed at fixed N.

This is a controlled-state factor cohort. It does not relabel repeated requests
as new interpretations, and its correlated family is not an NL scope policy.
"""
from copy import deepcopy
import json
from pathlib import Path
import random

from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,IntentSlot,canonical,fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.experiments.ch6_fact_index import pin,verify,read_index,write
from xgap.experiments.ch6_heldout import choose_anchors,predicate,ref,structure_identity
from xgap.experiments.ch6_sql_reference import evaluate
from xgap.experiments.controlled_state import publish_state,read_state
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.compact_query import validate_query
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.intent_scope import ScopePolicy

N_LEVELS=(10,50,100,500,1000,16,64,256,1024)
U_LEVELS=(1,2,3,5,8)
NAMES=('anchor','control','lower_time','upper_time','lower_measure','upper_measure','lower_target','upper_target')


def source_bounds(index):
    with read_index(index['database']['path']) as db:
        t0,t1,v0,v1=db.execute('SELECT min(ts),max(ts),min(value),max(value) FROM edges').fetchone()
        ids=[r[0] for r in db.execute('SELECT id FROM nodes WHERE kind=? ORDER BY id',(index['core']['target_type'],))]
        edge_count=db.execute('SELECT count(*) FROM edges').fetchone()[0]
        edge_ids=tuple(db.execute('SELECT id FROM edges ORDER BY id LIMIT 1 OFFSET ?',(i,)).fetchone()[0]
                       for i in (0,edge_count//4,3*edge_count//4,edge_count-1))
    if len(ids)<4 or t0==t1 or v0==v1 and index['dataset']!='D1':raise ValueError('Degenerate source factor range')
    # D1's unit measure is constant: two genuine edge-identity range choices
    # replace measure ranges there. No duplicate constants are called ambiguity.
    return dict(time=(t0,index['scope_cut_ms'],t1),measure=(v0,(v0+v1)/2,v1),
                edge_id=edge_ids,target=(ids[0],ids[len(ids)//4],ids[3*len(ids)//4],ids[-1]))


def build_family(core,bounds,anchors,*,n,u,snapshot,family_id):
    if not 1<=n<=1024 or not 1<=u<=8:raise ValueError('Factor representation bound exceeded')
    if u>3 and n!=8:raise ValueError('Higher-u cohort has declared fixed N=8 correlations')
    needed=n if u==1 else (n+1)//2 if u==2 else (n+3)//4
    if len(anchors)<needed or len(set(anchors))!=len(anchors):raise ValueError('Insufficient unique source anchors')
    t0,tm,t1=bounds['time'];v0,vm,v1=bounds['measure'];b0,bq,bt,b1=bounds['target']
    measure_property=core['measure'];low_values=(v0,vm);high_values=(vm,v1);names=NAMES
    if v0==v1:
        e0,eq,et,e1=bounds['edge_id'];measure_property='id';v0,v1=e0,e1
        low_values=(e0,eq);high_values=(et,e1);names=(*NAMES[:4],'lower_edge_id','upper_edge_id',*NAMES[6:])
    options=(anchors,core['control_values'],(t0,tm),(tm,t1),low_values,high_values,(b0,bq),(bt,b1))
    q=dict(nodes=[dict(var='a',type=core['node_type'],entity=None),dict(var='b',type=core['target_type'],entity=None)],
        edges=[dict(var='e',type=core['relation'],source='a',target='b')],path=None,
        where=[predicate('a','id','eq',anchors[0]),predicate('b',core['control'],'eq',core['control_values'][0]),
               predicate('e','timestamp','ge',t0),predicate('e','timestamp','le',t1),
               predicate('e',measure_property,'ge',v0),predicate('e',measure_property,'le',v1),
               predicate('b','id','ge',b0),predicate('b','id','le',b1)],
        select={'result':ref('b')},contribution_by=None,order_by=[dict(field='result',direction='asc')],limit=20)
    candidates=[]
    for i in range(n):
        query=deepcopy(q)
        # First three choices enumerate distinct anchor/control/time tuples.
        codes=(i if u==1 else i//2 if u==2 else i//4,(i if u==2 else i//2)%2,i%2,
               ((i>>2)^(i>>1))&1,((i>>2)^i)&1,((i>>1)^i)&1,((i>>2)^(i>>1)^i)&1,(i>>2)&1)
        for j in range(u):query['where'][j]['right']['value']=options[j][codes[j]]
        validate_query(query,version='v2');candidates.append(IntentCandidate.create(fingerprint(query),query))
    slots=tuple(IntentSlot(name,('where',i,'right','value')) for i,name in enumerate(names[:u]))
    family=IntentFamily(family_id,tuple(candidates),slots,snapshot,language_version='v2')
    if len({c.query_json for c in candidates})!=n:raise ValueError('Repeated queries are not N distinct interpretations')
    return family


def publish(*,index_receipt,profile_path,profile_sha256,output,seed=20260923):
    index=json.loads(Path(index_receipt).read_text());verify(index['database'])
    if not index.get('success'):raise ValueError('Successful source index required')
    profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
    doc,_,_,sources,backends,_,_=profile.materialize();snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    materialization=json.loads(Path(doc['offline']['materialization']['path']).read_text());verify(doc['offline']['materialization'])
    if materialization['index_receipt']['sha256']!=pin(index_receipt)['sha256']:raise ValueError('Source snapshot differs')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    bounds=source_bounds(index);write(root/'source-bounds.json',bounds)
    cases=[];excluded=[];receipt=dict(success=False,model_calls=0,backend_calls=0,formal_campaign_ready=False)
    try:
        for stratum in ('uniform','active-anchor'):
            anchors=choose_anchors(index,stratum=stratum,size=256,seed=f'{seed}:factors:{stratum}',scale=materialization['scale'])
            for factor,levels in (('N',N_LEVELS),('u',U_LEVELS)):
                for level in levels:
                    n,u=(level,3) if factor=='N' else (8,level)
                    cid=f"{index['dataset']}-factor-{stratum}-{factor}-{level}"
                    family=build_family(index['core'],bounds,anchors,n=n,u=u,snapshot=snapshot,family_id=cid)
                    # Choose private intent before any independent answer or method call.
                    query=json.loads(random.Random(str(seed)+cid).choice(family.candidates).query_json)
                    question='Controlled query-state study: resolve the published choices for anchor, recipient attribute, and declared range bounds; return up to 20 distinct target IDs in ascending order.'
                    directory=root/cid;directory.mkdir();write(directory/'private-preselection.json',dict(query=query,seed=seed))
                    state=publish_state(question,family,query,semantic_choices=[dict(name=s.name,type='query_coordinate',slots=[s.name]) for s in family.slots])
                    _,_,actual=read_state(state,question)
                    if (actual['initial_candidate_count'],actual['initial_ambiguity'])!=(n,u):raise ValueError('Actual factor differs from label')
                    max_ops=0;used=set()
                    for c in family.candidates:
                        program,assignment=lower_compact_query(json.loads(c.query_json),doc['source_schema'],version='v2',optimize=True)
                        max_ops=max(max_ops,len(program.operators));used.update(assignment.values())
                    if max_ops>64:raise ValueError('Actual factor exceeds physical operator bound')
                    expected=evaluate(query,index_receipt,scale=materialization['scale'])
                    request=write_once(directory/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',question_id=cid,
                        question=question,population=index['dataset']+' '+stratum+' controlled factor cohort',exposure='test'))
                    scope=write_once(directory/'scope.json',ScopePolicy(cid,(),language_version='v2').to_dict())
                    oracle=write_once(directory/'private-user.json',private_query_intent(question,query,language_version='v2'))
                    state_pin=write_once(directory/'controlled-state.json',state)
                    reference=write_once(directory/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',dataset=doc['dataset'],
                        question_id=cid,query_sha256=fingerprint(query),source_snapshot_sha256=snapshot,
                        ordered=True,normalization=dict(schema_version='xgap-row-normalization-v1',fields=dict(result='text')),rows=expected['rows']))
                    write(directory/'reference-evidence.json',expected)
                    cases.append(dict(case_id=cid,factor=factor,level=level,stratum=stratum,actual_N=n,actual_u=u,
                        request=request,scope=scope,oracle=oracle,controlled_state=state_pin,reference=reference,
                        reference_engine='independent_relational',source_snapshot_sha256=snapshot,max_operators=max_ops,
                        contributing_sources=sorted(used),template_family=structure_identity(query),
                        correlations='Explicit finite relation of coordinate values; no independence assumption',
                        nl_interface='unsupported: placeholder scope is not the correlated family; controlled_state is mandatory'))
        write(root/'bundle.json',dict(schema_version='xgap-ch6-factor-inputs-v1',input_track='controlled',dataset=index['dataset'],
            cases=cases,excluded=excluded,model_outputs_used=False,backend_admission='required',
            TS_reference='One fixed public NL configuration per cohort, no controlled-family injection; score only comparable metrics'))
        receipt.update(success=True,bundle=pin(root/'bundle.json'),cases=len(cases),excluded=excluded)
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    write(root/'receipt.json',receipt);return receipt
