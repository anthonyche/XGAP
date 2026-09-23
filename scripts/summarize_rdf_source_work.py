"""Compact observed evidence from one diagnostic; no causal inference or retry."""
import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(root):
    root=Path(root);samples=[]
    for line in (root/'samples.jsonl').read_text().splitlines():
        samples.append(json.loads(line))
    query=[s for s in samples if s['phase'] in ('query','complete')]
    last=query[-1] if query else samples[-1]
    blocking=Counter()
    for s in query:
        for t in s['sampled_uninterruptible_threads']:
            blocking[t['wchan'] or 'unavailable']+=1
    receipt_path=root/'receipt.json'
    receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    return dict(status=receipt['guard']['status'] if receipt else 'running_or_unsealed',
        phase=last['phase'],sampled_query_ms=last['query_elapsed_ms'],rows=last['rows'],
        source_counters=last['query_proc_delta'],index_counters=last['indexes'],
        query_samples=len(query),samples_with_uninterruptible_thread=sum(bool(s['sampled_uninterruptible_threads']) for s in query),
        blocked_thread_samples_by_wait_channel=dict(blocking),
        sampled_stack_tops=dict(Counter((s['query_thread_stack'] or ['unavailable'])[0] for s in query)),
        latest_operation=last['operation'],latest_operation_age_ms=last['operation_age_ms'],
        limitations='Samples are not wait durations. Index tuple yields are not physical scan pages. Instrumented replay, not paper latency; no cold-cache assertion.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');a=p.parse_args()
    print(json.dumps(summarize(a.root),indent=2))
