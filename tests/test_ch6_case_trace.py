import pytest
from xgap.experiments.ch6_case_trace import controller_events,author_events


def test_hypothetical_search_does_not_become_real_actions_or_certificates():
    core={'joint_policy':{'trace':[{'action':'ask','kind':'binding','evidence':{'reply':'A'}}],
                         'rounds':[{'records':[{'action':'unexecuted-probe'}]}],
                         'final_plan_executions':0,'terminal_certificate':{'upper_bound':0}}}
    rows=controller_events(core,{'path':'sealed','sha256':'frozen'},'XGAP')
    assert len(rows)==1 and rows[0]['action']=='ask' and rows[0]['rho'] is None
    core['joint_policy'].update(final_plan_executions=1,selected_terminal='Q:P',status='answered')
    rows=controller_events(core,{'path':'sealed','sha256':'frozen'},'XGAP')
    assert rows[-1]['action']=='execute' and rows[-1]['rho']==0


def test_author_actions_never_gain_xgap_certificates():
    raw=[{'questionId':'q','actions':[{'action_name':'execute_sparql','observation':'wrong rows','thought':'unused'}]}]
    rows=author_events(raw,{'path':'sealed','sha256':'frozen'},'q')
    assert rows[0]['rho'] is None and rows[0]['observation']=='wrong rows'
    assert 'thought' not in rows[0]
    with pytest.raises(ValueError):author_events(raw,{},'different question')
