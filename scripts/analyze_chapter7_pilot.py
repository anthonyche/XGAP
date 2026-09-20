#!/usr/bin/env python3
"""Sealed pilot tables; no models/backends, no formal-result or speedup claim."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from statistics import mean, stdev

from xgap.experiments.evidence_store import file_pin
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def read(pin):return json.loads(read_pinned(pin['path'],pin['sha256']))


def observed_mean(values):
    return mean(values) if values and all(v is not None for v in values) else None


def analyze(*,release_path,release_sha256,run,output):
    release_pin=dict(path=release_path,sha256=release_sha256);release=read(release_pin)
    if release['schema_version']!='xgap-ch7-finbench-pilot-v1':raise ValueError('Expected frozen pilot release')
    batch=read(release['batch']);run=Path(run).resolve();root=Path(output).resolve()
    root.mkdir(parents=True,exist_ok=False)
    identity=json.loads((run/'identity.json').read_text())['identity']
    if identity!={'manifest_sha256':release['batch']['sha256'],'source_commit':release['source_commit']}:
        raise ValueError('Run and release identities differ')
    cases={c['question_id']:c for c in release['cases']};rows=[];evidence=[]
    for cell in batch['cells']:
        request=read(cell['request']);case=cases[request['question_id']];path=run/'cells'/cell['cell_id']
        row=dict(cell_id=cell['cell_id'],question_id=request['question_id'],family_group_id=case['family_group_id'],
            template_family_id=case['template_family_id'],candidate_family_id=case['candidate_family_id'],
            track=case['track'],method=cell['method'],status='unattempted',attempted=False,sealed=False,
            answered=None,correct=None,answer_f1=None,total_online_ms=None,controlled_processing_ms=None,
            planning_ms=None,planning_cpu_ms=None,execution_ms=None,certificate_ms=None,expanded_states=None,
            model_calls=None,input_tokens=None,output_tokens=None,clarification_calls=None,disclosed_coordinates=None,
            token_usage_known=None,
            backend_calls=None,backend_response_bytes=None,final_plan_executions=None,
            expected_rows=None,actual_rows=None,worker_peak_rss_bytes=None,source_peak_rss_bytes=None,
            query_loss=None,query_loss_status=None,certificate_violation=None)
        if path.exists():row.update(status='incomplete_attempt',attempted=True)
        terminal=path/'terminal.json'
        if terminal.exists():
            terminal_pin=file_pin(terminal);saved=read(terminal_pin);trial=read(saved['outcome']);score=read(saved['score'])
            if (saved['cell_id']!=cell['cell_id'] or trial['request_sha256']!=cell['request']['sha256'] or
                    score['receipt_sha256']!=saved['outcome']['sha256'] or score['reference_sha256']!=cell['reference']['sha256']):
                raise ValueError('Cell identity differs from frozen design')
            timing_pin=file_pin(path/'execution/timing.json');timing=read(timing_pin)
            if timing['receipt']!=saved['outcome']:raise ValueError('Timing refers to a different sealed outcome')
            answered=trial['success'] and trial.get('final_plan_executions')==1
            row.update(status=trial['status'],attempted=True,sealed=True,answered=answered,
                correct=answered and score['answer_em']==1,answer_f1=score['answer_row_multiset_f1'] if answered else 0,
                total_online_ms=timing['total_online_ms'],
                expected_rows=score['expected_rows'],actual_rows=score['actual_rows'],
                expanded_states=(trial.get('search') or {}).get('expanded_states'),
                backend_response_bytes=(trial.get('source_observations') or {}).get('response_body_bytes'))
            peaks=(trial.get('resources') or {}).get('sampled_peak_rss_bytes') or {}
            row.update(worker_peak_rss_bytes=peaks.get('method'),source_peak_rss_bytes=peaks.get('source'))
            for key in ('controlled_processing_ms','planning_ms','planning_cpu_ms','execution_ms','certificate_ms',
                        'model_calls','input_tokens','output_tokens','clarification_calls','disclosed_coordinates',
                        'backend_calls','final_plan_executions'):
                row[key]=trial.get(key)
            # Timeout receipts retain the provider's historical zero counters,
            # but no response means remote billed usage was not observed.
            row['token_usage_known']=(row['model_calls']==0 or
                (row['input_tokens'] is not None and row['output_tokens'] is not None and
                 row['input_tokens']+row['output_tokens']>0))
            if not row['token_usage_known']:row.update(input_tokens=None,output_tokens=None)
            if saved.get('query_loss'):
                loss=read(saved['query_loss'])
                if loss['receipt_sha256']!=saved['outcome']['sha256'] or loss['oracle_sha256']!=cell['oracle']['sha256']:
                    raise ValueError('Query loss refers to a different sealed outcome')
                row.update(query_loss=loss['loss'],query_loss_status=loss['status'],certificate_violation=loss['certificate_violation'])
            evidence.append(dict(terminal=terminal_pin,outcome=saved['outcome'],score=saved['score'],
                timing=timing_pin,query_loss=saved.get('query_loss')))
        rows.append(row)
    with (root/'metrics.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summaries,pairs=summarize(rows)
    invocations=[]
    for folder in sorted((run/'invocations').iterdir()):
        pin=file_pin(folder/'receipt.json') if (folder/'receipt.json').exists() else None
        invocations.append(dict(path=str(folder),receipt=pin,closed=read(pin)['all_owned_closed'] if pin else False))
    complete=all(r['sealed'] for r in rows) and all(i['closed'] for i in invocations)
    summary=dict(schema_version='xgap-ch7-pilot-analysis-v1',release=release_pin,identity=identity,
        pilot_complete=complete,formal_result=False,status_counts=dict(Counter(r['status'] for r in rows)),
        unique_base_cases=len(cases),independent_templates=len({c['template_family_id'] for c in cases.values()}),
        summaries=summaries,paired_observations=pairs,invocations=invocations,
        raw_evidence=evidence,metrics=file_pin(root/'metrics.csv'),
        interpretation='development pilot only; shared template, no superiority inference; timing uses common completed cohorts')
    pin=write_once(root/'summary.json',summary)
    lines=['# FinBench Chapter 7 development pilot','',f'Complete and closed: {complete}. Formal paper result: false.',
        '24 base cases; 12 live NL and 12 controlled. One shared structural template. No speedup claim.','',
        '|Track|Mode|Sealed/planned|Answered|Correct|Empty references|Common timing cases|Measured max query loss|',
        '|---|---|---|---|---|---|---|---|']
    for s in summaries:lines.append(f"|{s['track']}|{s['method'].rsplit('-',1)[-1]}|{s['sealed']}/{s['planned']}|{s['answered']}|{s['correct']}|{s['empty_reference_cases']}/{s['reference_cases_observed']}|{s['common_completion_cases']}|{s['maximum_measured_loss']}|")
    lines+=['','Missing metrics remain blank/null. Failures remain in full-request quality denominators; unattempted/incomplete cells are separately retained.',
        'NL and controlled timing are separate. Repeats and mode variants do not increase the independent case count.',
        'Empty-reference frequency is reported: passing mostly empty cases is not strong evidence of answer-quality trade-offs.',
        'Inspect paired variance, emptiness, failures, transfer volume and source/worker resource traces before freezing a formal release.']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(summary=pin,pilot_complete=complete,status_counts=summary['status_counts'])))
    return summary


def summarize(rows):
    """Full quality denominators; paired latency only for common completions."""
    summaries=[];pairs=[]
    for track in ('nl','controlled'):
        group=[r for r in rows if r['track']==track]
        if not group:continue
        completed={m:{r['question_id'] for r in group if r['method']==m and r['answered']} for m in {r['method'] for r in group}}
        common=set.intersection(*completed.values())
        for method in sorted(completed):
            subset=[r for r in group if r['method']==method];sealed=[r for r in subset if r['sealed']]
            cohort=[r for r in subset if r['question_id'] in common]
            all_sealed=len(sealed)==len(subset);losses=[r['query_loss'] for r in sealed if r['query_loss'] is not None]
            references=[r['expected_rows'] for r in sealed if r['expected_rows'] is not None]
            nonempty=[r for r in sealed if r['expected_rows'] is not None and r['expected_rows']>0]
            summaries.append(dict(track=track,method=method,planned=len(subset),sealed=len(sealed),
                answered=sum(bool(r['answered']) for r in sealed),correct=sum(bool(r['correct']) for r in sealed),
                full_denominator_available=all_sealed,
                correct_completion_percent=100*mean(r['correct'] for r in subset) if all_sealed else None,
                answer_coverage_percent=100*mean(r['answered'] for r in subset) if all_sealed else None,
                answer_f1_mean_all_requests=mean(r['answer_f1'] for r in subset) if all_sealed else None,
                common_completion_cases=len(common),mean_online_ms_common=observed_mean([r['total_online_ms'] for r in cohort]),
                mean_controlled_ms_common=observed_mean([r['controlled_processing_ms'] for r in cohort]) if track=='controlled' else None,
                mean_clarifications_all=observed_mean([r['clarification_calls'] for r in subset]) if all_sealed else None,
                mean_response_bytes_all=observed_mean([r['backend_response_bytes'] for r in subset]) if all_sealed else None,
                mean_model_calls_all=observed_mean([r['model_calls'] for r in subset]) if all_sealed else None,
                mean_planning_ms_common=observed_mean([r['planning_ms'] for r in cohort]),
                mean_execution_ms_common=observed_mean([r['execution_ms'] for r in cohort]),
                reference_cases_observed=len(references),empty_reference_cases=sum(n==0 for n in references),
                nonempty_reference_cases=len(nonempty),correct_nonempty_reference_cases=sum(bool(r['correct']) for r in nonempty),
                observed_peak_worker_rss_bytes=max((r['worker_peak_rss_bytes'] for r in sealed if r['worker_peak_rss_bytes'] is not None),default=None),
                observed_peak_source_rss_bytes=max((r['source_peak_rss_bytes'] for r in sealed if r['source_peak_rss_bytes'] is not None),default=None),
                measured_loss_count=len(losses),maximum_measured_loss=max(losses) if losses else None,
                certificate_violations=sum(r['certificate_violation'] is True for r in sealed)))
        for qid in sorted(common):
            pair={r['method'].rsplit('-',1)[-1]:r for r in group if r['question_id']==qid}
            metric='total_online_ms' if track=='nl' else 'controlled_processing_ms'
            if all(pair[m][metric] is not None for m in ('exact','performance')):
                pairs.append(dict(track=track,question_id=qid,family_group_id=pair['exact']['family_group_id'],
                    metric=metric,exact=pair['exact'][metric],performance=pair['performance'][metric],
                    performance_minus_exact=pair['performance'][metric]-pair['exact'][metric]))
    for summary in summaries:
        differences=[p['performance_minus_exact'] for p in pairs if p['track']==summary['track']]
        summary['paired_difference_stdev_ms']=stdev(differences) if len(differences)>1 else None
    return summaries,pairs


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('release-path','release-sha256','run','output'):p.add_argument('--'+name,required=True)
    analyze(**vars(p.parse_args()))
