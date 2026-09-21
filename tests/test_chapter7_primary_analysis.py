"""Primary reporting: no frame pooling, survivor speedups, or false precision."""
from analyze_chapter7_primary import summarize, estimate, binary_estimate
from xgap.experiments.bounded_joint_contract import METHODS
from xgap.experiments.chapter7_finbench_strata import STRATA


def row(stratum,question,method,*,duration=10,answered=True,sealed=True,correct=None):
    return dict(stratum=stratum,question_id=question,family_group_id=stratum+question,track='nl',
        method=method,sealed=sealed,answered=answered if sealed else None,
        correct=(answered if correct is None else correct) if sealed else None,
        status='answered' if answered and sealed else 'timeout' if sealed else 'unattempted',
        expected_rows=1 if sealed else None,query_loss=0 if answered and sealed else None,
        certificate_violation=False,total_online_ms=duration,backend_response_bytes=100,
        answer_f1=float(answered) if sealed else None,planning_ms=1,execution_ms=8,
        clarification_calls=1,model_calls=1,input_tokens=10,output_tokens=3)


def test_frames_stay_separate_even_when_method_effects_reverse():
    rows=[row(s,str(q),m,duration=(10 if m==METHODS[0] else 20) if s==STRATA[0] else
        (60 if m==METHODS[0] else 30)) for s in STRATA for q in range(2) for m in METHODS]
    summaries,pairs,differences=summarize(rows)
    assert len(summaries)==4 and len(pairs)==4
    assert differences[STRATA[0]]['mean']==10
    assert differences[STRATA[1]]['mean']==-30
    assert all(s['planned']==2 and s['common_completion_cases']==2 for s in summaries)


def test_failed_exact_request_keeps_quality_denominator_and_excludes_both_latencies():
    rows=[row(s,str(q),m,duration=10 if q==0 else 100,
        answered=not(s==STRATA[0] and q==1 and m==METHODS[0]))
        for s in STRATA for q in range(2) for m in METHODS]
    summaries,pairs,_=summarize(rows)
    exact=next(s for s in summaries if s['stratum']==STRATA[0] and s['method']==METHODS[0])
    performance=next(s for s in summaries if s['stratum']==STRATA[0] and s['method']==METHODS[1])
    assert exact['correct_completion']['mean']==.5 and exact['coverage']['mean']==.5
    assert exact['planned']==2 and performance['latency_ms']['mean']==10
    assert performance['coverage']['mean']==1 and len(pairs)==3


def test_unattempted_request_cannot_produce_a_full_quality_estimate():
    rows=[row(s,str(q),m,sealed=not(s==STRATA[0] and q==1 and m==METHODS[0]))
        for s in STRATA for q in range(2) for m in METHODS]
    summaries,_,_=summarize(rows)
    exact=next(s for s in summaries if s['stratum']==STRATA[0] and s['method']==METHODS[0])
    assert not exact['full_denominator_available']
    assert exact['correct_completion']['mean'] is None and exact['latency_ms']['mean'] is None
    assert exact['status_counts']['unattempted']==1


def test_perfect_finite_quality_is_not_reported_with_zero_uncertainty():
    rows=[dict(family_group_id=str(i),correct=True) for i in range(24)]
    estimate=binary_estimate(rows,'correct',seed='fixed')
    assert estimate['mean']==1 and .8<estimate['ci95'][0]<.9
    assert .999999<estimate['ci95'][1]<=1
    assert estimate['families']==24 and estimate['interval'].startswith('wilson_')


def test_repeated_family_is_one_resampling_unit_and_unknown_cost_stays_unknown():
    rows=[dict(family_group_id='a',cost=10),dict(family_group_id='a',cost=10),
          dict(family_group_id='b',cost=20)]
    result=estimate(rows,'cost',seed='fixed',replicates=200)
    assert result['records']==3 and result['families']==2
    assert result['mean']==40/3 and result['ci95']==[10,20]
    rows[0]['cost']=None
    assert estimate(rows,'cost',seed='fixed')['mean'] is None
