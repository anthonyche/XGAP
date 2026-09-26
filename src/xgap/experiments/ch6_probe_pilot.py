"""Freeze a new, explicit probe scenario without rewriting inactive Ch6 releases.

This publisher reads public controlled families, source contracts and declared
estimates only. It neither gathers statistics nor runs a method. Priors are bound
to the complete public candidate order; they cannot be transferred to a different
NL-generated family merely because its candidate count happens to agree.
"""
from dataclasses import replace
import json
from pathlib import Path

from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.unified_information import targets_from_dict
from xgap.agent.unified_lookahead import cost
from xgap.experiments.ch6_formal_protocol import METHODS, load_pin
from xgap.experiments.controlled_state import read_state
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration, load_configuration, validate_method


def probe_summary(settings, report=None):
    """Keep declaration, permission and observed work distinct; missing is null."""
    probes = {t.name for t in settings.information_targets if t.kind == 'probe'}
    core = (report.get('joint_policy') or report) if report is not None else None
    trace = core.get('trace') if core is not None else None
    facts = core.get('selected_facts') if core is not None else None
    return dict(probe_registered_count=len(probes),
        probe_enabled_count=len(probes) if settings.information_mode == 'all' else 0,
        probe_axis_active=bool(probes),
        probe_selected_calls=None if trace is None else sum(t['kind'] == 'probe' for t in trace),
        probe_known_fact_count=None if facts is None else len(probes.intersection(facts)),
        availability_scope='registered and method-enabled; not a promise of selection or resource feasibility')


def publish(input_pin, output):
    """Publish four paired configs for one pinned controlled-family scenario."""
    spec = load_pin(input_pin)
    fields = {'schema_version', 'base_configuration', 'profile', 'request', 'controlled_state',
              'information_registry', 'candidate_prior', 'aggregation', 'probe_price'}
    if set(spec) != fields or spec['schema_version'] != 'xgap-ch6-probe-pilot-input-v1':
        raise ValueError('Explicit new probe-pilot input required')
    if spec['aggregation'] not in ('max', 'expectation'):
        raise ValueError('Declare max or expectation explicitly; never infer the objective')
    cost(spec['probe_price'])
    if spec['probe_price'] <= 0:
        raise ValueError('A positive declared probe-price multiplier is required')

    base, information, settings, costs = load_configuration(
        spec['base_configuration']['path'], spec['base_configuration']['sha256'])
    profile = FrozenOneShotProfile.load(spec['profile']['path'], expected_sha256=spec['profile']['sha256'])
    doc, _, _, sources, backends, client_specs, _ = profile.materialize()
    request = load_pin(spec['request'])
    family, _, _ = read_state(load_pin(spec['controlled_state']), request['question'])
    if family.source_snapshot != snapshot_identity(sources, backends, doc['source_schema']):
        raise ValueError('Public family and profile source snapshot differ')

    registry = load_pin(spec['information_registry'])
    if (set(registry) != {'schema_version', 'profile', 'targets', 'basis'}
            or registry['schema_version'] != 'xgap-ch6-information-registry-v1'
            or registry['profile'] != spec['profile'] or not isinstance(registry['basis'], str)
            or not registry['basis'].strip() or not isinstance(registry['targets'], list)):
        raise ValueError('Frozen information registry must identify this profile and its estimate basis')
    targets = targets_from_dict(registry['targets'])
    for target in targets:
        source = sources.get(target.source_id)
        if (source is None or source.snapshot_version != target.version
                or target.backend not in source.replica_backend_ids):
            raise ValueError('Information target source/version/backend differs from the pinned profile')
        language = 'cypher' if client_specs[target.backend]['engine'] == 'neo4j' else 'sparql'
        if json.loads(target.artifact_json)['language'] != language:
            raise ValueError('Information artifact language differs from its pinned backend')
        if spec['aggregation'] == 'expectation' and target.probabilities is None:
            raise ValueError('Expectation requires every target outcome probability, including unknown')

    weights = None
    ids = [candidate.candidate_id for candidate in family.candidates]
    if spec['candidate_prior'] is not None:
        prior = load_pin(spec['candidate_prior'])
        if (set(prior) != {'schema_version', 'controlled_state', 'candidate_ids', 'weights', 'basis'}
                or prior['schema_version'] != 'xgap-ch6-candidate-prior-v1'
                or prior['controlled_state'] != spec['controlled_state'] or prior['candidate_ids'] != ids
                or not isinstance(prior['weights'], list) or len(prior['weights']) != len(ids)
                or not isinstance(prior['basis'], str) or not prior['basis'].strip()):
            raise ValueError('Candidate prior must bind every public candidate in its original order')
        weights = tuple(prior['weights'])
    if spec['aggregation'] == 'expectation' and weights is None:
        raise ValueError('Expectation requires an explicit frozen candidate prior')

    settings = replace(settings, limits=replace(settings.limits, aggregation=spec['aggregation']),
        candidate_weights=weights, information_targets=tuple(
            replace(target, action_cost=target.action_cost * spec['probe_price'])
            if target.kind == 'probe' else target for target in targets))
    variants = {}
    for label in ('XGAP', 'NP', 'SH', 'GR'):
        variant = replace(settings, decision_order='joint',
            information_mode='no_probe' if label == 'NP' else 'all',
            action_objective='myopic' if label == 'GR' else 'continuation',
            limits=replace(settings.limits, depth=1) if label in ('SH', 'GR') else settings.limits)
        validate_method(METHODS[label], variant)
        variants[label] = (variant, configuration(settings=variant, information=information,
            costs=costs, provider=base['provider']))

    # Validate everything before creating any new artifact directory.
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    configs = {label: write_once(root / (label + '-config.json'), config)
               for label, (_, config) in variants.items()}
    receipt = dict(schema_version='xgap-ch6-probe-pilot-configurations-v1', input=input_pin,
        success=True, configurations=configs, base_configuration=configs['XGAP'],
        input_track='controlled', family_identity=family.identity, candidate_ids=ids,
        profile=spec['profile'], aggregation=spec['aggregation'], probe_price=spec['probe_price'],
        diagnostics={label: probe_summary(variant) for label, (variant, _) in variants.items()},
        prior_scope='Exact public controlled family and candidate order; not an NL prior policy',
        selection_claim=False, source_statistics_collected=False,
        estimator_scope='Unchanged frozen estimator plus explicitly declared category work costs',
        model_calls=0, backend_calls=0, method_results_read=0, formal_campaign_ready=False)
    return write_once(root / 'receipt.json', receipt)
