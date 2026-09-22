"""Read sealed engineering comparisons without executing queries or fitting."""
import argparse
import csv
import json
from pathlib import Path

from xgap.experiments.evidence_store import read_json_evidence,file_pin
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def load(pin):return json.loads(read_pinned(pin['path'],pin['sha256']))


def summarize(parent,followup,output):
    old,new=Path(parent),Path(followup);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    release=json.loads((new/'release.json').read_text())
    if read_pinned(release['parent']['path'],release['parent']['sha256'])!=(old/'release.json').read_bytes():
        raise ValueError('Wrong parent release')
    for root in (old,new):
        receipts=list((root/'batch/invocations').glob('*/receipt.json'))
        if not receipts or not all(json.loads(p.read_text())['all_owned_closed'] for p in receipts):
            raise ValueError('Missing closure evidence')
    rows=[];evidence=[]
    for cell in load(release['manifest'])['cells']:
        for version,root in (('before',old),('after',new)):
            directory=root/'batch/cells'/cell['cell_id']
            terminal=json.loads((directory/'terminal.json').read_text())
            r=load(terminal['outcome']);score=load(terminal['score']);loss=load(terminal['query_loss'])
            timing=json.loads((directory/'execution/timing.json').read_text());core=read_json_evidence(r['core'])
            obs=r['source_observations']
            rows.append(dict(cell_id=cell['cell_id'],question_id=r['question_id'],version=version,
                success=r['success'],answer_em=score['answer_em'],answer_f1=score['answer_row_multiset_f1'],
                expected_rows=score['expected_rows'],actual_rows=score['actual_rows'],
                query_loss=loss['loss'],certificate_violation=loss['certificate_violation'],
                epsilon=loss['epsilon'],total_online_ms=timing['total_online_ms'],planning_cpu_ms=r['planning_cpu_ms'],
                execution_ms=r['execution_ms'],clarification_calls=r['clarification_calls'],disclosed_fields=r['disclosed_coordinates'],
                backend_http_attempts=obs['requests'],response_bytes=obs['response_body_bytes'],
                payload_bytes=obs['request_body_bytes']+obs['request_target_bytes']+obs['response_body_bytes'],
                model_calls=r['model_calls'],final_plan_executions=r['final_plan_executions'],
                completed_root_actions=core['rounds'][0].get('completed_root_actions'),
                first_round_selection=core['rounds'][0].get('selection_basis','legacy_fallback'),
                completion_cache_hits=core.get('completion_cache_hits'),completion_evaluations=core.get('completion_evaluations')))
            evidence.append(dict(version=version,cell=cell['cell_id'],terminal=file_pin(directory/'terminal.json'),
                outcome=terminal['outcome'],score=terminal['score'],query_loss=terminal['query_loss'],timing=file_pin(directory/'execution/timing.json')))
    with (out/'cells.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary=dict(schema_version='xgap-ch6-planner-followup-results-v1',source_commit=release['source_commit'],
        release=file_pin(new/'release.json'),unique_exposed_cases=3,repetitions_per_version=1,model_calls=0,
        same_inputs_and_epsilon=True,interpretations_may_differ=True,same_query_speedup_claim=False,
        formal_or_generalization_result=False,rows=rows,evidence=evidence,
        all_owned_closed=True,scope='engineering before/after; no external baseline or epsilon sweep')
    result=write_once(out/'summary.json',summary)
    print(json.dumps(dict(summary=result,rows=rows)))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('parent','followup','output'):p.add_argument('--'+name,required=True)
    summarize(**vars(p.parse_args()))
