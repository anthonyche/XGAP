"""Checked representative reduction of an existential leaf, never answer LIMIT.

An edge and its degree-one endpoint disappear at the declared contribution
projection. Once every predicate involving them is evaluated locally, any one
satisfying witness per retained endpoint preserves that projection. Remaining
joins/filters/aggregation stay unchanged. No source observation is performed.
"""
from collections import Counter
from dataclasses import replace
import json

from xgap.compilers.cypher import _cypher_identifier as ident
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import compile_semantic_source
from xgap.semantic.program import SemanticOperatorKind as S

PROFILE='contribution-leaf-witness-v1'


def leaf_proofs(query):
    if query.get('path') or query.get('contribution_by') is None:return
    if any(n.get('entity') is not None for n in query['nodes']):return
    retained=set(query['contribution_by'])
    for e in query['select'].values():
        r=e if 'var' in e else e['field']
        if r:retained.add(r['var'])
    incidence=Counter(v for e in query['edges'] for v in (e['source'],e['target']))
    anchors={}
    for p in query['where']:
        if p['op']=='eq' and p['left']['property']=='id' and type(p['right'].get('value')) is str:
            anchors.setdefault(p['left']['var'],p['right']['value'])
    for edge in query['edges']:
        if edge['var'] in retained:continue
        for leaf,boundary in ((edge['source'],edge['target']),(edge['target'],edge['source'])):
            if leaf in retained or incidence[leaf]!=1 or leaf==boundary:continue
            guards=[];admitted=True
            for p in query['where']:
                variables={r['var'] for r in (p['left'],p['right']) if 'var' in r}
                if not variables&{leaf,edge['var']}:continue
                if edge['var'] in variables:admitted=False;break
                operands=[]
                for r in (p['left'],p['right']):
                    if 'value' in r:
                        if type(r['value']) is not str:admitted=False;break
                        operands.append(dict(value=r['value']))
                    elif r['property']!='id':admitted=False;break
                    elif r['var'] in (leaf,boundary):operands.append(dict(endpoint='source' if r['var']==edge['source'] else 'target'))
                    elif r['var'] in anchors:operands.append(dict(value=anchors[r['var']]))
                    else:admitted=False;break
                if not admitted:break
                if p['value_type']=='scalar':
                    # String-literal equality is total even when a property is
                    # absent or has another type. General typed equality between
                    # two native properties is deliberately not admitted here.
                    if p['op'] not in ('eq','ne') or not any('value' in r for r in operands):admitted=False;break
                elif p['value_type']!='lexical_string':admitted=False;break
                guards.append(dict(op=p['op'],value_type=p['value_type'],left=operands[0],right=operands[1]))
            if admitted:
                yield dict(edge=edge['var'],leaf=leaf,boundary=boundary,
                    boundary_column='source' if boundary==edge['source'] else 'target',guards=guards,
                    retained_variables=sorted(retained),proof='all leaf predicates enforced before representative selection; contribution projection removes both witness identities')


def compile_leaf_bound(base,backend,proof,*,parameter,max_bindings):
    """One native correlated call, at most one real edge row per binding key."""
    import hashlib
    p=base.parameters;point=p.get('native_binding_checkpoint',{})
    if (base.language!='cypher' or p.get('compiler')!='semantic_edge_match_v1'
            or point.get('text_sha256')!=hashlib.sha256(base.text.encode()).hexdigest()
            or p['output_columns']!=['entity','source','target']):
        raise ValueError('Leaf reduction requires an exact scalar-free Cypher edge Match')
    ns='xgap_strategy_entity_namespace';key='xgap_leaf_key'
    params={**p,ns:backend.resource_namespace};checks=[]
    def operand(r):
        if 'value' in r:
            name='xgap_leaf_literal_'+str(len(params));params[name]=r['value'];return '$'+name,True
        return ident(point['variables'][r['endpoint']])+'.id',False
    for guard in proof['guards']:
        left,lc=operand(guard['left']);right,rc=operand(guard['right'])
        op={'eq':'=','ne':'<>','lt':'<','le':'<=','gt':'>','ge':'>='}[guard['op']]
        typed=' AND '.join(e+' IS :: STRING NOT NULL' for e,c in ((left,lc),(right,rc)) if not c) or 'true'
        if guard['value_type']=='lexical_string' or guard['op']=='eq':
            checks.append('(CASE WHEN '+typed+' THEN '+left+op+right+' ELSE false END)')
        else:
            value=right if lc else left
            checks.append('(CASE WHEN '+value+' IS NULL THEN false WHEN '+typed+' THEN '+left+op+right+' ELSE true END)')
    variable=ident(point['variables'][proof['boundary_column']]);prop=ident(backend.identity_property)
    checks.append('($'+ns+' + '+variable+'.'+prop+') = '+key)
    offset=point['offset'];text=base.text[:offset]+'WITH *\nWHERE '+' AND '.join(checks)+'\n'+base.text[offset:]
    # Indexable local identity equality precedes expansion. Keep the canonical
    # equality too; malformed or foreign namespace keys never become matches.
    prefix='CALL {\n'
    anchor=('WITH '+key+'\nMATCH ('+variable+')\nWHERE '+key+' STARTS WITH $'+ns+
            ' AND '+variable+'.'+prop+' = substring('+key+', size($'+ns+'))\n')
    text=prefix+anchor+text[len(prefix):]
    text='UNWIND $'+parameter+' AS '+key+'\nCALL {\nWITH '+key+'\n'+text+'\nLIMIT 1\n}\nRETURN DISTINCT entity, source, target'
    for name in ('native_binding_checkpoint','rdf_binding_checkpoint'):params.pop(name,None)
    params.update(bound_entity_parameter=parameter,bound_identity_column=proof['boundary_column'],
        binding_key_work_profile='scheduler-distinct-key-cap-v1',
        leaf_witness=dict(profile=PROFILE,proof=proof,returned_rows_per_key_upper_bound=1,
                          adjacency_scan_bound=None,max_bindings=max_bindings))
    return replace(base,text=text,parameters=params,artifact_id=base.artifact_id+'-leaf-witness')


def compile_rdf_leaf_bound(base,backend,proof,*,parameter,max_bindings,max_bytes):
    """Finite UNION of independently bounded singleton queries, one HTTP call.

    SPARQL lacks correlated LIMIT subqueries. The typed binder expands at most
    K branches, enforcing a bound on the entire expanded request, never silently
    truncating keys. A branch keeps one actual jointly satisfying edge binding.
    """
    import hashlib
    from xgap.backends.mapping import RdfBackendMapping
    from xgap.backends.rdf_terms import validate_iri
    from xgap.backends.sparql_bindings import IRI_VALUES_MARKER
    p=base.parameters;point=p.get('rdf_binding_checkpoint',{})
    if (base.language!='sparql' or p.get('compiler')!='semantic_edge_match_v1'
            or point.get('text_sha256')!=hashlib.sha256(base.text.encode()).hexdigest()
            or p['output_columns']!=['entity','source','target']):
        raise ValueError('Leaf reduction requires an exact scalar-free RDF edge Match')
    column=proof['boundary_column'];leaf_column='target' if column=='source' else 'source'
    if any(r.get('endpoint')==column for g in proof['guards'] for r in (g['left'],g['right'])):
        raise ValueError('RDF leaf guard depending on a multivalued boundary property is not admitted')
    mapping=backend.backend_mapping
    if not isinstance(mapping,RdfBackendMapping):mapping=RdfBackendMapping.from_artifact(mapping,backend_id=backend.backend_id)
    id_iri=validate_iri(mapping.resolve('id','properties').iri)
    scalar='?xgap_leaf_id';checks=[]
    for g in proof['guards']:
        def operand(r):return json.dumps(r['value'],ensure_ascii=False) if 'value' in r else 'STR('+scalar+')'
        left,right=operand(g['left']),operand(g['right'])
        op={'eq':'=','ne':'!=','lt':'<','le':'<=','gt':'>','ge':'>='}[g['op']]
        fallback='true' if g['value_type']=='scalar' and g['op']=='ne' else 'false'
        checks.append('IF(BOUND('+scalar+'), IF(isLiteral('+scalar+'), IF(DATATYPE('+scalar+
            ') = <http://www.w3.org/2001/XMLSchema#string>, '+left+op+right+', '+fallback+'), '+fallback+'), false)')
    identity=point.get('identity_body')
    constant_body=point.get('endpoint_bodies',{}).get(column) if identity is not None else None
    variables=({'entity':'entity','source':'source','target':'target'}
               if identity is not None else point['variables'])
    extra=IRI_VALUES_MARKER+'\n'
    if checks:
        # Only existence of a jointly satisfying local property value matters:
        # its scalar is absent from the DISTINCT edge/endpoint projection.
        # Keep that lookup correlated with the bound leaf. An early mandatory
        # property triple lets ARQ's filter placement split the BGP BEFORE the
        # edge-to-leaf connection, producing endpoint-adjacency x all leaf IDs.
        # EXISTS cannot test this guard until the leaf is bound by the edge BGP.
        extra+='FILTER EXISTS { ?'+variables[leaf_column]+' <'+id_iri+'> '+scalar+' .\nFILTER('+' && '.join(checks)+') }\n'
    flat=point.get('flat_body')
    if identity is not None:
        # A representative branch needs its first satisfying row, not all
        # distinct witnesses. The typed binder adds LIMIT 1 independently to
        # every key and retains DISTINCT over their combined identity rows.
        # Direct identity variables also remove Extend/alias scope barriers.
        text='SELECT ?entity ?source ?target WHERE {\n'+extra+'\n'.join(constant_body if constant_body is not None else identity)+'\n}'
    elif flat is not None:
        # Keep one projection over the compiler-owned scalar-free relation.
        # No OPTIONAL/scalar column is admitted above; all removed inner
        # variables are exactly aliases of the three final identity columns.
        text='SELECT DISTINCT ?entity ?source ?target WHERE {\n'+extra+'\n'.join(flat)+'\n}'
    else:
        at=point['offset'];text=base.text[:at]+'\n'+extra+base.text[at:]
    params={k:v for k,v in p.items() if k not in ('native_binding_checkpoint','rdf_binding_checkpoint')}
    params.update(bound_entity_parameter=parameter,bound_identity_column=column,
        binding_key_work_profile='scheduler-distinct-key-cap-v1',
        sparql_iri_binding=dict(parameter=parameter,variable=variables[column],max_bindings=max_bindings,max_bytes=max_bytes,
            **({'singleton_anchor':point['endpoint_anchors'][column]} if identity is None else {}),
            **({'inline_singleton':True} if constant_body is not None else {}),
            per_key_limit=1,projection=p['output_columns']),
        leaf_witness=dict(profile=PROFILE,proof=proof,returned_rows_per_key_upper_bound=1,adjacency_scan_bound=None,max_bindings=max_bindings))
    return replace(base,text=text,parameters=params,artifact_id=base.artifact_id+'-leaf-witness')


def witness_neighbors(query,program,plan,backends,policy):
    contribution=program.metadata.get('compact_lowering',{}).get('contribution_projection')
    if not contribution:return
    variables=[n['var'] for n in query['nodes']]+[e['var'] for e in query['edges']]
    identities={v:'v'+str(i) for i,v in enumerate(variables)}
    operators={o.operator_id:o for o in program.operators};placement=plan.metadata['source_bindings']
    for proof in leaf_proofs(query):
        candidates=[o for o in program.operators if o.kind is S.MATCH and 'edge' in o.parameters
                    and o.parameters.get('entity_field')==identities[proof['edge']]]
        # Union coverage, shared reads and unbound scans need different proofs.
        if len(candidates)!=1:continue
        match=candidates[0]
        remote=next((n for n in plan.nodes if n.node_id==match.operator_id+'/native'),None)
        if (remote is None or remote.kind is not R.REMOTE_BIND_QUERY or len(remote.semantic_operator_ids)!=1
                or remote.parameters['artifact']['parameters'].get('leaf_witness')):continue
        backend=backends[remote.parameters['backend_id']]
        if remote.parameters['artifact']['parameters'].get('bound_identity_column')!=proof['boundary_column']:continue
        leaf_reads=[o for o in program.operators if o.kind is S.MATCH and 'node' in o.parameters
                    and o.parameters.get('entity_field')==identities[proof['leaf']]]
        # Leaf scalar relations must be the same source facts, and expose only
        # id (the only admitted guard field). Do not choose a witness before a
        # remote property/coverage condition that could invalidate that witness.
        if any(placement.get(o.operator_id)!=backend.backend_id or set(o.parameters.get('properties',{}).values())-{'id'}
               for o in leaf_reads):continue
        if any(o.constraints for o in [match,*leaf_reads]):continue
        base=next(n for n in compile_semantic_source(match,backend).nodes if n.kind is R.REMOTE_QUERY)
        raw=QueryArtifact.from_dict(base.parameters['artifact'])
        if raw.language=='cypher':
            artifact=compile_leaf_bound(raw,backend,proof,parameter=remote.parameters['parameter'],max_bindings=policy.max_bindings)
        elif raw.language=='sparql':
            if any(r.get('endpoint')==proof['boundary_column'] for g in proof['guards'] for r in (g['left'],g['right'])):continue
            artifact=compile_rdf_leaf_bound(raw,backend,proof,parameter=remote.parameters['parameter'],max_bindings=policy.max_bindings,
                max_bytes=policy.max_binding_bytes)
        else:continue
        new=replace(remote,parameters={**remote.parameters,'artifact':artifact.to_dict()})
        yield [new if n.node_id==remote.node_id else n for n in plan.nodes],{**proof,'contribution_operator':contribution['operator_id']}
