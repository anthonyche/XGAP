"""Unified entry on an eight-entity local graph; no model or network calls."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from xgap.api import answer_unified
from xgap.agent.scope_authority import QueryIntentAuthority, private_query_intent
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits
from xgap.experiments.bounded_joint_toy import QUESTION, TemplateProposalProvider, local_runtime, toy_scope
from xgap.semantic.interpretation import InterpretationRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--depth', type=int, choices=range(1, 5), default=1)
    parser.add_argument('--epsilon', default='0')
    parser.add_argument('--relaxable', nargs='*', default=[], help='Declared validation requirement names (Lambda)')
    parser.add_argument('--sequential', action='store_true')
    args = parser.parse_args()
    data, options, _ = local_runtime()
    schema = options.pop('source_schema')
    settings = UnifiedSettings(epsilon=args.epsilon, relaxable=tuple(args.relaxable),
        limits=Limits(depth=args.depth),
        decision_order='semantic_then_physical' if args.sequential else 'joint')
    with tempfile.TemporaryDirectory(prefix='xgap-private-toy-') as directory:
        path = Path(directory)/'user.json'
        path.write_text(json.dumps(private_query_intent(QUESTION, data['query_template'])))
        authority = QueryIntentAuthority(path, hashlib.sha256(path.read_bytes()).hexdigest())
        result = answer_unified(InterpretationRequest(QUESTION, {'source_schema': schema}),
            TemplateProposalProvider(data['query_template']), settings=settings,
            scope_policy=toy_scope(), authority=authority, **options)
    print(json.dumps({key: result.get(key) for key in (
        'success', 'status', 'profile_id', 'scope_confirmed', 'candidate_count',
        'total_user_calls', 'model_calls', 'physical_actions', 'probe_calls',
        'final_plan_executions', 'answer_rows', 'planning_cpu_ms',
        'realized_trace_work_estimate')}, indent=2))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
