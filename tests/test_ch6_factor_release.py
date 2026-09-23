"""Real controlled-state cardinality is required, and factors are not overall n."""
from copy import deepcopy
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,IntentSlot,fingerprint
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.ch6_formal_protocol import METHODS,FIGURES
from xgap.experiments.ch6_release_audit import audit_release
from xgap.experiments.ch6_heldout import template_query
from xgap.experiments.ch6_fact_index import CORES


def test_factor_release_checks_actual_family_and_keeps_overall_denominator(tmp_path):
    def saved(name,doc):
        path=tmp_path/(name+'.json');write(path,doc);return pin(path)
    q=template_query(CORES['D1'],'window_edge','a',1);q2=deepcopy(q);q2['where'][0]['right']['value']='b'
    family=IntentFamily('fixture',(IntentCandidate.create('a',q),IntentCandidate.create('b',q2)),
        (IntentSlot('anchor',('where',0,'right','value')),),'snapshot',language_version='v2')
    question='resolve a or b';state=publish_state(question,family,q,semantic_choices=[dict(name='anchor',type='coordinate',slots=['anchor'])])
    common=dict(scope=saved('scope',{}),oracle=saved('oracle',dict(question_sha256=fingerprint(question))),
        controlled_state=saved('state',state),reference_engine='independent_relational',template_family='test-shape',
        source_snapshot_sha256='snapshot',stratum='uniform')
    def case(cid):return dict(common,case_id=cid,request=saved(cid+'-request',dict(question_id=cid,question=question)),
        reference=saved(cid+'-reference',dict(question_id=cid)))
    primary=dict(case('main'),workload='W1');factor=dict(case('factor'),factor='N',level=2,actual_N=2,actual_u=1)
    overall=saved('overall',dict(schema_version='xgap-ch6-heldout-cases-v1',dataset='D1',split='test',
        method_outputs_used_for_selection=False,template_splits=dict(test=['test-shape'],development=[],pilot=[]),cases=[primary]))
    factors=saved('factors',dict(schema_version='xgap-ch6-factor-inputs-v1',dataset='D1',model_outputs_used=False,cases=[factor]))
    gate=saved('gate',dict(success=True))
    support=saved('support',dict(schema_version='xgap-ch6-case-support-v1',method_outputs_used=False,cases=[
        dict(case_id=cid,deployment='rdf',source_snapshot_sha256='snapshot',methods={m:dict(status='supported',basis='fixture capability',evidence_pin=gate) for m in METHODS}) for cid in ('main','factor')]))
    release=dict(schema_version='xgap-ch6-formal-release-v1',methods=list(METHODS),figures=[f.id for f in FIGURES],
        automatic_retries=0,method_results_read_at_release=0,output_root=str(tmp_path/'future'),
        budget={k:1 for k in ('total_wall_seconds','package_max_bytes','free_disk_reserve_bytes','model_calls_cap','input_tokens_cap','output_tokens_cap','repetitions')},
        case_bundles=[overall],factor_bundles=[factors],support_contract=support,
        sample_counts={d:{w:int(d=='D1' and w=='W1') for w in ('W1','W2','W3','W4')} for d in ('D1','D2','D3')},
        units=[],support_exceptions=[],gates={n:gate for n in ('five_method_gate','factor_gate','scoring_gate')},artifact_pins=[])
    result=audit_release(release,free_bytes=100)
    checked={c['check']:c['passed'] for c in result['checks']}
    assert checked['sample_D1_W1'] and checked['factor_actual_N_u_factor']
    assert not result['success'] # Missing real factor levels, figures and dispatch are never ready.
    factor['actual_N']=1000
    release['factor_bundles']=[saved('tampered-factors',dict(schema_version='xgap-ch6-factor-inputs-v1',dataset='D1',model_outputs_used=False,cases=[factor]))]
    result=audit_release(release,free_bytes=100)
    assert any(c['check']=='factor_actual_N_u_factor' and not c['passed'] for c in result['checks'])
