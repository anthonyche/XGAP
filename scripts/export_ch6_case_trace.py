#!/usr/bin/env python3
"""Export C1 realized action data and T1 from five pinned outcomes; zero calls."""
import argparse
from pathlib import Path
from xgap.experiments.ch6_formal_protocol import load_pin,write_csv
from xgap.experiments.ch6_case_trace import extract
from xgap.experiments.one_shot_records import write_once


def export(spec_path,spec_sha256,output):
    spec=load_pin(dict(path=spec_path,sha256=spec_sha256));result=extract(spec)
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    pin=write_once(root/'C1-trace.json',result)
    rows=[event for item in result['methods'].values() for event in item['events']]
    if rows:write_csv(root/'T1.csv',rows)
    write_once(root/'receipt.json',dict(trace=pin,actual_actions=len(rows),model_calls=0,backend_calls=0,
        methods={m:dict(status=v['status'],actions=len(v['events'])) for m,v in result['methods'].items()}))
    return pin


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('spec-path','spec-sha256','output'):p.add_argument('--'+name,required=True)
    print(export(**vars(p.parse_args())))
