"""Versioned unified run settings; immutable inputs shared by all contract values."""
from dataclasses import asdict,fields
import json

from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_information import targets_from_dict
from xgap.agent.unified_lookahead import Limits,Resources
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.planning.joint_cost import JointCostProfile
from xgap.experiments.one_shot_profile import read_pinned

METHODS=('xgap-unified-lookahead','xgap-unified-sequential','xgap-unified-two-stage',
         'xgap-unified-no-probe','xgap-unified-shallow','xgap-unified-myopic')
TRACK='natural_language_unified_lookahead'
CONTROLLED_TRACK='controlled_unified_lookahead'
REQUEST_METRICS=('initial_decision_estimate_including_common_actions','realized_trace_work_estimate')
ONLINE_METRICS=('probe_calls','metadata_calls','physical_actions','plan_registry_count','plan_registry_bytes',
    'estimate_evaluations','estimate_cache_hits','initialization_ms','local_action_ms','acquisition_ms',
    'expanded_states','certificate_checks','certificate_cache_hits','optional_plan_rejections',
    'realized_acquisition_cost_estimate','selected_execution_cost_estimate')
METRICS=REQUEST_METRICS+ONLINE_METRICS


def metric_values(core):
    """Keep whole-request prices distinct from nested online-only diagnostics."""
    online=core.get('joint_policy') or core
    return {**{k:core.get(k) for k in REQUEST_METRICS},**{k:online.get(k) for k in ONLINE_METRICS}}


def configuration(*,settings=UnifiedSettings(),information=FamilyInformationPolicy(),costs=JointCostProfile(),
                  provider='frozen_compact_model'):
    data=asdict(settings)
    version='xgap-unified-run-config-v3' if settings.live_probe_policy is not None else 'xgap-unified-run-config-v2'
    if settings.live_probe_policy is None:data.pop('live_probe_policy')
    return dict(schema_version=version,settings=data,information=asdict(information),
                costs=asdict(costs),provider=provider)


def load_configuration(path,sha256):
    raw=json.loads(read_pinned(path,sha256))
    if (set(raw)!={'schema_version','settings','information','costs','provider'}
            or raw['schema_version'] not in ('xgap-unified-run-config-v1','xgap-unified-run-config-v2','xgap-unified-run-config-v3')
            or raw['provider'] not in ('frozen_compact_model','frozen_compact_model_equivalence_v1',
                                      'frozen_compact_model_public_contract_v1','development_toy_template')):
        raise ValueError('Invalid unified run configuration')
    def checked(cls,doc):
        if not isinstance(doc,dict) or set(doc)!={f.name for f in fields(cls)}:
            raise ValueError('Missing or unknown '+cls.__name__+' setting')
        return dict(doc)
    doc=dict(raw['settings'])
    if raw['schema_version'] in ('xgap-unified-run-config-v1','xgap-unified-run-config-v2'):
        if 'live_probe_policy' in doc:raise ValueError('Live probe policy needs a v3 configuration')
        doc['live_probe_policy']=None
    if raw['schema_version']=='xgap-unified-run-config-v1':
        if set(doc)!={f.name for f in fields(UnifiedSettings)}-{'information_mode','action_objective'}:
            raise ValueError('Missing or unknown legacy UnifiedSettings setting')
        doc.update(information_mode='all',action_objective='continuation')
    settings=checked(UnifiedSettings,doc)
    limits=checked(Limits,settings['limits']);limits['resources']=Resources(**checked(Resources,limits['resources']))
    settings['limits']=Limits(**limits);settings['relaxable']=tuple(settings['relaxable'])
    if settings['candidate_weights'] is not None:settings['candidate_weights']=tuple(settings['candidate_weights'])
    settings['information_targets']=targets_from_dict(settings['information_targets'])
    from xgap.agent.live_probe import policy_from_dict
    settings['live_probe_policy']=policy_from_dict(settings['live_probe_policy'])
    information=checked(FamilyInformationPolicy,raw['information'])
    information['additional_scopes']=tuple(tuple(x) for x in information['additional_scopes'])
    return raw,FamilyInformationPolicy(**information),UnifiedSettings(**settings),JointCostProfile(**checked(JointCostProfile,raw['costs']))


def validate_method(method,settings):
    """Prevent silent variant mixing; preserve the historical sequential ID."""
    if method not in METHODS:raise ValueError('Unknown unified method')
    order={'xgap-unified-sequential':'semantic_then_physical','xgap-unified-two-stage':'two_stage'}.get(method,'joint')
    info='no_probe' if method=='xgap-unified-no-probe' else 'all'
    objective='myopic' if method=='xgap-unified-myopic' else 'continuation'
    if (settings.decision_order!=order or settings.information_mode!=info or settings.action_objective!=objective
            or method=='xgap-unified-shallow' and settings.limits.depth!=1):
        raise ValueError('Method identity differs from frozen variant settings')
