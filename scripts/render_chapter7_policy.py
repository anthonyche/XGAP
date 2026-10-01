#!/usr/bin/env python3
"""Render a sealed complete policy with observed versus planned branches."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import subprocess

from xgap.experiments.evidence_store import file_pin,read_json_evidence
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once


def render(core,title):
    policy=core.get('joint_policy') or core
    if not policy.get('success') or policy.get('final_plan_executions')!=1:
        raise ValueError('Case figure requires a successful observed single-plan execution')
    graph=policy['policy_evidence'];family=core['intent_family']
    if graph['schema_version']!='xgap-selected-intent-policy-v1' or len(graph['nodes'])>100:
        raise ValueError('Renderer requires a complete selected policy of at most 100 nodes')
    observed=policy['observed_policy_state_ids'];states={'state:'+str(n) for n in observed}
    path={(f'state:{a}:action',f'state:{b}') for a,b in zip(observed,observed[1:])}
    quote=lambda x:json.dumps(str(x))
    lines=['digraph policy {','graph [rankdir=TB, bgcolor="white", pad=0.18, nodesep=0.18, ranksep=0.32, dpi=144];',
           'node [fontname="Helvetica", fontsize=11, margin="0.08,0.06"];',
           'edge [fontname="Helvetica", fontsize=10];',
           'label='+quote(title+'\nSolid blue: observed path. Dashed gray: planned only.')+'; labelloc=t; fontsize=13;']
    for node in graph['nodes']:
        name=node['id'];kind=node['kind'];owner=name.split(':')[0]+':'+name.split(':')[1]
        active=owner in states
        if kind=='OR':label=f'State {node["state_id"]}\nOR';shape='ellipse'
        elif kind=='AND':
            label='Clarify: '+', '.join(node['arguments']['slots'])+'\nAND: '+str(node['declared_outcomes'])+' possible replies';shape='box'
        else:
            if active and (not observed or name!=f'state:{observed[-1]}:execute'
                    or node['candidate_id']!=policy['terminal_certificate']['candidate_id']):
                raise ValueError('Observed terminal differs from sealed selected candidate')
            cert=node['certificate'];values=[]
            for slot in family['slots']:
                value=node['query']
                for key in slot['path']:value=value[key]
                values.append(slot['name']+'='+json.dumps(value,separators=(',',':')))
            label=('EXECUTED' if active else 'Planned EXECUTE')+'\n'+'\n'.join(values)
            label+='\nU='+str(Fraction(**cert['upper_bound']))+' <= epsilon='+str(Fraction(**cert['epsilon']))
            shape='box'
        color='#17628a' if active else '#777777';style='rounded,filled' if active and shape=='box' else 'filled' if active else 'dashed'
        lines.append(quote(name)+' [label='+quote(label)+', shape='+shape+', color='+quote(color)
            +', style='+quote(style)+', fillcolor="'+('#eaf3f8' if active else 'white')+'", penwidth='+('2' if active else '1')+'];')
    for edge in graph['edges']:
        a,b=edge['source'],edge['target']
        active=(a,b) in path if edge['kind']=='outcome' else a in states
        label='reply' if edge['kind']=='outcome' else ''
        lines.append(quote(a)+' -> '+quote(b)+' [label='+quote(label)+', color="'+('#17628a' if active else '#888888')
            +'", style='+('solid' if active else 'dashed')+', penwidth='+('2' if active else '1')+'];')
    return '\n'.join(lines+['}'])+'\n'


def main(*,receipt_path,receipt_sha256,title,output):
    trial=json.loads(read_pinned(receipt_path,receipt_sha256));core=read_json_evidence(trial['core'])
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    dot=root/'policy.dot';dot.write_text(render(core,title))
    for fmt in ('pdf','png'):
        subprocess.run(['dot','-T'+fmt,str(dot),'-o',str(root/('policy.'+fmt))],check=True,timeout=30)
    pin=write_once(root/'manifest.json',dict(schema_version='xgap-sealed-policy-render-v1',
        source_receipt=dict(path=receipt_path,sha256=receipt_sha256),core=trial['core'],
        includes_unobserved_branches=True,counterfactual_measurements=False,
        outputs=[file_pin(root/name) for name in ('policy.dot','policy.pdf','policy.png')]))
    print(json.dumps(pin))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('receipt-path','receipt-sha256','title','output'):p.add_argument('--'+name,required=True)
    main(**vars(p.parse_args()))
