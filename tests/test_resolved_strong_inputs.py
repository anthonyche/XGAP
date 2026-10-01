"""Closed input authority, unchanged population and one tiny realized execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_practical_profile import FIXTURE, ROOT, no_network, sha
from test_cooperative_planning_budget import ControlledEstimator
from test_shared_native_reads import case
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.resolved_strong_inputs import closed_template, publish_resolved_cohort
from xgap.semantic.intake import DeterministicSemanticIntake, SemanticIntakeError
from xgap.semantic.interpretation import InterpretationRequest, TemplateInterpretationProvider
from xgap.semantic.program import SemanticGraphProgram


MODES = ROOT / 'experiments/protocols/resolved_strong_modes_dev_v1.json'


def simple_program():
    return SemanticGraphProgram.from_dict({'program_id': 'closed-people', 'operators': [
        {'operator_id': 'people', 'kind': 'match', 'input_ids': [], 'input_kinds': [],
         'output_kind': 'binding_set', 'parameters': {'node': {'label': 'Person'},
            'entity_field': 'person', 'properties': {'name': 'name'}}}], 'roots': ['people']})


def inputs(root):
    doc = json.loads((FIXTURE / 'profile.json').read_text())
    base = {k: deepcopy(doc[k]) for k in ('dataset', 'sources', 'backends', 'catalog', 'estimator')}
    base.update(schema_version='xgap-frozen-one-shot-profile-v1', source_schema={
        'toy': {'nodes': {'Person': {'properties': ['id']}}, 'edges': []},
        'toy-people': {'nodes': {'Person': {'properties': ['id', 'name', 'age']}}, 'edges': []}})
    for k in ('catalog', 'estimator'):
        base[k]['path'] = str((FIXTURE / base[k]['path']).resolve())
    base_pin = write_once(root / 'base.json', base)
    items = []
    for i, split in enumerate(('development', 'estimator_training', 'evaluation')):
        qid = 'explicit-' + str(i)
        request = write_once(root / f'request-{i}.json', {
            'schema_version': 'xgap-one-shot-evaluation-request-v1', 'question_id': qid,
            'question': f'Return people, wording {i}', 'population': 'original-tiny', 'exposure': split})
        semantics = write_once(root / f'semantics-{i}.json', {'family': 'closed-people',
            'program': simple_program().to_dict(), 'operator_sources': {'people': 'intentionally-invalid-gold-source'},
            'reference_sparql': 'not used to plan', 'runtime_input': False})
        items.append({'question_id': qid, 'split': split, 'family': 'closed-people', 'files': {
            'request': request, 'gold': semantics,
            'reference': {'path': str(root / f'NEVER-OPEN-REFERENCE-{i}.json'), 'sha256': '0' * 64}}})
    population = write_once(root / 'population.json', {'schema_version': 'xgap-finbench-one-shot-population-v1',
        'dataset': base['dataset'], 'population_id': 'original-tiny', 'instance_count': 3, 'artifacts': items,
        'split_counts': {'development': 1, 'estimator_training': 1, 'evaluation': 1}})
    return dict(population_path=population['path'], population_sha256=population['sha256'],
        base_profile_path=base_pin['path'], base_profile_sha256=base_pin['sha256'],
        modes_path=MODES, modes_sha256=sha(MODES), output=root / 'published')


def test_closed_input_requires_opt_in_and_is_bound_to_the_exact_question():
    template = closed_template(simple_program(), 'Return people', template_id='explicit-closed')
    with pytest.raises(SemanticIntakeError, match='requires holes'):
        DeterministicSemanticIntake(template)
    intake = DeterministicSemanticIntake(template, allow_closed=True)
    assert not intake.compile('Return people').program.holes
    with pytest.raises(SemanticIntakeError, match='Question differs'):
        intake.compile('Return accounts instead')
    template['metadata'].pop('trusted_question_sha256')
    with pytest.raises(SemanticIntakeError, match='pin the exact question'):
        DeterministicSemanticIntake(template, allow_closed=True)


def test_publish_preserves_every_group_meaning_and_reference_without_reading_answers(tmp_path, monkeypatch):
    args = inputs(tmp_path)
    loads = []
    original_load = FrozenResolutionBundle.load
    def counted(*a, **kw):
        loads.append(a[0])
        return original_load(*a, **kw)
    monkeypatch.setattr(FrozenResolutionBundle, 'load', counted)
    original_open = Path.open
    def guarded(path, *a, **kw):
        if path.name.startswith('NEVER-OPEN'):
            pytest.fail('Reference opened before a sealed trial')
        return original_open(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    pin = publish_resolved_cohort(**args)
    result = json.loads(Path(pin['path']).read_text())
    assert len(loads) == 1 and result['instance_count'] == 3
    assert result['split_counts'] == {'development': 1, 'estimator_training': 1, 'evaluation': 1}
    assert not result['reference_contents_read'] and not result['formal_campaign_ready']
    assert result['planning_runs'] == result['backend_calls'] == result['model_calls'] == result['catalog_builds'] == 0
    for i, group in enumerate(result['groups']):
        assert group['question_id'] == f'explicit-{i}'
        assert group['reference']['sha256'] == '0' * 64
        raw = json.loads(Path(group['request']['path']).read_text())
        assert raw['exposure'] == group['split'] and raw['trusted_bindings'] == raw['predictions'] == {}
        assert not ({'program', 'answer', 'rows', 'reference_sparql'} & raw.keys())
        doc = json.loads(Path(group['profile']['path']).read_text())
        assert doc['operator_sources'] == {} and 'source_schema' in doc
        assert all(v['client']['url'] == 'http://127.0.0.1:1' for v in doc['backends'].values())
        assert doc['modes']['performance']['semantic']['improve_physical']
        assert doc['modes']['performance']['search']['max_terminals_per_state'] == 2
        assert doc['catalog'] == json.loads(Path(args['base_profile_path']).read_text())['catalog']
    # A freshly admitted ordinary profile also rejects reuse for another question.
    group = result['groups'][0]
    profile, cfg = FrozenPracticalProfile.load_materialized(group['profile']['path'], expected_sha256=group['profile']['sha256'])
    raw = json.loads(Path(group['request']['path']).read_text())
    calls=[]
    from xgap.experiments import practical_profile as runtime
    original_route=runtime.source_assignments
    def route(*a,**kw):
        calls.append(True)
        return original_route(*a,**kw)
    monkeypatch.setattr(runtime,'source_assignments',route)
    prepared=profile.prepare(raw,request_sha256=group['request']['sha256'],request_root=tmp_path,mode='exact',materialized=cfg)
    assert len(calls)==1 and prepared.provider.operator_sources=={'people':'toy-people'}
    assert prepared.source_routing['elapsed_ms']>=0 and not prepared.source_routing['source_assignment_from_gold']
    planned=profile.run_prepared(prepared,execute=False)
    assert planned['search']['strong'] and planned['final_plan_executions']==0
    assert planned['source_routing']==prepared.source_routing
    assert len(calls)==1  # Running the admitted snapshot does not redo routing.
    raw['question'] = 'Another question'
    with pytest.raises(SemanticIntakeError, match='Question differs'):
        profile.prepare(raw, request_sha256='0' * 64, request_root=tmp_path, mode='exact', materialized=cfg)
    with pytest.raises(FileExistsError):
        publish_resolved_cohort(**args)


@pytest.mark.parametrize('change', ['duplicate', 'dataset', 'prediction'])
def test_bad_cohort_or_unmatched_mode_permissions_fail_before_publication(tmp_path, change):
    args = inputs(tmp_path)
    key = 'modes' if change == 'prediction' else 'population'
    doc = json.loads(Path(args[key + '_path']).read_text())
    if change == 'duplicate':
        doc['artifacts'][1]['question_id'] = doc['artifacts'][0]['question_id']
    elif change == 'dataset':
        doc['dataset']['version'] = 'changed'
    else:
        doc['modes']['performance']['semantic']['allowed_unvalidated'] = ['invented']
    pin = write_once(tmp_path / 'bad.json', doc)
    args.update({key + '_path': pin['path'], key + '_sha256': pin['sha256']})
    with pytest.raises(ValueError):
        publish_resolved_cohort(**args)
    assert not (tmp_path / 'published').exists()


@pytest.mark.parametrize('mode', ['exact', 'performance'])
def test_actual_closed_modes_can_improve_estimate_then_execute_one_tiny_plan(mode):
    program, _, backends, clients, _, calls, sources = case()
    template = closed_template(program, 'Count edge pairs', template_id='closed-pairs')
    intake = DeterministicSemanticIntake(template, allow_closed=True)
    provider = TemplateInterpretationProvider(intake, {'left': 'graph', 'right': 'graph'})
    admitted = SemanticGraphProgram.from_dict(provider.interpret(InterpretationRequest('Count edge pairs')).payload['program'])
    m = json.loads(MODES.read_text())['modes'][mode]
    limits = {**m['search'], 'resources': ResourceUsage(**m['search']['resources'])}
    estimator = ControlledEstimator(sources)  # Finite100/5 fixture, not learned or measured latency.
    result = run_practical_semantic_query(admitted, initial_state=BindingState(evidence=(
        BindingEvidence('$structure', program_identity(admitted), 'trusted_request', 'tiny', 'v1'),)),
        mode=PracticalMode(**m['semantic']), operator_sources={'left': 'graph', 'right': 'graph'},
        binding_values={}, sources=sources, backends=backends, backend_clients=clients,
        estimator=estimator, physical_profile=OneShotPolicy(**m['physical']), limits=StrongSearchLimits(**limits))
    assert result['success'] and result['answer_rows'] == [{'n': 14}], result
    assert result['search']['strong'] and result['search']['selected_estimated_cost'] == 5
    assert len(estimator.calls) > 1 and result['search']['first_feasible_estimated_cost'] == 100
    assert result['final_plan_executions'] == result['backend_remote_calls'] == len(calls) == 1
    assert result['model_calls'] == result['clarification_calls'] == 0
