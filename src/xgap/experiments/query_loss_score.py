"""Independent post-seal structured-query loss; never an answer-error bound."""
from copy import deepcopy
from fractions import Fraction
import json

from xgap.agent.intent_certificate import canonical, fingerprint
from xgap.experiments.evidence_store import read_json_evidence
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def query_loss(selected,truth,slots):
    """Independent implementation of the frozen coordinate/skeleton definition."""
    shells=[deepcopy(q) for q in (selected,truth)];denominator=0;numerator=0
    for slot in slots:
        weight=slot['weight'];values=[]
        if type(weight) is not int or weight<1 or type(slot['hard']) is not bool:raise ValueError('Invalid loss coordinate')
        for shell in shells:
            parent=shell
            for key in slot['path'][:-1]:parent=parent[key]
            values.append(canonical(parent[slot['path'][-1]]))
            parent[slot['path'][-1]]={'$loss_coordinate':slot['name']}
        if slot['hard'] and values[0]!=values[1]:return None
        if not slot['hard']:
            denominator+=weight
            if values[0]!=values[1]:numerator+=weight
    if canonical(shells[0])!=canonical(shells[1]):return None
    return Fraction(numerator,denominator or 1)


def score_query_loss(*,receipt,request,oracle,output):
    trial=json.loads(read_pinned(receipt['path'],receipt['sha256']))
    if (trial.get('schema_version')!='xgap-common-method-trial-v1' or trial.get('request_sha256')!=request['sha256']
            or trial.get('oracle_sha256')!=oracle['sha256']):raise ValueError('Sealed loss input identities differ')
    result=dict(schema_version='xgap-post-seal-query-loss-v1',receipt_sha256=receipt['sha256'],
        oracle_sha256=oracle['sha256'],status='not_executed',loss=None,loss_infinite=False,certificate_violation=None,
        scope='frozen structured query/intent loss; not output semantics or answer F1')
    attempts=trial.get('final_plan_executions')
    if attempts is None:result['status']='execution_count_unknown'
    elif attempts==1:
        try:
            core=read_json_evidence(trial['core']);policy=core.get('joint_policy') or core
            selected=policy['selected_query'];family=core['intent_family'];cert=policy['terminal_certificate']
            public=json.loads(read_pinned(request['path'],request['sha256']))
            private=json.loads(read_pinned(oracle['path'],oracle['sha256']))
            if (private['schema_version']!='xgap-private-query-intent-v1' or
                    private['question_sha256']!=fingerprint(public['question']) or
                    cert['candidate_id'] not in [c['candidate_id'] for c in family['candidates']]):
                raise ValueError('Private question or selected candidate identity differs')
            candidate=next(c for c in family['candidates'] if c['candidate_id']==cert['candidate_id'])
            if canonical(selected)!=candidate['query_json']:raise ValueError('Selected query differs from policy candidate')
            loss=query_loss(selected,private['query'],family['slots'])
            upper=Fraction(cert['upper_bound']['numerator'],cert['upper_bound']['denominator'])
            epsilon=Fraction(cert['epsilon']['numerator'],cert['epsilon']['denominator'])
            result.update(status='measured',loss=float(loss) if loss is not None else None,
                loss_fraction=dict(numerator=loss.numerator,denominator=loss.denominator) if loss is not None else None,
                loss_infinite=loss is None,certificate_upper_bound=float(upper),epsilon=float(epsilon),
                certificate_violation=loss is None or loss>upper or upper>epsilon,
                loss_denominator=sum(s['weight'] for s in family['slots'] if not s['hard']) or 1)
        except (KeyError,ValueError,TypeError,OSError) as error:
            result.update(status='loss_evidence_error',error=str(error))
    elif attempts!=0:raise ValueError('Unexpected final-plan count')
    write_once(output,result)
    return result
