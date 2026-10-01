"""Column NDV proxies for deduplicating bind requests; never resource bounds.

Propagation uses typed runtime columns and frozen source populations. Joins may
duplicate rows but cannot increase a preserved column's distinct values. Unknown
columns deliberately fall back to input rows, not zero or a guessed small NDV.
"""
from xgap.runtime.contracts import RuntimeNodeKind as R


def bind_keys(node,rows,columns):
    parent=node.inputs[0]
    return min(rows[parent],columns[parent].get(node.parameters.get('bind_field'),rows[parent]))


def _equal_constants(condition):
    if condition.get('op')=='and':
        for child in condition['args']:yield from _equal_constants(child)
    elif condition.get('op')=='eq' and 'value' in condition and condition['value'] is not None:
        yield condition['field']


def propagate(node,out,rows,columns,*,populations,degrees,unique_properties,sent=None):
    p=node.parameters;kind=node.kind
    incoming=dict(columns[node.inputs[0]]) if node.inputs else {}
    if kind in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY):
        a=p['artifact']['parameters'];compiler=a.get('compiler');backend=p['backend_id']
        if compiler=='native-spj-final-topk-v1':
            values={f:out for f in a['output_columns']}
        else:
            values={'entity':out}
            if compiler=='semantic_node_match_v1':
                values.update({f:out for f in a.get('scalar_properties',{})})
            else:
                descriptor=a.get('edge_statistics_descriptor',{})
                for column in ('source','target'):
                    role=('target' if column=='source' else 'source') if descriptor.get('direction')=='IN' else column
                    info=degrees.get((backend,descriptor.get('label'),role))
                    values[column]=min(out,float(info[1] if info else populations[backend][0]))
                values.update({f:out for f in a.get('scalar_properties',{})})
            if sent is not None:
                column=a.get('bound_identity_column','entity')
                if column in values:values[column]=min(values[column],sent)
                if compiler=='semantic_node_match_v1' and column=='entity':
                    # Only the frozen unique-property contract links these
                    # scalar projections to the logical node identity.
                    for f,prop in a.get('scalar_properties',{}).items():
                        if prop in unique_properties:values[f]=min(values[f],sent)
            for c in a.get('necessary_row_filters',{}).get('conditions',[]):
                for field in _equal_constants(c):
                    if field in values:values[field]=min(values[field],1.)
    elif kind is R.NORMALIZE_NODE_BINDINGS:
        aliases=p.get('identity_fields',{'entity':p.get('entity_field','entity')})
        values={aliases.get(f,f):v for f,v in incoming.items()}
    elif kind is R.COORDINATOR_ROW_PROJECT:
        values={name:incoming.get(spec['field'],rows[node.inputs[0]])
            for name,spec in p['projections'].items() if spec.get('kind')=='field'}
    elif kind is R.COORDINATOR_JOIN:
        left,right=node.inputs;values=dict(columns[left]);rvalues=columns[right]
        # Runtime column collision names can depend on values. Only unambiguous
        # left fields and noncolliding right fields are propagated; aliases not
        # known here fall back to rows at their consumer.
        values.update({f:v for f,v in rvalues.items() if f not in values})
        lk,rk=p['left_on'],p['right_on']
        common=min(columns[left].get(lk,rows[left]),rvalues.get(rk,rows[right]))
        if lk in columns[left]:values[lk]=min(values[lk],common)
        if rk not in columns[left] and rk in rvalues:values[rk]=min(values[rk],common)
    elif kind is R.COORDINATOR_FILTER:
        values=incoming
        for field in _equal_constants(p['condition']):
            if field in values:values[field]=min(values[field],1.)
    elif kind is R.COORDINATOR_SEMI_JOIN:
        values=incoming
        if p.get('left_value_mode','scalar')=='scalar':
            field=p['left_on'];right=node.inputs[1]
            if field in values:values[field]=min(values[field],columns[right].get(p['right_on'],rows[right]))
    elif kind is R.COORDINATOR_GROUP_AGGREGATE:
        values={f:incoming.get(f,out) for f in p.get('group_by',())}
    elif kind in (R.COORDINATOR_SORT_LIMIT,R.EXCHANGE):values=incoming
    else:values={}  # ALIGN/MERGE and unknown lineage never manufacture an NDV.
    return {f:min(out,max(0.,v)) for f,v in values.items()}
