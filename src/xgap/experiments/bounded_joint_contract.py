"""Pinned configuration shared by both current modes; no evaluation labels."""
from dataclasses import asdict, fields
from fractions import Fraction
import json

from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits
from xgap.experiments.one_shot_profile import read_pinned
from xgap.planning.joint_cost import JointCostProfile

METHODS = ('xgap-bounded-joint-exact', 'xgap-bounded-joint-performance')
TRACK = 'natural_language_bounded_joint'
METRICS = ('scope_confirmation_calls', 'total_user_calls', 'clarification_calls',
           'disclosed_coordinates', 'planning_cpu_ms', 'planning_ms', 'execution_ms',
           'end_to_end_ms', 'certificate_ms', 'physical_prepare_attempts', 'root_gap',
           'scope_confirmed', 'candidate_count', 'terminal_certificate', 'strong_plan',
           'user_intent_verified', 'estimated_policy_cost_including_common_actions', 'cost_scope')


def configuration(*, epsilon='0', information=FamilyInformationPolicy(), limits=StrongSearchLimits(),
                  costs=JointCostProfile(), provider='frozen_compact_model'):
    return dict(schema_version='xgap-bounded-joint-run-config-v1', epsilon=str(epsilon),
                information=asdict(information), limits=asdict(limits), costs=asdict(costs), provider=provider)


def load_configuration(path, sha256):
    raw = json.loads(read_pinned(path, sha256))
    if set(raw) != {'schema_version', 'epsilon', 'information', 'limits', 'costs', 'provider'} or raw['schema_version'] != 'xgap-bounded-joint-run-config-v1':
        raise ValueError('Invalid bounded joint configuration')
    if not isinstance(raw['epsilon'], str) or not 0 <= Fraction(raw['epsilon']) <= 1:
        raise ValueError('Epsilon must be a rational string in [0,1]')
    if raw['provider'] not in ('frozen_compact_model', 'development_toy_template'):
        raise ValueError('Unknown proposal provider')
    def checked(cls, values):
        if not isinstance(values, dict) or set(values) != {f.name for f in fields(cls)}:
            raise ValueError('Configuration fields differ from '+cls.__name__)
        return dict(values)
    info = checked(FamilyInformationPolicy, raw['information'])
    info['additional_scopes'] = tuple(tuple(s) for s in info['additional_scopes'])
    limits = checked(StrongSearchLimits, raw['limits'])
    limits['resources'] = ResourceUsage(**checked(ResourceUsage, limits['resources']))
    return raw, FamilyInformationPolicy(**info), StrongSearchLimits(**limits), JointCostProfile(**checked(JointCostProfile, raw['costs']))
