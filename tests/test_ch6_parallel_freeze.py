import pytest
from xgap.experiments.ch6_parallel_freeze import Reader, selected_plan, execute_frozen
from xgap.experiments.one_shot_records import write_once


def test_final_plan_is_kept_independent_of_success(tmp_path):
    plan = dict(plan_id='selected', roots=['r'], nodes=[dict(node_id='r',
        kind='remote_query', inputs=[], parameters={}, semantic_operator_ids=[])],
        metadata=dict(source_identities={'s': {'source_id': 's', 'snapshot_version': 'v1'}}))
    core = write_once(tmp_path/'core.json', dict(joint_policy=dict(
        selected_query={'query': 'public'}, execution=dict(physical_plan=plan))))
    pin = write_once(tmp_path/'outcome.json', dict(question_id='q', method='m',
        status='execution_failed', success=False, final_plan_executions=1, core=core))
    outcome, actual, query, status = selected_plan(dict(outcome=pin), Reader(tmp_path), case_id='q', method='m')
    assert status == 'frozen_selected_plan' and not outcome['success']
    assert actual.plan_id == 'selected' and query == {'query': 'public'}
    entry = dict(status=status, levels=[1,2,4,8], selected_plan=write_once(tmp_path/'plan.json',actual.to_dict()),
        selected_query=write_once(tmp_path/'query.json',query), source_identities=plan['metadata']['source_identities'])
    with pytest.raises(ValueError, match='Serving source identities'):
        execute_frozen(entry, None, parallelism=2, source_identities={})


def test_nonanswer_and_missing_artifact_are_explicit(tmp_path):
    reader = Reader(tmp_path)
    for count, expected in ((0,'no_final_plan'), (1,'missing_core_artifact')):
        pin = write_once(tmp_path/f'{count}.json', dict(question_id='q',method='m',final_plan_executions=count))
        assert selected_plan(dict(outcome=pin), reader, case_id='q', method='m')[-1] == expected
    with pytest.raises(ValueError, match='Sealed outcome'):
        selected_plan(dict(outcome=pin), reader, case_id='other', method='m')
