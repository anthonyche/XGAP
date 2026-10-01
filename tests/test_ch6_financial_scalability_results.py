"""Integrity checks for summaries of observed attempts; no execution or backends."""
import csv
import json
import math
from pathlib import Path

import pytest

from xgap.experiments.ch6_financial_scalability_results import METHODS, summarize_attempts, write_results
from xgap.experiments.ch6_financial_plan_comparability import SCHEMA as PLAN_SCHEMA


def row(scan='A_endpoints', x=4, repetition=0, latency=10, **updates):
    value = dict(scan_name=scan, x_value=x, method='XGAP', query_id='Q1', repetition=repetition,
        status='answered', request_latency_s=latency, backend_calls=x*5, realized_cost=x*5+1,
        planning_wall_ms=1000, planning_cpu_ms=900, execution_ms=latency*1000-1000 if latency is not None else None,
        peak_rss_mb=500, shards_touched=32, endpoints_actual=x if scan=='A_endpoints' else 32,
        cross_endpoint_edges=100, timestamp='2026-09-29T00:00:00+00:00')
    return {**value, **updates}


def triple(scan='A_endpoints', x=4, latency=10, **updates):
    return [row(scan, x, repetition, latency, **updates) for repetition in range(3)]


def point(result, scan='A_endpoints', x=4, query='Q1', method='XGAP'):
    return next(p for p in result['summary'] if (p['scan_name'],p['x_value'],p['query_id'],p['method'])==(scan,x,query,method))


def test_all_attempts_including_failure_and_deadline_enter_median():
    attempts = [row(latency=10), row(repetition=1, latency=40, status='failed'),
                row(repetition=2, latency=604.5, status='timeout', hard_deadline_observed=True,
                    backend_calls=None, realized_cost=None, peak_rss_mb=None)]
    result = summarize_attempts(attempts, endpoint_levels=(4,32))
    p = point(result)
    assert p['complete'] and p['request_latency_s_median']==40
    assert (p['success_count'],p['failed_count'],p['timeout_count'],p['censored_count'])==(1,1,1,1)
    assert p['backend_calls_valid_n']==2 and p['backend_calls_median'] is None
    assert p['realized_cost_median'] is None and p['peak_rss_mb_median'] is None
    timed = result['raw'][-1]
    assert timed['request_latency_s']==600 and timed['request_latency_observed_s']==604.5
    assert timed['latency_censored']


def test_timeout_is_not_automatically_promoted_to_600_and_missing_raw_stays_missing():
    attempts = [row(status='timeout', latency=60),
                row(repetition=1,status='timeout',latency=None,hard_deadline_observed=True)]
    result = summarize_attempts(attempts, endpoint_levels=(4,))
    assert result['raw'][0]['request_latency_s']==60
    assert result['raw'][1]['request_latency_s']==600 and result['raw'][1]['request_latency_observed_s'] is None
    assert point(result)['request_latency_s_median'] is None
    assert point(result)['missing_repetitions']==[2]


def test_missing_repeat_never_creates_attempt_or_complete_point_metric():
    result = summarize_attempts(triple()[:2], endpoint_levels=(4,32))
    assert len(result['raw'])==2
    assert point(result)['attempts_observed']==2
    assert point(result)['request_latency_s_valid_n']==2
    assert all(point(result)[key] is None for key in point(result) if key.endswith('_median'))
    assert point(result,x=32)['attempts_observed']==0 and not point(result,x=32)['complete']


def test_duplicate_is_rejected_and_matching_A_B_configs_are_distinct_attempts():
    with pytest.raises(ValueError,match='Duplicate'):
        summarize_attempts([row(),row()],endpoint_levels=(4,))
    attempts = triple(x=32)+triple(scan='B_workers',x=4)
    result = summarize_attempts(attempts,endpoint_levels=(32,))
    assert len(result['raw'])==6 and point(result,x=32)['complete']
    assert point(result,scan='B_workers',x=4)['complete']
    assert result['notes']['worker_scan_endpoints']==32


@pytest.mark.parametrize('updates',[
    dict(request_latency_s=float('nan')), dict(realized_cost=float('inf')),
    dict(backend_calls=1.5), dict(peak_rss_mb=-1), dict(repetition=True),
    dict(status='pending'), dict(timestamp=''), dict(hard_deadline_observed=True),
    dict(request_latency_observed_s=11), dict(latency_censored=True),
])
def test_invalid_observations_fail_instead_of_becoming_measurements(updates):
    with pytest.raises(ValueError):
        summarize_attempts([row(**updates)],endpoint_levels=(4,32))


def test_slope_and_ratios_require_complete_matched_uncensored_points():
    attempts = triple(x=4,latency=10)+triple(x=32,latency=40)
    result = summarize_attempts(attempts,endpoint_levels=(4,32))
    slope = next(n for n in result['notes']['endpoint_scaling_4_to_32']
                 if n['query_id']=='Q1' and n['metric']=='request_latency_s')
    assert slope['available'] and slope['ratio_last_over_first']==4
    assert slope['additive_difference']==30 and math.isclose(slope['log_log_slope'],2/3)
    attempts[-1].update(status='timeout',hard_deadline_observed=True,request_latency_s=601)
    result = summarize_attempts(attempts,endpoint_levels=(4,32))
    slope = result['notes']['endpoint_scaling_4_to_32'][0]
    assert not slope['available'] and 'censored' in slope['reason'] and slope['log_log_slope'] is None
    attempts[-1].update(status='answered',hard_deadline_observed=False,request_latency_s=40,endpoints_actual=16)
    result = summarize_attempts(attempts,endpoint_levels=(4,32))
    assert not point(result,x=32)['endpoint_count_match']
    assert result['notes']['endpoint_scaling_4_to_32'][0]['reason']=='actual_endpoint_count_not_confirmed'


def test_worker_scaling_retains_slowdown_and_does_not_invent_saturation():
    attempts = triple('B_workers',1,10)+triple('B_workers',2,5)+triple('B_workers',16,8)
    result = summarize_attempts(attempts,endpoint_levels=(2,4,8,16,32),worker_levels=(1,2,16))
    notes = result['notes']['worker_scaling'][0]
    assert notes['speedup_1_to_16']==1.25 and not notes['saturation_selected']
    assert notes['adjacent_gains'][1]['fractional_latency_gain']==pytest.approx(-.6)
    assert notes['adjacent_gains'][1]['speedup']==.625
    assert point(result,'B_workers',16)['expected_endpoints']==32


def test_phase_fractions_exclude_censored_and_missing_with_explicit_denominators():
    attempts = [row(latency=10,planning_wall_ms=2000,execution_ms=7000),
                row(repetition=1,latency=601,status='timeout',hard_deadline_observed=True),
                row(repetition=2,latency=20,planning_wall_ms=None)]
    result = summarize_attempts(attempts,endpoint_levels=(4,))
    phase = next(p for p in result['notes']['phase_fractions'] if p['scan_name']=='A_endpoints' and p['query_id']=='Q1')
    assert phase['valid_phase_n']==1 and phase['censored_excluded_n']==1 and phase['other_missing_phase_n']==1
    assert phase['measured_request_ms_denominator']==10000
    assert phase['planning_wall_fraction']==.2 and phase['execution_fraction']==.7
    assert phase['ratio_quantiles']['planning_wall_ms']==dict(valid_n=1,p25=.2,p50=.2,p75=.2)
    assert phase['ratio_quantiles']['execution_ms']['valid_n']==2


def test_writes_four_csv_and_notes_preserving_null_and_actual_run_metadata(tmp_path):
    attempts = triple(x=4,backend_calls=None,workers_actual=4,
                      deployment_metadata={'layout':'frozen'},source_commit='observed-commit')
    deployment={'layouts':{'4':{'actual_sources':4,'cross_endpoint_edges':100}},'logical_edges':100000000}
    receipt = write_results(attempts,tmp_path/'results',endpoint_levels=(4,32),deployment_metadata=deployment)
    assert len(receipt['files'])==6 and receipt['model_calls']==receipt['backend_calls']==0
    assert {Path(item['path']).name for item in receipt['files']}=={
        'scalability_A.csv','scalability_B.csv','scalability_A_summary.csv','scalability_B_summary.csv',
        'notes.json','scalability_notes.md'}
    with (tmp_path/'results/scalability_A.csv').open() as handle:
        raw = list(csv.DictReader(handle))
    assert len(raw)==3 and raw[0]['backend_calls']=='' and raw[0]['workers_actual']=='4'
    assert raw[0]['method']=='XGAP'
    assert json.loads(raw[0]['deployment_metadata'])=={'layout':'frozen'}
    with (tmp_path/'results/scalability_B.csv').open() as handle:
        assert list(csv.DictReader(handle))==[]
    notes=json.loads((tmp_path/'results/notes.json').read_text())
    assert notes['deployment_metadata']==deployment
    assert notes['methods']==list(METHODS) and notes['unsupported_methods']['TS']=='unsupported_mixed_native_rdf_deployment'
    markdown=(tmp_path/'results/scalability_notes.md').read_text()
    assert 'TS is unsupported' in markdown and 'p25 / p50 / p75' in markdown
    with pytest.raises(FileExistsError):
        write_results(attempts,tmp_path/'results',endpoint_levels=(4,32))
    with pytest.raises(ValueError,match='No observed attempts'):
        write_results([],tmp_path/'empty',endpoint_levels=(4,32))
    assert not (tmp_path/'empty').exists()


def test_markdown_notes_include_actual_layouts_and_every_failure_diagnostic(tmp_path):
    attempts=[row(method='XGAP',status='failed',error='source | failed\nnext line',error_type='RuntimeError',
        failure_phase='execution',worker_failures=[{'node_id':'scan','error':'source disconnected'}],
        observation_failure_categories={'source_transport':1},guard={'status':'completed','exit_code':2}),
        row(method='NP',status='timeout',latency=601,hard_deadline_observed=True,
            guard={'status':'cleanup_incomplete','decision_status':'request_deadline_exceeded'}),
        row(method='SH',status='failed'),row(method='GR',answer_em=0),row(repetition=1)]
    layouts={2:dict(endpoints_actual=2,neo4j=1,fuseki=1,atoms_per_endpoint=16,
        cross_endpoint_edges=13000000,source_groups=[dict(source_id='neo4j-00',engine='neo4j',atoms=[0,1]),
            dict(source_id='rdf-00',engine='rdf',atoms=[16,17])])}
    write_results(attempts,tmp_path/'results',endpoint_levels=(2,4),deployment_metadata=layouts)
    markdown=(tmp_path/'results/scalability_notes.md').read_text()
    assert '| 2 | 2 | 1 | 1 | 16 | 13000000 |' in markdown
    assert 'neo4j-00 (neo4j): atoms [0, 1]' in markdown and 'rdf-00 (rdf): atoms [16, 17]' in markdown
    assert 'source \\| failed<br>next line' in markdown
    assert 'source_transport' in markdown and 'source disconnected' in markdown
    assert 'hard_request_deadline_seconds' in markdown and 'request_deadline_exceeded' in markdown
    assert 'Reason unavailable in observed attempt' in markdown and 'answer_em' in markdown
    notes=json.loads((tmp_path/'results/notes.json').read_text())
    assert len(notes['failures'])==4
    assert [(item['method'],item['status']) for item in notes['failures']]==[
        ('XGAP','failed'),('NP','timeout'),('SH','failed'),('GR','answered')]
    with (tmp_path/'results/scalability_A.csv').open() as handle:
        assert len(list(csv.DictReader(handle)))==len(attempts)


def test_method_dimension_keeps_outcomes_and_scaling_independent():
    attempts=(triple(x=4,latency=10)+triple(x=32,latency=20)+
        triple(x=4,latency=30,method='NP')+triple(x=32,latency=120,method='NP')+
        triple(x=4,latency=50,method='SH',status='failed')+
        triple(x=4,latency=601,method='GR',status='timeout',hard_deadline_observed=True))
    result=summarize_attempts(attempts,endpoint_levels=(2,4,8,16,32))
    assert result['notes']['total_configured_points']==160
    assert len(result['raw'])==18 and result['notes']['complete_points']==6
    assert point(result,method='XGAP')['request_latency_s_median']==10
    assert point(result,method='NP')['request_latency_s_median']==30
    assert point(result,method='SH')['failed_count']==3
    assert point(result,method='GR')['timeout_count']==3
    assert point(result,method='GR')['request_latency_s_median']==600
    scaling={n['method']:n for n in result['notes']['endpoint_scaling_4_to_32']
        if n['query_id']=='Q1' and n['metric']=='request_latency_s'}
    assert scaling['XGAP']['ratio_last_over_first']==2 and scaling['NP']['ratio_last_over_first']==4
    assert not scaling['SH']['available'] and not scaling['GR']['available']
    assert not any(r['method']=='TS' for r in result['raw']+result['summary'])
    with pytest.raises(ValueError,match='Duplicate'):
        summarize_attempts(attempts+[attempts[0]],endpoint_levels=(2,4,8,16,32))


def test_missing_method_is_never_inferred_and_explicit_single_method_remains_supported():
    absent=row();absent.pop('method')
    with pytest.raises(ValueError,match='explicit configured method'):
        summarize_attempts([absent],endpoint_levels=(4,),methods=('XGAP',))
    for methods in ((),('XGAP','XGAP'),('TS',)):
        with pytest.raises(ValueError,match='Configured methods'):
            summarize_attempts([],endpoint_levels=(4,),methods=methods)
    with pytest.raises(ValueError,match='explicit configured method'):
        summarize_attempts([row(method='NP')],endpoint_levels=(4,),methods=('XGAP',))
    result=summarize_attempts(triple(),endpoint_levels=(4,),methods=('XGAP',))
    assert result['notes']['methods']==['XGAP'] and len(result['summary'])==24


def test_ratio_quantiles_use_per_attempt_fraction_not_ratio_of_metric_quantiles():
    attempts=[row(latency=10,planning_wall_ms=1000,execution_ms=8000),
        row(repetition=1,latency=20,planning_wall_ms=6000,execution_ms=10000),
        row(repetition=2,latency=100,planning_wall_ms=90000,execution_ms=10000)]
    result=summarize_attempts(attempts,endpoint_levels=(4,))
    groups=[n for n in result['notes']['phase_fraction_groups']
        if (n['scan_name'],n['method'],n['query_id'])==('A_endpoints','XGAP','Q1')]
    assert len(groups)==1
    quantiles=groups[0]['ratio_quantiles']
    assert quantiles['planning_wall_ms']['valid_n']==3
    assert quantiles['planning_wall_ms']['p25']==pytest.approx(.2)
    assert quantiles['planning_wall_ms']['p50']==pytest.approx(.3)
    assert quantiles['planning_wall_ms']['p75']==pytest.approx(.6)
    assert quantiles['execution_ms']['p25']==pytest.approx(.3)
    assert quantiles['execution_ms']['p50']==pytest.approx(.5)
    assert quantiles['execution_ms']['p75']==pytest.approx(.65)
    assert groups[0]['planning_wall_fraction']==pytest.approx(97000/130000)


def test_deployment_metadata_never_fills_missing_observations():
    result=summarize_attempts(triple(endpoints_actual=None,cross_endpoint_edges=None),endpoint_levels=(4,),
        deployment_metadata={'actual_endpoints':4,'cross_endpoint_edges':12345})
    assert not point(result)['endpoint_count_match']
    assert point(result)['endpoints_actual_median'] is None
    assert point(result)['cross_endpoint_edges_median'] is None
    with pytest.raises(ValueError):
        summarize_attempts([],endpoint_levels=(4,),deployment_metadata={'edges':float('nan')})


def test_observed_A_plan_variation_preserves_every_attempt_and_numeric_median():
    attempts=triple(selected_dag_sha256='a'*64)
    attempts[2]['selected_dag_sha256']='b'*64
    result=summarize_attempts(attempts,endpoint_levels=(4,))
    p=point(result)
    assert p['request_latency_s_median']==10 and len(result['raw'])==3
    assert p['selected_dag_distinct_count']==2 and p['selected_dag_unknown_count']==0
    assert p['execution_plan_distinct_count']==0 and p['execution_plan_unknown_count']==3
    assert p['plan_variation_observed']
    assert [r['selected_dag_sha256'] for r in result['raw']]==['a'*64,'a'*64,'b'*64]


def test_worker_E2E_configuration_comparison_remains_available_when_plans_differ():
    attempts=triple('B_workers',1,10,execution_plan_sha256='a'*64,
                    execution_plan_fingerprint_schema=PLAN_SCHEMA)
    attempts+=triple('B_workers',16,5,execution_plan_sha256='b'*64,
                     execution_plan_fingerprint_schema=PLAN_SCHEMA)
    result=summarize_attempts(attempts,endpoint_levels=(32,),worker_levels=(1,16))
    note=result['notes']['worker_scaling'][0]
    assert note['comparison_1_to_16']['available'] and note['speedup_1_to_16']==2
    assert note['comparison_scope']=='end_to_end_configuration_effect_with_fresh_planning'
    pure=note['pure_executor_comparison_1_to_16']
    assert not pure['available'] and pure['speedup'] is None
    assert pure['reason']=='execution_plan_varies_across_workers_or_repeats'
    assert not note['adjacent_gains'][0]['pure_executor_comparison']['available']


def test_same_plan_execution_comparison_requires_all_six_known_matching_pins():
    attempts=triple('B_workers',1,10,execution_plan_sha256='a'*64,
                    execution_plan_fingerprint_schema=PLAN_SCHEMA,
                    measurement_provenance={'node':'compt376','job_id':'3930000'})
    attempts+=triple('B_workers',16,5,execution_plan_sha256='a'*64,
                     execution_plan_fingerprint_schema=PLAN_SCHEMA,
                     measurement_provenance={'node':'compt376','job_id':'3930000'})
    def comparison():
        result=summarize_attempts(attempts,endpoint_levels=(32,),worker_levels=(1,16))
        return result['notes']['worker_scaling'][0]['pure_executor_comparison_1_to_16']
    pure=comparison()
    assert pure['available'] and pure['speedup']==2.25  # 9000 / 4000 execution ms
    attempts[4]['execution_plan_sha256']='b'*64
    assert comparison()['reason']=='execution_plan_varies_across_workers_or_repeats'
    attempts[4]['execution_plan_sha256']='a'*64
    attempts[4].pop('execution_plan_fingerprint_schema')
    assert comparison()['reason']=='execution_fingerprint_unavailable'
    attempts[4]['execution_plan_fingerprint_schema']=PLAN_SCHEMA
    attempts[4]['status']='failed'
    assert comparison()['reason']=='failed_execution_not_comparable'


@pytest.mark.parametrize('last_provenance,reason',[
    ({'node':'compt398','job_id':'3917571'},'physical_node_varies_across_workers_or_repeats'),
    ({'node':'compt376','job_id':'3917571'},'allocation_varies_across_workers_or_repeats'),
    ({'job_id':'3930000'},'physical_node_provenance_unavailable'),
    ({'node':'compt376'},'allocation_provenance_unavailable'),
    (None,'physical_node_provenance_unavailable'),
])
def test_executor_attribution_requires_all_six_observed_nodes_and_allocations(last_provenance,reason):
    attempts=triple('B_workers',1,10,execution_plan_sha256='a'*64,
        execution_plan_fingerprint_schema=PLAN_SCHEMA,
        measurement_provenance={'node':'compt376','job_id':'3930000'})
    attempts+=triple('B_workers',16,5,execution_plan_sha256='a'*64,
        execution_plan_fingerprint_schema=PLAN_SCHEMA,
        measurement_provenance={'node':'compt376','job_id':'3930000'})
    # A boundary or missing provenance on even one repeat blocks attribution.
    attempts[-1]['measurement_provenance']=last_provenance
    result=summarize_attempts(attempts,endpoint_levels=(32,),worker_levels=(1,16))
    note=result['notes']['worker_scaling'][0]
    assert note['comparison_1_to_16']['available'] and note['speedup_1_to_16']==2
    assert not note['comparison_1_to_16']['hardware_comparability']['available']
    pure=note['pure_executor_comparison_1_to_16']
    assert pure['reason']==reason and not pure['available'] and pure['speedup'] is None
    assert note['adjacent_gains'][0]['pure_executor_comparison']['reason']==reason
    assert point(result,'B_workers',16)['execution_ms_median']==4000
    assert len(result['raw'])==6
    assert result['raw'][-1]['measurement_provenance']==last_provenance


def test_hardware_boundary_preserves_endpoint_medians_and_exports_provenance(tmp_path):
    attempts=triple(x=4,latency=10,measurement_provenance={'node':'compt376','job_id':'3930000'})
    attempts+=triple(x=32,latency=40,measurement_provenance={'node':'compt398','job_id':'3917571'})
    result=summarize_attempts(attempts,endpoint_levels=(4,32))
    comparison=result['notes']['endpoint_scaling_4_to_32'][0]
    assert comparison['available'] and comparison['ratio_last_over_first']==4
    hardware=comparison['hardware_comparability']
    assert hardware['physical_node_changed'] and hardware['allocation_changed']
    assert hardware['observed_nodes']==['compt376','compt398']
    assert hardware['node_unknown_count']==hardware['allocation_unknown_count']==0
    assert not hardware['available']
    assert point(result,x=32)['request_latency_s_median']==40
    write_results(attempts,tmp_path/'hardware',endpoint_levels=(4,32))
    with (tmp_path/'hardware/scalability_A_summary.csv').open() as stream:
        summaries=list(csv.DictReader(stream))
    p=next(r for r in summaries if r['x_value']=='32' and r['method']=='XGAP' and r['query_id']=='Q1')
    assert json.loads(p['observed_nodes'])==['compt398']
    assert json.loads(p['observed_job_ids'])==['3917571']
    markdown=(tmp_path/'hardware/scalability_notes.md').read_text()
    assert 'compt376' in markdown and 'compt398' in markdown
    assert 'icosa256gb scheduler feature does not establish an identical CPU model' in markdown


def test_legacy_endpoint_data_with_unknown_hardware_remains_observed_not_dropped():
    result=summarize_attempts(triple(x=4)+triple(x=32,latency=40),endpoint_levels=(4,32))
    comparison=result['notes']['endpoint_scaling_4_to_32'][0]
    assert comparison['available'] and comparison['ratio_last_over_first']==4
    assert comparison['hardware_comparability']['reason']=='physical_node_provenance_unavailable'
    assert comparison['hardware_comparability']['node_unknown_count']==6
    assert point(result,x=32)['request_latency_s_median']==40


def test_legacy_selected_dag_hash_is_never_assumed_to_be_an_execution_fingerprint():
    attempts=triple('B_workers',1,10,selected_dag_sha256='a'*64)
    attempts+=triple('B_workers',16,5,selected_dag_sha256='a'*64)
    result=summarize_attempts(attempts,endpoint_levels=(32,),worker_levels=(1,16))
    pure=result['notes']['worker_scaling'][0]['pure_executor_comparison_1_to_16']
    assert pure['reason']=='execution_fingerprint_unavailable'
    assert result['notes']['worker_scaling'][0]['speedup_1_to_16']==2


def test_fast_failed_request_remains_in_median_but_cannot_support_latency_speedup():
    attempts=triple('B_workers',1,10)+triple('B_workers',16,1,status='failed')
    result=summarize_attempts(attempts,endpoint_levels=(32,),worker_levels=(1,16))
    assert point(result,'B_workers',16)['request_latency_s_median']==1
    comparison=result['notes']['worker_scaling'][0]
    assert comparison['speedup_1_to_16'] is None
    assert comparison['comparison_1_to_16']['reason']=='failed_request_not_a_successful_latency_comparison'
    a=triple(x=4,latency=10)+triple(x=32,latency=1,status='failed')
    notes=summarize_attempts(a,endpoint_levels=(4,32))['notes']['endpoint_scaling_4_to_32']
    assert not notes[0]['available']
    assert notes[1]['available']  # observed calls remain an independent cost metric
