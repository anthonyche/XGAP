"""New early-anchor risks only. Tiny RDF evaluator; no network/model services."""
from copy import deepcopy
from dataclasses import replace
import json

from rdflib import Graph
import pytest

from test_physical_strategies import NS, PREFIX, setup as old_setup
from test_one_shot_question import estimator, PIN, BUNDLE_FIXTURE
from xgap.agent.question import run_question
from xgap.backends.fuseki_client import FusekiClient
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.anchor_reduction import reduce_scalar_anchor
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


def tiny():
    backends, _, _, _ = old_setup()
    backends = {new: replace(backends[old], backend_id=new,
        backend_mapping=replace(backends[old].backend_mapping, backend_id=new),
        profile=replace(backends[old].profile, backend_id=new))
        for old, new in [('left_rdf', 'rdf_a'), ('right_rdf', 'rdf_b')]}
    facts = ' '.join(f't:{i} a t:Person; t:age 10.' for i in 'abcde')
    links = [('a','b'), ('a','c'), ('b','c'), ('c','d'), ('d','e'), ('e','a'),
             ('a','b'), ('a','a')]
    facts += ' '.join(f't:e{i} a t:Edge; t:source t:{s}; t:target t:{t}; t:label "KNOWS".'
                     for i, (s,t) in enumerate(links))
    graphs = {'rdf_a': Graph().parse(data=PREFIX+facts, format='turtle'),
              'rdf_b': Graph().parse(data=PREFIX+'t:a a t:Person; t:age 20.', format='turtle')}
    schema = {'identity_property': 'id',
        'graph': {'nodes': {'Person': {'properties': ['age']}},
                  'edges': [{'label': 'KNOWS', 'source': 'Person', 'target': 'Person', 'properties': []}]},
        'control': {'nodes': {'Person': {'properties': ['age']}}, 'edges': []}}
    q = {'nodes': [{'var':v, 'type':'Person', 'entity':None} for v in ('start','other')],
        'edges': [], 'path': {'var':'reach', 'type':'KNOWS', 'source':'start', 'target':'other',
            'min_hops':1, 'max_hops':3, 'mode':'ACYCLIC', 'time':None},
        'where':[{'left':{'var':'start','property':'age'}, 'op':'eq',
                  'right':{'value':20}, 'value_type':'scalar'}],
        'select':{'other':{'var':'other','property':None}, 'length':{'var':'reach','property':'length'}},
        'contribution_by':None, 'order_by':[{'field':f,'direction':'asc'} for f in ('length','other')], 'limit':None}
    program, sources = lower_compact_query(q, schema, version='v2')
    placement = {op: 'rdf_a' if source=='graph' else 'rdf_b' for op,source in sources.items()}
    calls = []
    class Local(FusekiClient):
        def _post_query(self, text):
            calls.append((self.backend_id, text))
            return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))
    clients = {b:Local(BackendDescriptor(b,'fuseki','sparql','rdf_graph')) for b in backends}
    registry = BackendPluginRegistry()
    for b, client in clients.items():
        registry.register(NativeBackendPlugin(b, client))
    return program, placement, backends, graphs, clients, FederatedScheduler(BackendInvokeTool(registry)), calls


EXPECTED = tuple({'other':NS+other, 'length':length} for length,other in
                 [(1,'b'),(1,'c'),(2,'c'),(2,'d'),(3,'d'),(3,'e')])


def compile_plan(program, placement, backends):
    return compile_semantic_program(program, source_bindings=placement, backends=backends,
                                    max_remote_calls=64, max_parallelism=1)


def test_union_anchor_preserves_independent_answer_and_reduces_path_work():
    p,s,b,graphs,_,scheduler,calls = tiny()
    before = p.to_dict()
    plain = compile_plan(p,s,b)
    reduced = reduce_scalar_anchor(p, plain)
    details = reduced.metadata['anchor_reduction']
    assert len(details['target_matches']) == 3  # first edge of each 1/2/3-hop branch
    assert next(op for op in p.operators if op.operator_id==details['driver']).kind.value=='union'
    a,b_result = scheduler.execute(plain),scheduler.execute(reduced)
    assert a.success and b_result.success
    assert a.final_rows == b_result.final_rows == EXPECTED
    assert a.total_remote_calls == b_result.total_remote_calls == len(s)
    joins = lambda result:sum(n.row_count for n in result.node_results if n.kind is R.COORDINATOR_JOIN
                              and '/anchor_reduction/' not in n.node_id)
    assert joins(b_result) < joins(a)
    # Different property values across providers cannot remove the matching key.
    assert any('20' in str(o) for o in graphs['rdf_b'].objects())
    row_counts = {n.node_id:n.row_count for n in b_result.node_results}
    assert all(row_counts[t+'/bindings']==8 for t in details['target_matches'])
    # Four outgoing edges remain, including equal-endpoint parallel edges and self-loop.
    assert all(row_counts[details['enforcing_filter']+'/anchor_reduction/'+t]==4 for t in details['target_matches'])
    assert p.to_dict()==before and len(calls)==2*len(s)
    print(json.dumps({'gate':'early-anchor-tiny', 'answer_rows':len(EXPECTED),
        'late_join_rows':joins(a), 'early_join_rows':joins(b_result),
        'source_calls_per_execution':len(s), 'target_matches':len(details['target_matches'])}))


def test_empty_anchor_and_duplicate_provider_keys_preserve_edge_counts():
    p,s,b,graphs,_,scheduler,_ = tiny()
    # A count over one-hop edge identities must preserve both parallel edges.
    raw=p.to_dict()
    source=next(op for op in raw['operators'] if op['kind']=='match' and 'edge' in op['parameters'])
    driver_ops=[op for op in raw['operators'] if op['kind']=='match' and 'node' in op['parameters']]
    union=next(op for op in raw['operators'] if op['kind']=='union' and set(op['input_ids'])=={o['operator_id'] for o in driver_ops})
    filtered=next(op for op in raw['operators'] if op['kind']=='filter' and op['parameters']['condition'].get('value')==20)
    identity=source['parameters']['source_field']; prop=next(iter(driver_ops[0]['parameters']['properties']))
    join={'operator_id':'count-join','kind':'join','input_ids':[source['operator_id'],union['operator_id']],
          'input_kinds':['binding_set']*2,'output_kind':'binding_set','parameters':{'left_on':identity,'right_on':identity}}
    filtered=deepcopy(filtered); filtered['input_ids']=['count-join']
    agg={'operator_id':'count','kind':'aggregate','input_ids':[filtered['operator_id']],
         'input_kinds':['binding_set'],'output_kind':'grouped_bindings',
         'parameters':{'group_by':[],'aggregations':{'n':{'op':'count','field':source['parameters']['entity_field'],'distinct':False}}}}
    raw['operators']=[source,*driver_ops,union,join,filtered,agg];raw['roots']=['count']
    p=SemanticGraphProgram.from_dict(raw);s={k:v for k,v in s.items() if k in {o['operator_id'] for o in raw['operators']}}
    # Same key is returned by both sources; it must not amplify a semijoin.
    graphs['rdf_a'].parse(data=PREFIX+'t:a t:age 20.',format='turtle')
    plan=reduce_scalar_anchor(p,compile_plan(p,s,b))
    assert scheduler.execute(plan).final_rows==({'n':4},)
    bad=p.to_dict(); next(o for o in bad['operators'] if o['kind']=='filter')['parameters']['condition']['value']=999
    empty=SemanticGraphProgram.from_dict(bad)
    result=scheduler.execute(reduce_scalar_anchor(empty,compile_plan(empty,s,b)))
    assert result.success and result.final_rows==({'n':0},)
    assert result.total_remote_calls==len(s)  # no invented source-call savings


def test_unsafe_uses_decline_without_changing_semantic_or_native_inputs():
    p,s,b,_,_,_,_=tiny()
    target=next(o.operator_id for o in p.operators if o.kind.value=='match' and 'edge' in o.parameters)
    # One shared target is a separate answer root: it cannot be filtered globally.
    raw=p.to_dict();raw['roots'].append(target)
    shared=SemanticGraphProgram.from_dict(raw);plan=compile_plan(shared,s,b)
    reduced=reduce_scalar_anchor(shared,plan)
    assert target not in reduced.metadata['anchor_reduction']['target_matches']
    assert plan.roots==reduced.roots
    # A limit between edges and the final predicate makes the push unsafe.
    raw=p.to_dict(); filt=next(o for o in raw['operators'] if o['kind']=='filter' and o['parameters']['condition'].get('value')==20)
    child=filt['input_ids'][0];identity='v0'
    raw['operators'].append({'operator_id':'early-limit','kind':'order_limit','input_ids':[child],
        'input_kinds':['binding_set'],'output_kind':'binding_set',
        'parameters':{'order_by':[{'field':identity,'direction':'asc'}],'limit':1}})
    filt['input_ids']=['early-limit']
    limited=SemanticGraphProgram.from_dict(raw);plan=compile_plan(limited,s,b)
    assert reduce_scalar_anchor(limited,plan) is plan
    # OR cannot be mistaken for a necessary equality.
    raw=p.to_dict(); filt=next(o for o in raw['operators'] if o['kind']=='filter' and o['parameters']['condition'].get('value')==20)
    filt['parameters']['condition']={'op':'or','args':[filt['parameters']['condition'],{'op':'eq','field':'f0','value':10}]}
    disjunctive=SemanticGraphProgram.from_dict(raw);plan=compile_plan(disjunctive,s,b)
    assert reduce_scalar_anchor(disjunctive,plan) is plan


def test_estimated_one_shot_entry_executes_only_one_reduced_plan(estimator):
    p,placement,backends,graphs,clients,_,calls=tiny()
    # This slice uses two equivalent tiny replicas to match the pre-existing
    # analytic estimator fixture; the separate-source correctness gate is above.
    union=graphs['rdf_a']+graphs['rdf_b'];graphs.update(rdf_a=union,rdf_b=union)
    sources={'toy':LogicalSource('toy','toy-v1',('rdf_a','rdf_b'))}
    class Provider:
        provider_id='authored-tiny-anchor-intent'
        def interpret(self, request):
            return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{
                'candidate_id':'tiny','quality_proxy':1.0,'program':p.to_dict(),
                'operator_sources':{o:'toy' for o in placement}}]})
    result=run_question(InterpretationRequest('Find distinct people reachable in one to three acyclic KNOWS hops from a person aged 20.',
        context={'query_id':'slice-query'}),Provider(),mode='performance',estimator=estimator,
        catalog_root=BUNDLE_FIXTURE/PIN['root'],catalog_hash=PIN['bundle_hash'],
        sources=sources,backends=backends,backend_clients=clients)
    assert result['success'],result
    assert tuple(result['answer_rows'])==EXPECTED
    assert result['final_plan_executions']==1 and result['observation_calls']==0
    assert result['interpretation_external_calls']==0 and len(calls)==result['backend_remote_calls']
    assert result['selection']['selection_uses_execution_observations'] is False
    assert 'mandatory-scalar-anchor-distinct-key-join-v1' in json.dumps(result)
    # The normalizer does not enlarge the estimated domain or permit cycles.
    domain=prepare_physical_strategies(p,source_bindings=placement,backends=backends,max_parallelism=1)
    assert len(domain.candidates)<=domain.candidate_count_upper_bound
    assert all(c.plan.metadata.get('anchor_reduction') for c in domain.candidates)


def test_bind_that_would_cycle_is_rejected_before_execution():
    p,s,b,_,_,_,calls=tiny()
    raw=p.to_dict()
    edge=next(o for o in raw['operators'] if o['kind']=='match' and 'edge' in o['parameters'])
    node=next(o for o in raw['operators'] if o['kind']=='match' and s[o['operator_id']]=='rdf_b')
    filt=deepcopy(next(o for o in raw['operators'] if o['kind']=='filter' and o['parameters']['condition'].get('value')==20))
    identity=node['parameters']['entity_field']
    join={'operator_id':'anchor-join','kind':'join','input_ids':[edge['operator_id'],node['operator_id']],
          'input_kinds':['binding_set']*2,'output_kind':'binding_set',
          'parameters':{'left_on':identity,'right_on':identity}}
    filt['input_ids']=['anchor-join'];raw['operators']=[edge,node,join,filt];raw['roots']=[filt['operator_id']]
    p=SemanticGraphProgram.from_dict(raw);s={o['operator_id']:s[o['operator_id']] for o in (edge,node)}
    plain=compile_plan(p,s,b)
    reduced=reduce_scalar_anchor(p,plain)
    artifacts=lambda plan:[n.parameters['artifact'] for n in plan.nodes if n.kind is R.REMOTE_QUERY]
    assert artifacts(reduced)==artifacts(plain)
    domain=prepare_physical_strategies(p,source_bindings=s,backends=b)
    assert len(domain.candidates)==2 and domain.candidate_count_upper_bound==3
    assert any('would cycle' in r['reason'] for r in domain.rejected_strategies)
    assert not calls
