"""Freeze already selected plans, never choose them using parallel performance."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.ch6_parallel import LEVELS, execute, ready_width
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.runtime.contracts import FederatedExecutionPlan


class Reader:
    def __init__(self, root, original_prefix=None):
        self.root = Path(root).resolve()
        self.original_prefix = Path(original_prefix) if original_prefix else None

    def load(self, pin):
        path = Path(pin['path'])
        if self.original_prefix and path.is_relative_to(self.original_prefix):
            path = self.root / path.relative_to(self.original_prefix)
        data = read_pinned(path, pin['sha256'])
        if pin.get('encoding') == 'gzip':
            data = gzip.decompress(data)
            if len(data) != pin['logical_bytes'] or hashlib.sha256(data).hexdigest() != pin['logical_sha256']:
                raise ValueError('Compressed core logical content differs')
        return json.loads(data)


def selected_plan(terminal, reader, *, case_id, method):
    """Read authoritative executed plan even when its answer was incorrect."""
    outcome = reader.load(terminal['outcome'])
    if outcome['question_id'] != case_id or outcome['method'] != method:
        raise ValueError('Sealed outcome differs from selected request')
    if outcome.get('final_plan_executions') != 1:
        return outcome, None, None, 'no_final_plan'
    if not outcome.get('core'):
        return outcome, None, None, 'missing_core_artifact'
    core = reader.load(outcome['core'])
    joint = core.get('joint_policy') or {}
    raw = (joint.get('execution') or {}).get('physical_plan')
    query = joint.get('selected_query')
    if raw is None or query is None:
        return outcome, None, None, 'missing_selected_plan_artifact'
    plan = FederatedExecutionPlan.from_dict(raw)
    if not plan.metadata.get('source_identities'):
        return outcome, None, None, 'missing_source_identities'
    return outcome, plan, query, 'frozen_selected_plan'


def freeze(*, release_pin, evidence_root, output, original_prefix=None, artifact_root=None):
    # A downloaded package may place release/selection beside, rather than
    # inside, the run's units tree. Pin relocation and cell lookup are separate.
    reader = Reader(artifact_root or evidence_root, original_prefix)
    release = reader.load(release_pin)
    if release['schema_version'] != 'xgap-ch6-small-real-release-v1':
        raise ValueError('A pinned small-real release is required')
    selection = reader.load(release['selection'])
    if selection['unique_query_intent_cases'] != 48:
        raise ValueError('Keep the preselected 48 cases')
    cohorts = {(c['dataset'], c['deployment']): c for c in selection['cohorts']}
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=False)
    entries = []
    for unit in release['units']:
        cohort = cohorts[(unit['dataset'], unit['deployment'])]
        manifest = reader.load(unit['manifest'])
        cells = {(unit['cell_cases'][c['cell_id']], c['method']): c['cell_id'] for c in manifest['cells']}
        for case in cohort['cases']:
            for label, method in METHODS.items():
                cid = cells.get((case['case_id'], method))
                entry = dict(dataset=unit['dataset'], deployment=unit['deployment'],
                    case_id=case['case_id'], method=label, cell_id=cid,
                    unit_id=unit['unit_id'], query_input=case['request'],
                    prepared_sources=cohort['prepared'], profile=cohort['profile'],
                    levels=list(LEVELS), status='pending_sealed_outcome',
                    selected_plan=None, selected_query=None, measurements=None)
                terminal_path = Path(evidence_root) / 'units' / unit['unit_id'] / 'cells' / (cid or '') / 'terminal.json'
                if label == 'TS':
                    entry.update(status='unsupported_deployment' if unit['deployment'] == 'native'
                                 else 'fixed_reference', levels=None,
                                 parameter_applicable=False,
                                 reference_state='sealed' if terminal_path.is_file() else 'pending')
                    if terminal_path.is_file():
                        terminal = json.loads(terminal_path.read_text())
                        outcome = reader.load(terminal['outcome'])
                        if terminal['cell_id'] != cid or outcome['question_id'] != case['case_id'] or outcome['method'] != method:
                            raise ValueError('Fixed reference differs from selected request')
                        entry['original_outcome'] = terminal['outcome']
                elif cid is None:
                    raise ValueError('Missing selected supported manifest cell')
                elif terminal_path.is_file():
                    terminal = json.loads(terminal_path.read_text())
                    if terminal['cell_id'] != cid: raise ValueError('Terminal cell identity differs')
                    outcome, plan, query, status = selected_plan(terminal, reader,
                        case_id=case['case_id'], method=method)
                    entry.update(status=status, original_outcome=terminal['outcome'],
                                 original_status=outcome['status'], parameter_applicable=True)
                    if plan is not None:
                        folder = out / unit['unit_id'] / cid; folder.mkdir(parents=True)
                        entry.update(selected_plan=write_once(folder / 'plan.json', plan.to_dict()),
                            selected_query=write_once(folder / 'query.json', query),
                            source_identities=plan.metadata['source_identities'],
                            static_ready_width=ready_width(plan))
                entries.append(entry)
    if len(entries) != 240: raise ValueError('Keep all 48 × five method positions')
    result = dict(schema_version='xgap-ch6-fixed-plan-parallel-recipe-v1',
        release=release_pin, selection=release['selection'], levels=list(LEVELS), entries=entries,
        counts=dict(Counter(e['status'] for e in entries)), model_calls=0, backend_calls=0,
        paper_measurements=False, selection_policy='All preselected cases; no correctness or speedup filtering',
        experiment_scope='Fixed-plan execution only, not end-to-end replanning or full-workload extrapolation',
        runtime_requirements=['existing guarded observed source session', 'same source identities and total CPU/RAM',
            'unchanged row/call/time budgets and cache protocol', 'record answer equality and source/coordinator resources'],
        pending_policy='Do not overwrite; create a new immutable recipe after additional sealed outcomes arrive')
    return write_once(out / 'recipe.json', result)


def execute_frozen(entry, backend_tool, *, parallelism, source_identities):
    """Call only within a caller-owned guarded source session; never starts one."""
    if entry['status'] != 'frozen_selected_plan': raise ValueError('No frozen executable plan')
    if parallelism not in entry['levels']: raise ValueError('Parallelism was not frozen')
    plan = FederatedExecutionPlan.from_dict(Reader('/').load(entry['selected_plan']))
    Reader('/').load(entry['selected_query'])
    if source_identities != entry['source_identities'] or plan.metadata['source_identities'] != source_identities:
        raise ValueError('Serving source identities differ from the selected plan')
    return execute(plan, backend_tool, parallelism=parallelism)
