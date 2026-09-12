"""New representation boundary only; no model, baseline or old campaign runs."""

import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

from xgap.experiments.finbench_rdf import (
    ENTITIES, FAMILIES, RESOURCE, SCHEMA, fixed_semantics_query,
    local_identity, materialize_finbench_rdf,
)
from xgap.experiments.m15_finbench_artifacts import DEFAULT_LOCK_PATH
from xgap.experiments.m15_finbench_partition import build_finbench_source_partition, NEO4J_BATCH_FILENAME


def tiny_partition(root):
    """Eight entities, repeated transfers, a cycle, a decreasing-time path,
    equal timestamps, two qualifying media and a closed/open window endpoint.
    Entity types deliberately share raw ID '1'. No gold drives preparation.
    """
    root=Path(root);root.mkdir(exist_ok=True)
    lock=json.loads(Path(DEFAULT_LOCK_PATH).read_text())
    tables={t['table_id']:t for t in lock['snapshot_tables']}
    rows={table:[] for table in tables}
    def add(table,**overrides):
        row={c:"" for c in tables[table]['columns']};row.update(overrides);rows[table].append(row)
    add('person',personId='1',personName='Alice',isBlocked='false')
    for account,blocked in [('1','false'),('2','true'),('3','true'),('4','true')]:
        add('account',accountId=account,isBlocked=blocked,nickname='account '+account)
    add('company',companyId='1',companyName='Company One',isBlocked='false')
    for mid in ('1','2'):
        add('medium',mediumId=mid,isBlocked='true',mediumType='PHONE',riskLevel='High risk')
    add('person_own_account',personId='1',accountId='1')
    for account in ('2','3','4'):
        add('company_own_account',companyId='1',accountId=account)
    for mid,account in [('1','2'),('2','2'),('1','3'),('1','4')]:
        add('medium_sign_in_account',mediumId=mid,accountId=account)
    transfers=[('1','2','10.125','01'),('1','2','5.875','01'),('2','3','7.0','02'),
               ('3','1','100.0','03'),('1','3','9.0','03'),('3','4','11.0','02'),
               ('1','2','50.0','04'),('2','4','13.0','01')]
    for i,(a,b,amount,day) in enumerate(transfers):
        add('account_transfer_account',fromId=a,toId=b,amount=amount,
            createTime=f'2020-01-{day} 00:00:00.000',orderNum=str(i))
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        for table,spec in tables.items():
            data=('|'.join(spec['columns'])+'\n'+''.join('|'.join(r[c] for c in spec['columns'])+'\n' for r in rows[table])).encode()
            member=tarfile.TarInfo(spec['member']);member.size=len(data);archive.addfile(member,io.BytesIO(data))
    data=buffer.getvalue();source=root/'tiny.tar.gz';source.write_bytes(data)
    lock['artifact']['size_bytes']=len(data);lock['artifact']['digest']['value']=hashlib.sha256(data).hexdigest()
    pin=root/'lock.json';pin.write_text(json.dumps(lock))
    partition=root/'partition';build_finbench_source_partition(archive_path=source,lock_path=pin,output_root=partition)
    return partition


def prepared(root):
    partition=tiny_partition(root)
    output=Path(root)/'rdf';receipt=materialize_finbench_rdf(partition,output)
    graph=Graph();graph.parse(output/'graph.ttl');graph.parse(output/'control.ttl')
    return partition,output,graph,receipt


def parameters():
    window={'start_time':'2020-01-01 00:00:00.000','end_time':'2020-01-04 00:00:00.000'}
    return [dict(window,person_id='1'),dict(window,start_account_id='1',max_hops=3),dict(window,risk_level='High risk',top_k=10)]


def expected_rows():
    # Independently hand-derived from the transfers above. F3 sees each eligible
    # account once even when two media qualify; day04 is excluded only in F3.
    return [
        [{'company_id':'1','account_id':'2','total_amount':66.0}, {'company_id':'1','account_id':'3','total_amount':9.0}],
        [{'other_id':'2','account_distance':1,'medium_id':'1','medium_type':'PHONE'},
         {'other_id':'2','account_distance':1,'medium_id':'2','medium_type':'PHONE'},
         {'other_id':'3','account_distance':1,'medium_id':'1','medium_type':'PHONE'},
         {'other_id':'3','account_distance':2,'medium_id':'1','medium_type':'PHONE'}],
        [{'company_id':'1','total_amount':56.0}],
    ]


def plain_rows(result):
    return [{str(name):term.toPython() for name,term in row.asdict().items()} for row in result]


def test_same_facts_identity_parallel_edges_and_original_partition_preserved(tmp_path):
    partition,output,graph,receipt=prepared(tmp_path)
    fb=Namespace(SCHEMA)
    assert receipt['entity_count']==8 and receipt['relationship_count']==16
    assert len(set(graph.subjects(RDF.type,fb.Edge)))==16
    assert len({RESOURCE+local_identity(t,'1') for t in ('person','account','company','medium')})==4
    assert local_identity('account','a/b') != local_identity('account','a_b')
    originals=[json.loads(x) for x in (partition/NEO4J_BATCH_FILENAME).read_text().splitlines()]
    revised=[json.loads(x) for x in (output/NEO4J_BATCH_FILENAME).read_text().splitlines()]
    for old,new in zip(originals,revised):
        for a,b in zip(old.get('parameters',{}).get('rows',[]),new.get('parameters',{}).get('rows',[])):
            props=dict(b['props']);identity=props.pop('xgap_id')
            assert props==a['props'] and 'xgap_id' not in a['props']
            assert (URIRef(RESOURCE+identity),fb.xgap_id,None) in graph
    assert all('SERVICE' not in fixed_semantics_query(f,p) for f,p in zip(FAMILIES,parameters()))


def test_three_rdf_queries_match_independent_answers_with_boundary_and_multiplicity(tmp_path):
    _,_,graph,_=prepared(tmp_path)
    for family,p,expected in zip(FAMILIES,parameters(),expected_rows()):
        assert plain_rows(graph.query(fixed_semantics_query(family,p)))==expected


def test_new_mapping_reaches_ordinary_match_compiler_and_identity_normalization(tmp_path):
    _,output,graph,_=prepared(tmp_path)
    from xgap.compilers.node_match import compile_node_match
    from xgap.pattern.ast import NodePattern
    from xgap.runtime.row_operations import normalize_node_bindings
    mapping=json.loads((output/'mapping.json').read_text())
    artifact=compile_node_match(NodePattern(label='XGAPFinBenchAccount',properties={'id':'2'}),
        {'source_id':'id'},backend_id='fuseki',backend_mapping=mapping['backend_mapping'],rdf_node_classes=tuple(mapping['rdf_node_classes']))
    result=json.loads(graph.query(artifact.text).serialize(format='json'))['results']['bindings']
    rdf=normalize_node_bindings(result,{'language':'sparql','identity_property':'xgap_id','resource_namespace':RESOURCE,'entity_field':'account','scalar_fields':['source_id']})
    native=normalize_node_bindings([{'entity':{'xgap_id':local_identity('account','2')},'source_id':'2'}],
        {'language':'cypher','identity_property':'xgap_id','resource_namespace':RESOURCE,'entity_field':'account','scalar_fields':['source_id']})
    assert rdf==native==({'account':RESOURCE+local_identity('account','2'),'source_id':'2'},)
