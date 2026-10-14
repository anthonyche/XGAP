from dataclasses import replace
from types import SimpleNamespace
import json
import pytest
from xgap.planning.source_statistics import SourceRecordStream,collect_source_statistics,resolve_estimator,load_source_statistics
from xgap.planning.joint_synopsis import JointSynopsis
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.contracts import RuntimeNode,RuntimeNodeKind as K
from test_relative_source_work import fixture


def model():
    domains={'node:property:bank':'bank','node:property:country':'country'}
    def records():
        for i in range(1000):yield dict(kind='node',values={'node:property:bank':'A' if i<900 else 'B','node:property:country':'US' if i<900 else 'UK'})
    return collect_source_statistics([SourceRecordStream('neo4j','source-a','v1',records(),domains,(tuple(domains),))],provenance_ref='local-source-export')


def test_correlated_conjunction_avoids_independent_selectivity_error_and_roundtrips(tmp_path):
    m=model();_,base=fixture()
    remote=RuntimeNode('read',K.REMOTE_QUERY,parameters=dict(backend_id='neo4j',artifact=dict(artifact_id='a',language='cypher',text='RETURN x',parameters=dict(compiler='semantic_node_match_v1',scalar_properties={'bank':'bank','country':'country'}))))
    def filtered(parent,name,field,value):return RuntimeNode(name,K.COORDINATOR_FILTER,(parent,),dict(condition=dict(op='eq',field=field,value=value)))
    a=filtered('read','a','bank','A');b=filtered('a','b','country','UK')
    plan=replace(base,nodes=(remote,a,b),roots=('b',),metadata={'source_identities':{'neo4j':dict(source_id='source-a',snapshot_version='v1')}})
    estimate=m.predict(plan)
    counts={n['node']:n['estimated_rows'] for n in estimate.provenance['nodes']}
    assert counts['a']==900 and counts['b']==0
    independent=replace(m,joint_synopses=()).predict(plan)
    assert independent.provenance['nodes'][-1]['estimated_rows']==90
    assert frozen_estimator_from_dict(m.to_dict()).predict(plan).relative_cost==estimate.relative_cost
    path=tmp_path/'stats.json';path.write_text(json.dumps(m.to_dict()))
    assert load_source_statistics(path).model_sha256==m.model_sha256
    clients={'neo4j':SimpleNamespace(descriptor=SimpleNamespace(runtime={'statistics_catalog_path':str(path)}))}
    assert resolve_estimator(None,None,clients,{'a':LogicalSource('source-a','v1',('neo4j',))}).model_sha256==m.model_sha256
    with pytest.raises(ValueError,match='snapshot'):resolve_estimator(None,m,clients,{'a':LogicalSource('source-a','v2',('neo4j',))})


def test_joint_population_validation_and_bounded_tail():
    with pytest.raises(ValueError):JointSynopsis('a',('x','y'),'d',5,1,(((1,2),4),))
    p=JointSynopsis('a',('x','y'),'d',100,3,(((1,None),50),))
    d=p.distribution(100,('x','y')).filtered(dict(op='eq',field='x',value=1),.5)
    assert d.rows==75
    assert d.filtered(dict(op='eq',field='x',value=1),.5).rows==75


def test_statistics_reach_public_nl_entry_without_hidden_collection(tmp_path):
    from xgap.experiments.bounded_joint_toy import local_runtime
    from test_unified_family import invocation
    _,options,_=local_runtime()
    from xgap.experiments.bounded_joint_toy import load_inputs
    from rdflib import URIRef,RDF
    data,graphs=load_inputs();streams=[]
    encoding=data['mapping']['rdf_edge_encoding']
    for name,graph in graphs.items():
        nodes=set().union(*(set(graph.subjects(RDF.type,URIRef(c))) for c in data['mapping']['rdf_node_classes']))
        records=[dict(kind='node',values={'node:property:xgap_id':str(graph.value(n,URIRef(
            'https://xgap.dev/benchmark/finbench/v0.1.0/schema/xgap_id')))}) for n in sorted(nodes)]
        records.extend(dict(kind='edge',label=str(graph.value(e,URIRef(encoding['label_predicate_iri']))),values={})
            for e in graph.subjects(RDF.type,URIRef(encoding['edge_class_iri'])))
        streams.append(SourceRecordStream(name,name,'tiny-v1',iter(records),{'node:property:xgap_id':'identity'}))
    m=collect_source_statistics(streams,provenance_ref='synthetic-local-fixture')
    report,calls=invocation(tmp_path,source_statistics=m)
    assert report['success'],report
    assert report['source_statistics_sha256']==m.model_sha256
    assert report['final_plan_executions']==1 and report['model_calls']==0
    assert report['joint_policy']['external_calls_during_search']==0
    assert report['backend_remote_calls']==len(calls)
    assert report['joint_policy']['execution']['result']['value']['retention']['streaming_profile']=='disk-backed-all-operators-v1'


def test_source_export_derives_exact_endpoint_skew_and_checks_uniqueness():
    stream=SourceRecordStream('b','s','v',iter([
        {'kind':'edge','label':'T','values':{'edge:T:source':'hot'}} for _ in range(99)]+
        [{'kind':'edge','label':'T','values':{'edge:T:source':'cold'}}]),{'edge:T:source':'identity'})
    m=collect_source_statistics([stream],provenance_ref='local')
    assert m.endpoint_degrees==(('b','T','source',100,2,9802,99),)
    with pytest.raises(ValueError,match='unique'):
        collect_source_statistics([SourceRecordStream('b','s','v',iter([
            {'kind':'node','values':{'node:property:id':1}}]*2),{'node:property:id':'id'})],
            provenance_ref='local',unique_node_properties=('id',))


def test_joint_null_boolean_and_column_comparison_survive_projection_and_memo():
    from xgap.planning.cardinality_synopsis import ColumnSynopsis,filter_columns,local_columns
    rows=((('A','A'),8),(('B',None),2))
    j=JointSynopsis('b',('x','y'),'d',10,2,rows).distribution(10,('x','y'))
    columns={'x':ColumnSynopsis('b','x','d',10,2,(('A',8),('B',2))).distribution(10),
        'y':ColumnSynopsis('b','y','d',10,1,(('A',8),),2).distribution(10),('x','y'):j}
    for condition,expected in [(dict(op='eq',field='x',right_field='y'),8),
        (dict(op='is_null',field='y'),2),(dict(op='or',args=[dict(op='eq',field='x',value='A'),dict(op='is_null',field='y')]),10)]:
        _,out=filter_columns(columns,condition,10);assert out==expected
    from dataclasses import replace
    _,base=fixture();m=model()
    # A session must preserve joint distributions rather than stringify their keys.
    node=RuntimeNode('a',K.REMOTE_QUERY,parameters=dict(backend_id='neo4j',artifact=dict(artifact_id='a',language='cypher',text='RETURN 1',parameters=dict(compiler='semantic_node_match_v1',scalar_properties={'bank':'bank','country':'country'}))))
    plan=replace(base,nodes=(node,),roots=('a',),metadata={'source_identities':{'neo4j':dict(source_id='source-a',snapshot_version='v1')}})
    session=m.for_request();a=session.predict(plan);b=session.predict(plan)
    assert a.relative_cost==b.relative_cost and session.hits>0
