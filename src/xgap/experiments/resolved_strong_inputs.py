"""Publish an existing resolved FinBench cohort as explicit strong-method inputs.

Only metadata and declared semantics are consumed. Reference contents, graph
records, model services and method outputs are not inputs to this publisher.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile, REQUEST_SCHEMA, SCHEMA
from xgap.experiments.practical_study import SCHEMA as STUDY_SCHEMA
from xgap.semantic.binding import bind_semantic_query
from xgap.semantic.intake import DeterministicSemanticIntake, INTAKE_SCHEMA_VERSION
from xgap.semantic.program import SemanticGraphProgram, hard_constraints_sha256


INPUT_SCOPE = 'trusted_resolved_semantics; physical planning, not unaided NL or information-policy accuracy'
SPLITS = ('development', 'estimator_training', 'evaluation')


def _pin(raw, origin):
    path = str((origin / raw['path']).resolve())
    digest = raw['sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Exact input SHA-256 required')
    return {'path': path, 'sha256': digest}


def closed_template(program, question, *, template_id):
    """A trusted fully specified query, never an inferred answer or parsing claim."""
    if program.holes:
        raise ValueError('Resolved cohort requires a closed semantic program')
    operators = []
    for op in program.operators:
        raw = op.to_dict()
        if raw.pop('constraints'):
            raise ValueError('Resolved FinBench converter requires inline parameter conditions')
        raw['hole_ids'] = []
        operators.append(raw)
    return {'schema_version': INTAKE_SCHEMA_VERSION, 'template_id': template_id, 'template_version': '1',
        'holes': [], 'constraints': [], 'operators': operators, 'roots': list(program.roots),
        'metadata': {'input_scope': INPUT_SCOPE,
            'trusted_question_sha256': hashlib.sha256(question.encode('utf-8')).hexdigest()}}


def _same_meaning(original, prepared, bundle, assignments):
    bound = bind_semantic_query(prepared, {'program_id': prepared.program_id,
        'hard_constraints_sha256': hard_constraints_sha256(prepared),
        'hard_constraints_preserved': True, 'candidate_sets': []},
        binding_values=bundle.bindings, operator_sources=assignments)
    if ([o.to_dict() for o in original.operators] != [o.to_dict() for o in bound.program.operators]
            or original.roots != bound.program.roots or bound.program.holes):
        raise ValueError('Trusted intake changed the supplied resolved meaning')


def publish_resolved_cohort(*, population_path, population_sha256, base_profile_path,
        base_profile_sha256, modes_path, modes_sha256, output):
    """Preserve every declared group; fail instead of filtering unsupported inputs.

    Common dependencies are admitted once in this offline publication. The
    ordinary online worker still independently admits each request/profile.
    """
    started = time.perf_counter()
    origin = Path(population_path).resolve().parent
    population = json.loads(read_pinned(population_path, population_sha256))
    if (population.get('schema_version') != 'xgap-finbench-one-shot-population-v1'
            or not isinstance(population.get('artifacts'), list)
            or not 1 <= len(population['artifacts']) <= 128
            or population['instance_count'] != len(population['artifacts'])):
        raise ValueError('Expected the declared bounded FinBench population')
    items = population['artifacts']
    if (len({i['question_id'] for i in items}) != len(items)
            or set(i['split'] for i in items) - set(SPLITS)
            or dict(Counter(i['split'] for i in items)) != population['split_counts']):
        raise ValueError('Population IDs or declared split counts differ')
    base_root = Path(base_profile_path).resolve().parent
    base = json.loads(read_pinned(base_profile_path, base_profile_sha256))
    if base.get('schema_version') != 'xgap-frozen-one-shot-profile-v1' or base['dataset'] != population['dataset']:
        raise ValueError('Serving profile and population dataset differ')
    mode_document = json.loads(read_pinned(modes_path, modes_sha256))
    if (set(mode_document) != {'schema_version', 'profile_id', 'scope', 'modes'}
            or mode_document['schema_version'] != 'xgap-resolved-strong-modes-v1'):
        raise ValueError('Expected explicitly frozen resolved strong modes')
    modes = mode_document['modes']
    if set(modes) != {'exact', 'performance'} or any(
            m['actions'] or m['semantic']['allowed_unvalidated'] or
            m['search']['resources']['model_calls'] or m['search']['resources']['tokens']
            for m in modes.values()):
        raise ValueError('Resolved study uses identical fully bound inputs without acquisition')
    common = {k: deepcopy(base[k]) for k in ('dataset', 'catalog', 'estimator', 'sources', 'backends')}
    refs = [common['catalog']]
    if common['estimator'] is not None:
        refs.append(common['estimator'])
    refs += [s['equality_key_bounds'] for s in common['sources'].values() if 'equality_key_bounds' in s]
    for ref in refs:
        ref['path'] = str((base_root / ref['path']).resolve())
    for spec in common['backends'].values():
        spec['client']['url'] = 'http://127.0.0.1:1'  # Deployment is explicit, later.
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    groups = {split: [] for split in SPLITS}
    rows = []
    shared_cfg = None
    for index, item in enumerate(items):
        request_pin = _pin(item['files']['request'], origin)
        semantics_pin = _pin(item['files']['gold'], origin)
        reference_pin = _pin(item['files']['reference'], origin)  # Do not open.
        old_request = json.loads(read_pinned(request_pin['path'], request_pin['sha256']))
        if (old_request['schema_version'] != 'xgap-one-shot-evaluation-request-v1'
                or old_request['question_id'] != item['question_id']
                or old_request['population'] != population['population_id']):
            raise ValueError('Original request identity differs from population')
        supplied = json.loads(read_pinned(semantics_pin['path'], semantics_pin['sha256']))
        if supplied['family'] != item['family']:
            raise ValueError('Semantic family differs from declared group')
        program = SemanticGraphProgram.from_dict(supplied['program'])
        directory = root / f'group-{index:03}'
        directory.mkdir()
        template = closed_template(program, old_request['question'], template_id=f'resolved-finbench-{index:03}')
        intake_pin = write_once(directory / 'intake.json', template)
        request = {k: old_request[k] for k in ('question_id', 'question', 'population', 'exposure')}
        request.update(schema_version=REQUEST_SCHEMA, trusted_bindings={}, predictions={}, clarifications={})
        request_out = write_once(directory / 'request.json', request)
        doc = {**common, 'schema_version': SCHEMA, 'profile_id': f'{mode_document["profile_id"]}:{index:03}',
            'intake': {k: intake_pin[k] for k in ('path', 'sha256')}, 'operator_sources': {},
            'source_schema': base['source_schema'], 'acquisitions': {}, 'modes': modes,
            'offline': {'input_scope': INPUT_SCOPE,
                'authored_semantics_as_explicit_input': semantics_pin, 'original_request': request_pin,
                'parent_profile': {'path': str(Path(base_profile_path).resolve()), 'sha256': base_profile_sha256},
                'mode_configuration': {'path': str(Path(modes_path).resolve()), 'sha256': modes_sha256},
                'formal_campaign_release': False, 'catalog_builds': 0, 'fit_calls': 0, 'weights_changed': False}}
        profile_pin = write_once(directory / 'profile.json', doc)
        if shared_cfg is None:
            profile, shared_cfg = FrozenPracticalProfile.load_materialized(profile_pin['path'],
                expected_sha256=profile_pin['sha256'])
            cfg = shared_cfg
        else:
            # All dependency fields are exactly the same generated common object;
            # only the per-question intake, routing and provenance change.
            profile = FrozenPracticalProfile(directory, profile_pin['sha256'], json.dumps(doc))
            intake = DeterministicSemanticIntake(template, artifact_sha256=intake_pin['sha256'], allow_closed=True)
            cfg = (doc, intake, *shared_cfg[2:])
        for mode in modes:
            prepared = profile.prepare(request, request_sha256=request_out['sha256'], request_root=directory,
                mode=mode, materialized=cfg)
            _same_meaning(program, prepared.program, cfg[2], prepared.provider.operator_sources)
        group = {'request': request_out, 'profile': profile_pin, 'reference': reference_pin}
        groups[item['split']].append(group)
        rows.append({**{k: item[k] for k in ('question_id', 'split', 'family')}, **group,
            'intake': intake_pin, 'authored_semantics_as_explicit_input': semantics_pin,
            'source_routing_policy': 'online schema_required_fields_then_stable_source_id_v1',
            'operators': len(program.operators)})
    studies = {split: write_once(root / f'{split}-study-input.json', {'schema_version': STUDY_SCHEMA,
        'study_id': f'{mode_document["profile_id"]}:{split}', 'groups': selected})
        for split, selected in groups.items() if selected}
    return write_once(root / 'manifest.json', {'schema_version': 'xgap-resolved-strong-cohort-v1',
        'input_scope': INPUT_SCOPE, 'dataset': population['dataset'], 'instance_count': len(rows),
        'split_counts': population['split_counts'], 'groups': rows, 'study_inputs': studies,
        'original_population': {'path': str(Path(population_path).resolve()), 'sha256': population_sha256},
        'offline_preparation_ms': (time.perf_counter() - started) * 1000,
        'reference_contents_read': False, 'catalog_admission_count': 1, 'catalog_builds': 0,
        'model_calls': 0, 'backend_calls': 0, 'fit_calls': 0, 'planning_runs': 0,
        'automatic_retries': 0, 'formal_campaign_ready': False, 'paper_result': False})
