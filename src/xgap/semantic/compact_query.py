"""Bounded declarative graph intent; no generated aliases or physical choices.

The wire and local validator share this finite, nonrecursive schema. The existing
small schema evaluator is reused without adding a runtime dependency.
"""

from copy import deepcopy
import json
import re

from xgap.semantic.parameter_contract import _issues


SCHEMA = 'xgap-compact-graph-candidates-v1'
LOWERING = 'xgap-compact-graph-lowering-v1'
SCHEMA_V2 = 'xgap-compact-graph-candidates-v2'
LOWERING_V2 = 'xgap-compact-graph-lowering-v2'
TEXT = {'type': 'string', 'minLength': 1}
NULL = {'type': 'null'}
BOOL = {'type': 'boolean'}


def obj(fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def array(item, maximum, minimum=0):
    return {'type': 'array', 'items': item, 'maxItems': maximum, 'minItems': minimum}


def either(*items):
    return {'anyOf': list(items)}


REF = obj({'var': TEXT, 'property': either(TEXT, NULL)})
LITERAL = obj({'value': either(TEXT, {'type':'number'}, BOOL, NULL, {'const':''})})
PREDICATE = obj({'left': REF, 'op': {'enum':['eq','ne','lt','le','gt','ge']},
    'right': either(REF, LITERAL), 'value_type': {'enum':['scalar','timestamp_ms','lexical_string']}})
EXPR = either(REF, obj({'aggregate': {'enum':['sum','count','min','max']},
    'field': either(REF, NULL), 'distinct': BOOL}))
QUERY = obj({
    'nodes': array(obj({'var':TEXT, 'type':TEXT, 'entity':either(TEXT,NULL)}), 8, 1),
    'edges': array(obj({'var':TEXT, 'type':TEXT, 'source':TEXT, 'target':TEXT}), 12),
    'path': either(NULL, obj({'var':TEXT, 'type':TEXT, 'source':TEXT, 'target':TEXT,
        'min_hops':{'type':'integer','enum':[1,2,3]}, 'max_hops':{'type':'integer','enum':[1,2,3]},
        'mode':{'enum':['ACYCLIC','WALK']},
        'time':either(NULL,obj({'property':TEXT, 'lower':either(TEXT,NULL), 'upper':either(TEXT,NULL),
            'lower_inclusive':BOOL, 'upper_inclusive':BOOL, 'increasing':BOOL}))})),
    'where': array(PREDICATE, 32),
    'select': {'type':'object', 'additionalProperties':EXPR, 'minProperties':1},
    'deduplicate_by': either(NULL, array(TEXT, 12, 1)),
    'order_by': array(obj({'field':TEXT, 'direction':{'enum':['asc','desc']}}), 16),
    'limit': either(NULL, {'type':'integer','minimum':1})})


def query_schema(version='v1'):
    if version not in ('v1', 'v2'):
        raise ValueError('Unknown compact language version')
    schema = deepcopy(QUERY)
    if version == 'v2':
        schema['properties']['contribution_by'] = schema['properties'].pop('deduplicate_by')
        schema['required'] = [f if f != 'deduplicate_by' else 'contribution_by' for f in schema['required']]
    return schema


def compact_schema(candidate_cap, *, version='v1'):
    if type(candidate_cap) is not int or not 1<=candidate_cap<=8:
        raise ValueError('Compact candidate cap must be1..8')
    query = query_schema(version)
    return obj({'schema_version':{'const':SCHEMA if version == 'v1' else SCHEMA_V2}, 'candidates':array(obj({
        'candidate_id':TEXT, 'quality_proxy':either({'type':'number'},NULL), 'query':query}),candidate_cap,1)})


def validate_query(query, *, version='v1'):
    # Strict JSON and a byte bound precede traversal. No alias or response repair.
    if len(json.dumps(query,allow_nan=False).encode())>65536:
        raise ValueError('Compact query exceeds64KiB')
    errors=_issues(query_schema(version),query,'query')
    if errors: raise ValueError('; '.join(errors[:8]))
    if len(query['select'])>16 or query['limit'] is not None and query['limit']>1000:
        raise ValueError('Compact output/limit exceeds its profile')
    names=[v['var'] for v in query['nodes']+query['edges']]+([query['path']['var']] if query['path'] else [])
    if len(names)!=len(set(names)) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',n) for n in names):
        raise ValueError('Compact variables must be unique identifiers of at most32 characters')
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',n) for n in query['select']):
        raise ValueError('Invalid output alias')
    nodes={n['var']:n for n in query['nodes']}
    for edge in query['edges']+([query['path']] if query['path'] else []):
        if edge['source'] not in nodes or edge['target'] not in nodes:
            raise ValueError('Edge/path endpoints must be declared nodes')
    path=query['path']
    if path and (path['min_hops']>path['max_hops'] or nodes[path['source']]['type']!=nodes[path['target']]['type']):
        raise ValueError('Compact path requires ordered bounds and one homogeneous endpoint type')
    order=[o['field'] for o in query['order_by']]
    if len(order)!=len(set(order)) or not set(order)<=set(query['select']):
        raise ValueError('Order fields must be unique selected aliases')
    if query['limit'] is not None and not order:
        raise ValueError('Compact top K requires explicit ordering')
    keys=query['deduplicate_by' if version == 'v1' else 'contribution_by']
    if keys is not None and (len(keys)!=len(set(keys)) or not set(keys)<=set(names)-({path['var']} if path else set())):
        raise ValueError('Deduplication requires distinct node/edge variables')
    if version == 'v2' and keys is not None:
        measured = {e['field']['var'] for e in query['select'].values()
            if 'aggregate' in e and e['field'] is not None}
        if len(measured) > 1 or path and path['var'] in measured:
            raise ValueError('Contribution aggregates require one shared stored node/edge variable; separate grains and path aggregates are outside v2')
    return query
