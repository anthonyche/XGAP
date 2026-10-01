"""Publish one reusable source-only core profile before selecting any queries."""
from copy import deepcopy
from contextlib import ExitStack
from dataclasses import asdict, replace
import gzip
import hashlib
import json
from pathlib import Path

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.catalog.build import freeze_resolution_bundle
from xgap.compilers.features import default_profile
from xgap.experiments.ch6_fact_index import encoded,pin,verify,write
from xgap.experiments.ch6_materialize import NS,text_gzip
from xgap.experiments.compact_profile import load_compact_graph_provider
from xgap.experiments.one_shot_profile import FrozenOneShotProfile,SCHEMA,read_pinned
from xgap.planning.runtime_estimator import FrozenSourceStatistics,SourceStatistics
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment
from xgap.planning.runtime_work_estimator import FrozenWorkEstimator,frozen_estimator_from_dict


def source_catalog(meta, mapping):
    """Reconstruct source-only catalog documents without query or graph reads."""
    names=list(meta['rdf_loads'])
    catalog=dict(schema_version='m15-e3-resolution-catalog-v1',catalog_id='ch6-core-schema',catalog_version=meta['logical_facts_sha256'],entries=[],
        metadata=dict(offline=True,query_reads=0,answer_reads=0,authority='proposal only',
                      entity_scope='Typed IDs are explicit query literals. This schema catalog makes no free-name entity coverage claim.'))
    bindings={}
    def add(kind,value,aliases=()):
        key=kind+':'+hashlib.sha256(encoded(value).encode()).hexdigest()
        catalog['entries'].append(dict(candidate_id=key,kind=kind,canonical_label=str(value).lower() if type(value) is bool else str(value),
            aliases=list(aliases),authoritative_mentions=[],provenance=dict(source='frozen core schema')))
        bindings[key]=dict(kind=kind,value=value)
    terms=mapping['backend_mapping']['term_mappings'][names[0]]
    for name,t in sorted(terms.items()):
        if t['kind'] in ('class','relation'):add('type' if t['kind']=='class' else 'predicate',name)
    for name in names:add('source',name)
    for v in meta['core']['control_values']:add('constraint',v)
    return catalog, bindings


def publish(materialization, trained_profile, trained_profile_sha256, output, *, deployment='rdf'):
    meta=json.loads(Path(materialization).read_text())
    if not meta.get('success') or meta['schema_version']!='xgap-ch6-core-materialization-v1':
        raise ValueError('Successful same-facts core materialization required')
    if deployment not in ('rdf','native'):raise ValueError('Unknown deployment')
    if deployment=='native' and meta['source_count']!=2:raise ValueError('Native multi-shard loader not yet admitted')
    parent=json.loads(read_pinned(trained_profile,trained_profile_sha256))
    ref=parent['estimator'];model_data=json.loads(read_pinned(Path(trained_profile).parent/ref['path'],ref['sha256']))
    model=frozen_estimator_from_dict(model_data)
    trained=model if isinstance(model,FrozenWorkEstimator) else model.trained_model
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    for field in ('mapping','source_schema'):verify(meta[field])
    mapping=json.loads(Path(meta['mapping']['path']).read_text());schema=json.loads(Path(meta['source_schema']['path']).read_text())
    names=list(meta['rdf_loads']);graph_names=[n for n in names if n!='control']
    ids={n:('neo4j' if n=='graph' else 'fuseki') if deployment=='native' else 'rdf_'+n for n in names}
    catalog, bindings = source_catalog(meta, mapping)
    terms=mapping['backend_mapping']['term_mappings'][names[0]]
    write(root/'catalog-input.json',catalog);write(root/'bindings-input.json',bindings)
    frozen=freeze_resolution_bundle(catalog=root/'catalog-input.json',bindings=root/'bindings-input.json',output=root/'catalog')
    # Reuse the existing faithful generic schema-to-label conversion, with its
    # historical backend key rebound locally. It does not read questions.
    from prepare_chapter7_public_metadata import metadata_lines
    label_mapping=deepcopy(mapping);base=label_mapping['backend_mapping']
    base['backends']['fuseki']=dict(namespace=NS);base['term_mappings']['fuseki']=terms
    metadata=root/'metadata.nt'
    with metadata.open('x') as target:
        for line in metadata_lines(catalog,bindings,label_mapping):target.write(line)
    loads=deepcopy(meta['rdf_loads'])
    # The control file is small; stream its data and the shared public ontology
    # into one gzip stream instead of copying/re-parsing the large edge graph.
    verify(loads['control']);overlay=root/'control-public.ttl.gz'
    with ExitStack() as stack:
        out=text_gzip(stack,overlay)
        with gzip.open(loads['control']['path'],'rt') as source:
            for line in source:out.write(line)
        out.write('\n');out.write(metadata.read_text())
    loads['control']={**pin(overlay),'size_bytes':overlay.stat().st_size}
    entries=[];sources={};backends={}
    mapped={**mapping['backend_mapping'],'backends':{ids[n]:dict(namespace=NS) for n in names},
            'term_mappings':{ids[n]:terms for n in names}}
    for n in names:
        backend=ids[n];engine='neo4j' if backend=='neo4j' else 'fuseki'
        source_version=loads[n]['sha256'];sources[n]=dict(version=source_version,replicas=[backend])
        rows=meta['counts']['nodes']+(2*meta['source_original_edges'][n] if n in graph_names else 0)
        entries.append(SourceStatistics(backend,n,source_version,rows,128.0,pin(materialization)['sha256']))
        semantic=dict(resource_namespace=mapping['resource_namespace'],identity_property='xgap_id',
                      profile=replace(default_profile(engine),backend_id=backend).to_dict())
        if engine=='fuseki':semantic.update(backend_mapping=mapped,rdf_edge_encoding=mapping['rdf_edge_encoding'],rdf_node_classes=mapping['rdf_node_classes'])
        backends[backend]=dict(semantic=semantic,client=dict(engine=engine,url='http://127.0.0.1:7474' if engine=='neo4j' else 'http://127.0.0.1:3030',
                             database='neo4j' if engine=='neo4j' else n,timeout_seconds=20,auth=None))
    statistics=FrozenSourceStatistics('ch6-core-source-statistics-v1',meta['logical_facts_sha256'],tuple(entries))
    deployed=FrozenInstanceWorkDeployment('ch6-core-frozen-transfer-v1',trained,statistics,
        tuple((k,v['client']['engine']) for k,v in backends.items()),'offline materialization:'+pin(materialization)['sha256'])
    deployed.save(root/'estimator.json')
    provider=load_compact_graph_provider(prompt_version='v2',language_version='v2');cfg=provider.config
    (root/'prompt.txt').write_text(provider.system_prompt);prompt_pin=pin(root/'prompt.txt');modes={}
    for mode in ('precision','performance'):
        policy=replace(OneShotPolicy.for_mode(mode),candidate_cap=1,retrieval_rows_per_relation=None)
        modes[mode]=dict(policy=asdict(policy),provider=dict(provider_id='ch6-shared-compact-v2',base_url=cfg.base_url,model=cfg.model,
            api_key_env=cfg.api_key_env,wire_profile=cfg.safe_dict()['wire_profile'],prompt={k:prompt_pin[k] for k in ('path','sha256')},
            temperature=cfg.temperature,top_p=cfg.top_p,max_tokens=4096,timeout_seconds=60,disable_thinking=True))
    native_files={'load_neo4j_batches.jsonl':meta['native_load'],'control.ttl':loads['control']}
    doc=dict(schema_version=SCHEMA,profile_id='ch6-'+meta['dataset']+'-'+deployment+'-'+meta['logical_facts_sha256'][:16],
        dataset=dict(dataset_id=meta['dataset']+'-core',version=meta['logical_facts_sha256']),source_schema=schema,sources=sources,backends=backends,
        catalog=dict(path=str(root/'catalog'),bundle_hash=frozen['bundle_hash']),
        estimator={k:v for k,v in pin(root/'estimator.json').items() if k in ('path','sha256')},modes=modes,
        offline=dict(materialization=pin(materialization),materialization_root=meta['materialization_root'],
            rdf_loads=loads,native_load_files=native_files,shared_public_metadata=pin(metadata),
            native_bulk_files={name:ref for name,ref in meta['output_files'].items() if name.startswith('nodes-') or name=='relationships.csv.gz'},
            native_bulk_counts=dict(nodes=meta['counts']['nodes'],relationships=meta['counts']['view_edges'],load_calls=meta['native_batch_count']),
            trained_profile=dict(path=str(Path(trained_profile).resolve()),sha256=trained_profile_sha256),
            estimator_scope='unchanged frozen weights; full source counts; 128-byte declared work proxy; uncalibrated transfer',
            weights_changed=False,query_reads=0,answer_reads=0,model_calls=0,backend_calls=0,fit_calls=0,formal_campaign_ready=False))
    write(root/'profile.json',doc);profile=pin(root/'profile.json')
    FrozenOneShotProfile.load(profile['path'],expected_sha256=profile['sha256'])
    write(root/'receipt.json',dict(success=True,profile=profile,model_calls=0,backend_calls=0,
        catalog_entries=len(catalog['entries']),logical_facts_sha256=meta['logical_facts_sha256'],deployment=deployment,stores_prepared=False))
    return profile
