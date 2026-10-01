"""Stream a sealed Chapter 6 fact index to same-facts RDF and native loads.

Scale 4 means four disconnected replicas, explicitly not four times as much
independent real-world data. Source count repartitions the SAME facts. Offline
costs and duplicate identity stubs are declared separately from query costs.
"""
from contextlib import ExitStack
from dataclasses import asdict
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import time

from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.ch6_fact_index import encoded, pin, read_index, verify, write
from xgap.experiments.finbench_rdf import literal

NS='https://xgap.dev/ch6/schema/'
RESOURCE='https://xgap.dev/ch6/resource/'


def identity(value, replica=0):
    return 'r'+str(replica)+'_'+value.encode('utf-8').hex()


def iri(value, replica=0):
    return '<'+RESOURCE+identity(value,replica)+'>'


def text_gzip(stack,path):
    raw=stack.enter_context(Path(path).open('xb'))
    compressed=stack.enter_context(gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=1))
    return stack.enter_context(io.TextIOWrapper(compressed,encoding='utf-8',newline=''))


def materialize(index_receipt, output, *, scale='1', source_count=2):
    if scale not in ('.25','1','4') or source_count not in (2,4,8): raise ValueError('Undeclared factor level')
    meta=json.loads(Path(index_receipt).read_text())
    if not meta.get('success') or meta['schema_version']!='xgap-ch6-fact-index-v1': raise ValueError('Successful fact index required')
    verify(meta['database'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False); started=time.monotonic()
    core=meta['core']; relation=core['relation']; cut=meta['scope_cut_ms']; control=core['control']
    graphs=['graph'] if source_count==2 else ['graph'+str(i) for i in range(source_count-1)]
    names=graphs+['control'];copies=4 if scale=='4' else 1
    receipt=dict(schema_version='xgap-ch6-core-materialization-v1',success=False,dataset=meta['dataset'],
        index_receipt=pin(index_receipt),scale=scale,source_count=source_count,core=core,scope_cut_ms=cut,
        model_calls=0,backend_calls=0,query_reads=0,answer_reads=0,formal_workload_admitted=False,
        scale_semantics='1x full original core; .25x keeps original edge ordinal divisible by four and all nodes; 4x four disconnected identity-renamed full replicas',
        source_semantics='Same entities and relationships; edge ordinal hash partition across graph sources; control properties in control only; identity/type stubs replicated',
        materialization_root=str(root),native_bulk_import=True)
    try:
        if shutil.disk_usage(root).free < 22*1024**3:raise ValueError('Need 16-GiB output allowance plus six-GiB reserve')
        write(root/'intent.json',receipt)
        node_types={};prop_types={};counts=dict(nodes=0,original_edges=0,view_edges=0);logical_hash=hashlib.sha256()
        source_edges={n:0 for n in graphs};buffers={};batch_count=0
        with read_index(meta['database']['path']) as db, ExitStack() as stack:
            rdfs={n:text_gzip(stack,root/(n+'.ttl.gz')) for n in names}
            native=text_gzip(stack,root/'load_neo4j_batches.jsonl.gz')
            for handle in rdfs.values(): handle.write(f'@prefix s: <{NS}> .\n@prefix r: <{RESOURCE}> .\n')
            def flush(key=None):
                nonlocal batch_count
                for k in list(buffers) if key is None else [key]:
                    batch=buffers[k]
                    if not batch:continue
                    kind,table,statement=k
                    content=dict(kind=kind,source_table=table,statement=statement,parameters={'rows':batch})
                    content['batch_sha256']=hashlib.sha256(encoded(content).encode()).hexdigest()
                    native.write(encoded(content)+'\n');batch.clear();batch_count+=1
                    if batch_count>65536:raise ValueError('Native offline batch budget exceeded')
            def add(kind,table,statement,row):
                key=(kind,table,statement);batch=buffers.setdefault(key,[]);batch.append(row)
                if len(buffers)>16:raise ValueError('Unexpected native batch type fanout')
                if len(batch)>=2500:flush(key)
            kinds=[r[0] for r in db.execute('SELECT DISTINCT kind FROM nodes ORDER BY kind')]
            csvs={};field_sets={}
            for kind in kinds:
                props=set()
                for (raw,) in db.execute('SELECT props FROM nodes WHERE kind=?',(kind,)):
                    for k,v in json.loads(raw).items():
                        if k==control:continue
                        if k in prop_types and prop_types[k]!=type(v).__name__:raise ValueError('Mixed node property type')
                        prop_types[k]=type(v).__name__;props.add(k)
                fields=['xgap_id:ID','id']+sorted(props)+[':LABEL'];field_sets[kind]=fields
                csvs[kind]=csv.writer(text_gzip(stack,root/('nodes-'+kind+'.csv.gz')));csvs[kind].writerow(fields)
                node_types[kind]=dict(properties=['id','xgap_id',*sorted(props)])
                constraint=dict(kind='constraint',source_table=kind,statement=f'CREATE CONSTRAINT ch6_{kind}_id IF NOT EXISTS FOR (n:{kind}) REQUIRE n.xgap_id IS UNIQUE',parameters={})
                constraint['batch_sha256']=hashlib.sha256(encoded(constraint).encode()).hexdigest();native.write(encoded(constraint)+'\n')
            edge_csv=csv.writer(text_gzip(stack,root/'relationships.csv.gz'))
            edge_csv.writerow([':START_ID',':END_ID',':TYPE','xgap_id','id','timestamp:long',core['measure']+':double'])
            for replica in range(copies):
                for ident,kind,raw in db.execute('SELECT id,kind,props FROM nodes ORDER BY kind,id'):
                    props=json.loads(raw);local=identity(ident,replica);business=ident if replica==0 else ident+'@replica'+str(replica)
                    ordinary={'id':business,'xgap_id':local,**{k:v for k,v in props.items() if k!=control}}
                    common=f'r:{local} a s:{kind}; s:id {literal(business)}; s:xgap_id {literal(local)}'
                    for name in graphs:
                        body=''.join(f'; s:{k} {literal(v)}' for k,v in sorted(ordinary.items()) if k not in ('id','xgap_id'))
                        rdfs[name].write(common+body+' .\n')
                    if control in props:rdfs['control'].write(common+f'; s:{control} {literal(props[control])} .\n')
                    else:rdfs['control'].write(common+' .\n')
                    add('nodes',kind,f'UNWIND $rows AS row CREATE (n:{kind}) SET n = row.props',dict(id=business,props=ordinary))
                    csvs[kind].writerow([local,business,*[ordinary[k] for k in field_sets[kind][2:-1]],kind])
                    counts['nodes']+=1;logical_hash.update((encoded([replica,ident,kind,props])+'\n').encode())
                # Nodes must precede relationship MATCH in the transactional
                # fallback even when independent type buffers are not full.
                flush()
                for ordinal,ident,src,dst,stamp,value in db.execute('SELECT * FROM edges ORDER BY ordinal'):
                    if scale=='.25' and ordinal%4:continue
                    # A stable arithmetic partition avoids Python's randomized hash.
                    shard=graphs[(ordinal-1)%len(graphs)];counts['original_edges']+=1;source_edges[shard]+=1
                    source_id,target_id=identity(src,replica),identity(dst,replica)
                    for label in (relation,relation+('_EARLY' if stamp<=cut else '_LATE')):
                        local=identity(label+':'+ident,replica);properties={'id':ident,'xgap_id':local,'timestamp':stamp,core['measure']:value}
                        rdfs[shard].write(f'r:{local} a s:Edge; s:source r:{source_id}; s:target r:{target_id}; s:edgeLabel s:{label}'
                            +''.join(f'; s:{k} {literal(v)}' for k,v in sorted(properties.items()))+' .\n')
                        statement=f'UNWIND $rows AS row MATCH (a:{core["node_type"]} {{xgap_id:row.fromId}}), (b:{core["target_type"]} {{xgap_id:row.toId}}) CREATE (a)-[e:{label}]->(b) SET e = row.props'
                        add('relationships',label,statement,dict(fromId=source_id,toId=target_id,props=properties))
                        edge_csv.writerow([source_id,target_id,label,local,ident,stamp,value]);counts['view_edges']+=1
                    logical_hash.update((encoded([replica,ordinal,ident,src,dst,stamp,value])+'\n').encode())
                    if counts['original_edges']%100000==0:
                        if shutil.disk_usage(root).free<6*1024**3:raise ValueError('Six-GiB reserve reached')
                        if sum(p.stat().st_size for p in root.iterdir() if p.is_file())>16*1024**3:
                            raise ValueError('Sixteen-GiB compressed materialization bound reached')
            flush()
        edge_labels=[relation,relation+'_EARLY',relation+'_LATE'];kinds=sorted(node_types)
        properties={'id','xgap_id','timestamp',core['measure'],control,*prop_types}
        terms={k:dict(kind='property',representation=NS+k) for k in properties}
        terms.update({k:dict(kind='class',representation=NS+k) for k in kinds})
        terms.update({k:dict(kind='relation',representation=NS+k) for k in edge_labels})
        mapping=dict(resource_namespace=RESOURCE,identity_property='xgap_id',
            rdf_edge_encoding=asdict(RdfEdgeEncoding('ch6-core-v1',NS+'Edge',NS+'source',NS+'target',NS+'edgeLabel')),
            rdf_node_classes=[NS+k for k in kinds],
            backend_mapping=dict(mapping_id='ch6-core-v1',version='1',backends={n:dict(namespace=NS) for n in names},term_mappings={n:terms for n in names}))
        schema={n:dict(nodes=node_types,edges=[dict(label=l,source=core['node_type'],target=core['target_type'],properties=['id','xgap_id','timestamp',core['measure']]) for l in edge_labels],
                       description='Stored directed core edges and ordinary node attributes. Temporal view relations are disjoint source subsets.') for n in graphs}
        schema['control']=dict(nodes={k:dict(properties=['id','xgap_id',*([control] if k==core['target_type'] else [])]) for k in kinds},edges=[],description='Same-snapshot control attributes, entity type and identity stubs only')
        schema.update(shared_identity_namespace=RESOURCE,identity_property='xgap_id',
                      scalar_semantics={'id':'string','timestamp':'integer milliseconds',core['measure']:'number',
                                        control:'string' if control=='gender' else 'boolean','parallel_edges':'distinct edge identity; bag multiplicity retained'})
        write(root/'mapping.json',mapping);write(root/'source-schema.json',schema)
        files={p.name:pin(p) for p in sorted(root.iterdir()) if p.name!='intent.json'}
        receipt.update(success=True,counts=counts,logical_facts_sha256=logical_hash.hexdigest(),source_original_edges=source_edges,
                       native_batch_count=batch_count+len(kinds),output_files=files,mapping=files['mapping.json'],source_schema=files['source-schema.json'],
                       rdf_loads={n:{**files[n+'.ttl.gz'],'size_bytes':files[n+'.ttl.gz']['bytes']} for n in names},
                       native_load=files['load_neo4j_batches.jsonl.gz'],index_unchanged=pin(meta['database']['path'])==meta['database'])
        if not receipt['index_unchanged']:raise ValueError('Index changed during materialization')
    except Exception as error:receipt.update(success=False,error_type=type(error).__name__,error=str(error))
    receipt['offline_seconds']=time.monotonic()-started;write(root/'receipt.json',receipt)
    return receipt
