#!/usr/bin/env python3
"""Freeze support before outcomes. Wrong answers/timeouts never remove support."""
import argparse
import json
from pathlib import Path

from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.ch6_support import validate_support
from xgap.experiments.ch6_formal_protocol import METHOD_ORDER
from xgap.experiments.ch6_backend_eligibility import eligible


def validate_ts_nl_reference(bundle):
    """Admit the original NL on a materialized factor, never a state placeholder.

    This checks public provenance only. Oracle and answer files are not opened.
    The external worker still receives neither a scope nor controlled state.
    """
    if (bundle.get('schema_version')!='xgap-ch6-deployment-factor-v1'
            or bundle.get('deployment')!='rdf' or bundle.get('input_track')!='controlled'
            or bundle.get('factor') not in ('sources','graph_scale')
            or bundle.get('method_outputs_used_for_selection') is not False):
        raise ValueError('TS NL reference requires an outcome-independent RDF deployment factor')
    originals={}
    for pin in bundle['base_bundles']:
        base=load(pin)
        for case in base['cases']:
            if case['case_id'] in originals:raise ValueError('Ambiguous original NL identity')
            originals[case['case_id']]=case
    for case in bundle['cases']:
        original=originals.get(case.get('base_case_id'))
        if original is None:raise ValueError('Missing original NL case')
        request=load(case['request']);old=load(original['request'])
        if (request.get('schema_version')!='xgap-one-shot-evaluation-request-v1'
                or request.get('question_id')!=case['case_id']
                or not request.get('question') or request['question']!=old.get('question')
                or request.get('exposure')!='test'
                or case['template_family']!=original['template_family']):
            raise ValueError('Factor NL must preserve its frozen original question and family')


def freeze(spec_path,spec_sha256,output):
    spec=load(dict(path=spec_path,sha256=spec_sha256))
    if spec.get('schema_version')!='xgap-ch6-support-input-v1' or spec.get('method_outputs_used') is not False:
        raise ValueError('Pre-outcome support specification required')
    external=load(spec['external_interface_gate'])
    if not external.get('success'):raise ValueError('External interface must have actually passed its gate')
    cases=[];seen=set();counts={}
    for entry in spec['bundles']:
        bundle=load(entry['bundle']);admission=load(entry['backend_admission']);stores=load(entry['prepared'])
        if not stores.get('success'):
            raise ValueError('Compiler-only evidence cannot establish backend admission')
        if not eligible(admission,bundle_pin=entry['bundle'],prepared_pin=entry['prepared']):
            raise ValueError('A diagnostic subset cannot establish complete deployment support')
        if admission['profile']['sha256']!=bundle['profile']['sha256'] or stores['profile']['sha256']!=bundle['profile']['sha256']:
            raise ValueError('Support gate and actual deployment differ')
        controlled=bundle.get('input_track')=='controlled'
        reference=entry.get('ts_nl_reference',False)
        if type(reference) is not bool:raise ValueError('TS reference must be explicitly boolean')
        if reference:validate_ts_nl_reference(bundle)
        if not controlled and bundle.get('deployment_selection')!='balanced':
            raise ValueError('Overall study requires the prespecified mixed cohort')
        for c in bundle['cases']:
            if c['case_id'] in seen:raise ValueError('Duplicate mixed-workload case identity')
            seen.add(c['case_id']);assessments={}
            for method in METHOD_ORDER:
                deployment=c.get('deployment',bundle['deployment'])
                unsupported=method=='TS' and deployment=='native'
                interface=method=='TS' and controlled and not unsupported and not reference
                assessments[method]=dict(status='unsupported_deployment' if unsupported else 'unsupported_interface' if interface else 'supported',
                    basis='Original TS accepts SPARQL/RDF endpoints; no Neo4j/Cypher adapter' if unsupported else
                          'Original TS has no controlled-family input; a separately identified fixed NL cohort is required' if interface else
                          'Original frozen NL on this admitted RDF factor snapshot; controlled entry remains unsupported; separate NL timing, no paired controlled/NL speedup' if method=='TS' and reference else
                          'Admitted external NL-to-SPARQL/FedX interface on shared RDF; answer quality is not support' if method=='TS' else
                          'Shared compact grammar/compiler and actual source deployment admitted; method policy unchanged',
                    evidence_pin=spec['external_interface_gate'] if method=='TS' else entry['backend_admission'])
                if method=='TS' and reference:
                    assessments[method].update(input_track='nl',controlled_entry_supported=False,
                        input_provenance=entry['bundle'])
            sources=c['contributing_sources'];stratum='single-source' if len(sources)==1 else 'heterogeneous' if deployment=='native' else 'rdf-federation'
            cases.append(dict(case_id=c['case_id'],deployment=deployment,source_snapshot_sha256=c['source_snapshot_sha256'],
                source_stratum=stratum,sampling_stratum=c['stratum'],methods=assessments))
            key=bundle['dataset']+'/'+c['stratum']+'/'+c.get('workload','controlled-factor')+'/'+stratum
            counts[key]=counts.get(key,0)+1
    doc=dict(schema_version='xgap-ch6-case-support-v1',method_outputs_used=False,cases=cases,counts=counts,
             scope='predeclared deployment/operator capability; failures remain in supported denominators')
    validate_support(doc);write(output,doc);print(json.dumps(pin(output)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('spec-path','spec-sha256','output'):p.add_argument('--'+n,required=True)
    freeze(**vars(p.parse_args()))
