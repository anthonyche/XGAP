"""Explicit, append-only recovery of unattempted small-study cells.

The parent release and sealed outcomes remain immutable. A recovery is a new
supervisor attempt with an explicit wall-clock policy, not an ordinary resume
or a fresh 216-cell release. Preparation and inspection make no remote calls.
"""
import argparse
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

from xgap.experiments.one_shot_records import write_once
from xgap.experiments.batch_cell_identity import validate_cell_id

SCHEMA = 'xgap-ch6-small-continuation-v1'
REPO = Path(__file__).resolve().parents[1]
HARNESS_FILES = frozenset({
    'scripts/run_ch6_small_continuation.py', 'scripts/ch6_external_session.py',
    'src/xgap/experiments/owned_resources.py',
    'src/xgap/experiments/process_guard.py',
})
CLOSED_FIELDS = ('owned_groups_drained', 'owned_processes_terminal', 'observer_stopped')
USAGE_FIELDS = ('model_calls', 'input_tokens', 'output_tokens')
PACKAGING_FILES = frozenset({'scripts/build_ch6_small48_independent_handoff.py',
    'scripts/build_ch6_small_continuation_handoff.py'})


def pin(path, *, logical_path=None):
    path = Path(path)
    data = path.read_bytes()
    return dict(path=str(logical_path or path.resolve()), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def reader(mapper=None):
    """An optional path mapper permits read-only audits of downloaded evidence."""
    resolve = mapper or (lambda p: Path(p))
    def load(ref):
        path = Path(resolve(ref['path']))
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ref['sha256'] or ('bytes' in ref and len(data) != ref['bytes']):
            raise ValueError('Pinned recovery evidence differs: ' + ref['path'])
        return json.loads(data)
    return load, resolve


def require_closed(value):
    if not all(value.get(k) is True for k in CLOSED_FIELDS):
        raise ValueError('Prior owned services have not verified closure')
    if value.get('serving_copy_reclamation_complete') is False:
        raise ValueError('Prior serving copies require explicit recovery')
    for process in value.get('processes', []):
        cleanup = process.get('cleanup', {})
        if cleanup.get('complete') is not True or cleanup.get('live_pids'):
            raise ValueError('Prior process cleanup is incomplete')


def inspect_parent(release_pin, *, mapper=None):
    """Validate the entire sealed prefix and derive the untouched suffix.

    This checks available execution evidence. The full source/input admission
    audit is additionally required on the server immediately before execution.
    """
    load, resolve = reader(mapper)
    release = load(release_pin)
    if (release.get('schema_version') != 'xgap-ch6-small-real-release-v1' or
            release.get('automatic_retries') != 0 or len(release.get('units', [])) != 6):
        raise ValueError('A complete original small-study release is required')
    parent = Path(release['output_root'])
    evidence = []
    def local_json(logical):
        ref = pin(resolve(str(logical)), logical_path=logical)
        evidence.append(ref)
        return load(ref)
    identity = local_json(parent / 'identity.json')
    old_identity = identity.get('identity', {})
    if (old_identity.get('source_commit') != release['source_commit'] or
            any(old_identity.get('release', {}).get(k) != release_pin.get(k) for k in ('path', 'sha256'))):
        raise ValueError('Parent release identity differs')
    spent = dict(model_calls=0, input_tokens=0, output_tokens=0,
                 unknown_model_usage=False, sealed_cells=0, unsealed_cells=0)
    units = []
    expected_paths = set()
    pending_seen = False
    total = 0
    order = release['execution_dataset_order']
    unit_ids = [u['unit_id'] for u in release['units']]
    if len(set(unit_ids)) != 6 or {(u['dataset'], u['deployment']) for u in release['units']} != {
            (d, p) for d in ('D1', 'D2', 'D3') for p in ('native', 'rdf')}:
        raise ValueError('Original dataset/deployment membership differs')
    for unit in sorted(release['units'], key=lambda u: (order.index(u['dataset']), u['deployment'])):
        validate_cell_id(unit['unit_id'])
        manifest = load(unit['manifest'])
        evidence.append(unit['manifest'])
        unit_root = parent / 'units' / unit['unit_id']
        local_unit = Path(resolve(str(unit_root)))
        pending = []
        if local_unit.exists():
            ident = local_json(unit_root / 'identity.json')
            if ident.get('identity') != dict(manifest_sha256=unit['manifest']['sha256'], source_commit=release['source_commit']):
                raise ValueError('Prior batch identity differs')
            invocations = sorted((local_unit / 'invocations').iterdir())
            if not invocations:
                raise ValueError('Existing unit has no invocation history')
            for invocation in invocations:
                record = local_json(unit_root / 'invocations' / invocation.name / 'receipt.json')
                if record.get('all_owned_closed') is not True or record.get('error'):
                    raise ValueError('Unresolved prior invocation or closure')
                for closure in record.get('closures', []):
                    require_closed(closure)
        for cell in manifest['cells']:
            validate_cell_id(cell['cell_id'])
            total += 1
            logical = unit_root / 'cells' / cell['cell_id']
            physical = Path(resolve(str(logical)))
            if physical in expected_paths:
                raise ValueError('Duplicate parent cell identity')
            expected_paths.add(physical)
            if not physical.exists():
                pending_seen = True
                pending.append(cell)
                continue
            if pending_seen:
                raise ValueError('Attempted cells are not the original ordered prefix')
            if not (physical / 'terminal.json').is_file():
                raise ValueError('Unsealed prior cell requires recovery before continuation')
            terminal = local_json(logical / 'terminal.json')
            outcome, score = load(terminal['outcome']), load(terminal['score'])
            evidence.extend((terminal['outcome'], terminal['score']))
            if (terminal['cell_id'] != cell['cell_id'] or outcome['method'] != cell['method'] or
                    outcome['request_sha256'] != cell['request']['sha256'] or
                    score['receipt_sha256'] != terminal['outcome']['sha256'] or
                    score['reference_sha256'] != cell['reference']['sha256']):
                raise ValueError('Sealed cell/input identity differs')
            if 'query_loss' in terminal:
                loss = load(terminal['query_loss'])
                evidence.append(terminal['query_loss'])
                if loss['receipt_sha256'] != terminal['outcome']['sha256'] or loss['oracle_sha256'] != cell['oracle']['sha256']:
                    raise ValueError('Sealed interpretation score identity differs')
            for name in USAGE_FIELDS:
                value = outcome.get(name)
                if value is None and outcome.get('model_calls') == 0:
                    value = 0
                if type(value) is not int or value < 0:
                    raise ValueError('Prior model usage is incomplete')
                spent[name] += value
            spent['sealed_cells'] += 1
            if cell['method'] == 'aruqula-fedx':
                require_closed(local_json(logical / 'external-services' / 'closed.json'))
        units.append(dict(unit=unit, parent_manifest=unit['manifest'], manifest=manifest, pending_cells=pending))
    actual_paths = set(Path(resolve(str(parent))).glob('units/*/cells/*'))
    actual_units = {p.name for p in Path(resolve(str(parent))).glob('units/*')}
    if actual_units - set(unit_ids):
        raise ValueError('Unexpected parent unit outside the frozen release')
    if actual_paths - expected_paths or total != 216 or not 0 < spent['sealed_cells'] < total:
        raise ValueError('Unexpected parent cell membership or no strict continuation')
    return dict(parent_release=release_pin, source_commit=release['source_commit'],
                parent_started_unix=identity['started_unix'], usage=spent,
                remaining_cells=total-spent['sealed_cells'], total_cells=total,
                evidence_pins=evidence, units=units, release=release,
                audit_scope='sealed execution evidence; full server source/input audit required before execute')


def source_migration(repo, old_commit, new_commit, allowed_harness_changes):
    allowed = set(allowed_harness_changes)
    if not allowed <= HARNESS_FILES:
        raise ValueError('Migration allowlist includes experimental algorithm code')
    names = subprocess.check_output(['git', 'diff', '--name-only', old_commit, new_commit, '--'], cwd=repo, text=True).splitlines()
    illegal = [n for n in names if n not in allowed | PACKAGING_FILES and not n.startswith(('docs/', 'tests/')) and n != 'AGENTS.md']
    if illegal:
        raise ValueError('Non-harness source changes: ' + ', '.join(illegal))
    return dict(parent_commit=old_commit, continuation_commit=new_commit, changed_paths=names,
                allowed_runtime_paths=sorted(allowed), experimental_algorithm_unchanged=True)


def prepare(*, parent_release, output, source_commit, recovery_wall_seconds,
            prior_allocation_seconds, allowed_harness_changes, mapper=None, repo=REPO):
    """Write one new continuation contract; no credentials, services or submission."""
    checked = inspect_parent(parent_release, mapper=mapper)
    release = checked['release']
    for value in (recovery_wall_seconds, prior_allocation_seconds):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Explicit positive allocation and recovery wall time required')
    if recovery_wall_seconds + prior_allocation_seconds > release['budget']['total_wall_seconds']:
        raise ValueError('Recovery plus observed allocation exceeds original active wall allowance')
    migration = source_migration(repo, release['source_commit'], source_commit, allowed_harness_changes)
    root = Path(output).resolve()
    parent_local = Path((mapper or Path)(release['output_root'])).resolve()
    if root == parent_local or root in parent_local.parents or parent_local in root.parents:
        raise ValueError('Continuation output must be disjoint from parent evidence')
    root.mkdir(parents=True, exist_ok=False)
    units = []
    for item in checked['units']:
        if not item['pending_cells']:
            continue
        unit = item['unit']
        manifest = deepcopy(item['manifest'])
        manifest['cells'] = item['pending_cells']
        ref = write_once(root / (unit['unit_id'] + '-manifest.json'), manifest)
        units.append(dict(unit_id=unit['unit_id'], dataset=unit['dataset'], deployment=unit['deployment'],
                          parent_manifest=item['parent_manifest'], manifest=ref))
    contract = dict(schema_version=SCHEMA, parent_release=parent_release, parent_output_root=release['output_root'],
        source_commit=source_commit, source_migration=migration, units=units,
        prior_usage=checked['usage'], parent_evidence=checked['evidence_pins'],
        parent_started_unix=checked['parent_started_unix'], remaining_cells=checked['remaining_cells'],
        output_root=str(root / 'results'), original_budget=release['budget'],
        recovery_wall_seconds=recovery_wall_seconds, prior_allocation_seconds=prior_allocation_seconds,
        wall_policy='explicit recovery active-allocation allowance; offline repair wait excluded; supersedes parent elapsed-calendar wall policy',
        max_cells_per_source_session=release['max_cells_per_source_session'], automatic_retries=0,
        prepared_only=True, backend_calls=0, model_calls=0, submitted_jobs=0)
    return write_once(root / 'continuation.json', contract)


def execute(contract_pin):
    """One fresh continuation attempt, with inherited accounting and no retries."""
    from run_bounded_joint_batch import run, source_commit
    from run_ch6_formal_campaign import usage, package_bytes
    from run_ch6_small_study import stop_reason
    from xgap.experiments.ch6_small_release import audit
    load, _ = reader()
    cfg = load(contract_pin)
    if cfg.get('schema_version') != SCHEMA or source_commit() != cfg['source_commit']:
        raise ValueError('Continuation code/contract identity differs')
    checked = inspect_parent(cfg['parent_release'])
    if checked['usage'] != cfg['prior_usage'] or checked['evidence_pins'] != cfg['parent_evidence']:
        raise ValueError('Parent changed after continuation preparation')
    if (cfg['original_budget'] != checked['release']['budget'] or
            cfg['parent_output_root'] != checked['release']['output_root'] or
            cfg['remaining_cells'] != checked['remaining_cells'] or
            cfg['max_cells_per_source_session'] != checked['release']['max_cells_per_source_session'] or
            cfg.get('automatic_retries') != 0):
        raise ValueError('Continuation resets frozen parent budgets or membership')
    if any(type(cfg[k]) not in (int, float) or not math.isfinite(cfg[k]) or cfg[k] <= 0
           for k in ('recovery_wall_seconds', 'prior_allocation_seconds')) or (
            cfg['recovery_wall_seconds'] + cfg['prior_allocation_seconds'] > cfg['original_budget']['total_wall_seconds']):
        raise ValueError('Invalid explicit recovery wall allowance')
    if not audit(checked['release'])['success']:
        raise ValueError('Original full release no longer passes source/input audit')
    migration = source_migration(REPO, checked['source_commit'], cfg['source_commit'], cfg['source_migration']['allowed_runtime_paths'])
    if migration != cfg['source_migration']:
        raise ValueError('Source migration contract differs')
    wanted = [x for x in checked['units'] if x['pending_cells']]
    if len(wanted) != len(cfg['units']):
        raise ValueError('Continuation unit membership differs')
    for item, unit in zip(wanted, cfg['units']):
        expected = deepcopy(item['manifest']); expected['cells'] = item['pending_cells']
        if unit['unit_id'] != item['unit']['unit_id'] or load(unit['manifest']) != expected:
            raise ValueError('Continuation changes frozen cells, their order or budgets')
    if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):
        raise ValueError('Model credential unavailable')
    root = Path(cfg['output_root'])
    parent_root = Path(cfg['parent_output_root']).resolve()
    if root.resolve() == parent_root or root.resolve() in parent_root.parents or parent_root in root.resolve().parents:
        raise ValueError('Continuation output must remain disjoint')
    root.mkdir(parents=True, exist_ok=False)
    with (root / '.continuation.lock').open('x') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        write_once(root / 'identity.json', dict(contract=contract_pin, source_commit=cfg['source_commit'], started_unix=time.time()))
        status, error, invocations = 'all_unattempted_requests_processed', None, []
        def cumulative(current=None):
            current = dict(usage(root) if current is None else current)
            for key in (*USAGE_FIELDS, 'sealed_cells'):
                current[key] += cfg['prior_usage'][key]
            return current
        try:
            for unit in cfg['units']:
                manifest = load(unit['manifest']); design = manifest['design']
                target = root / 'units' / unit['unit_id']
                external_cap = load(manifest['external_runtime'])['model_budget']['max_calls'] if manifest.get('external_runtime') else 0
                def before(cell):
                    reason = stop_reason(cumulative(), cfg['original_budget'],
                        remaining_seconds=cfg['recovery_wall_seconds']-(time.monotonic()-started),
                        needed_seconds=design['method_wall_seconds']+2*design['startup_seconds'],
                        next_call_cap=external_cap if cell['method']=='aruqula-fedx' else 1)
                    if reason:
                        return reason
                    own = package_bytes(target) if target.exists() else 0
                    if package_bytes(Path(cfg['parent_output_root']))+package_bytes(root)-own+design['package_max_bytes'] > cfg['original_budget']['package_max_bytes']:
                        return 'continuation_package_budget'
                    return None
                while True:
                    accounted = usage(root)
                    if accounted['unsealed_cells'] or accounted['unknown_model_usage']:
                        status = 'accounting_incomplete'; break
                    pending = [c for c in manifest['cells'] if not (target/'cells'/c['cell_id']).exists()]
                    if not pending:
                        break
                    reason = before(pending[0])
                    if reason:
                        status = reason; break
                    result = run(manifest_path=unit['manifest']['path'], manifest_sha256=unit['manifest']['sha256'],
                        output=target, max_new_cells=min(len(pending), cfg['max_cells_per_source_session']), before_cell=before)
                    invocations.append(result.get('receipt'))
                    if result['status'] != 'returned' or not result['new_cells']:
                        status = result.get('budget_status') or 'continuation_' + result['status']; break
                if status != 'all_unattempted_requests_processed':
                    break
        except (Exception, KeyboardInterrupt) as exc:
            status='continuation_supervisor_failure'; error=dict(type=type(exc).__name__, message=str(exc))
        new_usage = usage(root)
        if new_usage['unsealed_cells'] or new_usage['unknown_model_usage']:
            status = 'accounting_incomplete'
        elif status == 'all_unattempted_requests_processed' and new_usage['sealed_cells'] != cfg['remaining_cells']:
            status = 'continuation_incomplete_membership'
        result = dict(schema_version=SCHEMA, status=status, error=error, contract=contract_pin,
            parent_usage=cfg['prior_usage'], new_usage=new_usage, cumulative_usage=cumulative(new_usage),
            invocations=invocations, elapsed_seconds=time.monotonic()-started,
            wall_policy=cfg['wall_policy'], automatic_retries=0, formal_campaign_ready=False)
        result['receipt'] = write_once(root/'receipt.json', result)
        return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract-path', required=True)
    parser.add_argument('--contract-sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    args=parser.parse_args(); ref=dict(path=args.contract_path,sha256=args.contract_sha256)
    cfg=reader()[0](ref)
    result=execute(ref) if args.execute else dict(action='inspect_only', contract=ref,
        remaining_cells=cfg['remaining_cells'], prior_usage=cfg['prior_usage'], model_calls=0, backend_calls=0)
    print(json.dumps(result))
    if args.execute and result['status'] != 'all_unattempted_requests_processed':
        raise SystemExit(2)
