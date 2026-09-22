"""Small offline development cases from frozen real facts; no method execution.

A simple nested-loop/DFS reference has no compiler or planner dependency. The
builder gates lowering separately, reports actual support, and never selects a
case using an answer, runtime, or winning method.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path

from xgap.agent.intent_certificate import IntentSlot,canonical,fingerprint
from xgap.semantic.intent_scope import ScopeDomain,ScopePolicy,construct_scope
from xgap.semantic.compact_lowering import lower_compact_query


def reference(query,facts):
    nodes={n['id']:n for n in facts['nodes']}
    def prop(row,ref):
        obj=row[ref['var']]
        return obj['id'] if ref['property'] is None else obj.get(ref['property'])
    compare={'eq':lambda a,b:a==b,'ne':lambda a,b:a!=b,'lt':lambda a,b:a<b,
             'le':lambda a,b:a<=b,'gt':lambda a,b:a>b,'ge':lambda a,b:a>=b}
    def accepts(row):
        for p in query['where']:
            if p['left']['var'] not in row or 'var' in p['right'] and p['right']['var'] not in row:continue
            a=prop(row,p['left']);b=prop(row,p['right']) if 'var' in p['right'] else p['right']['value']
            if a is None or b is None or not compare[p['op']](a,b):return False
        return True
    def attach(row,bindings):
        if any(k in row and row[k]['id']!=v['id'] for k,v in bindings.items()):return None
        candidate={**row,**bindings}
        return candidate if accepts(candidate) else None
    rows=[{}]
    for edge in query['edges']:
        found=[]
        for row in rows:
            for e in facts['relations'][edge['type']]:
                b={edge['source']:nodes[e['from']],edge['target']:nodes[e['to']],edge['var']:e}
                candidate=attach(row,b)
                if candidate is not None:found.append(candidate)
        rows=found
    path=query['path']
    if path:
        if path['time'] is not None:raise ValueError('This independent generic reference does not implement temporal path windows')
        outgoing=defaultdict(list)
        for e in facts['relations'][path['type']]:outgoing[e['from']].append(e)
        expanded=[]
        for row in rows:
            for start in facts['nodes']:
                initial=attach(row,{path['source']:start})
                if initial is None:continue
                def visit(current,visited,depth):
                    if depth>=path['min_hops']:
                        b={path['target']:nodes[current],path['var']:{'id':'path','length':depth}}
                        child=attach(initial,b)
                        if child is not None:expanded.append(child)
                    if depth==path['max_hops']:return
                    for e in outgoing.get(current,()):
                        if path['mode']=='ACYCLIC' and e['to'] in visited:continue
                        visit(e['to'],visited|{e['to']},depth+1)
                visit(start['id'],{start['id']},0)
        rows=expanded
    for n in query['nodes']:
        rows=[child for row in rows for node in facts['nodes'] if node['type']==n['type']
              for child in [attach(row,{n['var']:node})] if child is not None]
    grouped=defaultdict(list);fields=query['select'];plain=[k for k,v in fields.items() if 'aggregate' not in v]
    aggregates=[k for k in fields if k not in plain]
    for row in rows:grouped[tuple(prop(row,fields[k]) for k in plain)].append(row)
    output=[]
    for values,group in grouped.items():
        item=dict(zip(plain,values))
        for key in aggregates:
            spec=fields[key];parts=group
            if query['contribution_by']:
                seen=set();parts=[]
                for r in group:
                    stamp=tuple(r[v]['id'] for v in query['contribution_by'])
                    if stamp not in seen:seen.add(stamp);parts.append(r)
            vals=[prop(r,spec['field']) for r in parts] if spec['field'] else [1 for r in parts]
            vals=[v for v in vals if v is not None]
            if spec['distinct']:vals=list(dict.fromkeys(vals))
            op=spec['aggregate']
            item[key]=len(vals) if op=='count' else sum((Decimal(str(v)) for v in vals),Decimal(0)) if op=='sum' else min(vals) if op=='min' else max(vals)
        output.append(item)
    # Compact v2 projects distinct rows; contribution grain is separate.
    for order in reversed(query['order_by']):output.sort(key=lambda r:r[order['field']],reverse=order['direction']=='desc')
    return output[:query['limit']] if query['limit'] is not None else output


def public_schema(facts):
    kind=facts['node_type'];target_kind=facts.get('target_type',kind)
    kinds={n['type'] for n in facts['nodes']}
    control=facts['control_property']
    graph=dict(nodes={k:{'properties':sorted(set().union(*(n.keys() for n in facts['nodes'] if n['type']==k))-{'type',control})} for k in kinds},edges=[])
    for label,edges in facts['relations'].items():
        edgeprops=set().union(*(e.keys() for e in edges)) if edges else {'id','from','to'}
        graph['edges'].append(dict(label=label,source=kind,target=target_kind,properties=sorted(edgeprops-{'from','to'})))
    return {'identity_property':'identity', 'graph':graph,
            'control':dict(nodes={target_kind:{'properties':['identity','id',control]}},edges=[])}


def make_query(facts,shape,anchor,cross_source=False):
    kind=facts['node_type'];relation=facts['main_relation']
    def n(v):return dict(var=v,type=kind if v=='a' else facts.get('target_type',kind),entity=None)
    def e(v,s,t):return dict(var=v,type=relation,source=s,target=t)
    def r(v,p='id'):return dict(var=v,property=p)
    query=dict(nodes=[n('a'),n('b')],edges=[e('e','a','b')],path=None,
        where=[dict(left=r('a'),op='eq',right={'value':anchor},value_type='scalar')],
        select={'result':r('b')},contribution_by=None,order_by=[dict(field='result',direction='asc')],limit=None)
    if shape in ('S02','S03','S04'):
        query['nodes'].append(n('c'))
        query['edges'].append(e('f','b' if shape!='S03' else 'a','c'))
        query['select']['via']=r('c');query['order_by'].append(dict(field='via',direction='asc'))
        if shape=='S04':query['edges'].append(e('g','c','a'))
    if shape=='S05':
        query['edges']=[];query['path']=dict(var='reach',type=relation,source='a',target='b',min_hops=1,max_hops=2,mode='ACYCLIC',time=None)
        query['select']['distance']=r('reach','length');query['order_by'].append(dict(field='distance',direction='asc'))
    if shape in ('S06','S07','S08'):
        query['select']['total']=dict(aggregate='sum' if shape=='S07' else 'count',field=r('e',facts['measure']),distinct=False)
        query['contribution_by']=['e']
    if shape=='S08':query['order_by']=[dict(field='total',direction='desc'),dict(field='result',direction='asc')];query['limit']=5
    if cross_source:
        query['where'].append(dict(left=r('b',facts['control_property']),op='eq',right={'value':facts['control_values'][0]},value_type='scalar'))
    return query


def build_development(facts,output,*,seed=20260922):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);(root/'references').mkdir()
    def write(name,value):
        (root/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,default=str)+'\n')
    def lines(name,values):
        (root/name).write_text(''.join(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str)+'\n' for v in values))
    snapshot=fingerprint(facts);schema=public_schema(facts);anchors=sorted({e['from'] for e in facts['relations'][facts['main_relation']]})
    if len(anchors)<2:raise ValueError('Need at least two actual source anchors')
    templates=[];public=[];controlled=[];gold=[];rejections=[]
    # Fixed slots are kept out of the metric. No outcome/cost participates in this selection.
    specs=[('S01','W1'),('S02','W1'),('S03','W2'),('S04','W2'),('S05','W2'),('S06','W3'),('S07','W3'),('S08','W3'),('S02','W4'),('S06','W4')]
    if facts.get('target_type',facts['node_type'])!=facts['node_type']:
        specs=[('S01','W1'),('S01','W1'),('S03','W2'),('S03','W2'),('S06','W3'),('S06','W3'),('S07','W3'),('S08','W3'),('S01','W4'),('S06','W4')]
    for position,(shape,stratum) in enumerate(specs):
        case=facts['dataset']+'-dev-'+str(position+1).zfill(2);anchor=anchors[position%len(anchors)]
        if shape=='S07' and not facts.get('sum_meaningful'):
            rejections.append(dict(case_id=case,structure=shape,reason='No meaningful additive measure registered'));continue
        query=make_query(facts,shape,anchor,stratum in ('W3','W4'))
        domains=[]
        if stratum!='W1':domains.append(ScopeDomain(IntentSlot('entity',('where',0,'right','value')),(anchor,next(a for a in anchors if a!=anchor))))
        if stratum in ('W3','W4'):
            domains.append(ScopeDomain(IntentSlot('control',('where',1,'right','value')),tuple(facts['control_values'])))
            if shape in ('S06','S07','S08') and facts['sum_meaningful']:
                domains.append(ScopeDomain(IntentSlot('aggregation',('select','total','aggregate')),('count','sum')))
        if stratum=='W4':domains.append(ScopeDomain(IntentSlot('logical_scope',('edges',0,'type')),tuple(facts['scope_relations'])))
        family_id=facts['dataset']+'-'+shape+'-'+('cross' if stratum in ('W3','W4') else 'single')
        policy=ScopePolicy(case,tuple(domains),language_version='v2')
        try:
            # W4 base is a real scoped view, not a physical replica.
            if stratum=='W4':query['edges'][0]['type']=facts['scope_relations'][0]
            family=construct_scope([query],policy,snapshot)
            assignments=[]
            for c in family.candidates:
                program,assignment=lower_compact_query(json.loads(c.query_json),schema,version='v2',optimize=True)
                assignments.append(set(assignment.values()))
            if stratum in ('W3','W4') and any(len(s)<2 for s in assignments):raise ValueError('Declared cross-source candidate lacks two contributing sources')
        except Exception as error:
            rejections.append(dict(case_id=case,structure=shape,reason=str(error),status='lowering_failed'));continue
        # Hidden outcome chosen after public construction, uniform over distinct candidates.
        import random
        intended=random.Random(str(seed)+case).choice(family.candidates);q=json.loads(intended.query_json)
        rows=reference(q,facts);ref_id=case+'.json'
        write('references/'+ref_id,dict(rows=rows,row_contract='compact-v2 distinct typed rows; ordered as declared',
            implementation='independent nested loops and DFS; ch6_workload.reference',query_sha256=fingerprint(q),snapshot=snapshot))
        # This complete public language is a development fixture, not free-form NL coverage.
        clauses={'S01':'outgoing edges','S02':'two consecutive outgoing edges','S03':'two outgoing branches sharing the start',
                 'S04':'three outgoing edges closing back to the start; vertices may repeat','S05':'acyclic paths of length 1 or 2',
                 'S06':'edge count grouped by recipient','S07':'edge amount sum grouped by recipient','S08':'edge count grouped by recipient, top 5 by total descending then ID ascending'}
        nl=f"In {facts['dataset']}, use {clauses[shape]}. The public structured template defines direction, projection, grouping and ordering. "
        nl+=(f'Fixed anchor ID is {anchor}. ' if stratum=='W1' else 'Anchor is an explicitly controlled alias for one of the listed entity IDs. ')
        if stratum in ('W3','W4'):nl+='The listed recipient attribute value is unspecified. '
        if any(d.slot.name=='aggregation' for d in domains):nl+='The intended total means either count or sum, as listed. '
        if stratum=='W4':nl+='The intended logical time partition is unspecified; these views contain different edges. '
        pub=dict(case_id=case,dataset=facts['dataset'],workload=stratum,structure=shape,template_family_id=family_id,
            question=nl,exposure='development',nl_admission='controlled template description; not admitted as NL benchmark',
            public_template=query,scope_policy=policy.to_dict(),schema=schema,snapshot_hash=snapshot,
            epsilon='1/3',relaxable=[d.slot.name for d in domains if d.slot.name!='logical_scope'],
            mandatory_validation=[d.slot.name for d in domains if d.slot.name=='logical_scope'],backend_interface_admission='not_run')
        public.append(pub);controlled.append(dict(case_id=case,family=family.to_dict(),initial_clues={},gold_access=False,
            actions=['binding','registered metadata/probe after target publication','checked physical transforms'],
            coverage_status='publisher_constructed; requires private user attestation when publishing runtime input'))
        gold.append(dict(case_id=case,intended_query=q,candidate_id=intended.candidate_id,reference='references/'+ref_id,
            values={s.name:json.loads(v) for s,v in zip(family.slots,family.values[family.candidates.index(intended)])}))
        templates.append(dict(template_family_id=family_id,structure=shape,source='authored domain derivative',
            provenance=facts['provenance'],changes_from_source='compact complete-result development pattern; no claim of official query-card equivalence',
            lowering='passed_all_candidates',backend_interface='not_run',candidate_count=len(family.candidates)))
    lines('template_registry.jsonl',templates);lines('public_cases.jsonl',public);lines('controlled_states.jsonl',controlled)
    lines('private_gold.jsonl',gold);lines('rejections.jsonl',rejections)
    write('facts.json',facts)
    write('dataset_manifest.json',dict(dataset=facts['dataset'],snapshot_hash=snapshot,provenance=facts['provenance'],
        node_count=len(facts['nodes']),base_edges=len(facts['relations'][facts['main_relation']]),
        logical_scope_views=facts['scope_definitions'],mapping='source IDs exact; no external sameAs',
        scope='development subset, not full-scale benchmark',backend_load='not_run',source_partition=schema,
        cases=len(public),rejections=len(rejections),model_calls=0,backend_calls=0))
    write('split_manifest.json',dict(seed=seed,strategy='all these template families reserved for development',
        development=sorted({p['template_family_id'] for p in public}),test=[],formal_test_published=False,
        sampling='deterministic source-active anchors; not natural or uniform-ID population',base_cases=len(public)))
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    write('seal.json',dict(files=hashes,formal_result=False,private_files=['private_gold.jsonl','references/']))
    return dict(dataset=facts['dataset'],cases=len(public),rejections=rejections,output=str(root))
