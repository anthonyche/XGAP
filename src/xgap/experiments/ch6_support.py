"""Outcome-independent capability sets for a mixed workload.

Support is a release artifact, never inferred from answer correctness. All
methods use the same case identities, source snapshots and deployment for a
paired comparison. Declared inability and attempted failure are different facts.
"""
from collections import Counter
from xgap.experiments.ch6_formal_protocol import METHOD_ORDER


def validate_support(document):
    if (document.get('schema_version') != 'xgap-ch6-case-support-v1'
            or document.get('method_outputs_used') is not False):
        raise ValueError('Support must be frozen independently of method outcomes')
    cases = document['cases']
    if not cases or len({c['case_id'] for c in cases}) != len(cases):
        raise ValueError('Nonempty unique case identities required')
    for case in cases:
        if not case.get('deployment') or not case.get('source_snapshot_sha256'):
            raise ValueError('Support requires an actual deployment and snapshot')
        if set(case['methods']) != set(METHOD_ORDER):
            raise ValueError('Support must assess all five methods')
        for method, item in case['methods'].items():
            if item['status'] not in ('supported', 'unsupported_deployment', 'unsupported_operator', 'unsupported_interface'):
                raise ValueError('Unknown support is not formal admission')
            if not item.get('basis') or not item.get('evidence_pin'):
                raise ValueError('A capability assessment needs a basis and evidence')
            if method == 'TS' and item['status'] == 'supported' and case['deployment'] != 'rdf':
                raise ValueError('The current external adapter accepts RDF deployment only')
    return document


def summarize_supported(document, observations, method):
    """Return counts and the declared subset; never silently discard failures."""
    validate_support(document)
    if method not in METHOD_ORDER:
        raise ValueError('Unknown method')
    cases = {c['case_id']: c for c in document['cases']}
    supported = {cid for cid, c in cases.items() if c['methods'][method]['status'] == 'supported'}
    selected = []; seen = set()
    for row in observations:
        if row['method'] != method:
            continue
        cid = row['case_id']; identity = (cid, row['repeat'])
        if cid not in cases or identity in seen:
            raise ValueError('Unknown or duplicated observation')
        seen.add(identity)
        if cid not in supported:
            raise ValueError('Measured request conflicts with the frozen unsupported assessment')
        if (row['deployment'] != cases[cid]['deployment']
                or row['source_snapshot_sha256'] != cases[cid]['source_snapshot_sha256']):
            raise ValueError('Observation differs from the supported source configuration')
        selected.append(row)
    return dict(method=method, total_cases=len(cases), supported_cases=len(supported),
        support_rate=len(supported)/len(cases), attempted_cases=len({r['case_id'] for r in selected}),
        attempted_requests=len(selected), completed_requests=sum(bool(r['execution_success']) for r in selected),
        missing_cases=sorted(supported-{r['case_id'] for r in selected}),
        outcome_counts=dict(Counter(r['status'] for r in selected)), rows=selected)


def paired_xgap_subset(document, observations, method, *, completed_only=False):
    """XGAP and comparator on identical supported cases/repeats/timing scopes."""
    baseline = summarize_supported(document, observations, method)
    xgap = summarize_supported(document, observations, 'XGAP')
    index = {(r['case_id'], r['repeat']): r for r in xgap['rows']}
    pairs = []
    for other in baseline['rows']:
        own = index.get((other['case_id'], other['repeat']))
        if own is None or own['timing_scope'] != other['timing_scope']:
            continue
        if completed_only and not (own['execution_success'] and other['execution_success']):
            continue
        pairs.append((own, other))
    return pairs
