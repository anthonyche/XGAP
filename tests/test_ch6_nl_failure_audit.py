import hashlib
import json

import pytest
from audit_ch6_nl_failures import Pins, audit, difference_paths


def test_sealed_failure_audit_uses_pin_mirror_and_never_reports_credentials(tmp_path):
    mirror=tmp_path/'mirror';cell=mirror/'units/u/cells/c';cell.mkdir(parents=True)
    def put(name,value):
        data=json.dumps(value).encode();path=cell/name;path.write_bytes(data)
        return dict(path='/original/units/u/cells/c/'+name,sha256=hashlib.sha256(data).hexdigest())
    secret='b'*64
    core=put('core.json',dict(interpretation=dict(candidates=[dict(candidate_index=0,status='invalid')],
        provenance=dict(compact_lowering=dict(candidates=[dict(candidate_index=0,status='invalid',error='Bearer '+secret)])))))
    trial=put('receipt.json',dict(status='proposal_failed',method='xgap-unified-lookahead',question_id='q',core=core))
    put('terminal.json',dict(cell_id='c',outcome=trial))
    active=mirror/'units/u/cells/active';active.mkdir();(active/'receipt.json').write_text('unsealed garbage')
    result=audit(mirror,tmp_path/'result',mappings=[('/original',mirror)])
    assert result['failure_cells']==1 and result['sealed_statuses']=={'proposal_failed':1}
    assert result['failures_by_stage']=={'compact_lowering':1}
    assert secret not in json.dumps(result)
    assert result['method_results_created']==0 and result['model_calls']==result['backend_calls']==0


def test_mirror_hash_mismatch_rejected_and_ast_differences_expose_paths_only(tmp_path):
    root=tmp_path/'mirror';root.mkdir();(root/'x.json').write_text('{"value":"changed"}')
    with pytest.raises(ValueError,match='changed'):
        Pins([('/original',root)]).read(dict(path='/original/x.json',sha256='a'*64))
    paths=difference_paths({'where':[{'right':{'value':'private-user-intent'}}]},
                           {'where':[{'right':{'value':'public-proposal'}}]})
    assert paths==['/where/0/right/value']
    assert 'private-user-intent' not in json.dumps(paths)


def test_edge_type_domain_replay_is_opt_in_and_preserves_recorded_failure(tmp_path):
    from copy import deepcopy
    from xgap.experiments.ch6_d4_recipe import queries
    mirror=tmp_path/'mirror';cell=mirror/'units/u/cells/q-XGAP';cell.mkdir(parents=True)
    bank=tmp_path/'casebank/q';bank.mkdir(parents=True)
    def put(path,value):
        data=json.dumps(value).encode();path.write_bytes(data)
        original='/original/'+str(path.relative_to(mirror)) if path.is_relative_to(mirror) else str(path)
        return dict(path=original,sha256=hashlib.sha256(data).hexdigest())
    truth=queries()['anchored_edge']
    truth['nodes'].append(dict(var='c',type='Entity',entity=None))
    truth['edges'][0]['type']='LINKS_EARLY'
    truth['edges'].append(dict(var='w',type='LINKS',source='b',target='c'))
    truth['select']['result']['var']='c'
    proposal=deepcopy(truth);proposal['edges'].reverse();proposal['edges'][1]['type']='LINKS_LATE'
    # Use the production serializer so this fixture follows the actual scope schema.
    from xgap.semantic.intent_scope import ScopePolicy, ScopeDomain
    from xgap.agent.intent_certificate import IntentSlot
    scope=ScopePolicy('scope',(ScopeDomain(IntentSlot('relation',('edges',0,'type')),('LINKS_EARLY','LINKS_LATE')),),2,'v2').to_dict()
    op=put(bank/'private-user.json',dict(query=truth));sp=put(bank/'scope.json',scope)
    schema=dict(graph=dict(nodes={'Entity':dict(properties=['id','xgap_id'])},
        edges=[dict(label=l,source='Entity',target='Entity',properties=['id']) for l in ('LINKS','LINKS_EARLY','LINKS_LATE')]),
        shared_identity_namespace='https://xgap.dev/ch6/resource/',identity_property='xgap_id')
    core=put(cell/'core.json',dict(interpretation=dict(request=dict(context=dict(source_schema=schema)),
        provenance=dict(raw_compact_response=dict(candidates=[dict(query=proposal)])))))
    trial=put(cell/'receipt.json',dict(status='intent_outside_proposed_scope',method='xgap-unified-lookahead',question_id='q',
        core=core,oracle_sha256=op['sha256'],scope_sha256=sp['sha256']))
    put(cell/'terminal.json',dict(cell_id='q-XGAP',outcome=trial))
    old=audit(mirror,tmp_path/'old',mappings=[('/original',mirror)],case_banks=[bank.parent])
    new=audit(mirror,tmp_path/'new',mappings=[('/original',mirror)],case_banks=[bank.parent],replay_edge_type_domains=True)
    a,b=old['rows'][0],new['rows'][0]
    assert a['current_scope_covered'] is False and b['current_scope_covered'] is True
    assert a['scope_sha256']==b['scope_sha256']==sp['sha256']
    assert a['effective_scope_policy_sha256']!=b['effective_scope_policy_sha256']
    assert a['scope_adapter'] is None and b['scope_adapter']=='edge-type-domain-v1'
    assert a['recorded_status']==b['recorded_status']=='intent_outside_proposed_scope'
    assert new['recorded_statuses_changed']==new['method_results_created']==0
