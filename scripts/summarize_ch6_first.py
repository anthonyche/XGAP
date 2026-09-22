"""Post-seal results; no model or backend execution and no planner estimates."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics

from xgap.experiments.ch6_metrics import trace_cost
from xgap.experiments.evidence_store import read_json_evidence
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def load(pin):return json.loads(read_pinned(pin['path'],pin['sha256']))
def pin(path):
 path=Path(path);data=path.read_bytes()
 return dict(path=str(path),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
def mean(values):return statistics.mean(values) if values and all(v is not None for v in values) else None
def median(values):return statistics.median(values) if values and all(v is not None for v in values) else None

def summarize(root, output, continuation=None):
 root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=False)
 release=json.loads((root/'release.json').read_text());manifest=load(release['manifest'])
 invocations=[json.loads(p.read_text()) for p in sorted((root/'batch/invocations').glob('*/receipt.json'))]
 if not invocations or not all(d['all_owned_closed'] for d in invocations):raise ValueError('Source closure not verified')
 cases={c['question_id']:c for c in release['cases']};rows=[];retired=[]
 continuation=Path(continuation) if continuation else None
 continuation_release=None
 if continuation:
  continuation_release=json.loads((continuation/'release.json').read_text())
  if read_pinned(continuation_release['parent']['path'],continuation_release['parent']['sha256']) != (root/'release.json').read_bytes():
   raise ValueError('Continuation does not extend this frozen release')
  continuation_manifest=load(continuation_release['manifest'])
  for cell in continuation_manifest['cells']:
   if cell['method']!='xgap-unified-lookahead':raise ValueError('Retired method in continuation')
  continuation_receipts=list((continuation/'batch/invocations').glob('*/receipt.json'))
  if not continuation_receipts:raise ValueError('Missing continuation closure receipts')
  for p in continuation_receipts:
   if not json.loads(p.read_text())['all_owned_closed']:raise ValueError('Continuation sources not closed')
 for cell in manifest['cells']:
  directory=root/'batch/cells'/cell['cell_id']
  if cell['method']!='xgap-unified-lookahead':
   retired.append(dict(cell_id=cell['cell_id'],method=cell['method'],status='sealed_diagnostic_only' if (directory/'terminal.json').exists() else 'interrupted' if directory.exists() else 'not_run_after_correction'))
   continue
  if not directory.exists() and continuation:directory=continuation/'batch/cells'/cell['cell_id']
  terminal=json.loads((directory/'terminal.json').read_text());r=load(terminal['outcome']);score=load(terminal['score'])
  timing=json.loads((directory/'execution/timing.json').read_text());core=read_json_evidence(r['core']) if r.get('core') else {}
  online=core.get('joint_policy') or core;trace=online.get('trace');obs=r.get('source_observations') or {}
  query_loss=load(terminal['query_loss']) if terminal.get('query_loss') else {}
  case=cases[r['question_id']]
  actual=dict(clarification_calls=r.get('clarification_calls'),disclosed_fields=r.get('disclosed_coordinates'),
      backend_http_attempts=obs.get('requests'),planner_cpu_ms=r.get('planning_cpu_ms'))
  cost=trace_cost(actual,release['actual_trace_weights'])
  row=dict(cell_id=cell['cell_id'],question_id=r['question_id'],template=case['template'],stratum=case['stratum'],
      track='controlled' if 'controlled_state' in cell else 'nl',method=r['method'],status=r['status'],answered=r['success'],
      answer_em=score['answer_em'],answer_f1=score['answer_row_multiset_f1'],expected_rows=score['expected_rows'],
      actual_rows=score['actual_rows'],comparison_error=score['comparison_error'],error=r.get('error'),
      core_e2e_ms=r.get('end_to_end_ms'),total_online_ms=timing['total_online_ms'],planning_cpu_ms=r.get('planning_cpu_ms'),
      planning_ms=r.get('planning_ms'),execution_ms=r.get('execution_ms'),initialization_ms=online.get('initialization_ms'),
      model_calls=r.get('model_calls'),input_tokens=r.get('input_tokens'),output_tokens=r.get('output_tokens'),
      clarification_calls=r.get('clarification_calls'),scope_confirmation_calls=r.get('scope_confirmation_calls'),
      disclosed_coordinates=r.get('disclosed_coordinates'),backend_http_attempts=obs.get('requests'),
      transfer_payload_bytes=(obs['request_body_bytes']+obs['request_target_bytes']+obs['response_body_bytes']) if 'response_body_bytes' in obs else None,
      probe_calls=sum(t['kind']=='probe' for t in trace) if trace is not None else None,
      physical_actions=sum(t['kind']=='transform' for t in trace) if trace is not None else None,
      expanded_states=sum(round['expanded_states'] for round in online['rounds']) if 'rounds' in online else None,
      search_fallback_rounds=sum(round['status']!='completed' for round in online['rounds']) if 'rounds' in online else None,
      query_loss=query_loss.get('loss'),query_loss_status=query_loss.get('status','not_applicable_no_intent_certificate'),
      certificate_violation=query_loss.get('certificate_violation'),trace_actual_work=cost['trace_cost'],
      final_plan_executions=r.get('final_plan_executions'),guard_status=r.get('guard_status'),
      sampled_worker_rss_bytes=(r.get('resources') or {}).get('sampled_peak_rss_bytes',{}).get('method'))
  rows.append(row)
 with (out/'cells.csv').open('x',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 groups=[]
 for track in ('controlled','nl'):
  for stratum in ('uniform','active','all'):
   for method in dict.fromkeys(row['method'] for row in rows if row['track']==track):
    items=[r for r in rows if r['track']==track and r['method']==method and (stratum=='all' or r['stratum']==stratum)]
    groups.append(dict(track=track,stratum=stratum,method=method,n=len(items),answered=sum(r['answered'] for r in items),
       exact_answers=sum(r['answer_em'] for r in items),answer_f1_mean=mean([r['answer_f1'] for r in items]),
       total_online_ms_median_all_attempts=median([r['total_online_ms'] for r in items]),
       planning_cpu_ms_median=median([r['planning_cpu_ms'] for r in items]),execution_ms_median=median([r['execution_ms'] for r in items]),
       model_calls=sum(r['model_calls'] for r in items) if all(r['model_calls'] is not None for r in items) else None,
       input_tokens=sum(r['input_tokens'] for r in items) if all(r['input_tokens'] is not None for r in items) else None,
       output_tokens=sum(r['output_tokens'] for r in items) if all(r['output_tokens'] is not None for r in items) else None,
       backend_http_attempts=sum(r['backend_http_attempts'] for r in items),
       transfer_payload_bytes=sum(r['transfer_payload_bytes'] for r in items),
       status_counts=dict(Counter(r['status'] for r in items))))
 pairs=[]
 for track in ('controlled','nl'):
  subset=[r for r in rows if r['track']==track];methods=list(dict.fromkeys(r['method'] for r in subset))
  for i,a in enumerate(methods):
   for b in methods[i+1:]:
    for stratum in ('uniform','active','all'):
     left={r['question_id']:r for r in subset if r['method']==a and r['answered'] and (stratum=='all' or r['stratum']==stratum)}
     right={r['question_id']:r for r in subset if r['method']==b and r['answered'] and (stratum=='all' or r['stratum']==stratum)}
     common=sorted(left.keys()&right.keys())
     pairs.append(dict(track=track,stratum=stratum,method_a=a,method_b=b,common_answered_n=len(common),
       question_ids=common,median_a_online_ms=median([left[q]['total_online_ms'] for q in common]),
       median_b_online_ms=median([right[q]['total_online_ms'] for q in common]),
       both_exact_n=sum(left[q]['answer_em']==right[q]['answer_em']==1 for q in common)))
 summary=dict(schema_version='xgap-ch6-first-real-summary-v2',source_commit=release['source_commit'],release=pin(root/'release.json'),manifest=release['manifest'],
     continuation=dict(release=pin(continuation/'release.json'),source_commit=continuation_release['source_commit'],manifest=continuation_release['manifest']) if continuation else None,retired_cells=retired,
     unique_cases=release['unique_cases'],cells=len(rows),all_owned_closed=True,groups=groups,paired_common_answered=pairs,
     cases=[dict(question_id=q,template=c['template'],stratum=c['stratum'],reference_rows=next(r['expected_rows'] for r in rows if r['question_id']==q)) for q,c in cases.items()],
     certificate_checks=sum(r['certificate_violation'] is not None for r in rows),certificate_violations=sum(r['certificate_violation'] is True for r in rows),
     unknown_query_loss=sum(r['query_loss_status']=='loss_evidence_error' for r in rows),
     actual_trace_weights=release['actual_trace_weights'],formal_result=False,repeated_runs=0,template_generalization=False,
     scope='XGAP only after user correction. Six authored grounded cases, three shared template families, two source-only strata; real SF0.1 native services and real NL API; external Two-stage not admitted; no comparative advantage claim')
 summary_pin=write_once(out/'summary.json',summary)
 print(json.dumps(dict(summary=summary_pin,groups=[g for g in groups if g['stratum']=='all'],certificates=summary['certificate_checks'],violations=summary['certificate_violations'])))
 return rows,summary

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);p.add_argument('--continuation')
 a=p.parse_args();summarize(a.root,a.output,a.continuation)
