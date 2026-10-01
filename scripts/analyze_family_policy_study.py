#!/usr/bin/env python3
"""Post-seal complete-denominator analysis, with no method execution or fitting."""
import argparse
import csv
import json
from pathlib import Path
from statistics import median,mean

from xgap.agent.intent_certificate import IntentFamily
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def load(pin):return json.loads(read_pinned(pin['path'],pin['sha256']))


def analyze(release_path,release_sha256,run_root,output):
    release=json.loads(read_pinned(release_path,release_sha256));run_root=Path(run_root);root=Path(output);root.mkdir(parents=True,exist_ok=False)
    cases={c['question_id']:c for c in release['cases']};rows=[]
    for cell in release['cells']:
        case=cases[cell['question_id']];path=run_root/'cells'/cell['cell_id'];row={k:cell[k] for k in (
            'cell_id','round','group_index','method_position','label','method','epsilon','question_id','scenario')}
        row.update(reference_rows=case['reference_rows'],status='unrun',guard_status=None,observation_class='unrun',answered=False,answer_em=0,answer_f1=0,
            clarification_calls=None,disclosed_coordinates=None,information_burden=None,source_calls=None,
            response_body_bytes=None,planner_cpu_ms=None,certificate_ms=None,expanded_states=None,
            final_plan_executions=None,model_calls=None,actual_intent_discrepancy=None,answer_jaccard_discrepancy=None,
            online_ms=None,fresh_source_session=None,selected=None)
        if not (path/'terminal.json').exists():
            if path.exists():row.update(status='indeterminate_prior_intent',observation_class='indeterminate')
            rows.append(row);continue
        terminal=json.loads((path/'terminal.json').read_text());trial=load(terminal['outcome']);score=load(terminal['score'])
        core=load(trial['core_result']) if trial.get('core_result') else {}
        search=core.get('search') or {};obs=trial.get('source_observations') or {}
        guard_status=trial.get('guard_status')
        observation_class=('study_censored' if guard_status and guard_status.startswith('study_') else
            'method_observed' if trial['success'] or trial['status']=='no_feasible_strong_policy' else 'unresolved_failure')
        row.update(status=trial['status'],guard_status=guard_status,observation_class=observation_class,
            answered=trial['success'],answer_em=score['answer_em'],answer_f1=score['answer_row_multiset_f1'],
            answer_rows=score['actual_rows'],model_calls=trial.get('model_calls'),source_calls=obs.get('requests'),
            response_body_bytes=obs.get('response_body_bytes'),planner_cpu_ms=core.get('planning_cpu_ms'),
            certificate_ms=core.get('certificate_ms'),expanded_states=search.get('expanded_states'),
            final_plan_executions=core.get('final_plan_executions'),
            fresh_source_session=json.loads((path/'intent.json').read_text())['fresh_source_session'],
            online_ms=json.loads((path/'execution/timing.json').read_text())['total_online_ms'])
        for key in ('clarification_calls','disclosed_coordinates','physical_prepare_attempts','execution_ms'):
            row[key]=core.get(key)
        row['information_burden']=row['clarification_calls'] if case['information']['cost_basis']=='interactions' else row['disclosed_coordinates']
        row['information_unit']=case['information']['cost_basis']
        cert=core.get('terminal_certificate')
        if cert:
            family=IntentFamily.from_dict(load(cell['family'])['family']);names=[c.candidate_id for c in family.candidates]
            distance=family.distances[names.index(cert['candidate_id'])][names.index(case['hidden_truth_for_scoring_only'])]
            row.update(selected=cert['candidate_id'],actual_intent_discrepancy=float(distance) if distance is not None else 'infinity',
                certified_bound=cert['upper_bound']['numerator']/cert['upper_bound']['denominator'])
        if trial['success'] and not score['comparison_error']:
            result=load(trial['result']);reference=load(cell['reference'])
            encode=lambda values:{json.dumps(v,sort_keys=True) for v in values}
            a,e=encode(result['answer']),encode(reference['rows'])
            row['answer_jaccard_discrepancy']=1-len(a&e)/len(a|e) if a|e else 0
        rows.append(row)
    write_once(root/'cells.json',rows)
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (root/'cells.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    summaries=[]
    for scenario in ['all',*release['design']['scenarios']]:
        for label in release['design']['methods']:
            cohort=[r for r in rows if r['round']=='first' and r['label']==label and (scenario=='all' or r['scenario']==scenario)]
            answered=[r for r in cohort if r['answered']]
            observed=[r for r in cohort if r['observation_class']=='method_observed']
            def med(key):
                values=[r[key] for r in answered if isinstance(r.get(key),(int,float))]
                return median(values) if values else None
            summaries.append(dict(scenario=scenario,label=label,questions=len(cohort),answered=len(answered),
                method_observed=len(observed),study_censored=sum(r['observation_class']=='study_censored' for r in cohort),
                unrun=sum(r['observation_class']=='unrun' for r in cohort),
                coverage_observed=len(answered)/len(observed) if observed else None,
                mean_f1_observed=mean(r['answer_f1'] for r in observed) if observed else None,
                correct=sum(r['answer_em'] for r in cohort),coverage=len(answered)/len(cohort),
                mean_f1_all=mean(r['answer_f1'] for r in cohort),mean_f1_answered=mean(r['answer_f1'] for r in answered) if answered else None,
                median_fields_answered=med('disclosed_coordinates'),median_calls_answered=med('clarification_calls'),
                median_source_calls_answered=med('source_calls'),median_response_body_bytes_answered=med('response_body_bytes'),
                median_planner_cpu_ms_answered=med('planner_cpu_ms'),median_online_ms_answered=med('online_ms'),
                # Never add interaction units and disclosed-coordinate units.
                median_information_burden_answered=med('information_burden') if scenario!='all' else None))
    pairs=[]
    for case in release['cases']:
        for suffix in ('025','050'):
            a=next(r for r in rows if r['round']=='first' and r['question_id']==case['question_id'] and r['label']=='search_'+suffix)
            b=next(r for r in rows if r['round']=='first' and r['question_id']==case['question_id'] and r['label']=='fixed_'+suffix)
            paired=a['answered'] and b['answered']
            pairs.append(dict(question_id=case['question_id'],scenario=case['scenario'],epsilon=a['epsilon'],both_answered=paired,
                search_answered=a['answered'],fixed_answered=b['answered'],
                information_delta_search_minus_fixed=a['information_burden']-b['information_burden'] if paired else None,
                f1_delta_search_minus_fixed=a['answer_f1']-b['answer_f1'] if paired else None,
                scope='same declared epsilon and inputs; actual answer quality need not be identical'))
    repeats=[]
    for row in rows:
        if row['round']!='repeat':continue
        first=next(r for r in rows if r['round']=='first' and r['question_id']==row['question_id'] and r['label']==row['label'])
        repeats.append(dict(question_id=row['question_id'],label=row['label'],first_status=first['status'],repeat_status=row['status'],
            first_ms=first['online_ms'],repeat_ms=row['online_ms'],first_fresh=first['fresh_source_session'],repeat_fresh=row['fresh_source_session']))
    closures=[]
    for p in (run_root/'sessions').glob('*/closed.json'):
        c=json.loads(p.read_text());closures.append(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped')))
    session_count=len(list((run_root/'sessions').iterdir()))
    summary=dict(scope=release['design']['scope'],unique_questions=16,first_cells=96,repeat_cells=16,
        statuses={s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})},
        observation_classes={s:sum(r['observation_class']==s for r in rows) for s in sorted({r['observation_class'] for r in rows})},
        total_model_calls=sum(r['model_calls'] or 0 for r in rows),summaries=summaries,pairs=pairs,timing_repeats=repeats,
        sessions=session_count,closed_sessions=len(closures),all_closed=session_count==len(closures) and all(closures),
        denominator_warning='Planned-denominator coverage/F1 include unrun and censored cells and are not method-effect estimates; use matched fully observed cohorts.',
        analysis_scope='descriptive first pass; no significance, population, SOTA or open-NL claim',
        release=dict(path=release_path,sha256=release_sha256))
    write_once(root/'summary.json',summary)
    lines=['# Bounded intent-policy study: first results','',
        'Planned:16 distinct authored tasks on full SF0.1 facts;96 first-pass cells and16 timing repeats. This is not a completion claim.',
        '0 model calls by protocol. Internal simple controls, not SOTA. Conditional finite-family scope.', '',
        '| Method | Observed /16 | Censored | Unrun | Answered / observed | Exact answers / observed |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        if s['scenario']=='all':lines.append(f"| {s['label']} | {s['method_observed']} | {s['study_censored']} | {s['unrun']} | {s['answered']} / {s['method_observed']} | {s['correct']:g} / {s['method_observed']} |")
    lines+=['','Answer coverage and correctness have separate denominators. A non-answer is not an empty answer.',
        'Information burden units differ across scenario groups; the all-group report does not add those units.',
        'Observed denominators can differ: this table is accounting, not a ranking. Compare only matched fully observed questions. Unrun/censoring is not incorrectness.',
        'Timing is descriptive and remains affected by first/subsequent access, recovery and source warm caches.',
        '', 'Statuses: `'+json.dumps(summary['statuses'])+'`. All owned sessions closed: '+str(summary['all_closed'])+'.']
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(statuses=summary['statuses'],summary=str(root/'summary.json'),all_closed=summary['all_closed'])))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release-path',required=True);p.add_argument('--release-sha256',required=True)
    p.add_argument('--run-root',required=True);p.add_argument('--output',required=True)
    analyze(**vars(p.parse_args()))
