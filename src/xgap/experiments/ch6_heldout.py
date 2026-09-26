"""Source-only cohort publication with family splits and private references.

Authored bounded graph questions, not official benchmark query cards or arbitrary
NL coverage. Selection is sealed before references; a reference/admission failure
fails publication and never replaces a sampled case with a successful one.
"""
from copy import deepcopy
import heapq
import json
from pathlib import Path
import random
import time

from xgap.agent.intent_certificate import IntentSlot, canonical, fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.experiments.ch6_fact_index import pin, read_index, verify, write
from xgap.experiments.ch6_sql_reference import evaluate
from xgap.experiments.controlled_state import publish_state, read_state
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import validate_query
from xgap.semantic.intent_scope import ScopeDomain, ScopePolicy, construct_scope


TEMPLATES = {
    'development': ('plain_edge', 'plain_count'),
    'pilot': ('incoming_minimum', 'outgoing_maximum'),
    'test': ('window_edge', 'zigzag', 'ordered_star', 'cycle', 'bounded_path',
             'witnessed_count', 'witnessed_sum', 'ranked_count'),
}
STRUCTURES = dict(window_edge='S01', zigzag='S02', ordered_star='S03', cycle='S04',
                  bounded_path='S05', witnessed_count='S06', witnessed_sum='S07', ranked_count='S08')


def ref(var, prop='id'):
    return dict(var=var, property=prop)


def predicate(var, prop, op, value):
    return dict(left=ref(var, prop), op=op, right={'value':value},
                # The three formal cores store INTEGER epoch milliseconds;
                # timestamp_ms is the separate legacy calendar-string contract.
                value_type='lexical_string' if prop=='id' and op in ('lt','le','gt','ge') else 'scalar')


def template_query(core, name, anchor, cut, *, cross=False):
    start, target, relation = core['node_type'], core['target_type'], core['relation']
    def node(v, kind): return dict(var=v,type=kind,entity=None)
    def edge(v, a, b): return dict(var=v,type=relation,source=a,target=b)
    q=dict(nodes=[node('a',start),node('b',target)],edges=[edge('e','a','b')],path=None,
        where=[predicate('a','id','eq',anchor)],select={'result':ref('b')},contribution_by=None,
        order_by=[dict(field='result',direction='asc')],limit=20)
    if name=='bounded_path':
        if start!=target:raise ValueError('Homogeneous bounded paths are not admitted on the bipartite D2 core')
        q['nodes'].append(node('c',start));q['edges']=[edge('f','c','b')]
        q['where'].append(dict(left=ref('c'),op='ne',right=ref('a'),value_type='scalar'))
        q['path']=dict(var='reach',type=relation,source='a',target='b',min_hops=2,max_hops=3,mode='ACYCLIC',time=None)
        q['select']['distance']=ref('reach','length');q['order_by'].append(dict(field='distance',direction='asc'))
    elif name in ('zigzag','cycle','witnessed_count','witnessed_sum','ranked_count','incoming_minimum'):
        q['nodes'].append(node('c',start));q['edges'].append(edge('f','c','b'))
        q['where'].append(dict(left=ref('c'),op='ne',right=ref('a'),value_type='scalar'))
        if name in ('zigzag','cycle'):
            q['nodes'].append(node('d',target));q['edges'].append(edge('g','c','d'))
            q['where'].append(dict(left=ref('b'),op='ne',right=ref('d'),value_type='scalar'))
            q['select'].update(other=ref('c'),destination=ref('d'))
            if name=='cycle':q['edges'].append(edge('h','a','d'))
    elif name in ('ordered_star','outgoing_maximum'):
        q['nodes'].append(node('c',target));q['edges'].append(edge('f','a','c'))
        q['where'].append(dict(left=ref('b'),op='lt',right=ref('c'),value_type='lexical_string'))
        q['select']['other']=ref('c')
    if name in ('plain_count','witnessed_count','witnessed_sum','ranked_count','incoming_minimum','outgoing_maximum'):
        aggregate={'witnessed_sum':'sum','incoming_minimum':'min','outgoing_maximum':'max'}.get(name,'count')
        q['select']={'result':ref('b'),'total':dict(aggregate=aggregate,field=ref('e',core['measure']),distinct=False)}
        q['contribution_by']=['e']
        if name=='ranked_count':q['order_by']=[dict(field='total',direction='desc'),dict(field='result',direction='asc')]
    if name in TEMPLATES['test'] and name!='bounded_path':
        # Predicate operators and complete-result limits are fixed template
        # semantics; numeric cut points are source-only constants.
        q['where'].extend([predicate('e','timestamp','ge',cut),predicate('e',core['measure'],'ge',0)])
        if name=='window_edge':q['where'].append(predicate('e','timestamp','le',cut+366*86400000))
    if cross:q['where'].append(predicate('b',core['control'],'eq',core['control_values'][0]))
    if name!='ranked_count':q['order_by']=[dict(field=k,direction='asc') for k in q['select']]
    return validate_query(q,version='v2')


def structure_identity(query):
    """Erase literals/domain labels, not direction, predicates or aggregation.

    Family assignment is conservative: semantic equivalence is not claimed.
    All variants of a named family are assigned to one partition as well.
    """
    q=deepcopy(query);types={};relations={}
    for n in q['nodes']:
        types.setdefault(n['type'],'kind'+str(len(types)));n['type']=types[n['type']]
    for e in q['edges']+([q['path']] if q['path'] else []):
        label=e['type'].removesuffix('_EARLY').removesuffix('_LATE')
        relations.setdefault(label,'relation'+str(len(relations)));e['type']=relations[label]
    if q['path']:
        q['path']['min_hops']=q['path']['max_hops']='$bounded_integer'
        if q['path']['time']:
            for k in ('lower','upper'):
                if q['path']['time'][k] is not None:q['path']['time'][k]='$timestamp'
    if q['limit'] is not None:q['limit']='$bounded_top_k'
    for p in q['where']:
        if 'value' in p['right']:p['right']['value']={'literal_type':type(p['right']['value']).__name__}
        if p['left']['property'] in ('rating','amount','value'):p['left']['property']='measure'
        if p['left']['property'] in ('gender','isDrama','isBlocked'):
            p['left']['property']='control'
            if 'value' in p['right']:p['right']['value']={'literal_type':'control'}
    for e in q['select'].values():
        if 'aggregate' in e and e['field'] and e['field']['property'] in ('rating','amount','value'):
            e['field']['property']='measure'
    return fingerprint(q)


def choose_anchors(index, *, stratum, size, seed, scale='1'):
    if stratum not in ('uniform','active-anchor'):raise ValueError('Unknown sampling frame')
    kind=index['core']['node_type'];sql='SELECT n.id FROM nodes n WHERE n.kind=?'
    if stratum=='active-anchor':
        sql+=' AND EXISTS (SELECT 1 FROM edges e WHERE e.src=n.id'+(' AND e.ordinal%4=0' if scale=='.25' else '')+')'
    with read_index(index['database']['path']) as db:
        picked=heapq.nsmallest(size,((fingerprint([seed,row[0]]),row[0]) for row in db.execute(sql,(kind,))))
    if len(picked)!=size:raise ValueError('Sampling frame cannot supply the declared distinct anchor count')
    return [a for _,a in picked]


def make_family(core, name, anchors, cut, workload, snapshot, family_id):
    cross=workload in ('W3','W4');q=template_query(core,name,anchors[0],cut,cross=cross);domains=[]
    if workload!='W1':
        domains.append(ScopeDomain(IntentSlot('anchor',('where',0,'right','value')),tuple(anchors[:2]),
            dict(property='id',operators=['eq'])))
    if cross:
        at=next(i for i,p in enumerate(q['where']) if p['left']['property']==core['control'])
        domains.append(ScopeDomain(IntentSlot('control',('where',at,'right','value')),tuple(core['control_values']),
                                   dict(property=core['control'],operators=['eq'])))
        if workload=='W4':
            # Do not manufacture an empty EARLY branch by combining it with
            # timestamp >= the very same median used to define that view.
            q['where']=[p for p in q['where'] if p['left']!=ref('e','timestamp')]
            # The control slot may have moved after removing fixed predicates.
            at=next(i for i,p in enumerate(q['where']) if p['left']['property']==core['control'])
            domains[-1]=ScopeDomain(IntentSlot('control',('where',at,'right','value')),tuple(core['control_values']),
                                    dict(property=core['control'],operators=['eq']))
            path=('path','type') if q['path'] else ('edges',0,'type')
            scopes=(core['relation']+'_EARLY',core['relation']+'_LATE')
            if q['path']:q['path']['type']=scopes[0]
            else:q['edges'][0]['type']=scopes[0]
            domains.append(ScopeDomain(IntentSlot('logical_scope',path,hard=True),scopes,
                edge_selector={'types':list(scopes)} if path[0]=='edges' else None))
        elif q['path']:
            domains.append(ScopeDomain(IntentSlot('path_depth',('path','max_hops')),(2,3)))
        else:
            matches=[i for i,p in enumerate(q['where']) if p['left']==ref('e','timestamp') and p['op']=='ge']
            if not matches:
                q['where'].append(predicate('e','timestamp','ge',cut));matches=[len(q['where'])-1]
            domains.append(ScopeDomain(IntentSlot('lower_time',('where',matches[0],'right','value')),(cut-180*86400000,cut),
                                       dict(property='timestamp',operators=['ge'])))
    policy=ScopePolicy(family_id,tuple(domains),max_candidates=8,language_version='v2')
    return q,policy,construct_scope([q],policy,snapshot)


def question_text(core, name, query, policy):
    relation=core['relation'];measure=core['measure'];descriptions={
        'plain_edge':f'Follow outgoing {relation} edges from the start a to targets b.',
        'plain_count':f'Count distinct {relation} edge records from a to each target b.',
        'window_edge':f'Find targets b reached by an outgoing {relation} edge e from a.',
        'zigzag':f'Find directed {relation} connections a to b, c to b, and c to d; c differs from a and d differs from b.',
        'cycle':f'Find a directed {relation} rectangle: a to b, c to b, c to d, and a to d; c differs from a and d differs from b.',
        'ordered_star':f'Find two outgoing {relation} branches a to b and a to c, with the ID of b lexically smaller than that of c.',
        'bounded_path':f'Find targets b reachable from a by directed {relation} paths without repeated vertices, and their lengths. Require an incoming {relation} edge from another vertex c different from a to b.',
        'witnessed_count':f'For each target b reached from a by {relation}, require another start c different from a with an edge to b. Count the distinct a-to-b edge records, counting each once regardless of the number of such c.',
        'witnessed_sum':f'For each target b reached from a by {relation}, require another start c different from a with an edge to b. Sum {measure} over the distinct a-to-b edge records, counting each once regardless of the number of such c.',
        'ranked_count':f'Rank targets b by the number of distinct {relation} edge records from a, requiring another start c different from a linked to b. Count each a-to-b edge only once, regardless of other witnesses.',
        'incoming_minimum':f'Find the minimum {measure} of outgoing {relation} records from a to each b that also has a distinct incoming start c.',
        'outgoing_maximum':f'Find the maximum {measure} of outgoing {relation} records from a to each b for which a also reaches c and b has a lexically smaller ID than c.',
    }
    parts=[descriptions[name]];varying={d.slot.path:d for d in policy.domains}
    words={'eq':'equal to','ne':'different from','lt':'less than','le':'at most','gt':'greater than','ge':'at least'}
    for i,p in enumerate(query['where']):
        if 'value' not in p['right']:continue
        d=varying.get(('where',i,'right','value'))
        values=' or '.join(json.dumps(v) for v in d.values) if d else json.dumps(p['right']['value'])
        parts.append(f"{p['left']['var']}.{p['left']['property']} is {words[p['op']]} "+
            (f'one of these unresolved choices: {values}.' if d else values+'.'))
    if query['path']:
        parts.append('Path length is at least 2 and at most '+('an unresolved choice of 2 or 3.' if ('path','max_hops') in varying else '3.'))
    logical=next((d for d in policy.domains if d.slot.name=='logical_scope'),None)
    if logical:parts.append('For '+('the path relation' if query['path'] else 'the a-to-b edge relation')+
                            ', the intended time-partition view is unresolved: '+' or '.join(logical.values)+'.')
    parts.append('Return distinct rows with fields '+', '.join(k+'='+('the '+e['var']+'.'+str(e['property']) if 'var' in e else 'the stated '+e['aggregate']) for k,e in query['select'].items())+'.')
    parts.append('Order by '+', '.join(o['field']+' '+o['direction'] for o in query['order_by'])+' and return the first 20 rows.')
    return ' '.join(parts)


def publish(*, index_receipt, profile_path, profile_sha256, output, split, anchors_per_template, seed=20260923,
            deployment_selection='balanced',reference_workspace=None):
    if split not in TEMPLATES or not 1<=anchors_per_template<=100:raise ValueError('Explicit bounded split/size required')
    if deployment_selection not in ('balanced','all'):raise ValueError('Unknown predeclared deployment assignment')
    index=json.loads(Path(index_receipt).read_text());verify(index['database'])
    if not index.get('success'):raise ValueError('Successful independent index required')
    profile=FrozenOneShotProfile.load(profile_path,expected_sha256=profile_sha256)
    doc=json.loads(Path(profile_path).read_text());materialization=json.loads(Path(doc['offline']['materialization']['path']).read_text())
    verify(doc['offline']['materialization'])
    if materialization['index_receipt']['sha256']!=pin(index_receipt)['sha256']:raise ValueError('Profile and reference index differ')
    reference_database=None
    if reference_workspace is not None:
        verify(reference_workspace)
        workspace=json.loads(Path(reference_workspace['path']).read_text())
        if (not workspace.get('success') or workspace.get('schema_version')!='xgap-independent-reference-index-v1'
                or workspace['source_index']['sha256']!=pin(index_receipt)['sha256']
                or workspace['original_database']!=index['database']
                or workspace.get('row_mutations')!=0 or not workspace.get('source_copy_verified_before_ddl')):
            raise ValueError('Independent reference workspace source differs')
        verify(workspace['database']);reference_database=workspace['database']['path']
    scale=materialization['scale'];core=index['core'];dataset=index['dataset']
    deployment='native' if 'neo4j' in doc['backends'] else 'rdf'
    _,_,_,sources,backends,_,_=profile.materialize()
    snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();receipt=dict(success=False,model_calls=0,backend_calls=0,formal_campaign_ready=False)
    try:
        planned=[];excluded=[];registries={p:set() for p in TEMPLATES}
        # Registry is global in shape, independent of IDs and domain labels.
        for partition,names in TEMPLATES.items():
            for name in names:
                if name=='bounded_path' and core['node_type']!=core['target_type']:
                    if partition==split:excluded.append(dict(template=name,reason='D2 is bipartite; current path operator requires homogeneous endpoint types'))
                    continue
                if name=='witnessed_sum' and not core['sum_meaningful']:
                    if partition==split:excluded.append(dict(template=name,reason='No additive source measure in this declared D1 core'))
                    continue
                for w in ('W1','W2','W3','W4'):
                    q,_,_=make_family(core,name,['id:0','id:1'],index['scope_cut_ms'],w,snapshot,'registry')
                    registries[partition].add(structure_identity(q))
        if any(registries[a]&registries[b] for a,b in (('development','pilot'),('development','test'),('pilot','test'))):
            raise ValueError('Template structure collision across splits')
        for stratum in ('uniform','active-anchor'):
            for name in TEMPLATES[split]:
                if any(e['template']==name for e in excluded):continue
                anchors=choose_anchors(index,stratum=stratum,size=anchors_per_template+1,seed=f'{seed}:{split}:{stratum}:{name}',scale=scale)
                for i in range(anchors_per_template):
                    for w in ('W1','W2','W3','W4'):
                        case_id=f'{dataset}-{split}-{stratum}-{name}-{i:03d}-{w}'
                        q,policy,family=make_family(core,name,anchors[i:i+2],index['scope_cut_ms'],w,snapshot,case_id)
                        intended=random.Random(str(seed)+case_id).choice(family.candidates)
                        planned.append(dict(case_id=case_id,stratum=stratum,template=name,workload=w,
                            template_family=structure_identity(q),question=question_text(core,name,q,policy),
                            scope=policy.to_dict(),family=family.to_dict(),private_query=json.loads(intended.query_json)))
        # Balance independently within every frame/workload, before reference
        # reads. Two deployment publishers produce disjoint case IDs, not two
        # copies of a purportedly mixed cohort.
        for stratum in ('uniform','active-anchor'):
            for w in ('W1','W2','W3','W4'):
                group=sorted((r for r in planned if (r['stratum'],r['workload'])==(stratum,w)),
                             key=lambda r:fingerprint([seed,'deployment',r['case_id']]))
                for i,row in enumerate(group):row['assigned_deployment']='native' if i<len(group)//2 else 'rdf'
        # This private publisher record predates every reference computation.
        write(root/'private-preselection.json',dict(seed=seed,cases=planned,method_outputs_used=False,
            selection='hash-ranked IDs without replacement per template/frame; no answers, latency or method outcomes'))
        cases=[];admissions=[]
        for row in planned:
            if deployment_selection=='balanced' and row['assigned_deployment']!=deployment:continue
            cid=row['case_id'];q=row['private_query'];directory=root/cid;directory.mkdir()
            policy=ScopePolicy.from_dict(row['scope']);family=construct_scope([json.loads(row['family']['candidates'][0]['query_json'])],policy,snapshot)
            # Lowering every real candidate is a bounded offline admission, not
            # online enumeration of executed plans.
            used_sources=set();maximum_ops=0
            for candidate in family.candidates:
                program,assignment=lower_compact_query(json.loads(candidate.query_json),doc['source_schema'],version='v2',optimize=True)
                maximum_ops=max(maximum_ops,len(program.operators));used_sources.update(assignment.values())
                if maximum_ops>64:raise ValueError('Candidate exceeds the frozen 64-operator runtime bound: '+cid)
            question=row['question'];request=write_once(directory/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
                question_id=cid,question=question,population=dataset+' '+row['stratum'],exposure=split))
            oracle=write_once(directory/'private-user.json',private_query_intent(question,q,language_version='v2'))
            scope=write_once(directory/'scope.json',row['scope'])
            choices=[dict(name=s.name,type='hard_scope' if s.hard else 'query_coordinate',slots=[s.name]) for s in family.slots]
            controlled=publish_state(question,family,q,semantic_choices=choices)
            _,_,state=read_state(controlled,question)
            expected=(1,0) if row['workload']=='W1' else (2,1) if row['workload']=='W2' else (8,3)
            if (state['initial_candidate_count'],state['initial_ambiguity'])!=expected:raise ValueError('Actual N/u differs: '+cid)
            reference=evaluate(q,index_receipt,scale=scale,execution_database=reference_database)
            fields={k:('text' if 'var' in e and e['property']=='id' else 'integer' if 'var' in e or e['aggregate']=='count' else 'decimal3-half-up') for k,e in q['select'].items()}
            norm=dict(schema_version='xgap-row-normalization-v1',fields=fields)
            normalized=normalize_rows(reference['rows'],norm)
            reference_pin=write_once(directory/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
                dataset=doc['dataset'],question_id=cid,query_sha256=fingerprint(q),source_snapshot_sha256=snapshot,
                ordered=True,normalization=norm,rows=normalized))
            write(directory/'reference-evidence.json',{**reference,'query_sha256':fingerprint(q),'index':pin(index_receipt),
                'reference_workspace':reference_workspace})
            state_pin=write_once(directory/'controlled-state.json',controlled)
            cases.append({k:row[k] for k in ('case_id','stratum','template','workload','template_family')}|
                dict(request=request,oracle=oracle,scope=scope,reference=reference_pin,controlled_state=state_pin,
                    reference_engine=reference['engine'],initial_candidate_count=state['initial_candidate_count'],
                    initial_ambiguity=state['initial_ambiguity'],contributing_sources=sorted(used_sources),
                    deployment=deployment,source_snapshot_sha256=snapshot,
                    structures=[STRUCTURES.get(row['template'],'development')]))
            admissions.append(dict(case_id=cid,all_candidates_lowered=True,max_operators=maximum_ops,
                reference_rows=len(normalized),reference_seconds=reference['elapsed_seconds'],backend_roundtrip='required'))
        bundle=dict(schema_version='xgap-ch6-heldout-cases-v1',dataset=dataset,split=split,
            template_splits={p:sorted(v) for p,v in registries.items()},cases=cases,method_outputs_used_for_selection=False,
            sampling_frames=['uniform','active-anchor'],excluded_templates=excluded,preselection=pin(root/'private-preselection.json'),
            profile=dict(path=str(Path(profile_path).resolve()),sha256=profile_sha256),scale=scale,
            deployment_selection=deployment_selection,deployment=deployment,
            mixed_contract='balanced native/RDF within each sampling-frame/workload; W1/W2 graph-only, W3/W4 graph plus control',
            evidence_scope='authored bounded core queries; independent SQL reference; real backend admission still required')
        write(root/'bundle.json',bundle);write(root/'admission.json',dict(success=True,cases=admissions,backend_roundtrip=False))
        receipt.update(success=True,bundle=pin(root/'bundle.json'),cases=len(cases),excluded_templates=excluded)
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
        if hasattr(error,'evidence'):write(root/'reference-failure.json',error.evidence)
    receipt['offline_seconds']=time.monotonic()-started;write(root/'receipt.json',receipt)
    return receipt
