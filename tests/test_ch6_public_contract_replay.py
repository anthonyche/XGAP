from copy import deepcopy
import json

import pytest

from audit_ch6_public_contract_replay import replay_entry
from test_compact_constraints import constraints, query
from xgap.agent.intent_certificate import fingerprint
from xgap.semantic.compact_constraints import PublicCompactConstraints
from xgap.semantic.intent_scope import ScopePolicy


def inputs():
    contract, schema = constraints()
    schema['shared_identity_namespace'] = 'https://public.example/entity/'
    schema['graph']['edges'][0].update(source='Account', target='Account')
    doc = contract.to_dict(); doc['source_schema_sha256'] = fingerprint(schema)
    contract = PublicCompactConstraints.from_dict(doc).validate_source_schema(schema)
    truth = query(); raw = deepcopy(truth)
    raw['where'][1]['left']['property'] = raw['where'][1]['right']['property'] = 'xgap_id'
    raw['select']['total'] = dict(aggregate='count', field=dict(var='e', property='id'), distinct=True)
    core = dict(interpretation=dict(request=dict(context=dict(source_schema=schema)),
        provenance=dict(raw_compact_response=dict(candidates=[dict(query=raw)]))))
    return core, ScopePolicy('public-family', (), language_version='v2').to_dict(), dict(query=truth, language_version='v2'), contract


def test_replay_checks_public_proof_without_revising_history_or_emitting_private_values():
    core, scope, private, contract = inputs(); original = deepcopy((core, scope, private))
    result = replay_entry(core, scope, private, contract)
    assert result['current_scope_covered'] and not result['scope_covered_without_public_constraints']
    assert result['replay_status'] == 'scope_covered'
    assert (core, scope, private) == original
    assert 'account:1' not in json.dumps(result) and 'query' not in result


def test_replay_never_uses_private_intent_to_fix_malformed_model_declarations():
    core, scope, private, contract = inputs()
    raw = core['interpretation']['provenance']['raw_compact_response']['candidates'][0]['query']
    raw['nodes'].append(dict(var='e', type='TRANSFERRED_TO', entity=None))
    result = replay_entry(core, scope, private, contract)
    assert result['replay_status'] == 'proposal_still_rejected'
    assert not result['current_scope_covered'] and result['proposals_lowered'] == 0


def test_replay_declines_unrelated_public_schema_even_if_private_query_matches():
    core, scope, private, contract = inputs()
    core['interpretation']['request']['context']['source_schema']['shared_identity_namespace'] = 'https://different.example/'
    with pytest.raises(ValueError, match='different source schema'):
        replay_entry(core, scope, private, contract)
