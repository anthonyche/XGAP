#!/usr/bin/env python3
"""Pinned dual-frame primary results, full denominators and family uncertainty.

No model/backend calls. Only sealed outcomes are scored; incomplete releases are
reported but cannot supply a finished quantitative figure. Frames are never pooled.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import random
from statistics import mean

from xgap.experiments.bounded_joint_contract import METHODS
from xgap.experiments.chapter7_finbench_strata import STRATA
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

BOOTSTRAPS=2000
SEED='xgap-ch7-primary-family-bootstrap-v1'
MEASUREMENTS=('controlled_processing_ms','planning_ms','planning_cpu_ms','execution_ms','certificate_ms',
    'physical_prepare_attempts','model_calls','input_tokens','output_tokens','scope_confirmation_calls',
    'clarification_calls','total_user_calls','disclosed_coordinates','backend_calls','probe_calls',
    'final_plan_executions','candidate_count','root_gap')


def read(pin):
    return json.loads(read_pinned(pin['path'],pin['sha256']))


def quantile(values,p):
    values=sorted(values);at=(len(values)-1)*p;left=int(at);fraction=at-left
    return values[left]*(1-fraction)+values[min(left+1,len(values)-1)]*fraction


def estimate(rows,key,*,seed,replicates=BOOTSTRAPS):
    """Resample whole family clusters, retaining all their request records."""
    if not rows or any(r.get(key) is None for r in rows):
        return dict(mean=None,ci95=None,records=len(rows),families=0,interval='unavailable')
    groups=defaultdict(list)
    for row in rows:groups[row['family_group_id']].append(float(row[key]))
    totals=[(sum(v),len(v)) for _,v in sorted(groups.items())]
    point=mean(float(r[key]) for r in rows)
    if len(totals)<2:
        return dict(mean=point,ci95=None,records=len(rows),families=len(totals),interval='insufficient_families')
    rng=random.Random(seed);draws=[]
    for _ in range(replicates):
        drawn=[totals[rng.randrange(len(totals))] for _ in totals]
        draws.append(sum(x[0] for x in drawn)/sum(x[1] for x in drawn))
    return dict(mean=point,ci95=[quantile(draws,.025),quantile(draws,.975)],records=len(rows),
        families=len(totals),interval='family_cluster_percentile_bootstrap',replicates=replicates)


def binary_estimate(rows,key,*,seed):
    """Wilson for this release's one Bernoulli observation per anchor family.

    A future repeated-family release uses cluster resampling, explicitly labelled.
    Do not report a degenerate [1,1] bootstrap interval for 24/24 independent cases.
    """
    if not rows or any(r.get(key) is None for r in rows):return estimate(rows,key,seed=seed)
    if len({r['family_group_id'] for r in rows})!=len(rows):return estimate(rows,key,seed=seed)
    n=len(rows);p=mean(bool(r[key]) for r in rows);z=1.959963984540054;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return dict(mean=p,ci95=[max(0.,center-radius),min(1.,center+radius)],records=n,families=n,
        interval='wilson_one_observation_per_independent_family')


def collect(release,run):
    batch=read(release['batch']);run=Path(run)
    identity=json.loads((run/'identity.json').read_text())['identity']
    if identity!={'manifest_sha256':release['batch']['sha256'],'source_commit':release['source_commit']}:
        raise ValueError('Run and frozen release identities differ')
    cases={c['question_id']:c for c in release['cases']};rows=[];evidence=[]
    if len(cases)!=release['base_case_records']:raise ValueError('Duplicate/missing case identity')
    for cell in batch['cells']:
        request=read(cell['request']);case=cases[request['question_id']]
        if any(cell[k]!=case[k] for k in ('request','scope','oracle','reference','config')):
            raise ValueError('Cell pins differ from the published case')
        path=run/'cells'/cell['cell_id']
        row=dict(cell_id=cell['cell_id'],question_id=request['question_id'],family_group_id=case['family_group_id'],
            template_family_id=case['template_family_id'],stratum=case['stratum'],track=case['track'],
            method=cell['method'],status='incomplete_attempt' if path.exists() else 'unattempted',
            attempted=path.exists(),sealed=False,answered=None,correct=None,answer_f1=None,
            total_online_ms=None,backend_response_bytes=None,expanded_states=None,
            expected_rows=None,actual_rows=None,query_loss=None,certificate_violation=None,
            worker_peak_rss_bytes=None,source_peak_rss_bytes=None,token_usage_known=None,
            **{k:None for k in MEASUREMENTS})
        terminal=path/'terminal.json'
        if terminal.exists():
            terminal_pin=file_pin(terminal);saved=read(terminal_pin);trial=read(saved['outcome']);score=read(saved['score'])
            if (saved['cell_id']!=cell['cell_id'] or trial['method']!=cell['method'] or
                trial['question_id']!=request['question_id'] or trial['dataset']!=release['dataset'] or
                score['question_id']!=request['question_id'] or score['method']!=cell['method'] or
                trial['request_sha256']!=cell['request']['sha256'] or
                trial['scope_sha256']!=cell['scope']['sha256'] or trial['oracle_sha256']!=cell['oracle']['sha256'] or
                trial['joint_config_sha256']!=cell['config']['sha256'] or
                score['receipt_sha256']!=saved['outcome']['sha256'] or
                score['reference_sha256']!=cell['reference']['sha256']):
                raise ValueError('Sealed outcome or score belongs to a different configuration')
            timing_pin=file_pin(path/'execution/timing.json');timing=read(timing_pin)
            if timing['receipt']!=saved['outcome']:raise ValueError('Timing identity differs')
            answered=trial['success'] and trial.get('final_plan_executions')==1
            row.update(status=trial['status'],attempted=True,sealed=True,answered=answered,
                correct=answered and score['answer_em']==1,answer_f1=score['answer_row_multiset_f1'] if answered else 0,
                total_online_ms=timing['total_online_ms'],expected_rows=score['expected_rows'],actual_rows=score['actual_rows'],
                expanded_states=(trial.get('search') or {}).get('expanded_states'),
                backend_response_bytes=(trial.get('source_observations') or {}).get('response_body_bytes'),
                **{k:trial.get(k) for k in MEASUREMENTS})
            peak=(trial.get('resources') or {}).get('sampled_peak_rss_bytes') or {}
            row.update(worker_peak_rss_bytes=peak.get('method'),source_peak_rss_bytes=peak.get('source'))
            row['token_usage_known']=(row['model_calls']==0 or (row['input_tokens'] is not None and
                row['output_tokens'] is not None and row['input_tokens']+row['output_tokens']>0))
            if not row['token_usage_known']:row.update(input_tokens=None,output_tokens=None)
            if saved.get('query_loss'):
                loss=read(saved['query_loss'])
                if loss['receipt_sha256']!=saved['outcome']['sha256'] or loss['oracle_sha256']!=cell['oracle']['sha256']:
                    raise ValueError('Independent loss identity differs')
                row.update(query_loss=loss['loss'],certificate_violation=loss['certificate_violation'])
            elif answered:raise ValueError('Answered formal cell lacks independent query-loss check')
            evidence.append(dict(terminal=terminal_pin,outcome=saved['outcome'],score=saved['score'],
                timing=timing_pin,query_loss=saved.get('query_loss')))
        rows.append(row)
    return rows,evidence


def summarize(rows):
    summaries=[];pairs=[]
    if set(r['stratum'] for r in rows)!=set(STRATA):raise ValueError('Both formal frames required')
    for stratum in STRATA:
        group=[r for r in rows if r['stratum']==stratum]
        if any(r['track']!='nl' for r in group):raise ValueError('Primary release is NL only')
        if set(r['method'] for r in group)!=set(METHODS):raise ValueError('Both frozen methods required')
        counts=Counter((r['question_id'],r['method']) for r in group)
        if any(n!=1 for n in counts.values()):raise ValueError('This primary release has one repetition')
        planned={m:{r['question_id'] for r in group if r['method']==m} for m in METHODS}
        if planned[METHODS[0]]!=planned[METHODS[1]]:raise ValueError('Unpaired published requests')
        common=set.intersection(*({r['question_id'] for r in group if r['method']==m and r['answered']} for m in METHODS))
        for method in METHODS:
            subset=[r for r in group if r['method']==method];sealed=[r for r in subset if r['sealed']]
            full=len(sealed)==len(subset);cohort=[r for r in subset if r['question_id'] in common]
            seed=SEED+':'+stratum  # Same family resamples for both methods.
            def measured(key,*,cohort_only=False,binary=False):
                data=cohort if cohort_only else subset
                if not full:return dict(mean=None,ci95=None,records=len(data),families=0,interval='incomplete_release')
                return (binary_estimate if binary else estimate)(data,key,seed=seed)
            losses=[r['query_loss'] for r in sealed if r['query_loss'] is not None]
            refs=[r['expected_rows'] for r in sealed if r['expected_rows'] is not None]
            summaries.append(dict(stratum=stratum,method=method,planned=len(subset),sealed=len(sealed),
                answered=sum(r['answered'] for r in sealed),correct=sum(r['correct'] for r in sealed),
                status_counts=dict(Counter(r['status'] for r in subset)),
                common_completion_cases=len(common),empty_references=sum(n==0 for n in refs),
                reference_denominator=len(refs),nonempty_correct=sum(r['correct'] for r in sealed if r['expected_rows']),
                latency_ms=measured('total_online_ms',cohort_only=True),
                backend_response_bytes=measured('backend_response_bytes'),
                correct_completion=measured('correct',binary=True),coverage=measured('answered',binary=True),
                answer_f1=measured('answer_f1'),planning_ms=measured('planning_ms',cohort_only=True),
                execution_ms=measured('execution_ms',cohort_only=True),
                clarification_calls=measured('clarification_calls'),model_calls=measured('model_calls'),
                input_tokens=measured('input_tokens'),output_tokens=measured('output_tokens'),
                maximum_measured_loss=max(losses) if losses else None,measured_loss_cases=len(losses),
                certificate_violations=sum(r['certificate_violation'] is True for r in sealed),
                full_denominator_available=full))
        for qid in sorted(common):
            a,b=(next(r for r in group if r['question_id']==qid and r['method']==m) for m in METHODS)
            if a['family_group_id']!=b['family_group_id']:raise ValueError('Paired family identity differs')
            pairs.append(dict(stratum=stratum,question_id=qid,family_group_id=a['family_group_id'],
                exact_ms=a['total_online_ms'],performance_ms=b['total_online_ms'],
                performance_minus_exact_ms=b['total_online_ms']-a['total_online_ms']))
    differences={s:estimate([p for p in pairs if p['stratum']==s],'performance_minus_exact_ms',seed=SEED+':'+s)
                 for s in STRATA}
    return summaries,pairs,differences


def analyze(*,release_path,release_sha256,run,output):
    release_pin=dict(path=str(Path(release_path).resolve()),sha256=release_sha256);release=read(release_pin)
    if release.get('schema_version')!='xgap-ch7-finbench-formal-v1' or release.get('repetitions')!=1:
        raise ValueError('Expected frozen one-repetition formal primary release')
    run=Path(run).resolve();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    rows,evidence=collect(release,run);summaries,pairs,differences=summarize(rows)
    with (root/'metrics.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    invocations=[]
    for folder in sorted((run/'invocations').iterdir()):
        pin=file_pin(folder/'receipt.json') if (folder/'receipt.json').exists() else None
        invocations.append(dict(receipt=pin,closed=read(pin)['all_owned_closed'] if pin else False))
    complete=bool(invocations) and all(i['closed'] for i in invocations) and all(r['sealed'] for r in rows)
    summary=dict(schema_version='xgap-ch7-primary-analysis-v1',release=release_pin,
        dataset=release['dataset'],deployment='native_neo4j_fuseki',primary_batch_complete=complete,
        formal_result=True,full_chapter7_complete=False,source_commit=release['source_commit'],
        analysis_code=file_pin(__file__),bootstrap_seed=SEED,bootstrap_replicates=BOOTSTRAPS,
        metrics=file_pin(root/'metrics.csv'),summaries=summaries,paired_latency_differences=differences,
        paired_observations=pairs,raw_evidence=evidence,invocations=invocations,
        missing=['Freebase/FedShop primary panels','matched RDF external method comparison','E3-E6/E9-E20'],
        interpretation='Separate predeclared sampling populations; no answer-error bound or unseen-template generalization claim')
    pin=write_once(root/'summary.json',summary)
    lines=['# FinBench 正式主比较：双取样框','',f'完整封存并关闭：{complete}。三数据集/E1–E20 全目标完成：否。','',
        '|分层|方法|封存/计划|正确|回答|空参考|共同完成耗时均值(s)|每题澄清|',
        '|---|---|---|---|---|---|---|---|']
    for s in summaries:
        latency=s['latency_ms']['mean'];calls=s['clarification_calls']['mean']
        seconds=f'{latency/1000:.3f}' if latency is not None else '缺失'
        lines.append(f"|{s['stratum']}|{s['method'].rsplit('-',1)[-1]}|{s['sealed']}/{s['planned']}|{s['correct']}|{s['answered']}|{s['empty_references']}/{s['reference_denominator']}|{seconds}|{calls}|")
    lines+=['','延迟区间按 family 重采样；二元质量在每 family 一次观测时用 Wilson 95% 区间。',
        '未执行/未封存不记零；失败/非回答保留全部请求分母。耗时仅取共同完成集合，错误回答仍保留并在质量列显示。',
        'query loss 为结构意图差异，不能替代答案误差。两个抽样框不混合；不将未完成外部比较视为外部方法的零分。']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(summary=pin,primary_batch_complete=complete)))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('release-path','release-sha256','run','output'):p.add_argument('--'+name,required=True)
    analyze(**vars(p.parse_args()))
