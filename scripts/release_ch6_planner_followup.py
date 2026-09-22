"""Freeze exactly three previously exposed engineering cases; no model calls."""
import argparse
import json
from pathlib import Path

from run_bounded_joint_batch import source_commit,validate
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def release(parent,output):
    commit=source_commit();parent=Path(parent).resolve()
    old=json.loads((parent/'release.json').read_text())
    original=json.loads(read_pinned(old['manifest']['path'],old['manifest']['sha256']))
    ids={f'c{i:02d}-controlled-unified-lookahead' for i in (0,2,4)}
    cells=[c for c in original['cells'] if c['cell_id'] in ids]
    if len(cells)!=3 or any(c['method']!='xgap-unified-lookahead' or 'controlled_state' not in c for c in cells):
        raise ValueError('Expected the first uniform case from each frozen structure')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    manifest={**original,'cells':cells,'design':{**original['design'],'total_wall_seconds':900}}
    validate(manifest)
    pin=write_once(root/'manifest.json',manifest)
    result=dict(schema_version='xgap-ch6-planner-followup-v1',source_commit=commit,parent=file_pin(parent/'release.json'),
        manifest=pin,
        case_ids=sorted(ids),model_calls_cap=0,final_plans_cap=3,automatic_retries=0,
        held_out=False,selection='first uniform case of each predeclared template; not selected by result or speed',
        old_measurements_retained=True,changes='bounded request memoization and retain fully evaluated root incumbent',
        comparisons='single-observation engineering check; not a repeated speedup estimate')
    result['cases']=[c for c in old['cases'] if c['question_id'] in ('CH6-FIRST-00','CH6-FIRST-02','CH6-FIRST-04')]
    write_once(root/'release.json',result)
    print(json.dumps(pin))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parent',required=True);p.add_argument('--output',required=True)
    release(**vars(p.parse_args()))
