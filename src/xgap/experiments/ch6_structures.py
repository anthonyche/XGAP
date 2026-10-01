"""Parser-based source templates. Extraction is NOT compiler admission.

Parameter replacement happens on typed RDF terms, never by regex over SPARQL.
Ordered syntax normalization is deliberately weaker than query equivalence.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json

from pyparsing import ParseResults
from rdflib import BNode, Literal, URIRef, Variable
from rdflib.namespace import RDF, XSD
from rdflib.plugins.sparql import parser, algebra
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.paths import Path

NS={'wd':'http://www.wikidata.org/entity/','wdt':'http://www.wikidata.org/prop/direct/',
    'p':'http://www.wikidata.org/prop/','ps':'http://www.wikidata.org/prop/statement/',
    'pq':'http://www.wikidata.org/prop/qualifier/','xsd':str(XSD),'rdf':str(RDF),
    'dbo':'http://dbpedia.org/ontology/','dbr':'http://dbpedia.org/resource/',
    'dbp':'http://dbpedia.org/property/','rdfs':'http://www.w3.org/2000/01/rdf-schema#'}
BLOCKED={'OptionalGraphPattern','MinusGraphPattern','SubSelect','ServiceGraphPattern','GraphGraphPattern',
         'Builtin_NOTEXISTS','Builtin_EXISTS','GroupOrUnionGraphPattern'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def walk(value):
    yield value
    if isinstance(value,(dict,CompValue)):
        for key,item in value.items():
            if key!='_vars':yield from walk(item)
    elif isinstance(value,(list,tuple,ParseResults,set)):
        for item in value:yield from walk(item)


def encode(value):
    if isinstance(value,Variable):return {'term':'variable','value':str(value)}
    if isinstance(value,URIRef):return {'term':'iri','value':str(value)}
    if isinstance(value,BNode):return {'term':'blank','value':str(value)}
    if isinstance(value,Literal):return {'term':'literal','value':str(value),'datatype':str(value.datatype) if value.datatype else None,'language':value.language}
    if isinstance(value,CompValue):return {'node':value.name,'fields':{k:encode(v) for k,v in value.items() if k!='_vars'}}
    if isinstance(value,Path):return {'path':value.__class__.__name__,'fields':{k:encode(v) for k,v in vars(value).items()}}
    if isinstance(value,dict):return {str(k):encode(v) for k,v in value.items()}
    if isinstance(value,set):return sorted((encode(v) for v in value),key=lambda v:json.dumps(v,sort_keys=True))
    if isinstance(value,(list,tuple,ParseResults)):return [encode(v) for v in value]
    if value is None or type(value) in (str,int,float,bool):return value
    raise ValueError('Unserializable parser node '+type(value).__name__)


def extract(row, *, source_version, field='sparql_wikidata'):
    raw=row.get(field)
    result=dict(schema_version='xgap-typed-template-v1',source='LC-QuAD2.0',source_version=source_version,
                uid=row.get('uid'),source_field=field,source_fields=sorted(row),
                template_id=row.get('template_id'),template=row.get('template'),
                language={k:row[k] for k in ('question','paraphrased_question','NNQT_question','subgraph') if k in row},
                raw_query=raw,raw_query_sha256=hashlib.sha256((raw or '').encode()).hexdigest(),
                status='rejected',compiler_admission='not_attempted',changes_from_source=[])
    if not isinstance(raw,str) or not raw or len(raw.encode())>65536:
        return {**result,'reasons':['missing_or_oversized_query']}
    try:
        parsed=parser.parseQuery(raw)
        # RDFLib CompValue does not support deepcopy; translation mutates AST.
        original=parser.parseQuery(raw)
        result['raw_ast']=encode(original)
        translated=algebra.translateQuery(parsed,initNs=NS)
        result['resolved_algebra']=encode(translated.algebra)
        namespaces=dict(NS)
        for item in original[0]:
            if isinstance(item,CompValue) and item.name=='PrefixDecl':namespaces[item.get('prefix','')]=str(item['iri'])
        nodes=[x.name for x in walk(original) if isinstance(x,CompValue)]
        reasons=sorted(set(nodes)&BLOCKED)
        # A one-branch group is normal syntax, not UNION.
        if 'GroupOrUnionGraphPattern' in reasons and all(len(x['graph'])==1 for x in walk(original)
                if isinstance(x,CompValue) and x.name=='GroupOrUnionGraphPattern'):reasons.remove('GroupOrUnionGraphPattern')
        if any(isinstance(x,CompValue) and x.name=='PathElt' and x.get('mod') in ('*','+','?') for x in walk(original)):
            reasons.append('variable_length_path')
        triples=[]
        for x in walk(translated.algebra):
            if isinstance(x,CompValue) and x.name=='BGP':triples.extend(x['triples'])
        roles=defaultdict(set)
        for s,p,o in triples:
            for term,role in ((s,'entity'),(p,'relation'),(o,'type' if p==RDF.type else 'entity')):
                if isinstance(term,URIRef):roles[str(term)].add(role)
            if isinstance(p,Path):reasons.append('property_path_requires_explicit_domain_lowering')
        if any(str(x).startswith(('http://www.wikidata.org/prop/statement/','http://www.wikidata.org/prop/qualifier/'))
               or str(x).startswith('http://www.wikidata.org/prop/') and not str(x).startswith(NS['wdt'])
               for x in walk(translated.algebra) if isinstance(x,URIRef)):
            reasons.append('statement_or_qualifier')
        variables={};parameters={};domains=[]
        def normalize(x):
            if isinstance(x,CompValue) and x.name=='pname':
                prefix=x.get('prefix','');x=URIRef(namespaces[prefix]+x['localname'])
            if isinstance(x,Variable):
                variables.setdefault(str(x),'v'+str(len(variables)))
                return {'variable':variables[str(x)]}
            if isinstance(x,(URIRef,Literal)):
                encoded=encode(x);key=json.dumps(encoded,sort_keys=True)
                if key not in parameters:
                    name='p'+str(len(parameters));parameters[key]=name
                    domains.append(dict(name=name,term=encoded,roles=sorted(roles.get(str(x),{'literal'} if isinstance(x,Literal) else {'iri'}))))
                return {'parameter':parameters[key],'type':{k:v for k,v in encoded.items() if k!='value'},
                        'roles':next(d['roles'] for d in domains if d['name']==parameters[key])}
            if isinstance(x,CompValue):return {'node':x.name,'fields':{k:normalize(v) for k,v in x.items() if k!='_vars'}}
            if isinstance(x,(list,tuple,ParseResults)):return [normalize(v) for v in x]
            return encode(x)
        normalized=normalize(original[1])
        counts=Counter(str(v) for s,p,o in triples for v in (s,o))
        kinds=[]
        if len(triples)==1:kinds.append('S01')
        if 2<=len(triples)<=3:
            if len(triples)==3 and len(counts)==3 and all(n==2 for n in counts.values()):kinds.append('S04')
            elif max(counts.values(),default=0)==len(triples):
                center=max(counts,key=counts.get)
                into=any(str(o)==center for s,p,o in triples)
                out=any(str(s)==center for s,p,o in triples)
                kinds.append('S02' if len(triples)==2 and into and out else 'S03')
            else:kinds.append('S02')
        if 'Aggregate_Count' in nodes:kinds.append('S06')
        if 'Aggregate_Sum' in nodes:kinds.append('S07')
        if 'OrderClause' in nodes and 'LimitOffsetClauses' in nodes:kinds.append('S08')
        if not kinds:reasons.append('outside_initial_structure_catalog')
        result.update(normalized_ast=normalized,structure_hash=digest(normalized),parameters=domains,
            variable_map=variables,structure_categories=kinds,triples=encode(triples),
            output_semantics={k:[encode(x) for x in walk(original) if isinstance(x,CompValue) and x.name==k]
                for k in ('SelectQuery','GroupClause','HavingClause','OrderClause','LimitOffsetClauses')},
            status='rejected' if reasons else 'extracted_pending_domain_admission',reasons=sorted(set(reasons)))
    except Exception as error:
        result.update(reasons=['parse_or_translation_failed'],error_type=type(error).__name__,error=str(error))
    return result


def instantiate(record,bindings):
    """Typed total substitution into a preserved algebra, not auto-lowering.

    The caller must supply every parameter with the same RDF term kind/type.
    The resulting object must pass a domain-specific compiler/reference gate.
    """
    if record['status']!='extracted_pending_domain_admission':raise ValueError('Rejected source structure')
    params={p['name']:p for p in record['parameters']}
    if set(bindings)!=set(params):raise ValueError('Exact typed binding domain required')
    replacements={}
    for name,p in params.items():
        value=bindings[name];original=p['term']
        if not isinstance(value,dict) or set(value)!=set(original) or any(value[k]!=original[k] for k in original if k!='value'):
            raise ValueError('Incompatible parameter type: '+name)
        if not isinstance(value['value'],str) or not value['value']:raise ValueError('Invalid RDF lexical value')
        if value['term']=='literal' and value.get('datatype'):
            literal=Literal(value['value'],datatype=URIRef(value['datatype']))
            if literal.ill_typed:raise ValueError('Ill-typed RDF literal')
        replacements[json.dumps(original,sort_keys=True)]=value
    def visit(x):
        if isinstance(x,dict):
            key=json.dumps(x,sort_keys=True)
            if key in replacements:return deepcopy(replacements[key])
            return {k:visit(v) for k,v in x.items()}
        if isinstance(x,list):return [visit(v) for v in x]
        return x
    return dict(schema_version='xgap-instantiated-source-algebra-v1',source_structure=record['structure_hash'],
                bindings=bindings,resolved_algebra=visit(record['resolved_algebra']),compiler_admission='required')
