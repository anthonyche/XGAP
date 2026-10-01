"""The paid authority and post-seal loss use one source-proved equality contract."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_compact_constraints import constraints, query
from xgap.agent.intent_certificate import IntentSlot, fingerprint
from xgap.agent.scope_authority import QueryIntentAuthority, private_query_intent
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.query_loss_score import aligned_query_loss
from xgap.semantic.intent_scope import ScopeDomain, ScopePolicy, construct_scope


QUESTION='Count the primary edge contributions, with a declared window choice.'


def setup(tmp_path):
    truth=query();proposal=deepcopy(truth)
    proposal['select']['total']=dict(aggregate='count',field=dict(var='e',property='id'),distinct=True)
    policy=ScopePolicy('public-test-window',(
        ScopeDomain(IntentSlot('time',('where',2,'op')),('ge','gt')),),language_version='v2')
    draft=construct_scope([proposal],policy,'fixed-public-source')
    pin=write_once(tmp_path/'private.json',private_query_intent(QUESTION,truth,language_version='v2'))
    contract,_=constraints()
    authority=QueryIntentAuthority(Path(pin['path']),pin['sha256'],constraints=contract)
    return truth,draft,authority,contract


def test_proof_is_paid_bound_and_passed_to_scoped_user(tmp_path):
    truth,draft,authority,contract=setup(tmp_path)
    assert not replace(authority,constraints=None).confirm_scope(QUESTION,draft).value['covered']
    reply=authority.confirm_scope(QUESTION,draft)
    assert reply.value['covered'] and reply.value['public_constraints_sha256']==contract.identity
    assert reply.metrics['user_calls']==1 and reply.metrics['disclosed_coordinates']==0
    assert 'query' not in reply.value and 'candidate_id' not in reply.value
    family,user=authority.bind(QUESTION,draft,reply)
    selected=user._load(fingerprint(QUESTION))
    q=json.loads(family.candidates[selected].query_json)
    assert q['select']['total']['distinct'] is True  # Original candidate/physical semantics retained.
    assert aligned_query_loss(q,truth,family.to_dict(),language_version='v2',constraints=contract)==0
    with pytest.raises(ValueError,match='unique representation'):
        aligned_query_loss(q,truth,family.to_dict(),language_version='v2')
    with pytest.raises(ValueError,match='Positive'):
        replace(authority,constraints=None).bind(QUESTION,draft,reply)
    altered=contract.to_dict();altered['contract_id']='other-proof'
    with pytest.raises(ValueError,match='Positive'):
        replace(authority,constraints=type(contract).from_dict(altered)).bind(QUESTION,draft,reply)


def test_equalities_do_not_change_window_or_structure_loss(tmp_path):
    truth,draft,authority,contract=setup(tmp_path)
    reply=authority.confirm_scope(QUESTION,draft)
    family,user=authority.bind(QUESTION,draft,reply)
    index=user._load(fingerprint(QUESTION))
    wrong=json.loads(family.candidates[1-index].query_json)
    assert aligned_query_loss(wrong,truth,family.to_dict(),language_version='v2',constraints=contract)==1
    changed=deepcopy(truth);changed['edges'][0]['source']='c'
    with pytest.raises(ValueError,match='unique representation'):
        aligned_query_loss(wrong,changed,family.to_dict(),language_version='v2',constraints=contract)


def test_unknown_private_file_is_not_read_when_constructing_authority(tmp_path):
    contract,_=constraints()
    authority=QueryIntentAuthority(tmp_path/'absent','a'*64,constraints=contract)
    proposal=query();policy=ScopePolicy('public-only',(),language_version='v2')
    draft=construct_scope([proposal],policy,'public-source')
    reply=authority.confirm_scope(QUESTION,draft)
    assert reply.status.value=='error' and reply.metrics['user_calls']==1
