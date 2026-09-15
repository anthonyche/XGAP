"""Freeze and run the declared strong study, reusing owned serving/session gates.

No current-question plan probes, answer-dependent method selection or retries.
Only unstarted cells can resume after all prior owned sessions are closed.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from campaign_method_hosts import CampaignMethodHosts
from native_store_session import NativeStoreSession
from rdf_tdb_session import RdfTdbSession
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_methods import external_engine
from xgap.experiments.practical_study import dispatch_practical_group, freeze_study
from xgap.experiments.process_guard import ProcessBudget

REPO = Path(__file__).resolve().parents[1]
CLOSED = ('owned_groups_drained', 'owned_processes_terminal', 'observer_stopped')


def source_commit():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True):
        raise ValueError('Commit source before campaign work')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def read(pin):
    return json.loads(read_pinned(pin['path'], pin['sha256']))


def assert_closed(root):
    """Unfinished/inaccessible old sessions require reconciliation, never a retry."""
    for directory in sorted((Path(root) / 'sessions').glob('session-*')):
        closed = directory / 'closed.json'
        if not closed.exists() or not all(read(pin(closed))[k] for k in CLOSED):
            raise ValueError('Prior serving session is not verified closed: ' + str(directory))


def unstarted(schedule, ledger):
    return [c for c in schedule['cells'] if not (Path(ledger) / c['cell_id']).exists()]


def requires_retirement(row):
    if row['status'] == 'dispatch_failed': return True
    if row['status'] != 'outcome_sealed': return False
    receipt = read(row['outcome'])
    if not receipt['can_continue_session']: return True
    finalization = Path(row['outcome']['path']).parent / 'session-finalization.json'
    return not finalization.exists() or not read(pin(finalization))['can_continue_session']


def freeze(spec_pin, output):
    started = time.perf_counter(); commit = source_commit(); spec = read(spec_pin)
    if spec['schema_version'] != 'xgap-practical-campaign-spec-v1':
        raise ValueError('Expected the explicit campaign specification')
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    studies = {}
    for representation, entry in spec['studies'].items():
        cohort = read(entry['cohort']); study = read(entry['input'])
        selected = [g for g in cohort['groups'] if g['split'] == 'evaluation']
        expected = [{k: g[k] for k in ('request', 'profile', 'reference')} for g in selected]
        if study['groups'] != expected or len(expected) != 48:
            raise ValueError('Keep all 48 original evaluation groups in declared order')
        prepared = read(entry['prepared']); original = read(prepared['profile'])
        first = read(selected[0]['profile'])
        if original['sources'] != first['sources'] or original['dataset'] != first['dataset']:
            raise ValueError('Serving facts differ from the strong study')
        for name, backend in first['backends'].items():
            old = original['backends'][name]
            client = lambda b: {k: v for k, v in b['client'].items() if k != 'url'}
            if old['semantic'] != backend['semantic'] or client(old) != client(backend):
                raise ValueError('Serving semantic/client contract differs')
            if backend['client']['timeout_seconds'] != spec['source_budget']['timeout_seconds']:
                raise ValueError('Frozen source timeout differs')
        print(json.dumps({'phase': 'freeze_start', 'representation': representation, 'groups': 48}), flush=True)
        at = time.perf_counter()
        schedule = freeze_study(input_path=entry['input']['path'], input_sha256=entry['input']['sha256'],
                                output=root / representation)
        studies[representation] = {**entry, 'schedule': schedule,
            'offline_schedule_publication_ms': (time.perf_counter() - at) * 1000}
        print(json.dumps({'phase': 'freeze_complete', 'representation': representation, 'schedule': schedule}), flush=True)
    receipt = write_once(root / 'release.json', {'schema_version': 'xgap-practical-campaign-release-v1',
        'specification': spec_pin, 'source_commit': commit, 'driver': pin(__file__), 'studies': studies,
        'process_budget': spec['process_budget'], 'source_budget': spec['source_budget'],
        'release_scope': spec['scope'], 'formal_campaign_ready': True, 'paper_result': False,
        'inherited_method_results': 0, 'reference_contents_read': False,
        'model_calls': 0, 'source_queries': 0, 'automatic_retries': 0,
        'offline_release_ms': (time.perf_counter() - started) * 1000,
        'readiness_meaning': 'Pinned first evaluation configuration and verified existing execution gates; no claim of results or superiority'})
    print(json.dumps({'release': receipt}), flush=True)
    return receipt


def execute(release_pin, representation, output, max_dispatches, read_key=False):
    commit = source_commit(); release = read(release_pin)
    if release['schema_version'] != 'xgap-practical-campaign-release-v1' or not release['formal_campaign_ready']:
        raise ValueError('A released campaign is required')
    if commit != release['source_commit'] or pin(__file__) != release['driver']:
        raise ValueError('Do not change implementation within this campaign')
    entry = release['studies'][representation]; schedule = read(entry['schedule'])
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=True)
    identity = {'release': release_pin, 'representation': representation}
    marker = root / 'identity.json'
    if marker.exists():
        if read(pin(marker)) != identity: raise ValueError('Cannot mix releases')
    else: write_once(marker, identity)
    assert_closed(root)
    ledger = root / 'ledger'; previous = {str(p): pin(p) for p in ledger.rglob('*.json')}
    invocation = root / f'invocation-{len(list(root.glob("invocation-*.json"))):03}.json'
    report = {'schema_version': 'xgap-practical-campaign-invocation-v1', **identity, 'success': False,
        'source_commit': commit, 'maximum_dispatches': max_dispatches, 'dispatches': [], 'sessions': [],
        'automatic_retries': 0, 'warmup_queries': 0, 'credential_recorded': False}
    key_name = 'XGAP_EXTERNAL_LLM_API_KEY'; prior_key = os.environ.get(key_name)
    session = None; hosts = None; error = None
    def close():
        nonlocal session, hosts
        if session is None: return
        closure = session.close()
        report['sessions'].append({'root': str(session.root), 'ready': session.ready_pin,
            'closed': pin(session.root / 'closed.json'), 'closure': closure,
            'host_initializations': hosts.initializations if hosts else {}})
        session = hosts = None
        if not all(closure[k] for k in CLOSED): raise ValueError('Owned session closure incomplete')
    try:
        if read_key:
            os.environ[key_name] = getpass.getpass('LLM credential (not recorded): ')
        if any(external_engine(m) for m in schedule['methods']) and not os.environ.get(key_name):
            raise ValueError('Configured credential required for fixed information methods')
        for dispatch_index in range(max_dispatches):
            todo = unstarted(schedule, ledger)
            if not todo: break
            if session is None:
                assert_closed(root)
                index = len(list((root / 'sessions').glob('session-*')))
                cls = NativeStoreSession if representation == 'native' else RdfTdbSession
                session = cls(root=root / 'sessions' / f'session-{index:03}',
                    prepared_path=entry['prepared']['path'], prepared_sha256=entry['prepared']['sha256'],
                    budget=SourceObservationBudget(**release['source_budget']), discard_serving_copies=True)
                session.start()
                if representation == 'rdf':
                    hosts = CampaignMethodHosts(session, summary_path=entry['summary']['path'],
                                                summary_sha256=entry['summary']['sha256'])
            def deploy(cell):
                doc = read(cell['practical_profile'])
                for backend in doc['backends'].values(): backend['client']['url'] = session.observer.base_url
                return write_once(session.root / ('deployment-' + cell['cell_id'] + '.json'), doc)
            before = {c['cell_id'] for c in todo}
            rows = dispatch_practical_group(schedule_path=entry['schedule']['path'],
                schedule_sha256=entry['schedule']['sha256'], ledger=ledger, observer=session.observer,
                owned_services=lambda c: hosts.owned_for(external_engine(c['method'])) if hosts else session.owned,
                deployment_for=deploy, budget=ProcessBudget(**release['process_budget']),
                endpoint_for=(lambda c: hosts.start(external_engine(c['method']))) if hosts else None)
            new = [row for row in rows if row['cell_id'] in before]
            report['dispatches'].append({'session': str(session.root), 'cells': new})
            print(json.dumps({'phase': 'dispatch', 'representation': representation,
                'new_terminals': sum(row['status'] in ('outcome_sealed', 'dispatch_failed') for row in new),
                'remaining_unstarted': len(unstarted(schedule, ledger)), 'group_index': todo[0]['group_index']}), flush=True)
            # A failed method is never repeated. Retire all hosts and sources before
            # the next unstarted cell, including the rest of the interrupted group.
            failed = any(requires_retirement(row) for row in new)
            if failed: close()
            elif any(row['status'] == 'unrun_prerequisite' for row in new):
                raise ValueError('Unresolved prerequisite; leave remaining cells unstarted')
        report['success'] = True  # orchestration, not answer or method success
    except BaseException as exc:
        error = exc; report.update(error_type=type(exc).__name__, error=str(exc))
    finally:
        try: close()
        except BaseException as exc:
            error = exc; report.update(success=False, closure_error_type=type(exc).__name__, closure_error=str(exc))
        if prior_key is None: os.environ.pop(key_name, None)
        else: os.environ[key_name] = prior_key
        report['prior_journal_files_unchanged'] = all(pin(path) == old for path, old in previous.items())
        if not report['prior_journal_files_unchanged']: report['success'] = False
        report['remaining_unstarted'] = len(unstarted(schedule, ledger))
        report['indeterminate_cells'] = [c['cell_id'] for c in schedule['cells']
            if (ledger / c['cell_id']).exists() and not (ledger / c['cell_id'] / 'terminal.json').exists()]
        result = write_once(invocation, report)
        print(json.dumps({'invocation': result, 'orchestration_success': report['success'],
                          'remaining_unstarted': report['remaining_unstarted']}), flush=True)
    if error: raise error
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('freeze', 'run'))
    parser.add_argument('--input', required=True); parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--representation', choices=('native', 'rdf'))
    parser.add_argument('--max-dispatches', type=int, default=1); parser.add_argument('--read-key', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.max_dispatches <= 384: parser.error('Bound dispatches to 1..384')
    selected = {'path': str(Path(args.input).resolve()), 'sha256': args.sha256}
    if args.operation == 'freeze': freeze(selected, args.output)
    elif args.representation is None: parser.error('--representation is required for run')
    else: execute(selected, args.representation, args.output, args.max_dispatches, args.read_key)
