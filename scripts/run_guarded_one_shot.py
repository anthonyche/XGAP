#!/usr/bin/env python3
"""One guarded request; explicit execute, zero-call preflight by default."""
import argparse
import json
from xgap.experiments.guarded_one_shot import run_guarded_record

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('profile-path','profile-sha256','request-path','request-sha256','output','budget-path','budget-sha256'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--mode',choices=('precision','performance'),required=True)
    parser.add_argument('--operation',choices=('preflight','execute','replay'),default='preflight')
    parser.add_argument('--replay-path');parser.add_argument('--replay-sha256')
    result=run_guarded_record(**vars(parser.parse_args()))
    print(json.dumps({k:result[k] for k in ('success','status','supervised_end_to_end_ms','requires_external_quiescence_barrier')}))
    raise SystemExit(0 if result['success'] else 1)
