#!/usr/bin/env python3
"""Freeze support before outcomes. Wrong answers/timeouts never remove support."""
import argparse
import json
from pathlib import Path

from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.ch6_support import validate_support
from xgap.experiments.ch6_formal_protocol import METHOD_ORDER


def freeze(spec_path,spec_sha256,output):
    spec=load(dict(path=spec_path,sha256=spec_sha256))
    if spec.get('schema_version')!='xgap-ch6-support-input-v1' or spec.get('method_outputs_used') is not False:
        raise ValueError('Pre-outcome support specification required')
    external=load(spec['external_interface_gate'])
    if not external.get('success'):raise ValueError('External interface must have actually passed its gate')
    cases=[];seen=set();counts={}
    for entry in spec['bundles']:
        bundle=load(entry['bundle']);admission=load(entry['backend_admission']);stores=load(entry['prepared'])
        if not admission.get('success') or not admission.get('backend_roundtrip') or not stores.get('success'):
            raise ValueError('Compiler-only evidence cannot establish backend admission')
        if (admission.get('admission_scope','complete_bundle')!='complete_bundle'
                or admission.get('full_bundle_admitted',True) is not True):
            raise ValueError('A diagnostic subset cannot establish complete deployment support')
        if admission['profile']['sha256']!=bundle['profile']['sha256'] or stores['profile']['sha256']!=bundle['profile']['sha256']:
            raise ValueError('Support gate and actual deployment differ')
        controlled=bundle.get('input_track')=='controlled'
        if not controlled and bundle.get('deployment_selection')!='balanced':
            raise ValueError('Overall study requires the prespecified mixed cohort')
        for c in bundle['cases']:
            if c['case_id'] in seen:raise ValueError('Duplicate mixed-workload case identity')
            seen.add(c['case_id']);assessments={}
            for method in METHOD_ORDER:
                deployment=c.get('deployment',bundle['deployment'])
                unsupported=method=='TS' and deployment=='native'
                interface=method=='TS' and controlled and not unsupported
                assessments[method]=dict(status='unsupported_deployment' if unsupported else 'unsupported_interface' if interface else 'supported',
                    basis='Original TS accepts SPARQL/RDF endpoints; no Neo4j/Cypher adapter' if unsupported else
                          'Original TS has no controlled-family input; a separately identified fixed NL cohort is required' if interface else
                          'Admitted external NL-to-SPARQL/FedX interface on shared RDF; answer quality is not support' if method=='TS' else
                          'Shared compact grammar/compiler and actual source deployment admitted; method policy unchanged',
                    evidence_pin=spec['external_interface_gate'] if method=='TS' else entry['backend_admission'])
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
