from dataclasses import asdict
from copy import deepcopy
import pytest
from prepare_ch6_live_factor_refresh import refresh_config
from xgap.agent.live_probe import LiveProbePolicy
from xgap.experiments.ch6_formal_protocol import METHODS
from xgap.experiments.unified_contract import configuration


def test_controlled_refresh_keeps_knobs_and_has_no_nl_adapter():
    old=configuration(); before=deepcopy(old)
    policy=LiveProbePolicy(policy_id='fixture',basis='Declared public priors')
    new=refresh_config(old,policy,METHODS['XGAP'],price=5)
    assert old==before
    assert new['provider']=='frozen_compact_model'
    assert new['schema_version']=='xgap-unified-run-config-v3'
    assert new['settings']['limits']['depth']==old['settings']['limits']['depth']
    assert new['settings']['limits']['aggregation']=='expectation'
    assert new['settings']['live_probe_policy']['action_cost']==5*policy.action_cost
    assert new['settings']['information_targets']==old['settings']['information_targets']


def test_existing_live_registry_is_never_replaced():
    old=configuration(); policy=LiveProbePolicy(policy_id='fixture',basis='Declared public priors')
    old['settings']['candidate_weights']=[1]
    with pytest.raises(ValueError,match='silently'): refresh_config(old,policy,METHODS['XGAP'])
    old=configuration(provider='frozen_compact_model_equivalence_v1')
    with pytest.raises(ValueError,match='original'): refresh_config(old,policy,METHODS['XGAP'])


def test_np_remains_no_probe():
    old=configuration(); old['settings']['information_mode']='no_probe'
    policy=LiveProbePolicy(policy_id='fixture',basis='Declared public priors')
    new=refresh_config(old,policy,METHODS['NP'])
    assert new['settings']['information_mode']=='no_probe'
    with pytest.raises(ValueError,match='mismatch'):refresh_config(old,policy,METHODS['XGAP'])
