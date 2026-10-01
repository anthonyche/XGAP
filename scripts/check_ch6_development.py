"""One local compiled execution per prepared gold, independent reference check.

Offline development only. Never used as an online planner or timed experiment.
"""
import argparse,json
from pathlib import Path
from decimal import Decimal
from xgap.agent.intent_execution import family_runtime,snapshot_identity
from xgap.semantic.intent_scope import construct_scope,ScopePolicy
from xgap.experiments.ch6_local_runtime import local_runtime
from xgap.experiments.ch6_workload import reference


def canonical_rows(rows):
    return [{k:Decimal(str(v)) if k=='total' else int(v) if k=='distance' else v for k,v in r.items()} for r in rows]


def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--receipt',default='local_reference_gate.json')
    args=p.parse_args();records=[];output=args.root/args.receipt
    if output.exists():raise ValueError('Preserve previous gate; supply a new receipt name')
    for domain in ('D3','D1','D2'):
        root=args.root/domain;facts=json.loads((root/'facts.json').read_text());options,calls=local_runtime(facts)
        for row in (root/'private_gold.jsonl').read_text().splitlines():
            gold=json.loads(row);query=gold['intended_query'];start=len(calls)
            try:
                family=construct_scope([query],ScopePolicy('development-single',(),language_version='v2'),snapshot_identity(options['sources'],options['backends'],options['source_schema']))
                prepare,execute,*_=family_runtime(family,**options,seed_only=True,stepwise=True)
                plan=prepare(family.candidates[0],None);result=execute(plan)
                expected=reference(query,facts);actual=result.get('answer_rows')
                ok=result['success'] and canonical_rows(actual)==canonical_rows(expected)
                r=dict(case_id=gold['case_id'],success=ok,rows=len(expected),local_adapter_calls=len(calls)-start,
                    actual=actual if not ok else None,expected=expected if not ok else None,status=result.get('result',{}).get('status'))
            except Exception as error:r=dict(case_id=gold['case_id'],success=False,error_type=type(error).__name__,error=str(error))
            records.append(r);print(json.dumps(r,default=str),flush=True)
    output.write_text(json.dumps(dict(engine='RDFLib portable adapter, not Neo4j/Fuseki service',network_calls=0,model_calls=0,records=records,
        all_passed=all(r['success'] for r in records)),indent=2,default=str)+'\n')
    raise SystemExit(0 if all(r['success'] for r in records) else 1)
if __name__=='__main__':main()
