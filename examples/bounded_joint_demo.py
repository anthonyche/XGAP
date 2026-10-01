"""Historical bounded-joint entry; use unified_demo.py for current development."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from xgap.api import answer
from xgap.agent.scope_authority import QueryIntentAuthority, private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_toy import QUESTION, TemplateProposalProvider, local_runtime, toy_scope
from xgap.semantic.interpretation import InterpretationRequest


def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=('exact','performance'),default='exact')
    p.add_argument('--epsilon',default='0');args=p.parse_args()
    data,options,calls=local_runtime();schema=options.pop('source_schema')
    with tempfile.TemporaryDirectory(prefix='xgap-private-toy-') as directory:
        path=Path(directory)/'user.json';path.write_text(json.dumps(private_query_intent(QUESTION,data['query_template'])))
        authority=QueryIntentAuthority(path,hashlib.sha256(path.read_bytes()).hexdigest())
        result=answer(InterpretationRequest(QUESTION,{'source_schema':schema}),TemplateProposalProvider(data['query_template']),
            mode=args.mode,epsilon=args.epsilon,scope_policy=toy_scope(),authority=authority,
            limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16),**options)
    print(json.dumps({k:result.get(k) for k in ('success','status','mode','scope_confirmed','candidate_count',
        'total_user_calls','disclosed_coordinates','model_calls','final_plan_executions','answer_rows',
        'planning_cpu_ms','estimated_policy_cost_including_common_actions')},indent=2))
    return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
