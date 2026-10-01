from copy import deepcopy
from dataclasses import replace
import json
import threading

import pytest

from xgap.experiments import ch6_financial_calibration_queries as queries
from xgap.experiments.ch6_financial_scale import iter_accounts, iter_transfers
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.semantic.program import SemanticGraphProgram

NS = 'https://xgap.dev/ch6/schema/'
RESOURCE = 'https://xgap.dev/ch6/resource/'


def _schema():
    schema = dict(identity_property='xgap_id', shared_identity_namespace=RESOURCE)
    for bank in range(32):
        schema[queries.source_id(bank)] = dict(owner_banks=[bank],
            nodes={'Account':dict(properties=['id','xgap_id','isBlocked'])},
            edges=[dict(label='TRANSFERRED_TO', source='Account', target='Account',
                        properties=['id','xgap_id','amount','timestamp'])])
    return schema


def _fixture():
    """Hand-authored witnesses, duplicate witnesses, and cross-bank nonwitnesses."""
    accounts, edges = [], []
    for bank in range(32):
        aid = lambda local:f'account:{bank*9+local:010d}'
        for local in range(9):
            accounts.append((aid(local),'Account',bank,'true' if local == 3 else 'false'))
        def edge(name, a, b, amount, timestamp=queries.CUTOFF_MS):
            edges.append((f'{bank}:{name}','TRANSFERRED_TO',aid(a),aid(b),bank,bank,bank,amount,timestamp))
        edge('eligible',0,2,7)
        edge('witness',1,2,9,queries.CUTOFF_MS-1)  # Witness time is unconstrained.
        edge('duplicate-witness',4,2,12)
        edge('blocked',0,3,5)
        edge('blocked-witness',1,3,15)
        edge('old-primary',0,5,999,queries.CUTOFF_MS-1)
        edge('old-witness',1,5,15)
        edge('cross-only-primary',0,6,9999)
        other=(bank+1)%32
        edges.append((f'{bank}:cross-only-witness','TRANSFERRED_TO',aid(1),f'account:{other*9+6:010d}',bank,bank,other,15,queries.CUTOFF_MS))
    return accounts, edges


def test_eight_query_domains_shapes_and_repetitions_are_prespecified():
    workload=queries.build_workload()
    assert [c['case_id'] for c in workload['cases']] == [f'Q{i}' for i in range(1,9)]
    assert [c['declared_source_span'] for c in workload['cases']] == [1,1,4,4,16,16,32,32]
    assert [c['aggregate'] for c in workload['cases']] == ['count','sum']*4
    assert [c['template_origin'] for c in workload['cases']] == ['W3','W4']*4
    assert len(workload['schedule']) == 24
    for c in workload['cases']:
        assert len(c['source_ids']) == len(set(c['source_ids'])) == len(c['banks'])
        assert c['executor_parallelism'] == 4 and c['maximum_answer_rows'] == 1
        assert c['provenance']['fixed_intent'] and not c['provenance']['ambiguity_evaluation']
        assert c['model_calls'] == c['scope_confirmation_calls'] == 0
        for b in c['branches']:
            q=b['query']
            assert len(q['edges']) == 2 and q['contribution_by'] == ['e']
            assert q['edges'][1]['source'] == 'c' and q['edges'][1]['target'] == 'b'
            assert list(q['select']) == ['total'] and q['order_by'] == [] and q['limit'] is None
            assert b['anchor'] == f"account:{b['bank']*312500:010d}"
            assert any(p['left'] == {'var':'e','property':'timestamp'} and p['right'] == {'value':queries.CUTOFF_MS} for p in q['where'])
        assert [r['repetition'] for r in workload['schedule'] if r['case_id']==c['case_id']] == [0,1,2]
    assert workload == queries.build_workload()


def test_independent_reference_does_not_double_count_witnesses_or_other_banks():
    accounts,edges=_fixture()
    for case in queries.build_workload(nodes_per_bank=9)['cases']:
        answer=queries.reference(case,iter(accounts),lambda:iter(edges))
        assert answer == [{'total':len(case['banks'])*(1 if case['aggregate']=='count' else 7)}]


def test_real_generator_reference_agrees_with_independent_direct_join():
    accounts=[r for b in range(32) for r in iter_accounts(b,nodes_per_bank=9)]
    edges=[r for b in range(32) for r in iter_transfers(b,nodes_per_bank=9)]
    blocked={r[0]:r[3]=='true' for r in accounts}
    for case in queries.build_workload(nodes_per_bank=9)['cases']:
        anchors={b['bank']:b['anchor'] for b in case['branches']}
        accepted=[]
        for e in edges:
            if (e[4] in anchors and e[2]==anchors[e[4]] and e[8]>=queries.CUTOFF_MS
                    and e[7]>=0 and not blocked[e[3]]
                    and any(f[4]==e[4] and f[3]==e[3] and f[2]!=e[2] for f in edges)):
                accepted.append(e)
        expected=len(accepted) if case['aggregate']=='count' else sum(e[7] for e in accepted)
        assert queries.reference(case,iter(accounts),lambda:iter(edges)) == [{'total':expected}]


def test_lowered_dags_preserve_all_sources_and_are_ordinary_compiler_inputs():
    from xgap.compilers.features import default_profile
    backends={queries.source_id(b):SemanticBackend(queries.source_id(b),RESOURCE,identity_property='xgap_id',
        profile=replace(default_profile('neo4j'),backend_id=queries.source_id(b))) for b in range(32)}
    for case in queries.build_workload(nodes_per_bank=9)['cases']:
        program,sources=queries.lower_case(case,_schema())
        assert not program.holes and set(sources.values()) == set(case['source_ids'])
        assert SemanticGraphProgram.from_dict(program.to_dict()) == program
        plan=compile_semantic_program(program,source_bindings=sources,backends=backends,
                                      max_remote_calls=256,max_parallelism=4)
        assert plan.max_parallelism == 4 and len(plan.nodes)>0
        assert set(plan.metadata['source_bindings'].values()) == set(case['source_ids'])
        assert len([o for o in program.operators if o.operator_id.endswith('/tag')]) == len(case['banks'])
    assert len(program.operators)>64  # Composition, not a silent compact-profile expansion.


def test_frozen_case_and_complete_source_domain_cannot_be_silently_changed():
    c=deepcopy(queries.build_workload(nodes_per_bank=9)['cases'][0]);c['cutoff_ms']+=1
    with pytest.raises(ValueError,match='frozen recipe'):
        queries.lower_case(c,_schema())
    c=queries.build_workload(nodes_per_bank=9)['cases'][2]
    s=_schema();s.pop(c['source_ids'][0])
    with pytest.raises(ValueError,match='Missing declared'):
        queries.lower_case(c,s)
    s=_schema();s[c['source_ids'][0]]['owner_banks']=[0,1]
    with pytest.raises(ValueError,match='exact single owner-bank'):
        queries.lower_case(c,s)


def test_real_rdf_execution_of_multi_bank_count_and_sum_matches_gold():
    rdf=pytest.importorskip('rdflib',minversion='7.1.4')
    from xgap.backends.fuseki_client import FusekiClient
    from xgap.compilers.features import default_profile
    from xgap.compilers.rdf_encoding import RdfEdgeEncoding
    from xgap.infrastructure.descriptors import BackendDescriptor
    from xgap.runtime.scheduler import FederatedScheduler
    from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
    accounts,edges=_fixture();node_by_id={r[0]:r for r in accounts}
    ident=lambda value:'r0_'+value.encode().hex()
    uri=lambda value:rdf.URIRef(RESOURCE+ident(value))
    graphs={queries.source_id(b):rdf.Graph() for b in range(32)}
    for e in edges:
        g=graphs[queries.source_id(e[4])];edge=uri('TRANSFERRED_TO:'+e[0])
        for aid in e[2:4]:
            row=node_by_id[aid];u=uri(aid)
            g.add((u,rdf.RDF.type,rdf.URIRef(NS+'Account')))
            for key,value in [('id',aid),('xgap_id',ident(aid)),('isBlocked',row[3]=='true')]:
                g.add((u,rdf.URIRef(NS+key),rdf.Literal(value)))
        g.add((edge,rdf.RDF.type,rdf.URIRef(NS+'Edge')))
        for key,value in [('source',uri(e[2])),('target',uri(e[3])),('edgeLabel',rdf.URIRef(NS+'TRANSFERRED_TO')),
                          ('id',rdf.Literal(e[0])),('xgap_id',rdf.Literal(ident('TRANSFERRED_TO:'+e[0]))),
                          ('amount',rdf.Literal(e[7])),('timestamp',rdf.Literal(e[8]))]:
            g.add((edge,rdf.URIRef(NS+key),value))
    terms={k:dict(kind='property',representation=NS+k) for k in ['id','xgap_id','isBlocked','amount','timestamp']}
    terms.update(Account=dict(kind='class',representation=NS+'Account'),TRANSFERRED_TO=dict(kind='relation',representation=NS+'TRANSFERRED_TO'))
    mapping=dict(mapping_id='fixture',version='1',backends={s:dict(namespace=NS) for s in graphs},term_mappings={s:terms for s in graphs})
    encoding=RdfEdgeEncoding('fixture',NS+'Edge',NS+'source',NS+'target',NS+'edgeLabel')
    backends={s:SemanticBackend(s,RESOURCE,identity_property='xgap_id',backend_mapping=mapping,
        rdf_edge_encoding=encoding,rdf_node_classes=(NS+'Account',),profile=replace(default_profile('fuseki'),backend_id=s)) for s in graphs}
    parser_lock=threading.Lock()  # RDFLib parser is not a concurrent HTTP service.
    class IndependentRdf(FusekiClient):
        def _post_query(self,text):
            with parser_lock:
                return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))
    plugins=BackendPluginRegistry()
    for sid in graphs:
        plugins.register(NativeBackendPlugin(sid,IndependentRdf(BackendDescriptor(sid,'fuseki','sparql','rdf'))))
    for case in queries.build_workload(nodes_per_bank=9)['cases'][2:4]:
        program,sources=queries.lower_case(case,_schema())
        plan=compile_semantic_program(program,source_bindings=sources,backends=backends,max_remote_calls=256,max_parallelism=4)
        result=FederatedScheduler(BackendInvokeTool(plugins)).execute(plan)
        assert result.success, [(n.node_id,n.error) for n in result.node_results if n.error and 'dependency' not in n.error.lower()]
        assert list(result.final_rows)==queries.reference(case,iter(accounts),lambda:iter(edges))
        assert len(result.final_rows)==1


def test_shared_eight_query_reference_uses_only_two_edge_and_one_account_pass():
    accounts,edges=_fixture()
    workload=queries.build_workload(nodes_per_bank=9)
    passes={'accounts':0, 'edges':0}
    def account_stream():
        passes['accounts']+=1
        return iter(accounts)
    def edge_stream():
        passes['edges']+=1
        return iter(edges)
    all_gold=queries.reference_workload(workload,account_stream,edge_stream)
    assert passes == {'accounts':1,'edges':2}
    assert len(all_gold)==8
    for case in workload['cases']:
        assert all_gold[case['case_id']] == queries.reference(case,iter(accounts),lambda:iter(edges))
    changed=deepcopy(workload);changed['cases'][0]['cutoff_ms']+=1
    with pytest.raises(ValueError,match='unchanged calibration'):
        queries.reference_workload(changed,account_stream,edge_stream)
