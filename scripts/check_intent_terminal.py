#!/usr/bin/env python3
"""One tiny terminal mechanism gate, not a dataset experiment or parameter sweep."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tests'))
from test_compact_lowering import inputs, EXPECTED
from test_intent_execution import case
from test_intent_certificate import family
from xgap.experiments.one_shot_records import write_once


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    data=inputs.__wrapped__()
    rows=[]
    for label,mode,epsilon,budget in [('exact','exact','0',2),
            ('bounded','performance','1/2',1),('exact_budget1','exact','0',1)]:
        directory=root/label;directory.mkdir()
        r,calls=case(data,directory,mode,epsilon,budget)
        f=family(r['source_snapshot'])
        hidden=json.loads((directory/'private-intent.json').read_text())
        truth=next(i for i,c in enumerate(f.candidates) if c.candidate_id==hidden['candidate_id'])
        selected=r['terminal_certificate']['candidate_id'] if r['terminal_certificate'] else None
        selected_index=next((i for i,c in enumerate(f.candidates) if c.candidate_id==selected),None)
        reference=EXPECTED[1][:3]
        actual=r['answer_rows']
        encode=lambda row:json.dumps(row,sort_keys=True)
        a={encode(row) for row in actual} if actual is not None else set()
        b={encode(row) for row in reference}
        summary=dict(mode=mode,epsilon=epsilon,budget=budget,status=r['status'],
            clarification_calls=r['clarification_calls'],final_plan_executions=r['final_plan_executions'],
            physical_prepare_attempts=r['physical_prepare_attempts'],model_calls=r['model_calls'],
            tokens=r['tokens'],source_calls=len(calls),
            returned_rows=None if actual is None else len(actual),reference_rows=len(reference),
            answer_exact_match=None if actual is None else actual==reference,
            answer_jaccard_discrepancy=None if actual is None else 1-len(a&b)/len(a|b),
            intent_discrepancy=None if selected_index is None else float(f.distances[selected_index][truth]),
            certificate=r['terminal_certificate'],certificate_ms=r['certificate_ms'],
            oracle_processing_ms=r['oracle_processing_ms'],clarification_wall_ms=r['clarification_wall_ms'],
            execution_ms=r['execution_ms'],end_to_end_ms=r['adapter_end_to_end_ms'],
            coordinator_bytes_moved=(r.get('execution') or {}).get('result',{}).get('metrics',{}).get('bytes_moved'),
            source_wire_bytes=None)  # RDFLib adapter performs no HTTP/wire capture.
        # Score after completion; reference never enters the controller/oracle.
        write_once(directory/'run.json',r)
        write_once(directory/'score.json',{'reference':reference,'summary':summary})
        rows.append(summary)
    write_once(root/'public_family.json',asdict(f))
    for name,graph in data[-1].items():
        graph.serialize(root/(name+'.ttl'),format='turtle')
    report=dict(scope='single known eight-node mechanism case with four public intents; not open-NL or native-service evaluation',
        model_calls=0,native_service_calls=0,results=rows,
        success=(rows[0]['answer_exact_match'] is True and rows[1]['answer_jaccard_discrepancy']==.25
            and rows[2]['status']=='clarification_budget' and
            [r['clarification_calls'] for r in rows]==[2,1,1] and
            [r['physical_prepare_attempts'] for r in rows]==[1,1,0]))
    write_once(root/'receipt.json',report)
    print(json.dumps(report))
    return 0 if report['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    raise SystemExit(main(**vars(p.parse_args())))
