#!/usr/bin/env python3
"""Three predeclared tiny frontier points; no model, native services or sweeping."""
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
import argparse
import sys

REPO=Path(__file__).resolve().parents[1];sys.path.insert(0,str(REPO/'tests'))
from test_compact_lowering import inputs,EXPECTED
from test_intent_execution import runtime
from test_intent_strong import clustered_family,private_user,QUESTION
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.nl_strong_question import run_nl_strong_question
from xgap.semantic.interpretation import InterpretationRequest
from xgap.experiments.one_shot_records import write_once


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    specifications=[('exact','0'),('performance','1/4'),('performance','1/2')]
    write_once(root/'intent.json',dict(scope='known tiny mechanism; not paper evaluation',
        specifications=specifications,private_intent='central',metric='four equal semantic coordinates',
        maximum_model_calls=0,maximum_final_executions=3,full_intent_available_in_both_modes=True))
    rows=[];data=inputs.__wrapped__()
    for index,(mode,epsilon) in enumerate(specifications):
        directory=root/str(index);directory.mkdir();options,calls=runtime(data)
        f=clustered_family(snapshot_identity(options['sources'],options['backends'],options['source_schema']))
        oracle=private_user(directory,f,'central')
        report=run_nl_strong_question(InterpretationRequest(QUESTION,{'source_schema':options.pop('source_schema')}),None,
            mode=mode,policy=options.pop('physical_profile'),bundle=None,user_oracle=oracle,intent_family=f,
            family_information=FamilyInformationPolicy(),family_epsilon=epsilon,propose_with_model=False,**options)
        write_once(directory/'core.json',report)
        encoded=lambda values:{json.dumps(v,sort_keys=True) for v in values}
        reference=encoded(EXPECTED[1]);actual=encoded(report['answer_rows'] or [])
        cert=report.get('terminal_certificate');selected=cert['candidate_id'] if cert else None
        selected_index=next((i for i,c in enumerate(f.candidates) if c.candidate_id==selected),None)
        score=dict(mode=mode,epsilon=epsilon,success=report['success'],selected=selected,
            answer_rows=report['answer_rows'],answer_em=report['answer_rows']==EXPECTED[1],
            answer_jaccard_discrepancy=1-len(reference&actual)/len(reference|actual) if report['success'] else None,
            intent_discrepancy=float(f.distances[selected_index][0]) if selected_index is not None else None,
            clarification_calls=report['clarification_calls'],disclosed_coordinates=report['disclosed_coordinates'],
            expanded_states=report['search']['expanded_states'],physical_prepare_attempts=report['physical_prepare_attempts'],
            final_plan_executions=report['final_plan_executions'],source_calls=len(calls),
            certificate_ms=report['certificate_ms'],planning_ms=report['planning_ms'],planning_cpu_ms=report['planning_cpu_ms'],
            execution_ms=report['execution_ms'],end_to_end_ms=report['end_to_end_ms'],
            oracle_reply_bytes=report['oracle_reply_bytes'],source_wire_bytes=None)
        write_once(directory/'score.json',score);rows.append(score)
    write_once(root/'public_family.json',f.to_dict())
    for name,graph in data[-1].items():graph.serialize(root/(name+'.ttl'),format='turtle')
    receipt=dict(success=all(r['success'] for r in rows) and [r['clarification_calls'] for r in rows]==[1,0,0]
        and [r['answer_em'] for r in rows]==[True,True,False],results=rows,
        scope='one known eight-node case, three contract settings; no timing significance or SOTA claim',
        model_calls=0,source_wire_bytes=None)
    write_once(root/'receipt.json',receipt);print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    raise SystemExit(main(**vars(p.parse_args())))
