"""New public entry contracts retain admitted sources and five-method fairness."""
from copy import deepcopy

import pytest

import ch6_source_runtime as runtime
import run_bounded_joint_batch as batch
from test_bounded_joint_batch import fixture, install_fake_runtime, launch
from test_ch6_source_runtime import admitted
from xgap.experiments import ch6_small_migration as migration
from xgap.experiments import compact_constraints_profile as constraints
from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.one_shot_records import write_once


def migrated_cohort(root, monkeypatch, old_cells, prepared):
    request = write_once(root / 'new-request.json', {
        **runtime.load(old_cells[0]['request']), 'question': 'A development question. Public edge roles.'})
    profile = write_once(root / 'parent-profile.json', dict(profile_id='original'))
    proof = write_once(root / 'source-only-proof.json', dict(public=True))
    entry = write_once(root / 'entry-profile.json', dict(
        profile_id='derived', offline=dict(compact_public_constraints=proof)))
    certificate = write_once(root / 'migration.json', dict(schema_version='test'))
    original = old_cells[0]
    cohort = dict(deployment='rdf', parent_prepared=prepared, parent_profile=profile,
        entry_profile=entry, cases=[dict(case_id='q', request=request,
            original_request=original['request'], reference=original['reference'],
            oracle=original['oracle'], scope=original['scope'])])
    # Certificate proof construction has its own tests. Here check the caller
    # cannot replace its checked deployment/profile pair or skip cell validation.
    def checked(pin, *, prepared_pin, entry_profile_pin):
        assert pin == certificate and prepared_pin == prepared and entry_profile_pin == entry
        return cohort
    monkeypatch.setattr(migration, 'migration_cohort', checked)
    new_cells = [{**cell, 'request': request} for cell in old_cells]
    return cohort, certificate, entry, new_cells


def test_migration_reuses_original_admission_without_admitting_new_nl(tmp_path, monkeypatch):
    manifest = fixture(tmp_path)
    config, prepared, _, _ = admitted(tmp_path, monkeypatch, manifest['cells'])
    cohort, cert, entry, cells = migrated_cohort(tmp_path, monkeypatch, manifest['cells'], prepared)
    design = dict(source_runtime=config)
    with pytest.raises(ValueError, match='outside'):
        runtime.validate_admission(design, 'rdf', prepared, cells=cells)
    assert runtime.validate_admission(design, 'rdf', prepared, cells=cells,
        entry_migration=cert, entry_profile=entry) == config
    assert cells[0]['request'] != manifest['cells'][0]['request']  # no in-place relabeling
    bad = deepcopy(cells); bad[0]['reference']['sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='shared migration'):
        runtime.validate_admission(design, 'rdf', prepared, cells=bad,
            entry_migration=cert, entry_profile=entry)
    with pytest.raises(ValueError, match='pinned together'):
        runtime.validate_admission({}, 'rdf', prepared, cells=cells, entry_migration=cert)
    with pytest.raises(ValueError, match='deployment differs'):
        runtime.validate_admission({}, 'native', prepared, cells=cells,
            entry_migration=cert, entry_profile=entry)


def test_migrated_batch_uses_actual_endpoints_four_internal_profiles_and_original_ts(tmp_path, monkeypatch):
    import ch6_external_session as external
    manifest = fixture(tmp_path); original = manifest['cells'][0]
    cells = []
    for i, method in enumerate(METHODS.values()):
        cell = {**original, 'cell_id': str(i), 'method': method}
        if method == batch.EXTERNAL_METHOD:
            cell = {k: v for k, v in cell.items() if k in ('cell_id', 'method', 'request', 'reference')}
        cells.append(cell)
    config, prepared, _, _ = admitted(tmp_path, monkeypatch, cells)
    cohort, cert, entry, migrated = migrated_cohort(tmp_path, monkeypatch, cells, prepared)
    # Actual selection pins omit optional bytes whereas prepared session pins
    # include it; path and SHA determine identity, not dictionary decoration.
    serving_parent = deepcopy(cohort['parent_profile'])
    cohort['parent_profile'] = {k: v for k, v in serving_parent.items() if k != 'bytes'}
    manifest.update(schema_version=batch.FORMAL_SCHEMA, deployment='rdf', prepared=prepared,
        cells=migrated, external_runtime=write_once(tmp_path / 'external.json', {}),
        entry_migration=cert, entry_profile=entry)
    manifest['design']['source_runtime'] = config
    seen, sessions = install_fake_runtime(monkeypatch)
    original_trial = batch.run_nl_trial
    base = batch.NativeStoreSession
    original_profiles = []; internal_profiles = []; proof_checks = []
    class Session(base):
        def start(self):
            doc = dict(profile_id='live', backends={'graph': {'client': {'url': 'http://127.0.0.1:9182'}}},
                source_schema={'public': True}, modes={'old': 'unchanged'}, offline=dict(
                    serving_endpoint_parent=serving_parent,
                    prepared_stores={k: v for k, v in prepared.items() if k != 'bytes'},
                    source_runtime=config['contract'], tdb2_serving_file_mode='direct'))
            self.profile = write_once(self.root / 'profile.json', doc)
            original_profiles.append(deepcopy(doc))
    monkeypatch.setattr(batch, 'RdfTdbSession', Session)
    def check_proof(doc, *, profile_root):
        proof_checks.append(deepcopy(doc))
        assert runtime.load(doc['offline']['compact_public_constraints']) == {'public': True}
    monkeypatch.setattr(constraints, 'load_public_compact_constraints', check_proof)
    def trial(**kwargs):
        assert kwargs['request_path'] == migrated[0]['request']['path']
        internal_profiles.append(dict(path=kwargs['profile_path'], sha256=kwargs['profile_sha256']))
        return original_trial(**kwargs)
    monkeypatch.setattr(batch, 'run_nl_trial', trial)
    class External:
        def __init__(self, *, source_session, **kwargs):
            self.source_session = source_session
            assert runtime.load(source_session.profile) == original_profiles[0]
        def start(self): pass
        def close(self):
            return dict(owned_groups_drained=True, owned_processes_terminal=True, observer_stopped=True)
    monkeypatch.setattr(external, 'ExternalSession', External)
    def external_trial(**kwargs):
        assert kwargs['request'] == migrated[0]['request']
        return original_trial(output=kwargs['output'], method=batch.EXTERNAL_METHOD,
            request_sha256=kwargs['request']['sha256'])
    monkeypatch.setattr(external, 'run_trial', external_trial)
    result, _ = launch(tmp_path, manifest)
    assert result['status'] == 'returned' and result['counts']['sealed'] == 5
    assert len(sessions) == 1 and sessions[0].closed and seen == ['0', '1', '2', '3', '4']
    assert len(internal_profiles) == 4 and len({p['sha256'] for p in internal_profiles}) == 1
    effective = runtime.load(internal_profiles[0])
    assert effective['offline'].pop('compact_public_constraints') == runtime.load(entry)['offline']['compact_public_constraints']
    assert effective == original_profiles[0]
    assert runtime.load(sessions[0].profile) == original_profiles[0]
    import json
    receipt = json.loads((sessions[0].root / 'entry-profile-receipt.json').read_text())
    assert receipt['changed_fields'] == ['offline.compact_public_constraints']
    assert 'new NL interpretations are not pre-admitted' in receipt['admission_scope']
    assert len(proof_checks) == 2 and all('oracle' not in d for d in proof_checks)


def test_entry_extension_is_explicit_and_formal_only(tmp_path):
    manifest = fixture(tmp_path)
    manifest['entry_migration'] = manifest['prepared']
    with pytest.raises(ValueError, match='pinned together'):
        batch.validate(manifest)
    manifest['entry_profile'] = manifest['prepared']
    with pytest.raises(ValueError, match='Formal entry'):
        batch.validate(manifest)
