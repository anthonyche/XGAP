"""Freeze a balanced small workload from public metadata, without reading outcomes.

W1/W2 are single-source semantic strata; W3/W4 are cross-source strata.
Selection never treats W as a query-shape or execution-difficulty category.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import pin_file
from xgap.experiments.one_shot_records import write_once

SCHEMA = 'xgap-ch6-small-real-selection-v1'
SEED = 'xgap-small-real-balanced-20260926-v1'
CASE_PINS = ('request', 'scope', 'oracle', 'reference', 'controlled_state')
EXPOSURE = 'previously_exposed_authored_small_evaluation'


def select_cases(bundle, *, seed=SEED):
    """One hash-ranked case per W × sampling frame, for one fixed deployment."""
    if bundle.get('method_outputs_used_for_selection') is not False:
        raise ValueError('The source bundle must declare outcome-independent selection')
    dataset, deployment = bundle['dataset'], bundle['deployment']
    if dataset not in ('D1', 'D2', 'D3') or deployment not in ('native', 'rdf'):
        raise ValueError('Unexpected dataset or deployment')
    cases = bundle['cases']
    if len({c['case_id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate source case IDs')
    chosen = []
    for workload in ('W1', 'W2', 'W3', 'W4'):
        for stratum in ('uniform', 'active-anchor'):
            group = [c for c in cases if c['workload'] == workload and c['stratum'] == stratum]
            if not group:
                raise ValueError(f'Missing prespecified stratum: {dataset}/{deployment}/{workload}/{stratum}')
            for c in group:
                expected_sources = 1 if workload in ('W1', 'W2') else 2
                if (c['deployment'] != deployment or len(set(c['contributing_sources'])) != expected_sources
                        or c['initial_ambiguity'] != {'W1': 0, 'W2': 1, 'W3': 3, 'W4': 3}[workload]):
                    raise ValueError('Case does not satisfy the frozen W/deployment definition')
            def rank(c):
                return hashlib.sha256(f'{seed}|{dataset}|{deployment}|{workload}|{stratum}|{c["case_id"]}'.encode()).hexdigest()
            winner = min(group, key=lambda c: (rank(c), c['case_id']))
            item = deepcopy(winner)
            item.update(selection_rank=rank(winner), stratum_population=len(group),
                        selection_probability=f'1/{len(group)}', exposure=EXPOSURE)
            chosen.append(item)
    return chosen


class MirrorPins:
    """Resolve server pins against read-only mirrors; hashes, never path guesses, authorize bytes."""
    def __init__(self, server_root, roots):
        self.server_root = Path(server_root)
        self.roots = [Path(r) for r in roots]
        self.verified = {}

    def verify(self, pin):
        if pin['sha256'] in self.verified:
            return Path(self.verified[pin['sha256']]['local_path'])
        relative = Path(pin['path']).relative_to(self.server_root)
        for root in self.roots:
            path = root / relative
            if path.is_file() and pin_file(path)['sha256'] == pin['sha256']:
                self.verified[pin['sha256']] = dict(server_pin=pin, local_path=str(path),
                                                   bytes=path.stat().st_size)
                return path
        raise ValueError(f'No verified local bytes for {pin["path"]}')

    def load_public(self, pin):
        return json.loads(self.verify(pin).read_text())


def prepare(index, output):
    """Write six immutable launch templates and a 48-case selection, with no queries."""
    if index.get('schema_version') != 'xgap-ch6-small-sample-input-v1':
        raise ValueError('Explicit small-sample inputs required')
    if index.get('selection_seed') != SEED:
        raise ValueError('The declared selection seed is fixed, not a search parameter')
    pins = MirrorPins(index['server_root'], index['mirror_roots'])
    cohorts = []
    seen = set()
    for entry in index['cohorts']:
        spec = pins.load_public(entry['source_spec'])
        bundle = pins.load_public(spec['bundle'])
        identity = (bundle['dataset'], bundle['deployment'])
        if identity in seen:
            raise ValueError('Duplicate cohort')
        seen.add(identity)
        selected = select_cases(bundle)
        if spec.get('case_ids') is not None and set(c['case_id'] for c in selected) - set(spec['case_ids']):
            raise ValueError('Selection is outside the frozen release support cohort')
        for key in ('prepared', 'backend_admission'):
            pins.verify(spec[key])
        pins.verify(bundle['profile'])
        if spec.get('external_runtime'):
            pins.verify(spec['external_runtime'])
        for case in selected:
            for key in CASE_PINS:
                # Private oracle/reference content is hashed only, never parsed or used for ranking.
                pins.verify(case[key])
        cohort = dict(dataset=identity[0], deployment=identity[1], source_spec=entry['source_spec'],
                      bundle=spec['bundle'], profile=bundle['profile'],
                      case_ids=[c['case_id'] for c in selected], cases=selected,
                      prepared=spec['prepared'], backend_admission=spec['backend_admission'],
                      design=spec['design'], external_runtime=spec.get('external_runtime'),
                      parameters=spec.get('parameters', {}),
                      method_requests=8 * (5 if identity[1] == 'rdf' else 4),
                      input_track='nl', exposure=EXPOSURE)
        cohorts.append(cohort)
    if seen != {(d, p) for d in ('D1', 'D2', 'D3') for p in ('native', 'rdf')}:
        raise ValueError('Exactly the six frozen dataset/deployment cohorts are required')
    cohorts.sort(key=lambda c: (c['dataset'], c['deployment']))
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    for c in cohorts:
        name = f'{c["dataset"]}-{c["deployment"]}'
        template = dict(schema_version='xgap-ch6-batch-input-v1', prepared=c['prepared'],
                        external_runtime=c['external_runtime'], deployment=c['deployment'],
                        input_track='nl', exposure=EXPOSURE, order_seed=20260926,
                        design=c['design'], cases=c['cases'],
                        methods=['XGAP', 'NP', 'SH', 'GR', 'TS'])
        c['input_template'] = write_once(root / f'{name}-input-template.json', template)
    manifest = dict(schema_version=SCHEMA, selection_seed=SEED, cohorts=cohorts,
                    unique_query_intent_cases=48, cases_per_domain=16, cases_per_W_per_domain=4,
                    repetitions=1, supported_method_requests=216,
                    methods=['XGAP', 'NP', 'SH', 'GR', 'TS'],
                    method_results_read=0, private_answers_parsed=0, model_calls=0, backend_calls=0,
                    launch_ready=False, exposure=EXPOSURE,
                    provenance='Existing authored templates on real snapshots; not benchmark query-card equivalence',
                    sampling='Minimum SHA-256 rank within W × frame × deployment; no outcome filtering',
                    aggregation='Report frame/deployment strata and W-equal means; baseline-paired subsets',
                    pending=['Attach paid-probe configurations and pin the executable code',
                             'Small-study launch audit and authenticated service access'],
                    source_graph_size='Unchanged complete frozen dataset snapshots',
                    figure_scope='E1/E2/F1/F2/F7/F8 and actual C1 traces; factor scans need separate inputs')
    result = write_once(root / 'small-selection.json', manifest)
    write_once(root / 'local-pin-verification.json', dict(verified=list(pins.verified.values()),
                                                       private_content_read_only_for_hashing=True))
    import csv
    with (root / 'selected-cases.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['dataset', 'deployment', 'workload', 'stratum',
                                                    'case_id', 'template', 'structures', 'initial_candidate_count',
                                                    'contributing_sources', 'selection_rank', 'exposure'])
        writer.writeheader()
        for c in cohorts:
            for case in c['cases']:
                writer.writerow({k: c['dataset'] if k == 'dataset' else
                                 json.dumps(case[k]) if isinstance(case[k], list) else case[k]
                                 for k in writer.fieldnames})
    return result
