"""Prespecified JSON/SPARQL financial equivalence, only after outcome sealing."""
from collections import Counter
import json
import time

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows, validate_normalization
from xgap.experiments.evidence_store import read_json_evidence

XSD='http://www.w3.org/2001/XMLSchema#'
NUMERIC={XSD+s for s in ('integer','decimal','double','float','int','long','short','byte',
    'nonNegativeInteger','positiveInteger','unsignedInt','unsignedLong','unsignedShort','unsignedByte',
    'nonPositiveInteger','negativeInteger')}


def sparql_values(document, normalization):
    fields=validate_normalization(normalization)
    variables=document['head']['vars']
    if len(variables)!=len(set(variables)) or set(variables)!=set(fields):
        raise ValueError('SPARQL result columns differ from declared answer schema')
    rows=[]
    for row in document['results']['bindings']:
        if set(row)!=set(fields):raise ValueError('Unbound or undeclared answer field')
        result={}
        for name,term in row.items():
            if term.get('type') not in ('literal','typed-literal') or term.get('xml:lang') or not isinstance(term.get('value'),str):
                raise ValueError('Financial answers require declared untagged literal terms')
            datatype=term.get('datatype',XSD+'string')
            if (fields[name]=='text' and datatype!=XSD+'string') or (fields[name]!='text' and datatype not in NUMERIC):
                raise ValueError('SPARQL term datatype differs from declared answer kind')
            result[name]=term['value']
        rows.append(result)
    return rows


def score_trial(receipt_path, *, receipt_sha256, reference_path, reference_sha256, output):
    started=time.perf_counter();r=json.loads(read_pinned(receipt_path,receipt_sha256))
    if r.get('schema_version')!='xgap-common-method-trial-v1':raise ValueError('A sealed common method outcome is required')
    ref=json.loads(read_pinned(reference_path,reference_sha256))
    if (ref.get('schema_version')!='xgap-normalized-row-reference-v1' or
        ref.get('question_id')!=r.get('question_id') or ref.get('dataset')!=r.get('dataset') or
        type(ref.get('ordered')) is not bool):raise ValueError('Reference identity differs')
    spec=ref['normalization'];expected=normalize_rows(ref['rows'],spec);actual=[];error=None
    try:
        if r['success']:
            result=read_json_evidence(r['result'])
            if result['answer_format'] not in ('sparql_json','json_rows'):raise ValueError('Unknown answer format')
            rows=sparql_values(result['answer'],spec) if result['answer_format']=='sparql_json' else result['answer']
            actual=normalize_rows(rows,spec)
    except (ValueError,TypeError,KeyError,OSError,EOFError) as exc:error=type(exc).__name__+': '+str(exc)
    encode=lambda row:json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)
    a,e=list(map(encode,actual)),list(map(encode,expected));aa,ee=Counter(a),Counter(e)
    comparable=r['success'] and error is None;overlap=sum((aa&ee).values())
    score={'schema_version':'xgap-common-row-score-v1',**{k:r[k] for k in ('method','track','question_id','dataset','population','exposure')},
        'receipt_sha256':receipt_sha256,'reference_sha256':reference_sha256,
        'execution_success':r['success'],'answer_em':float(comparable and (a==e if ref['ordered'] else aa==ee)),
        'answer_row_multiset_f1':(2*overlap/(len(a)+len(e)) if a or e else 1.0) if comparable else 0.0,
        'actual_rows':len(a) if comparable else None,'expected_rows':len(e),'comparison_error':error,
        'ordered':ref['ordered'],'normalization':spec,'status':r['status'],
        'evaluation_ms_before_score_seal':(time.perf_counter()-started)*1000,
        'scope':'post-seal evaluation, outside method online latency; preserve original order and bags'}
    write_once(output,score);return score
