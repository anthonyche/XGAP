"""Aggregation correctness: support denominators, censoring, pairing and identity."""
from copy import deepcopy
import json
import pytest
from xgap.experiments.ch6_aggregate import reduce_cohort
from xgap.experiments.ch6_formal_protocol import METHODS, pin_file


def fixture(tmp_path):
    def save(name, value):
        p=tmp_path/name;p.write_text(json.dumps(value));return pin_file(p)
    dataset=dict(dataset_id='fixture',version='a'*64)
    metadata={c:dict(family_id='family-'+c,question_id=c,stratum='uniform') for c in ('a','b')}
    support=save('support.json',dict(schema_version='xgap-ch6-case-support-v1',method_outputs_used=False,cases=[
        dict(case_id=c,deployment='rdf',source_snapshot_sha256=dataset['version'],methods={m:
             dict(status='unsupported_operator' if c=='b' and m=='TS' else 'supported',
                  basis='before-run operator capability',evidence_pin={'path':'fixture'}) for m in METHODS}) for c in metadata]))
    prepared=save('prepared.json',dict(success=True,dataset=dataset));trials=[]
    for method in METHODS:
        for c in metadata:
            if method=='TS' and c=='b':continue
            failed=method=='NP' and c=='b';censored=method=='GR' and c=='a'
            outcome=save(method+c+'-outcome.json',dict(method=METHODS[method],question_id=c,dataset=dataset,
                track='natural_language',success=not failed and not censored,status='answered' if not failed else 'timeout',
                request_sha256='r'+c,source_observations=dict(requests=4,request_body_bytes=10,request_target_bytes=20,response_body_bytes=30),
                clarification_calls=0,planning_ms=5,failure_scope='study_budget_censoring_not_method_incorrectness' if censored else None))
            score=save(method+c+'-score.json',dict(receipt_sha256=outcome['sha256'],answer_em=0 if failed or censored else 1,
                answer_row_multiset_f1=0 if failed or censored else 1,comparison_error=None))
            timing=save(method+c+'-timing.json',dict(receipt=outcome,total_online_ms=10 if method=='XGAP' else 20))
            terminal=save(method+c+'-terminal.json',dict(cell_id=method+c,outcome=outcome,score=score))
            manifest=save(method+c+'-manifest.json',dict(deployment='rdf',prepared=prepared,cells=[dict(cell_id=method+c,
                method=METHODS[method],request=dict(sha256='r'+c))]))
            trials.append(dict(case_id=c,repeat=0,terminal=terminal,timing=timing,manifest=manifest))
    return dict(schema_version='xgap-ch6-cohort-input-v1',cohort_id='gate',dataset=dataset,support=support,
                case_metadata=metadata,repetitions=1,trials=trials,trace_cost_weights={'backend_http_attempts':1},bootstrap=10)


def test_support_failures_and_censoring_have_distinct_denominators(tmp_path):
    result=reduce_cohort(fixture(tmp_path));m=result['methods']
    assert m['TS']['supported_cases']==1 and m['TS']['support_rate']==.5
    assert m['NP']['metrics']['answer_em']['value']==.5  # timeout remains zero
    assert m['NP']['metrics']['e2e_ms']['scored_requests']==1
    assert m['GR']['metrics']['answer_em']['value']==1
    assert m['GR']['study_censored_requests']==1
    assert result['paired_xgap']['TS']['summary']['value']==2
    assert not result['fully_observed'] and not result['formal_release_admitted']


def test_missing_repeats_and_duplicates_cannot_be_hidden(tmp_path):
    spec=fixture(tmp_path);spec['repetitions']=2
    result=reduce_cohort(spec)
    assert len(result['methods']['XGAP']['missing_requests'])==2
    assert result['methods']['XGAP']['expected_requests']==4
    spec['trials'].append(deepcopy(spec['trials'][0]))
    with pytest.raises(ValueError,match='duplicated'):reduce_cohort(spec)


def test_source_or_stratum_mismatch_rejected(tmp_path):
    spec=fixture(tmp_path);spec['case_metadata']['b']['stratum']='active'
    with pytest.raises(ValueError,match='stratum'):reduce_cohort(spec)
    spec['case_metadata']['b']['stratum']='uniform';spec['dataset']['version']='wrong'
    with pytest.raises(ValueError,match='Dataset'):reduce_cohort(spec)
