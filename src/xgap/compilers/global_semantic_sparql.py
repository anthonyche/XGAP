"""Bounded grounded relational meaning -> one unresolved global SELECT.

No queries, source assignment optimization, family dispatch or answer reference.
See docs/decisions/shared_global_sparql_v1.md for the finite scalar/data contract.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.semantic.parameter_contract import validate_program_parameters
from xgap.semantic.calendar_time import MILLISECOND_PATTERN
from xgap.semantic.program import SemanticOperatorKind as S

PROFILE='xgap-global-semantic-sparql-v1'
XSD='http://www.w3.org/2001/XMLSchema#'


def variable(field):
    if not isinstance(field,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',field):
        raise ValueError('Global compiler fields must be SPARQL-safe identifiers')
    return '?'+field


def literal(value):
    if value is None:return '(1 / 0)'  # Unbound projection, not a magic RDF value.
    if type(value) is bool:return 'true' if value else 'false'
    if type(value) in (int,float):return json.dumps(value,allow_nan=False)
    if type(value) is str:return json.dumps(value,ensure_ascii=True)
    raise ValueError('Global scalar literal is outside the declared profile')


def bound(expression):
    return ('BOUND('+expression+')' if re.fullmatch(r'\?[A-Za-z_][A-Za-z0-9_]*',expression)
            else 'COALESCE(sameTerm('+expression+','+expression+'),false)')


def condition(c,fields):
    op=c['op']
    if op in ('and','or'):
        return '('+(' && ' if op=='and' else ' || ').join(condition(a,fields) for a in c['args'])+')'
    if op=='not':return '(!'+condition(c['arg'],fields)+')'
    left=fields[c['field']]
    if op in ('is_null','is_not_null'):return ('!' if op=='is_null' else '')+bound(left)
    right=fields[c['right_field']] if 'right_field' in c else literal(c['value'])
    symbol={'eq':'=','ne':'!=','lt':'<','le':'<=','gt':'>','ge':'>='}[op]
    if c.get('value_type')=='timestamp_ms':
        pattern=literal(MILLISECOND_PATTERN)
        checks=' && '.join(f'(DATATYPE({v})=<{XSD}string> && STRLEN(STR({v}))>=19 && '
            f'STRLEN(STR({v}))<=23 && SUBSTR(STR({v}),1,4)!="0000" && REGEX(STR({v}),{pattern}))'
            for v in (left,right))
        values=[f'<{XSD}dateTime>(REPLACE(STR({v})," ","T"))' for v in (left,right)]
        expr=checks+' && ('+values[0]+' '+symbol+' '+values[1]+')'
    elif op in ('eq','ne'):
        # SPARQL errors on different literal kinds; XGAP equality is total.
        numeric=f'(isNumeric({left}) && isNumeric({right}))'
        same=f'(DATATYPE({left})=DATATYPE({right}))'
        equal=f'IF({numeric} || COALESCE({same},false),COALESCE({left}={right},false),false)'
        expr=('!('+equal+')' if op=='ne' else equal)
        # Even inequality with a missing/null operand is false.
        expr=bound(left)+' && '+(bound(right)+' && ' if 'right_field' in c else '')+expr
        if 'value' in c and c['value'] is None:expr='false'
    else:
        expr=f'isNumeric({left}) && isNumeric({right}) && ({left} {symbol} {right})'
    return 'COALESCE(('+expr+'),false)'


@dataclass(frozen=True)
class Relation:
    body: str
    values: dict[str,str]
    expanded: int
    suffix: str=''


# Native Match text uses quoted literals/IRIs. Only variable tokens are renamed;
# words resembling variables inside data are not changed.
TOKENS=re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|<[^<>\s]*>|\?[A-Za-z_][A-Za-z0-9_]*')


def rename_variables(text,prefix):
    return TOKENS.sub(lambda m:'?'+prefix+m[0][1:] if m[0].startswith('?') else m[0],text)


def select_text(body,values,*,distinct=True,suffix=''):
    selected=' '.join(v if v==variable(f) else '('+v+' AS '+variable(f)+')' for f,v in values.items())
    return 'SELECT '+('DISTINCT ' if distinct else '')+selected+' WHERE {\n'+body+'\n}'+suffix


def compile_global_program(program, mapping, *, max_expanded_nodes=4096,max_query_bytes=1048576):
    raw=program.to_dict();serialized=json.dumps(raw,sort_keys=True,allow_nan=False).encode()
    if len(serialized)>131072 or not 1<=len(program.operators)<=64 or len(program.roots)!=1 or program.holes:
        raise ValueError('Global compiler requires a grounded bounded single-root program')
    if (type(max_expanded_nodes) is not int or not 1<=max_expanded_nodes<=4096 or
            type(max_query_bytes) is not int or not 1<=max_query_bytes<=1048576):
        raise ValueError('Invalid global compilation resource bounds')
    validate_program_parameters(raw)
    allowed={S.MATCH,S.FILTER,S.UNION,S.JOIN,S.PROJECT,S.AGGREGATE,S.ORDER_LIMIT}
    for op in program.operators:
        if op.kind not in allowed:raise ValueError('Unsupported global semantic operator: '+op.kind.value)
        if op.kind is S.ORDER_LIMIT and op.operator_id!=program.roots[0]:
            raise ValueError('Global OrderLimit must be the final semantic operator')
        if op.kind is S.AGGREGATE and any(a['op'] not in ('sum','count') for a in op.parameters['aggregations'].values()):
            raise ValueError('Global aggregate bridge admits SUM/COUNT only')
    backend=SemanticBackend('fuseki',mapping['resource_namespace'],mapping['identity_property'],
        backend_mapping=mapping['backend_mapping'],rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
        rdf_node_classes=tuple(mapping['rdf_node_classes']),profile=default_profile('fuseki'))
    plan=compile_semantic_program(program,source_bindings={o.operator_id:'fuseki' for o in program.operators if o.kind is S.MATCH},
        backends={'fuseki':backend},max_remote_calls=64,max_parallelism=1)
    relations={};total_bytes=0
    def materialize(body,values,prefix,*,distinct=True,suffix=''):
        names={f:prefix+str(i) for i,f in enumerate(values)}
        query=select_text(body,{names[f]:v for f,v in values.items()},distinct=distinct,suffix=suffix)
        return '{ '+query+' }',{f:variable(n) for f,n in names.items()}
    def fresh(relation,prefix):
        return rename_variables(relation.body,prefix),{f:rename_variables(v,prefix) for f,v in relation.values.items()}
    def save(node,body,values,expanded,suffix=''):
        nonlocal total_bytes
        size=len(select_text(body,values,suffix=suffix).encode())
        if size>max_query_bytes:raise ValueError('Global query byte bound exceeded')
        relations[node.node_id]=Relation(body,values,expanded,suffix);total_bytes+=size
    for index,node in enumerate(plan.nodes):
        p=node.parameters;kind=node.kind
        expanded=1+sum(relations[i].expanded for i in node.inputs)
        if expanded>max_expanded_nodes:raise ValueError('Global DAG expansion bound exceeded before inlining')
        if kind is R.REMOTE_QUERY:
            artifact=p['artifact'];prefix='r'+str(index)+'_'
            body='{ '+rename_variables(artifact['text'],prefix)+' }'
            values={f:variable(prefix+f) for f in artifact['parameters']['output_columns']}
            save(node,body,values,expanded);continue
        inputs=[fresh(relations[source],f's{index}i{position}_') for position,source in enumerate(node.inputs)]
        body,fields=inputs[0];expressions=dict(fields);suffix=''
        if kind is R.NORMALIZE_NODE_BINDINGS:
            identities=p.get('identity_fields',{'entity':p['entity_field']})
            expressions={target:'STR('+fields[source]+')' for source,target in identities.items()}
            expressions.update({f:fields[f] for f in p['scalar_fields']})
        elif kind is R.COORDINATOR_ROW_PROJECT:
            expressions={}
            for name,spec in p['projections'].items():
                if spec['kind'] not in ('field','literal'):raise ValueError('Global bridge requires row projections')
                expressions[name]=fields[spec['field']] if spec['kind']=='field' else literal(spec['value'])
            retained={s['field'] for s in p['projections'].values() if s['kind']=='field'}
            if not set(fields)<=retained:
                # Only an injective rename may elide a set projection boundary.
                body,expressions=materialize(body,expressions,f'p{index}f')
        elif kind is R.COORDINATOR_FILTER:
            body+=' FILTER('+condition(p['condition'],fields)+') '
        elif kind is R.COORDINATOR_JOIN:
            other,right=inputs[1];left_key,right_key=p['left_on'],p['right_on']
            if set(fields)&set(right)-{left_key if left_key==right_key else ''}:
                raise ValueError('Global join inputs must use the validated column renaming')
            body+=other+' FILTER('+condition({'op':'eq','field':'l','right_field':'r'},
                {'l':fields[left_key],'r':right[right_key]})+') '
            expressions.update({f:v for f,v in right.items() if f not in expressions})
        elif kind is R.MERGE:
            names={f:f'u{index}f{i}' for i,f in enumerate(fields)}
            branches=['{ '+select_text(child,{names[f]:v for f,v in child_fields.items()},distinct=False)+' }'
                      for child,child_fields in inputs]
            body=' UNION '.join('{'+branch+'}' for branch in branches)
            body,expressions=materialize(body,{f:variable(n) for f,n in names.items()},f'm{index}f')
        elif kind is R.COORDINATOR_GROUP_AGGREGATE:
            # A single set boundary before aggregation also retains join/union
            # multiplicity semantics; this is not a current-query optimizer.
            body,fields=materialize(body,fields,f'a{index}i')
            expressions={f:fields[f] for f in p['group_by']}
            for output,a in p['aggregations'].items():
                value=fields[a['field']] if a.get('field') is not None else '*'
                expressions[output]=a['op'].upper()+'('+('DISTINCT ' if a.get('distinct') else '')+value+')'
            grouping=' GROUP BY '+' '.join(fields[f] for f in p['group_by']) if p['group_by'] else ''
            body,expressions=materialize(body,expressions,f'a{index}o',distinct=False,suffix=grouping)
        elif kind is R.COORDINATOR_SORT_LIMIT:
            ordering=[]
            for spec in p['order_by']:
                v=fields[spec['field']]
                ordering.extend([('ASC' if spec.get('nulls','last')=='first' else 'DESC')+'('+bound(v)+')',
                    spec.get('direction','asc').upper()+'('+v+')'])
            suffix=' ORDER BY '+' '.join(ordering)
            if p['limit'] is not None:suffix+=' LIMIT '+str(p['limit'])
        else:raise ValueError('Unsupported global runtime primitive: '+kind.value)
        save(node,body,expressions,expanded,suffix)
    final=relations[plan.roots[0]];text=select_text(final.body,final.values,suffix=final.suffix)
    return QueryArtifact(program.program_id+'-global','sparql',text,kind='compiled',parameters={
        'compiler':PROFILE,'semantic_program_sha256':hashlib.sha256(serialized).hexdigest(),
        'output_columns':list(final.values),'semantic_operators':len(program.operators),'runtime_relations':len(relations),
        'expanded_relations':final.expanded,'maximum_expanded_relations':max_expanded_nodes,
        'query_bytes':len(text.encode()),'maximum_query_bytes':max_query_bytes,'construction_bytes':total_bytes,
        'source_addresses_bound':False,'model_calls':0,'backend_calls':0,'fit_calls':0,
        'numeric_equivalence':'published financial finite scalars; native floating SUM under frozen decimal3 evaluation',
        'ordering_scope':'homogeneous scalar columns; declared keys determine top-K boundary'})
