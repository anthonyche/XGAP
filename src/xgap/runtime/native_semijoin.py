"""Exact external-dimension membership followed by one native SPJ query.

One external node relation may contribute only its existence after local
predicates. External scalar aliases may be carried internally but never escape
into answers, ordering, joins or new predicates. A checked bound external read
and its dependencies provide keys BEFORE complete native prefix/final top-K.
"""
from dataclasses import replace
import hashlib
import json

from xgap.compilers.native_spj import compile_native_spj
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.anchor_reduction import depends_on
from xgap.runtime.contracts import RuntimeNode,RuntimeNodeKind as R
from xgap.runtime.physical_strategies import _bound_match_artifact
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.semantic.program import SemanticOperatorKind as S


PARAMETER='xgap_spj_membership_keys'


def _terms(c):
    if c['op']=='and':
        for child in c['args']:yield from _terms(child)
    else:yield c


def _fields(c):
    if c['op'] in ('and','or'):return set().union(*(_fields(a) for a in c['args']))
    if c['op']=='not':return _fields(c['arg'])
    return {c[k] for k in ('field','right_field') if k in c}


def _rename_fields(c,aliases):
    if c['op'] in ('and','or'):return {**c,'args':[_rename_fields(a,aliases) for a in c['args']]}
    if c['op']=='not':return {**c,'arg':_rename_fields(c['arg'],aliases)}
    return {k:aliases.get(v,v) if k in ('field','right_field') else v for k,v in c.items()}


def _reduction(program,placement,backends,schema):
    """Bounded tree rewrite; side predicates must already hold on its driver."""
    ops={o.operator_id:o for o in program.operators}
    if len(ops)>64 or len(program.roots)!=1 or program.holes:raise ValueError('Bounded grounded tree required')
    native=[b for b in set(placement.values()) if (backends[b].profile.engine if backends[b].profile else b)=='neo4j']
    if len(native)!=1:raise ValueError('Exactly one native core required')
    backend=native[0];side=[o for o in program.operators if o.kind is S.MATCH and placement[o.operator_id]!=backend]
    if len(side)!=1 or 'edge' in side[0].parameters:raise ValueError('One external node dimension required')
    side=side[0];side_id=side.operator_id;external=backends[placement[side_id]]
    if external.resource_namespace!=backends[backend].resource_namespace:raise ValueError('Different identity namespaces')
    if side.constraints or side.required_capabilities:raise ValueError('Additional dimension requirements')
    consumers={k:[] for k in ops}
    for o in program.operators:
        for i in o.input_ids:consumers[i].append(o)
    if any(len(c)>1 for c in consumers.values()):raise ValueError('Shared semantic branch')
    branch={side_id};tip=side;enforced=set();scalar=set(side.parameters.get('properties',{}))
    key=side.parameters.get('entity_field','entity')
    while len(consumers[tip.operator_id])==1 and consumers[tip.operator_id][0].kind is S.FILTER:
        tip=consumers[tip.operator_id][0];branch.add(tip.operator_id)
        if tip.constraints or tip.required_capabilities:raise ValueError('Additional filter requirements')
        for c in _terms(tip.parameters['condition']):
            if not _fields(c)<=scalar|{key}:raise ValueError('Unbound side predicate')
            enforced.add(json.dumps(c,sort_keys=True))
    if len(consumers[tip.operator_id])!=1:raise ValueError('External dimension needs one consuming join')
    join=consumers[tip.operator_id][0]
    if join.kind is not S.JOIN or join.parameters['left_on']!=key or join.parameters['right_on']!=key:
        raise ValueError('Same canonical identity join required')
    if join.constraints or join.required_capabilities:raise ValueError('Additional join requirements')
    other=next(i for i in join.input_ids if i!=tip.operator_id)
    # Side scalars may pass through intermediate projections, but may not
    # influence the native answer except through the already enforced predicate.
    native_matches=[o for o in program.operators if o.kind is S.MATCH and o.operator_id!=side_id]
    original=compile_semantic_program(program,source_bindings=placement,backends=backends,
        max_remote_calls=64,max_parallelism=1)
    schemas=original.metadata['schemas']
    if scalar&{key} or any(scalar&set(schemas[o.operator_id]['fields']) for o in native_matches):
        raise ValueError('Scalar collision')
    targets=[o.operator_id for o in native_matches if 'edge' not in o.parameters and o.parameters.get('entity_field','entity')==key]
    if len(targets)!=1:raise ValueError('One native node identity representative required')
    aliases={join.operator_id:other};removed=branch|{join.operator_id};kept=[]
    external_fields={};dropped=[]
    def resolve(i):
        seen=set()
        while i in aliases:
            if i in seen:raise ValueError('Cyclic bypass')
            seen.add(i);i=aliases[i]
        return i
    for o in program.operators:
        if o.kind not in (S.MATCH,S.FILTER,S.JOIN,S.PROJECT,S.ORDER_LIMIT):raise ValueError('Non-SPJ core')
        if o.constraints or o.required_capabilities:raise ValueError('Additional semantic requirements')
        p=dict(o.parameters)
        inherited=dict(external_fields[o.input_ids[0]]) if o.input_ids else {}
        if o.kind is S.MATCH:
            output={f:f for f in scalar} if o.operator_id==side_id else {}
        elif o.kind is S.JOIN:
            right=external_fields[o.input_ids[1]]
            if p['left_on'] in inherited or p['right_on'] in right:
                raise ValueError('External scalar join key')
            left_fields=schemas[o.input_ids[0]]['fields']
            output={**inherited,**{p.get('right_prefix','right_')+f if f in left_fields
                and not f==p['left_on']==p['right_on'] else f:v for f,v in right.items()}}
        elif o.kind is S.PROJECT:
            if any(v.get('kind')!='field' for v in p['projections'].values()):
                raise ValueError('Computed projection')
            output={f:inherited[v['field']] for f,v in p['projections'].items() if v['field'] in inherited}
        else:output=inherited
        external_fields[o.operator_id]=output
        if o.operator_id in program.roots and output:raise ValueError('External scalar output')
        if o.operator_id in removed:continue
        if o.kind is S.FILTER:
            terms=[]
            for c in _terms(p['condition']):
                if _fields(c)&set(inherited):
                    checked=_rename_fields(c,inherited)
                    if not _fields(checked)<=scalar|{key} or json.dumps(checked,sort_keys=True) not in enforced:
                        raise ValueError('External predicate not guaranteed by the side relation')
                else:terms.append(c)
            if not terms:
                aliases[o.operator_id]=resolve(o.input_ids[0]);continue
            p['condition']=terms[0] if len(terms)==1 else dict(op='and',args=terms)
        elif o.kind is S.PROJECT:
            p['projections']={f:v for f,v in p['projections'].items() if f not in output}
            if not p['projections']:raise ValueError('Empty native projection')
            if output:dropped.append(dict(operator=o.operator_id,fields=sorted(output)))
        elif o.kind is S.ORDER_LIMIT:
            if any(s['field'] in inherited for s in p['order_by']):raise ValueError('External scalar ordering')
        kept.append(replace(o,input_ids=tuple(resolve(i) for i in o.input_ids),parameters=p))
    reduced=replace(program,operators=tuple(kept),roots=tuple(resolve(i) for i in program.roots))
    bound={k:v for k,v in placement.items() if k!=side_id}
    artifact,_=compile_native_spj(reduced,backends[backend],schema,bound,
        prefix_topk=True,identity_membership=(targets[0],PARAMETER))
    proof=dict(profile='native-external-semijoin-v1',external_match=side_id,external_output=tip.operator_id,
        native_key_driver=other,
        identity_field=key,native_backend=backend,external_backend=placement[side_id],
        external_scalar_fields=sorted(scalar),side_predicates_enforced=True,global_topk_after_membership=True,
        removed_intermediate_scalar_projections=dropped,external_output_absent=True,
        original_program_sha256=hashlib.sha256(json.dumps(program.to_dict(),sort_keys=True).encode()).hexdigest(),
        binding_overflow='fail without truncation',current_query_observation_calls=0)
    return artifact,proof


def semijoin_nodes(program,plan,backends,schema,policy,cache):
    """Construct or reuse a paid bound prefix, without observing source rows."""
    placement=plan.metadata['source_bindings'];cache_key=('semijoin',program.program_id,
        json.dumps(program.to_dict(),sort_keys=True),tuple(sorted(placement.items())))
    if cache_key not in cache:
        cache[cache_key]=None
        cache[cache_key]=_reduction(program,placement,backends,schema)
    compiled=cache[cache_key]
    if compiled is None:return None
    artifact,proof=compiled;proof=dict(proof);nodes={n.node_id:n for n in plan.nodes}
    remote=nodes.get(proof['external_match']+'/native')
    if remote is None or len(remote.semantic_operator_ids)!=1:return None
    if remote.kind is R.REMOTE_QUERY:
        # This contraction's canonical prerequisite is a key restriction at
        # the same identity join. Build it as part of the checked transform,
        # rather than requiring a separately attractive intermediate plan.
        key_driver=plan.metadata['operator_outputs'][proof['native_key_driver']]
        if depends_on(plan,key_driver,remote.node_id):return None
        bound,parameter=_bound_match_artifact(QueryArtifact.from_dict(remote.parameters['artifact']),
            backends[proof['external_backend']],max_bindings=policy.max_bindings,
            max_binding_bytes=policy.max_binding_bytes,identity_column='entity',capped_key_work=True)
        remote=replace(remote,kind=R.REMOTE_BIND_QUERY,inputs=(key_driver,),parameters={**remote.parameters,
            'artifact':bound.to_dict(),'bind_field':proof['identity_field'],
            'parameter':parameter,'max_bindings':policy.max_bindings})
        nodes[remote.node_id]=remote
        proof['external_bind_created']=True
    elif remote.kind is not R.REMOTE_BIND_QUERY:return None
    else:proof['external_bind_created']=False
    driver=plan.metadata['operator_outputs'][proof['external_output']]
    ancestors=set();stack=[driver]
    while stack:
        k=stack.pop()
        if k in ancestors:continue
        ancestors.add(k);stack.extend(nodes[k].inputs)
    if remote.node_id not in ancestors or plan.roots[0] in ancestors:raise ValueError('Invalid dimension dependency')
    if any(n.kind not in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY,R.NORMALIZE_NODE_BINDINGS,
            R.COORDINATOR_FILTER,R.COORDINATOR_ROW_PROJECT,R.COORDINATOR_JOIN,R.COORDINATOR_SEMI_JOIN)
            for n in plan.nodes if n.node_id in ancestors):raise ValueError('Truncated or unsupported dimension driver')
    final=RuntimeNode(plan.roots[0],R.REMOTE_BIND_QUERY,inputs=(driver,),parameters=dict(
        backend_id=proof['native_backend'],artifact=artifact.to_dict(),bind_field=proof['identity_field'],
        parameter=PARAMETER,max_bindings=policy.max_bindings),semantic_operator_ids=tuple(o.operator_id for o in program.operators))
    return [nodes[n.node_id] for n in plan.nodes if n.node_id in ancestors]+[final],proof
