"""Real same-engine grouping of immutable financial owner-bank atoms.

The canonical graph and physical property encoding stay unchanged. Bank domains
are metadata, not source-local semantics: callers must retain the explicit
canonical sender-ID range on each witness branch after grouping.
"""
from copy import deepcopy
import hashlib
import json
import mmap
from pathlib import Path
import shutil
import time

from xgap.experiments import ch6_financial_materialize as atom
from xgap.experiments.ch6_financial_scale import source_layout as _source_layout

PROFILE = 'xgap-financial-owner-bank-grouping-v1'
GIB = atom.GIB


def grouped_layout(source_count, *, nodes_per_bank):
    """Return actual endpoint groups; retain the existing S32 source identities."""
    result = _source_layout(source_count, nodes_per_bank=nodes_per_bank)
    if source_count == 32:
        for source in result['sources']:
            source['source_id'] = source['engine']+'-'+str(source['atoms'][0]).zfill(2)
    return result


def _read_pin(pin):
    path = Path(pin['path'])
    if path.is_symlink() or not path.is_file() or path != path.resolve():
        raise ValueError('Pinned materialization file is missing or redirected')
    if atom.pin(path) != pin:
        raise ValueError('Pinned materialization file changed: '+str(path))
    return json.loads(path.read_text())


def _verified_atoms(pin, manifest_pin, manifest):
    """Validate original metadata and read every frozen input/index byte once."""
    doc = _read_pin(pin)
    per_bank = manifest['recipe']['nodes_per_bank']
    if (doc.get('schema_version') != atom.VERSION or doc.get('success') is not True
            or doc.get('source_count') != 32 or doc.get('canonical_manifest') != manifest_pin
            or doc.get('logical_facts_sha256') != manifest['logical_facts_sha256']
            or doc.get('canonical_digests') != manifest['canonical_digests']
            or doc.get('logical_edges') != manifest['counts']['logical_edges']
            or doc.get('logical_nodes') != manifest['counts']['accounts']):
        raise ValueError('Original 32-atom materialization differs from frozen canonical graph')
    expected = grouped_layout(32, nodes_per_bank=per_bank)['sources']
    if len(doc.get('sources', [])) != 32:
        raise ValueError('Original atom source inventory differs')
    for source, layout in zip(doc['sources'], expected):
        if (any(source.get(k) != layout[k] for k in ('source_id','engine','atoms','logical_edges'))
                or source.get('owned_accounts') != per_bank
                or type(source.get('materialized_nodes')) is not int
                or source['materialized_nodes'] < per_bank):
            raise ValueError('Original atom source identity/count differs')
        pins = (list(source['native_bulk_files'].values()) if source['engine']=='neo4j'
                else [source['rdf_load']])
        for ref in pins:
            path = Path(ref['path'])
            if path.is_symlink() or path != path.resolve() or atom.pin(path) != ref:
                raise ValueError('Original atom input changed: '+str(path))
        if (source['engine']=='neo4j' and
                set(source['native_bulk_files']) != {'nodes-Account.csv.gz','relationships.csv.gz'}):
            raise ValueError('Original atom native file schema differs')
    for key in ('mapping','source_schema'):
        _read_pin(doc[key])
    index = doc['property_index']; path = Path(index['path'])
    if (path.is_symlink() or path != path.resolve() or atom.pin(path) != index
            or index['bytes'] != manifest['counts']['accounts']):
        raise ValueError('Original canonical account property index differs')
    schema = _read_pin(doc['source_schema'])
    for source in doc['sources']:
        if schema[source['source_id']].get('owner_banks') != source['atoms']:
            raise ValueError('Original atom source schema domain differs')
    return doc


def _cross_endpoint_count(manifest, source_count):
    matches = [r for r in manifest['graph_statistics']['topology']['cross_source_edges']
               if r['source_count']==source_count]
    if len(matches)!=1:
        raise ValueError('Canonical endpoint crossing statistics missing or ambiguous')
    value = matches[0]['cross_source_edges']
    if (type(value) is not int or value < 0 or value > manifest['counts']['logical_edges']
            or matches[0]['within_source_edges']+value != manifest['counts']['logical_edges']):
        raise ValueError('Canonical endpoint crossing statistics invalid')
    return value


def _source_schema(sources, nodes_per_bank):
    from xgap.experiments.ch6_financial_scalability_queries import ownership_basis
    schema = {s['source_id']: dict(nodes={'Account': dict(properties=['id','xgap_id','isBlocked'])},
        edges=[dict(label='TRANSFERRED_TO',source='Account',target='Account',
                    properties=['id','xgap_id','amount','timestamp'])],
        owner_banks=s['atoms'], endpoint_copies=s['endpoint_copies']) for s in sources}
    schema.update(shared_identity_namespace=atom.RESOURCE, identity_property='xgap_id',
        financial_canonical_ownership=ownership_basis(nodes_per_bank),
        scalar_semantics=dict(id='string',isBlocked='boolean',amount='integer cents',
                              timestamp='integer UTC milliseconds'),
        endpoint_replication='Only nodes needed by local edges plus owner nodes; each logical edge belongs to exactly one source')
    return schema


def materialize_grouped(canonical_root, atom_materialization_pin, output, *, source_count,
                        canonical_manifest_sha256=None, execute=False,
                        max_output_bytes=256*GIB, reserve_bytes=6*GIB, progress=None):
    """Build S real source loads, or reference the unchanged 32-atom files.

    No graph regeneration, database work, query execution or model calls occurs.
    Failed new outputs remain intact. Existing materialization is never edited.
    """
    # Reuse the existing frozen canonical domain/schema validation without writes.
    base = atom.materialize(canonical_root, output,
        canonical_manifest_sha256=canonical_manifest_sha256, execute=False,
        max_output_bytes=max_output_bytes, reserve_bytes=reserve_bytes)
    if type(execute) is not bool:
        raise ValueError('Execution must be an explicit boolean')
    if execute and canonical_manifest_sha256 is None:
        raise ValueError('Execute requires the frozen canonical manifest SHA-256')
    canonical = Path(canonical_root).expanduser().resolve(); root = Path(output).expanduser().resolve()
    manifest_pin=base['canonical_manifest']; manifest=json.loads((canonical/'manifest.json').read_text())
    per_bank=manifest['recipe']['nodes_per_bank']; nodes=base['logical_nodes']; edges=base['logical_edges']
    layout=grouped_layout(source_count,nodes_per_bank=per_bank)
    prior=_verified_atoms(atom_materialization_pin,manifest_pin,manifest)
    crossings=_cross_endpoint_count(manifest,source_count)
    planned={**base,'source_count':source_count,'grouping_profile':PROFILE,'layout':layout,
        'atomic_materialization':dict(atom_materialization_pin),
        'physical_encoding_unchanged':True,'logical_facts_unchanged':True,
        'bank_witness_scope':'Caller must retain explicit canonical witness sender-ID bank ranges; source membership alone is insufficient',
        'cross_endpoint_edges':crossings,'within_endpoint_edges':edges-crossings,
        'cross_endpoint_count_basis':'verified canonical graph-statistics frozen in the canonical manifest',
        'input_reused':source_count==32,'source_files_rewritten':source_count!=32}
    if not execute:
        return planned
    prior_root=Path(atom_materialization_pin['path']).resolve().parent
    if (root.exists() or root==canonical or canonical.is_relative_to(root)
            or root.is_relative_to(canonical) or root==prior_root or prior_root.is_relative_to(root)
            or root.is_relative_to(prior_root)):
        raise ValueError('New separate grouped materialization directory required; no implicit resume')
    parent=root.parent
    while not parent.exists(): parent=parent.parent
    if shutil.disk_usage(parent).free < max_output_bytes+reserve_bytes:
        raise ValueError('Insufficient space for output cap plus reserve')
    root.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    budget=atom._Budget(root,max_output_bytes,reserve_bytes)
    sources=[]
    try:
        atom._json(root/'intent.json',planned,budget)
        if source_count==32:
            # Preserve mapping/source IDs and source objects exactly for store reuse.
            result={**deepcopy(prior),**planned,'executed':True,'success':True,
                'source_files_rewritten':False,'offline_seconds':time.perf_counter()-start,
                'max_output_bytes':max_output_bytes,'reserve_bytes':reserve_bytes}
            atom._json(root/'receipt.json',result,budget)
            return result
        chunks=atom._chunks(manifest,per_bank)
        bank_sources={bank:s['source_id'] for s in layout['sources'] for bank in s['atoms']}
        digest=hashlib.sha256(atom._header(atom.TRANSFER_FIELDS)); edge_ordinal=0; observed_crossings=0
        with Path(prior['property_index']['path']).open('rb') as property_file:
            with mmap.mmap(property_file.fileno(),0,access=mmap.ACCESS_READ) as properties:
                for group in layout['sources']:
                    engine=group['engine']; sid=group['source_id']; banks=group['atoms']
                    directory=root/sid;directory.mkdir();bitmap=bytearray((nodes+7)//8)
                    owned_accounts=len(banks)*per_bank
                    for bank in banks:
                        for n in range(bank*per_bank,(bank+1)*per_bank): atom._mark(bitmap,n)
                    edge_path=directory/('relationships.csv.gz' if engine=='neo4j' else 'data.nt.gz')
                    local_edges=0;materialized_nodes=0;decoded_bytes=0
                    with atom._compressed(edge_path,budget) as stream:
                        if engine=='neo4j': stream.write(atom.EDGE_HEADER);decoded_bytes+=len(atom.EDGE_HEADER)
                        for bank in banks:
                            bank_edges=0
                            for chunk in chunks['transfers'][bank]:
                                for row in atom._rows(canonical,chunk,digest):
                                    ident,kind,source,target,owner,sbank,tbank,amount,timestamp=row
                                    a=int(source[8:]);b=int(target[8:]);stamp=int(timestamp);value=int(amount)
                                    if (ident!=f'transfer:{edge_ordinal:012d}' or kind!='TRANSFERRED_TO'
                                            or source!=f'account:{a:010d}' or target!=f'account:{b:010d}'
                                            or not 0<=a<nodes or not 0<=b<nodes or a==b
                                            or owner!=str(bank) or sbank!=str(bank) or a//per_bank!=bank
                                            or tbank!=str(b//per_bank) or not 1<=value<=1000000
                                            or not atom.START_MS<=stamp<atom.START_MS+atom.WINDOW_MS
                                            or properties[a] not in (1,2) or properties[b] not in (1,2)):
                                        raise ValueError('Invalid canonical transfer or absent endpoint')
                                    atom._mark(bitmap,a);atom._mark(bitmap,b)
                                    block=((','.join((atom.identity(source),atom.identity(target),kind,
                                        atom.identity(kind+':'+ident),ident,timestamp,amount))+'\r\n').encode()
                                        if engine=='neo4j' else atom._edge_rdf(ident,source,target,amount,timestamp))
                                    stream.write(block);decoded_bytes+=len(block)
                                    local_edges+=1;bank_edges+=1;edge_ordinal+=1
                                    observed_crossings+=bank_sources[bank]!=bank_sources[b//per_bank]
                            if bank_edges!=per_bank*atom.DEGREE:
                                raise ValueError('Canonical bank edge count differs')
                        if engine=='rdf':
                            for n in atom._marked(bitmap):
                                if properties[n] not in (1,2):raise ValueError('Invalid canonical account property')
                                block=atom._node_rdf(f'account:{n:010d}','true' if properties[n]==2 else 'false')
                                stream.write(block);decoded_bytes+=len(block);materialized_nodes+=1
                    source=dict(source_id=sid,engine=engine,atoms=list(banks),logical_edges=local_edges,
                        owned_accounts=owned_accounts,endpoint_node_properties='verified actual canonical values',
                        temporal_view_copies=0,decoded_input_bytes=decoded_bytes)
                    if engine=='neo4j':
                        node_path=directory/'nodes-Account.csv.gz'
                        with atom._compressed(node_path,budget) as stream:
                            stream.write(atom.NODE_HEADER);source['decoded_input_bytes']+=len(atom.NODE_HEADER)
                            for n in atom._marked(bitmap):
                                if properties[n] not in (1,2):raise ValueError('Invalid canonical account property')
                                business=f'account:{n:010d}';blocked='true' if properties[n]==2 else 'false'
                                block=f'{atom.identity(business)},{business},{blocked},Account\r\n'.encode()
                                stream.write(block);source['decoded_input_bytes']+=len(block);materialized_nodes+=1
                        source.update(native_bulk_files={node_path.name:atom.pin(node_path),edge_path.name:atom.pin(edge_path)},
                            physical_neo4j_relationships=local_edges,rdf_triples=0)
                    else:
                        source.update(rdf_load=atom.pin(edge_path),physical_neo4j_relationships=0,
                            rdf_triples=local_edges*8+materialized_nodes*4)
                    source.update(materialized_nodes=materialized_nodes,endpoint_copies=materialized_nodes-owned_accounts)
                    source['compressed_input_bytes']=sum(p['bytes'] for p in source.get('native_bulk_files',{}).values())+source.get('rdf_load',{}).get('bytes',0)
                    atom._json(directory/'receipt.json',dict(schema_version=atom.VERSION,success=True,**source),budget)
                    sources.append(source)
                    if progress:progress(dict(phase='grouped_materialize',source_id=sid,atoms=banks,
                        logical_edges=local_edges,sources_completed=len(sources),elapsed_seconds=time.perf_counter()-start))
        if edge_ordinal!=edges or digest.hexdigest()!=manifest['canonical_digests']['transfers']:
            raise ValueError('Canonical transfer digest/count differs')
        if observed_crossings!=crossings:
            raise ValueError('Observed endpoint crossings differ from canonical statistics')
        if atom.pin(prior['property_index']['path'])!=prior['property_index']:
            raise ValueError('Canonical account property index changed during materialization')
        if atom.pin(canonical/'manifest.json')!=manifest_pin:
            raise ValueError('Canonical manifest changed during grouped materialization')
        mapping=atom._mapping([s['source_id'] for s in sources])
        atom._json(root/'mapping.json',mapping,budget);atom._json(root/'source-schema.json',_source_schema(sources,per_bank),budget)
        result={**planned,'executed':True,'success':True,'sources':sources,
            'mapping':atom.pin(root/'mapping.json'),'source_schema':atom.pin(root/'source-schema.json'),
            'property_index':prior['property_index'],'canonical_digests':manifest['canonical_digests'],
            'logical_edge_rows_emitted':sum(s['logical_edges'] for s in sources),
            'physical_neo4j_relationships':sum(s['physical_neo4j_relationships'] for s in sources),
            'rdf_triples':sum(s['rdf_triples'] for s in sources),
            'materialized_node_copies':sum(s['materialized_nodes'] for s in sources),
            'additional_endpoint_copies':sum(s['endpoint_copies'] for s in sources),
            'compressed_input_bytes':sum(s['compressed_input_bytes'] for s in sources),
            'decoded_input_bytes':sum(s['decoded_input_bytes'] for s in sources),
            'cross_endpoint_edges':observed_crossings,'cross_endpoint_count_basis':'actual canonical transfer stream verified against frozen statistics',
            'offline_seconds':time.perf_counter()-start,'backend_store_bytes':None,
            'max_output_bytes':max_output_bytes,'reserve_bytes':reserve_bytes}
        atom._json(root/'receipt.json',result,budget)
        return result
    except BaseException as error:
        atom._json(root/'failure.json',dict(schema_version=atom.VERSION,success=False,
            error_type=type(error).__name__,error=str(error),completed_sources=len(sources),
            partial_inputs_preserved=True,automatic_retries=0))
        raise
