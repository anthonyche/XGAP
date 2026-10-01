"""Post-seal C1/T1 projection. Never confuse hypothetical search with actions."""
from xgap.experiments.ch6_formal_protocol import METHODS,load_pin
from xgap.experiments.evidence_store import read_json_evidence


def controller_events(core,pin,method):
    policy=core.get('joint_policy') or {};events=[]
    for index,step in enumerate(policy.get('trace',[])):
        evidence=step.get('evidence') or {}
        events.append(dict(method=method,round=index,action=step['action'],action_state=step['kind'],
            observation=evidence,preferred_query=None,rho=None,preferred_plan=None,
            evidence_pin=pin,evidence_pointer='/joint_policy/trace/'+str(index),realized=True))
    # Search records and choices alone do not prove that execution happened.
    if policy.get('final_plan_executions')==1:
        certificate=policy.get('terminal_certificate') or {}
        events.append(dict(method=method,round=len(events),action='execute',action_state='execute',
            observation=policy.get('status'),preferred_query=certificate.get('candidate_id'),
            rho=certificate.get('upper_bound'),preferred_plan=policy.get('selected_terminal'),
            evidence_pin=pin,evidence_pointer='/joint_policy',realized=True))
    return events


def author_events(document,pin,question_id):
    if len(document)!=1 or document[0].get('questionId')!=question_id:raise ValueError('Author trace question differs')
    return [dict(method='TS',round=i,action=a['action_name'],action_state=a['action_name'],
                 observation=a.get('observation'),preferred_query=None,rho=None,preferred_plan=None,
                 evidence_pin=pin,evidence_pointer='/0/actions/'+str(i),realized=True)
            for i,a in enumerate(document[0]['actions'])]


def extract(spec):
    if spec.get('schema_version')!='xgap-ch6-case-input-v1' or set(spec['methods'])!=set(METHODS):
        raise ValueError('Five explicitly specified methods required')
    output=dict(schema_version='xgap-ch6-case-trace-v1',question_id=spec['question_id'],methods={},
                scope='Actual controller/author actions only; excludes frontend initialization. Unrecorded intermediate query/rho/plan remain null.')
    request_sha=None
    for method,entry in spec['methods'].items():
        pin=entry.get('outcome')
        if pin is None:
            if entry.get('status') not in ('not_run','unsupported_deployment','unsupported_interface') or not entry.get('reason'):
                raise ValueError('Missing method requires explicit reason')
            output['methods'][method]={**entry,'events':[]};continue
        trial=load_pin(pin)
        if trial['method']!=METHODS[method] or trial['question_id']!=spec['question_id']:
            raise ValueError('Case/method identity mismatch')
        if request_sha is None:request_sha=trial['request_sha256']
        elif request_sha!=trial['request_sha256']:raise ValueError('Methods did not receive the same request')
        events=[];reason=''
        if method=='TS':
            worker=load_pin(trial['worker']) if trial.get('worker') else {}
            author=worker.get('author_output')
            if author:events=author_events(load_pin(author),author,spec['question_id'])
            else:reason='No sealed author action sequence; do not reconstruct it from model proposals or substitute another question.'
        elif trial.get('core'):
            events=controller_events(read_json_evidence(trial['core']),trial['core'],method)
        else:reason='No sealed realized controller trace.'
        output['methods'][method]=dict(status='recorded' if events else 'unavailable',run_status=trial['status'],
            reason=reason,events=events,outcome=pin)
    output['request_sha256']=request_sha
    return output
