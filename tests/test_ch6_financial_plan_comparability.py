"""Worker-independent pins must not hide different binding-key execution work."""
from copy import deepcopy

import pytest

from xgap.experiments.ch6_financial_plan_comparability import plan_fingerprints


def plan():
    return dict(plan_id='constructed-a', max_parallelism=4, max_remote_calls=160,
        nodes=[dict(node_id='bank16/cq8/native', kind='remote_bind_query',
            inputs=['bank16/cq7/filter'], parameters=dict(backend_id='rdf-16',
                artifact=dict(text='SELECT ?x WHERE { {{XGAP_IRI_VALUES}} ?x ?p ?o }')))],
        roots=['bank16/cq8/native'], metadata=dict(source_identities={'rdf-16': 'snapshot'},
            financial_composition=dict(selected_branch_plans=['construction-a'], proof='same-bank ownership')))


def test_worker_setting_and_construction_labels_preserve_execution_pin_not_audit():
    first=plan(); changed=deepcopy(first)
    changed.update(plan_id='constructed-b', max_parallelism=16)
    changed['metadata']['financial_composition']['selected_branch_plans']=['construction-b']
    a,b=plan_fingerprints(first),plan_fingerprints(changed)
    assert a['plan_audit_sha256'] != b['plan_audit_sha256']
    assert a['execution_plan_sha256'] == b['execution_plan_sha256']
    assert first == plan()  # computing a fingerprint never mutates frozen plans


@pytest.mark.parametrize('change', [
    lambda p: p['nodes'][0].update(inputs=['bank16/cq4/filter']),
    lambda p: p['nodes'][0]['parameters'].update(backend_id='rdf-17'),
    lambda p: p['nodes'][0]['parameters']['artifact'].update(text='SELECT * WHERE {}'),
    lambda p: p['metadata']['source_identities'].update({'rdf-16': 'new-snapshot'}),
    lambda p: p.update(max_remote_calls=32),
    lambda p: p['metadata'].update(new_unknown_execution_flag=True),
])
def test_execution_relevant_and_unknown_changes_are_conservatively_distinct(change):
    first=plan(); changed=deepcopy(first); change(changed)
    assert plan_fingerprints(first)['execution_plan_sha256'] != plan_fingerprints(changed)['execution_plan_sha256']


def test_absent_plan_or_nonfinite_content_cannot_create_a_fingerprint():
    for value in (None, {}, {'nodes': []}):
        with pytest.raises(ValueError):
            plan_fingerprints(value)
    value=plan();value['metadata']['unknown']=float('nan')
    with pytest.raises(ValueError):
        plan_fingerprints(value)
