"""Reuse frozen stores with an explicit formal scalar/routing profile revision.

No data reload, queries, outcomes, estimator fit or baseline changes. Every
materialized graph shard has the full node table; only edge rows are partitioned.
"""
from copy import deepcopy
from pathlib import Path

from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.ch6_fact_index import pin
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once


REVISION='ch6-explicit-scalars-canonical-node-provider-v1'


def revise_schema(schema):
    result=deepcopy(schema)
    graphs=sorted(k for k,v in result.items() if isinstance(v,dict) and v.get('edges'))
    if not graphs or 'control' not in result:raise ValueError('Formal graph/control coverage required')
    # The materializer writes every node and ordinary property to every graph
    # shard. Declare one complete provider, not several disjoint node partitions.
    for name in graphs[1:]:
        for node in result[name]['nodes'].values():node['properties']=['xgap_id']
    for node in result['control']['nodes'].values():
        node['properties']=[p for p in node['properties'] if p!='id']
    result['replicated_node_coverage']=dict(profile=REVISION,canonical_provider=graphs[0],
        proof='ch6-core-materialization-v1 writes all nodes/ordinary attributes to each graph shard',
        edge_coverage='all graph shards remain required; no edge source removed')
    return result


def revise(prepared_pin,output):
    prepared=load(prepared_pin)
    if not prepared.get('success'):raise ValueError('Successful frozen stores required')
    parent=prepared['profile'];profile=FrozenOneShotProfile.load(parent['path'],expected_sha256=parent['sha256'])
    import json
    doc=json.loads(profile.document_json);old=deepcopy(doc)
    if doc['offline'].get('formal_profile_revision'):raise ValueError('Formal revision already applied')
    materialization=load(doc['offline']['materialization'])
    if not materialization['success'] or materialization['schema_version']!='xgap-ch6-core-materialization-v1':
        raise ValueError('Complete replicated-node materialization required')
    if doc['source_schema']!=load(materialization['source_schema']):
        raise ValueError('Only original formal source coverage may be revised')
    build=load(prepared['input_seal'])
    if build['profile']!=parent:raise ValueError('Prepared input identity differs')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    origin=Path(parent['path']).parent
    for key in ('estimator','catalog'):doc[key]['path']=str((origin/doc[key]['path']).resolve())
    prompts={}
    for mode in doc['modes'].values():
        provider=mode['provider'];ref=provider['prompt']
        text=read_pinned(origin/ref['path'],ref['sha256']).decode()
        marker='(scalar or timestamp_ms). Timestamp ordering uses timestamp_ms explicitly.'
        if text.count(marker)!=1:raise ValueError('Unknown shared prompt contract')
        text=text.replace(marker,'(scalar, timestamp_ms or lexical_string). Use lexical_string for lexical business-ID '
            'comparisons; this is Unicode code-point order without numeric coercion. Integer epoch-millisecond '
            'fields use scalar numerical comparisons. Only calendar-string timestamps use timestamp_ms.')
        if text not in prompts:
            path=root/('prompt-'+str(len(prompts))+'.txt');path.write_text(text)
            prompts[text]=pin(path)
        provider['prompt']={k:prompts[text][k] for k in ('path','sha256')}
        provider['provider_id']+=':'+REVISION
    doc['source_schema']=revise_schema(doc['source_schema'])
    doc['profile_id']+=':'+REVISION
    doc['offline']['formal_profile_revision']=dict(profile=REVISION,parent=parent,
        prepared_parent=prepared_pin,source_data_changed=False,queries_read=0,answers_read=0,
        model_calls=0,backend_calls=0,baseline_algorithm_changed=False)
    # Only routing declarations and shared scalar grammar instructions change.
    for key in ('dataset','sources','backends'):
        if doc[key]!=old[key]:raise ValueError('Data/backend identity changed')
    child=write_once(root/'profile.json',doc)
    FrozenOneShotProfile.load(child['path'],expected_sha256=child['sha256'])
    build['profile']=child
    build['store_reuse']=dict(prepared_parent=prepared_pin,original_input=prepared['input_seal'],profile_revision=REVISION)
    seal=write_once(root/'input-seal.json',build)
    result={**prepared,'profile':child,'input_seal':seal,'store_reuse':build['store_reuse']}
    # Preserve original loader/engine/store measurements verbatim and identify
    # their origin; this is a binding receipt, never another successful reload.
    return write_once(root/'receipt.json',result)
