"""Necessary string/boolean row conditions; final typed filters must remain.

Only recognized primitive values are screened. Other types and unbound values
pass through; no path-predicate equality or RDF existential reinterpretation.
"""
from dataclasses import replace
import json
import re

from xgap.compilers.cypher import _cypher_identifier
from xgap.infrastructure.runtime import QueryArtifact


PROFILE='necessary-primitive-row-equality-v1'
XSD='http://www.w3.org/2001/XMLSchema#'


def add_necessary_row_filters(artifact: QueryArtifact, conditions: list[dict]) -> QueryArtifact:
    params=artifact.parameters
    if (artifact.kind!='compiled' or params.get('compiler') not in ('semantic_node_match_v1','semantic_edge_match_v1')
            or 'retrieval_budget' in params or 'necessary_row_filters' in params):
        raise ValueError('Necessary row filter requires an unbudgeted Match artifact')
    columns=params.get('output_columns')
    if not isinstance(columns,list) or not columns or any(not isinstance(c,str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',c) for c in columns):
        raise ValueError('Explicit native result columns required')
    if not 1<=len(conditions)<=64:raise ValueError('Necessary row filter bound exceeded')
    expressions=[]
    for c in conditions:
        if set(c)!={'op','field','value'} or c['op']!='eq' or c['field'] not in columns or type(c['value']) not in (str,bool):
            raise ValueError('Only string/boolean equality on a native output is supported')
        value=json.dumps(c['value'],ensure_ascii=False,allow_nan=False)
        if artifact.language=='cypher':
            field=_cypher_identifier(c['field']);kind='STRING' if type(c['value']) is str else 'BOOLEAN'
            expressions.append(f'(CASE WHEN {field} IS :: {kind} NOT NULL THEN {field} = {value} ELSE true END)')
        elif artifact.language=='sparql':
            field='?'+c['field'];kind='string' if type(c['value']) is str else 'boolean'
            if kind=='string':comparison=f'sameTerm({field}, {value})'
            else:
                accepted='"true", "1"' if c['value'] else '"false", "0"'
                comparison=(f'IF(STR({field}) IN ("true", "false", "1", "0"), '
                            f'STR({field}) IN ({accepted}), true)')
            expressions.append(f'IF(BOUND({field}), IF(isLiteral({field}), '
                f'IF(DATATYPE({field}) = <{XSD+kind}>, {comparison}, true), true), true)')
        else:raise ValueError('No necessary row filter compiler for this language')
    if artifact.language=='cypher':
        names=', '.join(_cypher_identifier(c) for c in columns)
        text='CALL {\n'+artifact.text+'\n}\nWITH '+names+'\nWHERE '+' AND '.join(expressions)+'\nRETURN '+names
    else:
        text='SELECT '+' '.join('?'+c for c in columns)+' WHERE {\n{\n'+artifact.text+'\n}\nFILTER('+' && '.join(expressions)+')\n}'
    return replace(artifact,text=text,parameters={**params,'necessary_row_filters':{
        'profile':PROFILE,'conditions':[dict(c) for c in conditions],
        'unknown_types_and_missing_retained':True,'final_typed_filter_required':True}})
