"""New control rules and independent temporal reference on hand-checked facts."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from test_compact_lowering import inputs

from xgap.agent.intent_certificate import TerminalContract
from xgap.agent.intent_strong import FamilyInformationPolicy,run_strong_intent
from xgap.agent.intent_user import ScopedFamilyUser,private_family_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.family_policy_study import family_for,csv_reference
from xgap.experiments.one_shot_records import write_once


def run(tmp_path,scenario,strategy='search',mode='performance',epsilon='1/2',fields=32):
    f=family_for('1','2020-01-01 00:00:00.000','2020-01-04 00:00:00.000',scenario,'tiny')
    p=write_once(tmp_path/'private.json',private_family_intent(f,'question','q7' if len(f.candidates)==8 else 'q0'))
    user=ScopedFamilyUser(f,p['path'],p['sha256'])
    r=run_strong_intent('question',TerminalContract(f,mode=mode,epsilon=epsilon),user,strategy=strategy,
        information=FamilyInformationPolicy(cost_basis='interactions' if scenario=='cheap_full' else 'disclosed_coordinates',
            max_disclosed_coordinates=fields),limits=StrongSearchLimits(improvement_actions=16),
        prepare=lambda c,cert:SimpleNamespace(nodes=()),execute=lambda _:dict(success=True,answer_rows=[]))
    return r


@pytest.mark.parametrize('scenario',['partial_information','cheap_full','hard_confirmation'])
def test_simple_choices_and_search_keep_declared_strong_contract(tmp_path,scenario):
    results={}
    for label,strategy,mode,eps in [('search','search','performance','1/2'),('fixed','fixed','performance','1/2'),
            ('full','full','exact','0')]:
        path=tmp_path/label;path.mkdir();results[label]=run(path,scenario,strategy,mode,eps)
        assert results[label]['success'] and results[label]['strong_plan']
        assert results[label]['final_plan_executions']==1 and results[label]['search']['external_calls_during_search']==0
    if scenario=='partial_information':
        assert results['search']['disclosed_coordinates']==1
        assert results['fixed']['disclosed_coordinates']==2
        assert results['full']['disclosed_coordinates']==3
    elif scenario=='cheap_full':
        assert results['search']['clarification_calls']==results['full']['clarification_calls']==1
        assert results['fixed']['clarification_calls']==2
    else:
        assert all(r['terminal_certificate']['upper_bound']=={'numerator':0,'denominator':1} for r in results.values())
        assert results['fixed']['clarification_calls']==3


def test_fixed_cannot_skip_a_field_or_break_budget_to_get_answer(tmp_path):
    a=tmp_path/'a';a.mkdir();b=tmp_path/'b';b.mkdir()
    search=run(a,'partial_information',fields=1);fixed=run(b,'partial_information','fixed',fields=1)
    assert search['success'] and search['disclosed_coordinates']==1
    assert not fixed['strong_plan'] and fixed['final_plan_executions']==fixed['clarification_calls']==0


def test_csv_reference_respects_boundaries_cycles_and_parallel_reachability():
    edge=lambda a,b,t:SimpleNamespace(from_id=a,to_id=b,create_time=f'2020-01-0{t} 00:00:00.000')
    data=SimpleNamespace(outgoing={'1':[edge('1','2',1),edge('1','2',1)],'2':[edge('2','1',2),edge('2','3',2)]},
        media_by_account={'1':['m'],'2':['m'],'3':['m']},media={'m':{'isBlocked':'true','mediumType':'PHONE'}})
    family=family_for('1','2020-01-01 00:00:00.000','2020-01-04 00:00:00.000','near_cluster','tiny')
    counts=[len(csv_reference(data,json.loads(c.query_json))) for c in family.candidates]
    assert counts==[2,1,0,2,3]


def test_independent_reference_agrees_with_actual_tiny_compiler_execution(inputs):
    from test_compact_lowering import execute
    edge=lambda a,b,t:SimpleNamespace(from_id=a,to_id=b,create_time=f'2020-01-0{t} 00:00:00.000')
    # Separate hand-authored diamond including time boundary; generate its exact RDF facts.
    from rdflib import Graph,Namespace,URIRef,Literal
    from rdflib.namespace import RDF
    from xgap.experiments.finbench_rdf import SCHEMA,RESOURCE
    from xgap.experiments.family_policy_study import NORMALIZATION
    from xgap.experiments.row_normalization import normalize_rows
    fb=Namespace(SCHEMA);g=Graph();c=Graph();ids={a:URIRef(RESOURCE+'study-'+a) for a in ('1','2','3','m')}
    for a,iri in ids.items():
        for target in (g,c):
            target.add((iri,RDF.type,fb.Medium if a=='m' else fb.Account));target.add((iri,fb.sourceId,Literal(a)))
            target.add((iri,fb.xgap_id,Literal('study-'+a)))
    c.add((ids['m'],fb.isBlocked,Literal(True)));c.add((ids['m'],fb.mediumType,Literal('PHONE')))
    for i,(a,b,t) in enumerate([('1','2',1),('1','2',1),('2','1',2),('2','3',2)]):
        e=URIRef(RESOURCE+'study-edge'+str(i))
        for p,v in [(RDF.type,fb.Edge),(fb.edgeLabel,fb.TRANSFERRED_TO),(fb.source,ids[a]),(fb.target,ids[b]),
                    (fb.xgap_id,Literal('study-edge'+str(i))),(fb.createTime,Literal(f'2020-01-0{t} 00:00:00.000'))]:g.add((e,p,v))
    for a in ('1','2','3'):
        e=URIRef(RESOURCE+'study-sign'+a)
        for p,v in [(RDF.type,fb.Edge),(fb.edgeLabel,fb.SIGNED_IN_TO),(fb.source,ids['m']),(fb.target,ids[a]),
                    (fb.xgap_id,Literal('study-sign'+a))]:g.add((e,p,v))
    data=SimpleNamespace(outgoing={'1':[edge('1','2',1),edge('1','2',1)],'2':[edge('2','1',2),edge('2','3',2)]},
        media_by_account={'1':['m'],'2':['m'],'3':['m']},media={'m':{'isBlocked':'true','mediumType':'PHONE'}})
    f=family_for('1','2020-01-01 00:00:00.000','2020-01-04 00:00:00.000','near_cluster','tiny')
    for candidate in f.candidates:
        query=json.loads(candidate.query_json);actual,_,_=execute(query,(*inputs[:-1],{'graph':g,'control':c}),optimize=True)
        assert normalize_rows(actual,NORMALIZATION)==csv_reference(data,query)
