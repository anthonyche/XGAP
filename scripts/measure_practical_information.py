"""Measure a frozen three-question development information sample, never graph execution."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

from xgap.agent.practical_planning import PracticalSemanticDomain
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import CapturingAcquisition
from xgap.tools.contracts import ToolContext, ToolStatus


def main(protocol_path,protocol_sha256,output,operation='preflight',read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    r={'schema_version':'xgap-information-cost-measurement-v1','operation':operation,'success':False,
        'protocol':{'path':str(Path(protocol_path).resolve()),'sha256':protocol_sha256},
        'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'paper_result':False,'source_calls':0,'planning_runs':0,'fit_calls':0,'catalog_builds':0,
        'reference_contents_read':False,'model_attempts':0,'authority_attempts':0,
        'automatic_retries':0,'credential_recorded':False,'samples':[]}
    key_name='XGAP_EXTERNAL_LLM_API_KEY';previous=os.environ.get(key_name)
    try:
        if subprocess.check_output(['git','status','--porcelain'],text=True):raise ValueError('Commit before measurement')
        r['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        p=json.loads(read_pinned(protocol_path,protocol_sha256))
        if (p['schema_version']!='xgap-practical-information-cost-basis-v1' or len(p['questions'])!=3 or
            len({q['question_id'] for q in p['questions']})!=3 or p['maximum_model_attempts']!=3 or
            p['maximum_authority_attempts']!=3 or p['timeout_seconds']!=200 or
            p['stop_remote_after_non_success'] is not True or p['source_calls']!=0 or p['retries']!=0):
            raise ValueError('Expected the fixed bounded development protocol')
        if operation=='measure':
            key=getpass.getpass('LLM credential (not recorded): ') if read_key else previous
            if not key:raise ValueError('Missing configured model credential')
            os.environ[key_name]=key;key=None
        with deadline(p['timeout_seconds']):
            cohort=json.loads(read_pinned(p['cohort']['path'],p['cohort']['sha256']))
            prepared=[]
            for selection in p['questions']:
                group=next(g for g in cohort['groups'] if g['question_id']==selection['question_id'])
                if group['split']!='development' or group['family']!=selection['family']:
                    raise ValueError('Only the selected development question is allowed')
                if sorted(selection['order'])!=['clarification:relation','llm:relation']:
                    raise ValueError('Each available tool is attempted at most once per question')
                profile,cfg=FrozenPracticalProfile.load_materialized(group['profile']['path'],expected_sha256=group['profile']['sha256'])
                raw=json.loads(read_pinned(group['request']['path'],group['request']['sha256']))
                q=profile.prepare(raw,request_sha256=group['request']['sha256'],request_root=Path(group['request']['path']).parent,
                    mode='performance',materialized=cfg)
                provider=q.model_providers['relation-model'];safe=provider.config.safe_dict()
                if (safe['model']!='qwen3.8-27b' or safe['max_tokens']!=512 or safe['timeout_seconds']!=45 or
                    safe['api_key_env']!=key_name or safe['max_repair_calls']!=0):raise ValueError('Model budget/config changed')
                opts=q.options
                domain=PracticalSemanticDomain(q.program,operator_sources=q.provider.operator_sources,
                    binding_values=cfg[2].bindings,sources=cfg[4],backends=cfg[5],mode=opts.mode,actions=opts.actions,
                    predictions=opts.predictions,physical_profile=opts.physical_profile)
                actions={a.action_id:a for a in domain.actions(opts.initial_state)}
                if set(actions)!=set(selection['order']):raise ValueError('Expected the two independent tools')
                if next(a for a in opts.actions if a.action_id=='llm:relation').resources.tokens!=4096:
                    raise ValueError('Model token reservation changed')
                prepared.append((selection,group,q,actions,safe))
            r['inputs']=write_once(root/'inputs.json',[{'selection':s,'profile':g['profile'],'request':g['request'],
                'safe_provider':safe,'arguments':{k:a.arguments for k,a in actions.items()}}
                for s,g,q,actions,safe in prepared])
            if operation=='measure':
                remote_failed=False
                for i,(selection,group,q,actions,safe) in enumerate(prepared):
                    captures=[];directory=root/f'question-{i}';directory.mkdir()
                    values={}
                    for action_id in selection['order']:
                        model=action_id=='llm:relation';action=actions[action_id]
                        row={'question_id':group['question_id'],'family':group['family'],'action_id':action_id}
                        r['samples'].append(row)
                        if model and remote_failed:
                            row.update(status='not_attempted',reason='earlier_remote_non_success');continue
                        tool=CapturingAcquisition(q.options.resolution_tools.get(action.tool_name),directory,captures)
                        r['model_attempts' if model else 'authority_attempts']+=1
                        at=time.perf_counter();result=tool.invoke(action.arguments,ToolContext('information-cost-basis',i,action_id))
                        wall=(time.perf_counter()-at)*1000
                        row.update(status=result.status.value,measured_wall_ms=wall,reported_metrics=dict(result.metrics),
                            capture=captures[-1]['capture'],value=result.value)
                        if model and q.model_providers['relation-model'].last_invocation is not None:
                            row['invocation']=write_once(directory/'model-invocation.json',q.model_providers['relation-model'].last_invocation.to_dict())
                        values[action_id]=result.value if result.status is ToolStatus.SUCCESS else None
                        if model and result.status is not ToolStatus.SUCCESS:remote_failed=True
                        print(json.dumps({k:row[k] for k in ('question_id','action_id','status','measured_wall_ms','reported_metrics')}),flush=True)
                    if all(values.get(k) for k in actions):
                        r.setdefault('development_slot_agreement',[]).append({'question_id':group['question_id'],
                            'agrees':values['llm:relation']['candidate_id']==values['clarification:relation']['candidate_id']})
                r['cost_samples']={}
                for action_id in ('llm:relation','clarification:relation'):
                    rows=[x for x in r['samples'] if x['action_id']==action_id]
                    costs=[x['measured_wall_ms'] for x in rows if x['status']==ToolStatus.SUCCESS.value]
                    r['cost_samples'][action_id]={'expected_attempts':3,'successful_attempts':len(costs),
                        'median_wall_ms':statistics.median(costs) if len(costs)==3 else None,
                        'min_wall_ms':min(costs) if costs else None,'max_wall_ms':max(costs) if costs else None,
                        'complete':len(costs)==3,'scope':'development invocation including capture overhead, not general calibration'}
            r['success']=True
    except Exception as error:r.update(error_type=type(error).__name__,error=str(error))
    finally:
        if previous is None:os.environ.pop(key_name,None)
        else:os.environ[key_name]=previous
        pin=write_once(root/'receipt.json',r)
    print(json.dumps({'success':r['success'],'receipt':pin,'model_attempts':r['model_attempts'],
        'authority_attempts':r['authority_attempts'],'error':r.get('error')}),flush=True)
    return 0 if r['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol-path',required=True);parser.add_argument('--protocol-sha256',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--operation',choices=('preflight','measure'),default='preflight')
    parser.add_argument('--read-key',action='store_true')
    raise SystemExit(main(**vars(parser.parse_args())))
