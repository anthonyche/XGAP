"""Real portable scalar queries and live-family binding, no remote endpoints."""
from dataclasses import replace
import hashlib
import json

import pytest

from test_unified_actions import fixture
from test_unified_family import invocation
from xgap.agent.live_probe import LiveProbePolicy,bind_live_probes,capped_count
from xgap.agent.unified_family import UnifiedSettings,FamilyDomain,FamilyState
from xgap.agent.unified_contract import UnifiedTerminalContract
from xgap.agent.unified_lookahead import Limits,Resources,State,Observation,Terminal,choose,run_online
from xgap.experiments.unified_contract import configuration,load_configuration
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.runtime.contracts import RuntimeNodeKind as R


def settings(**policy):
    return UnifiedSettings(limits=Limits(depth=2,optional_ms=3000,aggregation='expectation'),
        live_probe_policy=LiveProbePolicy('frozen-test-policy','Explicit uniform prior; portable test, not fitted',**policy))


def test_new_policy_is_opt_in_roundtrips_and_legacy_configs_are_unchanged(tmp_path):
    raw=configuration(settings=settings())
    assert raw['schema_version']=='xgap-unified-run-config-v3'
    p=tmp_path/'config.json';p.write_text(json.dumps(raw))
    _,_,loaded,_=load_configuration(p,hashlib.sha256(p.read_bytes()).hexdigest())
    assert loaded==settings()
    old=configuration()
    assert old['schema_version']=='xgap-unified-run-config-v2' and 'live_probe_policy' not in old['settings']
    with pytest.raises(ValueError,match='explicit expectation'):
        UnifiedSettings(live_probe_policy=settings().live_probe_policy)
    with pytest.raises(ValueError,match='no prebound'):
        replace(settings(),candidate_weights=(1,))


def test_actual_family_bindings_and_source_receipts_are_public_bounded_and_real():
    _,options,calls,family,prepare,_=fixture()
    seeds={i:(prepare(c,None),0,Resources()) for i,c in enumerate(family.candidates)}
    bound,receipt=bind_live_probes(settings(max_targets=3),family,seeds,options['sources'])
    assert not calls and len(bound.information_targets)==3
    assert receipt['backend_calls']==receipt['private_inputs_read']==0
    assert receipt['public_family_sha256']==family.identity
    assert bound.candidate_weights==(1.0,)*len(family.candidates)
    assert receipt['omitted_by_capacity']>0
    for target in bound.information_targets:
        label,record=target.invoke(options['backend_clients'],options['sources'])
        assert label=='small' and record['success'] and record['semantic_authority'] is False
        assert record['rows'][0]['value'] is not None
    assert len(calls)==3
    # A different actually proposed candidate order gets newly bound weights and
    # identities, rather than positional weights copied from another proposal.
    changed=replace(family,candidates=tuple(reversed(family.candidates)))
    new_seeds={i:(prepare(c,None),0,Resources()) for i,c in enumerate(changed.candidates)}
    _,new_receipt=bind_live_probes(settings(),changed,new_seeds,options['sources'])
    assert new_receipt['candidate_ids']==list(reversed(receipt['candidate_ids']))


def domain_fixture():
    data,options,calls,family,prepare,execute=fixture()
    i=next(i for i,c in enumerate(family.candidates) if json.loads(c.query_json)==data['query_template'])
    seed=prepare(family.candidates[i],None)
    moves=PhysicalMoves(family,options['source_schema'],options['backends'],options['physical_profile'])
    alternate=next(p for p in moves.neighbors(i,seed) if p.metadata['unified_rewrite']['rule']=='entity_bind')
    modified=next(n for n in alternate.nodes if n.kind is R.REMOTE_BIND_QUERY)
    bound,_=bind_live_probes(settings(max_targets=16,sparse_rows=5,dense_rows=1000,
        row_cost=.01,bind_startup=2,bind_fraction=.01),family,{i:(seed,0,Resources())},options['sources'])
    target=next(t for t in bound.information_targets if t.applies(family.candidates[i].candidate_id,modified))
    bound=replace(bound,information_targets=(target,))
    domain=FamilyDomain('q',UnifiedTerminalContract(family,(),epsilon='1'),
        {i:(seed,0,Resources(remote_calls=16,bytes=None,peak_bytes=None))},JointCostProfile(),
        authority_name='user',authority_version=family.identity,settings=bound)
    key=domain.store(i,alternate)
    state=FamilyState(pools=((i,(domain.seed_keys[i],key)),))
    return data,options,calls,execute,target,domain,state,i


def test_cost_neutral_prior_does_not_reward_probe_without_plan_choice():
    _,_,calls,_,target,domain,_,i=domain_fixture()
    state=FamilyState()
    key=domain.seed_keys[i]
    prior=domain.score(state,key)
    action=next(domain.information_actions(state))
    expected=sum(o.probability*domain.score(o.payload,key) for o in action.outcomes)
    assert expected==pytest.approx(prior)
    assert all(len(domain.terminals(o.payload))==1 for o in action.outcomes)
    selected=choose(State(state),domain,limits=domain.settings.limits)
    assert isinstance(selected['choice'],Terminal) and not calls
    # A fact about this candidate's one operator is not a backend-global signal.
    plan=domain.plans[key][1]
    assert sum(target.applies(domain.contract.family.candidates[i].candidate_id,n) for n in plan.nodes)==1
    assert all(not target.applies('different-candidate',n) for n in plan.nodes)


def test_paid_real_probe_changes_selected_plan_and_np_only_disables_acquisition():
    data,options,calls,execute,target,domain,actual,i=domain_fixture()
    blind=domain.terminals(actual)[0]
    assert blind.payload['plan'].metadata['unified_rewrite']['rule']=='entity_bind'
    actual_box=[actual]
    def perform(action):
        assert action.kind=='probe'
        label,evidence=target.invoke(options['backend_clients'],options['sources'])
        actual_box[0]=next(o.payload for o in action.outcomes if o.label==label)
        return Observation(label,actual_box[0],Resources(remote_calls=1,bytes=None,peak_bytes=None),evidence)
    result=run_online(actual,domain,perform=perform,execute=lambda terminal:execute(terminal.payload['plan']),
                      limits=domain.settings.limits)
    assert result['success'] and result['final_plan_executions']==1
    assert [t['kind'] for t in result['trace']]==['probe']
    assert result['selected_terminal']!=blind.key
    assert result['answer_rows']==data['expected']
    assert result['trace'][0]['declared_action_cost']==target.action_cost
    domain.settings=replace(domain.settings,information_mode='no_probe')
    assert list(domain.information_actions(actual))==[]
    assert domain.terminals(actual)[0]==blind


def test_unknown_probe_preserves_seed_and_does_not_repeat():
    _,_,calls,execute,target,domain,state,_=domain_fixture()
    def unknown(action):
        assert action.kind=='probe'
        return Observation('unknown',state,Resources(remote_calls=1,bytes=None,peak_bytes=None),
            {'success':False,'label':'unknown','semantic_authority':False})
    result=run_online(state,domain,perform=unknown,execute=lambda terminal:execute(terminal.payload['plan']),
                      limits=domain.settings.limits)
    assert result['success'] and result['final_plan_executions']==1
    assert [t['kind'] for t in result['trace']]==['probe']
    assert len(domain.terminals(state))==2


def test_nl_entry_binds_actual_proposals_and_still_executes_once(tmp_path):
    # No controlled/gold family is supplied to the live policy. The authority
    # still independently confirms scope and validates required semantics.
    report,calls=invocation(tmp_path,settings(max_targets=2))
    assert report['success'],report
    bound=report['joint_policy']['live_probe_binding']
    assert len(bound['candidate_ids'])==report['candidate_count']
    assert len(bound['registered_targets'])==2 and bound['private_inputs_read']==0
    assert report['final_plan_executions']==1
    assert report['joint_policy']['external_calls_during_search']==0
    assert len(calls)==report['backend_remote_calls']+report['probe_calls']
