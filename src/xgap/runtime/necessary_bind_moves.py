"""Answer-blind necessary-key reductions for the fixed-depth neighborhood.

Only exclusive inner-join subtrees with preserved canonical identity columns
qualify. The final joins/filters stay in place; no rows are truncated and a bind
overflow remains a failure. These transformations do not invoke an endpoint.
"""
from dataclasses import replace

from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.anchor_reduction import reduce_scalar_anchor,depends_on
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.physical_strategies import _bound_match_artifact
from xgap.semantic.program import SemanticOperatorKind as S


def mandatory_anchor_bind(program,plan,backends,policy):
    if 'anchor_reduction' in plan.metadata:return None
    reduced=reduce_scalar_anchor(program,plan)
    anchor=reduced.metadata.get('anchor_reduction')
    if not anchor:return None
    key=anchor['enforcing_filter']+'/anchor_reduction/keys'
    operators={o.operator_id:o for o in program.operators};nodes={n.node_id:n for n in reduced.nodes}
    replacements={}
    for target in anchor['target_matches']:
        op=operators[target];remote=nodes[target+'/native']
        if remote.kind is not R.REMOTE_QUERY or len(remote.semantic_operator_ids)!=1:return None
        column=next((c for c in ('source','target') if op.parameters.get(c+'_field',c)==anchor['identity_field']),None)
        if column is None or depends_on(reduced,key,remote.node_id):return None
        artifact,param=_bound_match_artifact(QueryArtifact.from_dict(remote.parameters['artifact']),
            backends[remote.parameters['backend_id']],max_bindings=policy.max_bindings,
            max_binding_bytes=policy.max_binding_bytes,identity_column=column,capped_key_work=True)
        replacements[remote.node_id]=replace(remote,kind=R.REMOTE_BIND_QUERY,inputs=(key,),
            parameters={**remote.parameters,'artifact':artifact.to_dict(),'bind_field':anchor['identity_field'],
                        'parameter':param,'max_bindings':policy.max_bindings})
    return replace(reduced,nodes=tuple(replacements.get(n.node_id,n) for n in reduced.nodes))


def nested_key_targets(identifier,field,operators,schemas,consumers,roots,chain=()):
    """Yield at most one path per exclusive source leaf; all alternatives stay safe.

    Follow the actual output-column provenance. A JOIN retains left names and
    prefixes colliding right names except its same-named equality key. A UNION
    may restrict each branch independently using the same necessary key set.
    """
    op=operators[identifier]
    if identifier in roots or consumers[identifier]!=1:return
    chain=(*chain,identifier)
    if op.kind is S.MATCH:
        identities={op.parameters.get('entity_field','entity'):'entity'}
        if 'edge' in op.parameters:
            identities.update({op.parameters.get(c+'_field',c):c for c in ('source','target')})
        if field in identities:yield op,chain,identities[field]
    elif op.kind is S.FILTER:
        yield from nested_key_targets(op.input_ids[0],field,operators,schemas,consumers,roots,chain)
    elif op.kind is S.PROJECT:
        projection=op.parameters['projections'].get(field,{})
        if projection.get('kind')=='field':
            yield from nested_key_targets(op.input_ids[0],projection['field'],operators,schemas,consumers,roots,chain)
    elif op.kind is S.UNION:
        for child in op.input_ids:
            yield from nested_key_targets(child,field,operators,schemas,consumers,roots,chain)
    elif op.kind is S.JOIN:
        left,right=op.input_ids;left_fields=schemas[left]['fields'];p=op.parameters
        if field in left_fields:
            yield from nested_key_targets(left,field,operators,schemas,consumers,roots,chain)
        for original in schemas[right]['fields']:
            renamed=p.get('right_prefix','right_')+original if original in left_fields and not original==p['left_on']==p['right_on'] else original
            if renamed==field:
                yield from nested_key_targets(right,original,operators,schemas,consumers,roots,chain)
