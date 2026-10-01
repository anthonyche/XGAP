import csv
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDF, URIRef

from xgap.experiments import ch6_financial_materialize as atom
from xgap.experiments import ch6_financial_grouped_materialize as grouped
from xgap.experiments.ch6_financial_scale import generate


@pytest.fixture
def frozen(tmp_path):
    canonical=tmp_path/'canonical'
    manifest=generate(canonical,execute=True,nodes_per_bank=9,chunk_rows=37,
        max_output_bytes=4*1024**2,reserve_bytes=0)
    manifest=json.loads((canonical/'manifest.json').read_text())
    root=tmp_path/'atoms'
    atoms=atom.materialize(canonical,root,execute=True,
        canonical_manifest_sha256=atom.pin(canonical/'manifest.json')['sha256'],
        max_output_bytes=16*1024**2,reserve_bytes=0)
    return canonical,manifest,atoms,atom.pin(root/'receipt.json')


def run(frozen,output,count,**options):
    canonical,_,_,pin=frozen
    return grouped.materialize_grouped(canonical,pin,output,source_count=count,execute=True,
        canonical_manifest_sha256=atom.pin(canonical/'manifest.json')['sha256'],
        max_output_bytes=options.pop('max_output_bytes',16*1024**2),reserve_bytes=0,**options)


def rows(canonical,manifest,kind):
    result=[]
    for chunk in manifest['chunks']:
        if chunk['kind']==kind:
            with gzip.open(canonical/chunk['path'],'rt',newline='') as stream:
                result.extend(csv.DictReader(stream))
    return result


def native(pin):
    with gzip.open(pin['path'],'rt',newline='') as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize('count',[2,4,8,16,32])
def test_grouping_keeps_every_edge_once_and_deduplicates_endpoint_accounts(frozen,tmp_path,count):
    canonical,manifest,old,_=frozen
    result=run(frozen,tmp_path/('sources-'+str(count)),count)
    accounts={r['id']:r for r in rows(canonical,manifest,'accounts')}
    transfers={r['id']:r for r in rows(canonical,manifest,'transfers')}
    seen={};node_copies=0;ns=Namespace(atom.NS)
    layout=grouped.grouped_layout(count,nodes_per_bank=9)
    assert result['layout']==layout and len(result['sources'])==count
    by_bank={b:s['source_id'] for s in result['sources'] for b in s['atoms']}
    for source,expected in zip(result['sources'],layout['sources']):
        assert all(source[k]==expected[k] for k in ('source_id','engine','atoms','logical_edges'))
        assert source['owned_accounts']==len(source['atoms'])*9
        assert source['logical_edges']==len(source['atoms'])*90
        node_copies+=source['materialized_nodes']
        if source['engine']=='neo4j':
            nodes=native(source['native_bulk_files']['nodes-Account.csv.gz'])
            edges=native(source['native_bulk_files']['relationships.csv.gz'])
            assert len(nodes)==len({n['id'] for n in nodes})==source['materialized_nodes']
            node_ids={n['xgap_id:ID'] for n in nodes}
            for node in nodes:
                assert node['isBlocked:boolean']==accounts[node['id']]['isBlocked']
                assert node['xgap_id:ID']==atom.identity(node['id'])
            for edge in edges:
                original=transfers[edge['id']]
                assert edge[':START_ID']==atom.identity(original['source'])
                assert edge[':END_ID']==atom.identity(original['target'])
                assert edge[':START_ID'] in node_ids and edge[':END_ID'] in node_ids
                assert edge['amount:long']==original['amount']
                assert edge['timestamp:long']==original['timestamp']
                assert edge['id'] not in seen;seen[edge['id']]=source['source_id']
        else:
            graph=Graph().parse(data=gzip.decompress(Path(source['rdf_load']['path']).read_bytes()).decode(),format='nt')
            assert len(graph)==source['rdf_triples']
            nodes=list(graph.subjects(RDF.type,ns.Account))
            assert len(nodes)==source['materialized_nodes']
            for node in nodes:
                business=str(graph.value(node,ns.id))
                assert graph.value(node,ns.isBlocked).toPython()==(accounts[business]['isBlocked']=='true')
                assert str(graph.value(node,ns.xgap_id))==atom.identity(business)
            for edge in graph.subjects(RDF.type,ns.Edge):
                ident=str(graph.value(edge,ns.id));original=transfers[ident]
                assert graph.value(edge,ns.source)==URIRef(atom.RESOURCE+atom.identity(original['source']))
                assert graph.value(edge,ns.target)==URIRef(atom.RESOURCE+atom.identity(original['target']))
                assert graph.value(edge,ns.amount).toPython()==int(original['amount'])
                assert graph.value(edge,ns.timestamp).toPython()==int(original['timestamp'])
                assert ident not in seen;seen[ident]=source['source_id']
    assert set(seen)==set(transfers)
    assert all(seen[i]==by_bank[int(r['owner_bank'])] for i,r in transfers.items())
    cross=sum(by_bank[int(r['source_bank'])]!=by_bank[int(r['target_bank'])] for r in transfers.values())
    assert result['cross_endpoint_edges']==cross
    assert result['within_endpoint_edges']+cross==2880
    assert result['materialized_node_copies']==node_copies<=old['materialized_node_copies']
    assert result['logical_edges']==result['logical_edge_rows_emitted']==2880
    assert result['physical_neo4j_relationships']==1440
    assert result['canonical_digests']==manifest['canonical_digests']
    assert result['logical_facts_sha256']==manifest['logical_facts_sha256']
    assert result['model_calls']==result['backend_calls']==result['query_calls']==0
    assert result['services_prepared'] is False
    if count<32:
        schema=json.loads(Path(result['source_schema']['path']).read_text())
        assert all(schema[s['source_id']]['owner_banks']==s['atoms'] for s in result['sources'])
    else:
        assert result['sources']==old['sources']
        assert result['mapping']==old['mapping'] and result['source_schema']==old['source_schema']
        assert result['input_reused'] and not result['source_files_rewritten']
        assert {p.name for p in Path(result['output']).iterdir()}=={'intent.json','receipt.json'}
        assert [s['source_id'] for s in result['sources'][16:]]==['rdf-'+str(b) for b in range(16,32)]


def test_source_grouping_cannot_erase_same_bank_witness_scope(frozen,tmp_path):
    # Find a concrete primary edge with a witness in another bank and show that
    # sharing a physical source never makes that witness part of the bank query.
    canonical,manifest,_,_=frozen
    result=run(frozen,tmp_path/'two',2)
    transfers=rows(canonical,manifest,'transfers')
    pair=next((e,f) for e in transfers for f in transfers
        if e['target']==f['target'] and int(e['owner_bank'])<16 and int(f['owner_bank'])<16
        and e['owner_bank']!=f['owner_bank'])
    e,f=pair;bank=int(e['owner_bank']);lower=f'account:{bank*9:010d}';upper=f'account:{(bank+1)*9:010d}'
    grouped_nodes=native(result['sources'][0]['native_bulk_files']['nodes-Account.csv.gz'])
    assert e['source'] in {n['id'] for n in grouped_nodes} and f['source'] in {n['id'] for n in grouped_nodes}
    assert lower<=e['source']<upper and not lower<=f['source']<upper
    assert 'sender-ID bank ranges' in result['bank_witness_scope']


def test_dry_run_and_source32_do_not_rewrite_frozen_inputs(frozen,tmp_path,monkeypatch):
    canonical,_,_,pin=frozen
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    def forbidden(*args,**kwargs):raise AssertionError('must not regenerate or convert reused S32 data')
    monkeypatch.setattr(atom,'_rows',forbidden)
    plan=grouped.materialize_grouped(canonical,pin,tmp_path/'dry',source_count=32)
    assert not (tmp_path/'dry').exists() and not plan['executed']
    run(frozen,tmp_path/'reuse',32)
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in before.items())


@pytest.mark.parametrize('kind',['canonical_chunk','atom_input','property_index'])
def test_tampered_inputs_cannot_publish_success(frozen,tmp_path,kind):
    canonical,manifest,atoms,_=frozen
    if kind=='canonical_chunk':target=canonical/next(c['path'] for c in manifest['chunks'] if c['kind']=='transfers')
    elif kind=='atom_input':target=Path(atoms['sources'][0]['native_bulk_files']['relationships.csv.gz']['path'])
    else:target=Path(atoms['property_index']['path'])
    with target.open('ab') as stream:stream.write(b'changed')
    output=tmp_path/'invalid'
    with pytest.raises(ValueError,match='changed|differs'):
        run(frozen,output,2)
    assert not (output/'receipt.json').exists()
    if kind=='canonical_chunk':
        assert json.loads((output/'failure.json').read_text())['partial_inputs_preserved']


def test_small_output_budget_preserves_partial_and_existing_outputs(frozen,tmp_path):
    output=tmp_path/'small'
    with pytest.raises(ValueError,match='output byte limit'):
        run(frozen,output,2,max_output_bytes=7000)
    assert not (output/'receipt.json').exists()
    assert json.loads((output/'failure.json').read_text())['partial_inputs_preserved']
    (output/'keep').write_text('old')
    with pytest.raises(ValueError,match='New separate'):
        run(frozen,output,2)
    assert (output/'keep').read_text()=='old'


@pytest.mark.parametrize('count',[1,3,64,True])
def test_nonexistent_or_duplicate_source_layout_rejected(frozen,tmp_path,count):
    with pytest.raises(ValueError,match='2, 4, 8, 16, or 32'):
        run(frozen,tmp_path/'invalid',count)
    assert not (tmp_path/'invalid').exists()
