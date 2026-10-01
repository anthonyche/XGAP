from copy import deepcopy
import pytest

from xgap.experiments.ch6_small_sample import select_cases


def bundle():
    cases = []
    for w in ('W1', 'W2', 'W3', 'W4'):
        for frame in ('uniform', 'active-anchor'):
            for n in range(3):
                cases.append(dict(case_id=f'D1-{frame}-{n}-{w}', workload=w, stratum=frame,
                                  deployment='native', initial_ambiguity={'W1': 0, 'W2': 1, 'W3': 3, 'W4': 3}[w],
                                  contributing_sources=['graph'] if w in ('W1', 'W2') else ['graph', 'control']))
    return dict(dataset='D1', deployment='native', method_outputs_used_for_selection=False, cases=cases)


def test_selection_uses_public_ids_not_input_order_or_results():
    original = bundle()
    selected = select_cases(original)
    changed = deepcopy(original)
    changed['cases'].reverse()
    for c in changed['cases']:
        c['answer_em'] = 0
        c['latency'] = 10000
    assert [c['case_id'] for c in selected] == [c['case_id'] for c in select_cases(changed)]
    assert len(selected) == 8
    assert {(c['workload'], c['stratum']) for c in selected} == {
        (w, f) for w in ('W1', 'W2', 'W3', 'W4') for f in ('uniform', 'active-anchor')}
    assert all(c['exposure'] == 'previously_exposed_authored_small_evaluation' for c in selected)


@pytest.mark.parametrize('mutation', ['missing_frame', 'bad_source', 'ambiguity', 'outcome_selected'])
def test_rejects_scope_or_sampling_mismatch(mutation):
    d = bundle()
    if mutation == 'missing_frame':
        d['cases'] = [c for c in d['cases'] if not (c['workload'] == 'W2' and c['stratum'] == 'uniform')]
    elif mutation == 'bad_source':
        d['cases'][0]['contributing_sources'] = ['graph', 'control']
    elif mutation == 'ambiguity':
        d['cases'][0]['initial_ambiguity'] = 3
    else:
        d['method_outputs_used_for_selection'] = True
    with pytest.raises(ValueError):
        select_cases(d)
