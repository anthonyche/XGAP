"""Publish, preflight, execute or replay one pinned practical request.

Source/model services and offline training are managed outside this entry. Replay
matches exact acquisition arguments and exact native artifacts once; historical
paid metrics are provenance rather than new network/token consumption.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import threading
import time

from xgap.experiments.one_shot_profile import _fields, _file, native_clients, read_pinned
from xgap.experiments.one_shot_records import BackendReplay, CapturingClient, write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_outcome import write_outcome
from xgap.tools.contracts import ToolResult, ToolStatus


REPLAY_SCHEMA='xgap-practical-call-replay-v2'


def publish_profile(*,profile_path,profile_sha256,output):
    profile=FrozenPracticalProfile.load(profile_path,expected_sha256=profile_sha256)
    doc=json.loads(profile.document_json)
    refs=[doc['intake'],doc['catalog']]
    if doc['estimator'] is not None:refs.append(doc['estimator'])
    refs += [s['equality_key_bounds'] for s in doc['sources'].values() if 'equality_key_bounds' in s]
    refs += [a['provider']['prompt'] for a in doc['acquisitions'].values() if a['kind']=='model']
    for pin in refs:pin['path']=str((profile.root/pin['path']).resolve())
    doc['offline']={**doc['offline'],'published_from':{'path':str(Path(profile_path).resolve()),'sha256':profile_sha256},
        'publication_model_calls':0,'publication_source_calls':0,'publication_fit_calls':0}
    output=Path(output).resolve()
    FrozenPracticalProfile(output.parent,'0'*64,json.dumps(doc)).materialize()
    return write_once(output,doc)


class CapturingAcquisition:
    def __init__(self,tool,root,records):
        self.tool,self.root,self.records=tool,root,records
    @property
    def spec(self):return self.tool.spec
    def invoke(self,args,context):
        index=len(self.records)
        row={'tool_name':self.spec.name,'arguments':args,'status':'started'}
        self.records.append(row)
        write_once(self.root/f'acquisition-{index:04}-intent.json',row)
        result=self.tool.invoke(args,context)
        row.update(status='returned',result=result.to_dict())
        row['capture']=write_once(self.root/f'acquisition-{index:04}-result.json',row)
        return result


class AcquisitionReplay:
    def __init__(self,tool,records,consumed):
        self.tool,self.records,self.consumed=tool,records,consumed
    @property
    def spec(self):return self.tool.spec
    def invoke(self,args,context):
        started=time.perf_counter()
        index=len(self.consumed)
        if index>=len(self.records):raise ValueError('No acquisition replay remains')
        row=self.records[index]
        if row['tool_name']!=self.spec.name or row['arguments']!=args:
            raise ValueError('Acquisition replay input/provenance differs')
        raw=row['result']
        if row['status']!='returned' or raw['tool_name']!=self.spec.name:
            raise ValueError('Acquisition replay record identity invalid')
        self.consumed.append(index)
        return ToolResult(self.spec.name,ToolStatus(raw['status']),value=raw['value'],error=raw['error'],
            metadata={**raw.get('metadata',{}),'execution_kind':'offline_replay',
                'historical_metrics':raw.get('metrics',{})},
            metrics={'model_calls':0,'tokens':0,'remote_calls':0,'elapsed_ms':(time.perf_counter()-started)*1000})


def _rows(rows):
    return Counter(json.dumps(r,sort_keys=True,separators=(',',':')) for r in rows) if rows is not None else None


def outcome_fingerprint(result):
    """Costs vary in replay; semantic/tool/node outcomes must not vary."""
    observed=[]
    for o in result.get('execution_state',{}).get('observations',[]):
        if o['kind']!='tool_result':continue
        raw=o['payload']
        row={'tool_name':o['source'],'status':raw['status'],'error':raw['error']}
        if o['source']=='practical.execute_final':
            execution=(raw.get('value') or {}).get('result',{})
            value=execution.get('value') or {}
            row.update(execution_status=execution.get('status'),execution_error=execution.get('error'),
                roots=value.get('root_rows'),final_rows=value.get('final_rows'),
                nodes=[{k:n.get(k) for k in ('node_id','kind','status','row_count','error')}
                       for n in value.get('node_results',[])])
        else:row['value']=raw.get('value')
        observed.append(row)
    return {'status':result['status'],'success':result['success'],'answer_rows':result['answer_rows'],
        'final_plan_executions':result['final_plan_executions'],'observations':observed}


def run_record(*,profile_path,profile_sha256,request_path,request_sha256,mode,output,
               operation='preflight',replay_path=None,replay_sha256=None):
    if operation not in ('preflight','execute','replay'):raise ValueError('Unknown practical record operation')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    receipt={'schema_version':'xgap-practical-record-v1','success':False,'operation':operation,'mode':mode,
        'outcome':None,
        'model_network_calls':0,'source_network_calls':0,'final_plan_executions':0,'fit_calls':0,
        'automatic_retries':0,'profile':{'path':str(Path(profile_path).resolve()),'sha256':profile_sha256},
        'request':{'path':str(Path(request_path).resolve()),'sha256':request_sha256}}
    sources,acquisitions,consumed=[],[],[];clients={};replay=None
    phase='admission'
    try:
        profile,cfg=FrozenPracticalProfile.load_materialized(profile_path,expected_sha256=profile_sha256)
        raw=json.loads(read_pinned(request_path,request_sha256))
        # Request admission and response pin syntax validation, without authority-file reads.
        prepared=profile.prepare(raw,request_sha256=request_sha256,request_root=Path(request_path).resolve().parent,
            mode=mode,materialized=cfg)
        receipt['admission_ms']=(time.perf_counter()-started)*1000
        receipt['dependency_lifetime']='one admitted snapshot per record request'
        write_once(root/'input.json',{'request':raw,'profile_sha256':profile_sha256,'mode':mode})
        if operation=='replay':
            replay=json.loads(read_pinned(replay_path,replay_sha256))
            _fields(replay,('schema_version','question','acquisitions','backends','expected_success','expected_rows',
                'captures_complete','expected_outcome'),('provenance',))
            if replay['schema_version']!=REPLAY_SCHEMA or replay['question']!=raw['question']:
                raise ValueError('Replay schema/question differs')
            if replay['captures_complete'] is not True:
                raise ValueError('Incomplete capture cannot be certified as a faithful replay')
            if not isinstance(replay['acquisitions'],list) or len(replay['acquisitions'])>32:
                raise ValueError('Acquisition replay bound exceeded')
            if not isinstance(replay['backends'],list) or len(replay['backends'])>64:
                raise ValueError('Source replay bound exceeded')
            # Embedded capture pins stay relative to the replay manifest, not cwd.
            records=[]
            for pin in replay['backends']:
                _fields(pin,('path','sha256'),('bytes',))
                capture_root=Path(replay_path).resolve().parent
                data=_file(capture_root,{k:pin[k] for k in ('path','sha256')})
                if 'bytes' in pin and (type(pin['bytes']) is not int or pin['bytes']!=len(data)):
                    raise ValueError('Source capture byte count differs')
                row=json.loads(data)
                # Preserve exact artifact matching when independent source calls
                # start in a different order. Recheck the pin at consumption.
                records.append({'backend_id':row['backend_id'],'artifact':row['artifact'],
                    'status':row['status'],'response_record':{
                        'path':str((capture_root/pin['path']).resolve()),
                        'sha256':pin['sha256'],'bytes':len(data)}})
            clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in cfg[6]}
            wrap=lambda tool:AcquisitionReplay(tool,replay['acquisitions'],consumed)
        elif operation=='execute':
            lock=threading.Lock()
            clients={b:CapturingClient(c,root,sources,lock,retain_payloads=False) for b,c in native_clients(cfg[6]).items()}
            wrap=lambda tool:CapturingAcquisition(tool,root,acquisitions)
        else:
            clients=None;wrap=None
        if operation!='preflight':write_once(root/'intent.json',{'operation':operation,'maximum_final_plans':1,
            'profile_sha256':profile_sha256,'request_sha256':request_sha256})
        phase='request'
        result=profile.run_prepared(prepared,execute=operation!='preflight',backend_clients=clients,
            acquisition_wrapper=wrap,preparation_ms=receipt['admission_ms'])
        receipt['result']=write_once(root/'result.json',result)
        receipt['outcome']=write_outcome(root,result,receipt['result'])
        receipt.update(status=result['status'],final_plan_executions=result['final_plan_executions'],
            success=result['search']['strong'] if operation=='preflight' else result['success'],
            acquisition_invocations=len(acquisitions) if operation=='execute' else len(consumed),
            source_invocations=result['backend_remote_calls'])
        if operation=='replay':
            matched=(result['success']==replay['expected_success'] and _rows(result['answer_rows'])==_rows(replay['expected_rows'])
                and outcome_fingerprint(result)==replay['expected_outcome']
                and len(consumed)==len(replay['acquisitions']) and sum(c.position for c in clients.values())==len(replay['backends']))
            receipt.update(replay_match=matched,original_execution_success=replay['expected_success'],
                success=matched,execution_kind='offline_replay')
        elif operation=='execute':
            receipt.update(model_network_calls=result['model_calls'],source_network_calls=len(sources),
                execution_kind='configured_native',tokens=result['tokens'])
            # Export only observed costs/outcomes, never retry an indeterminate call.
            receipt['replay']=write_once(root/'replay.json',{'schema_version':REPLAY_SCHEMA,'question':raw['question'],
                'acquisitions':[{k:r[k] for k in ('tool_name','arguments','status','result')} for r in acquisitions if r['status']=='returned'],
                'backends':[r['response_record'] for r in sources if r['status']=='returned'],
                'captures_complete':all(r['status']=='returned' for r in sources+acquisitions),
                'expected_success':result['success'],'expected_rows':result['answer_rows'],
                'expected_outcome':outcome_fingerprint(result)})
    except (OSError,ValueError,KeyError,TypeError) as error:
        receipt.update(error=str(error),failure_phase=phase)
        if operation=='execute':
            receipt['source_network_calls']=len(sources)
            paid=[r.get('result',{}).get('metrics',{}).get('model_calls') for r in acquisitions]
            receipt['model_network_calls']=None if any(v is None for v in paid) else sum(paid)
    finally:
        receipt['elapsed_ms']=(time.perf_counter()-started)*1000
        write_once(root/'receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation',choices=('publish','preflight','execute','replay'),required=True)
    parser.add_argument('--profile-path',required=True);parser.add_argument('--profile-sha256',required=True)
    parser.add_argument('--request-path');parser.add_argument('--request-sha256')
    parser.add_argument('--mode',choices=('exact','performance'));parser.add_argument('--output',required=True)
    parser.add_argument('--replay-path');parser.add_argument('--replay-sha256')
    args=vars(parser.parse_args())
    if args['operation']=='publish':
        result=publish_profile(**{k:args[k] for k in ('profile_path','profile_sha256','output')})
    else:
        if not all(args[k] for k in ('request_path','request_sha256','mode')):parser.error('Request and mode required')
        if args['operation']=='replay' and not all(args[k] for k in ('replay_path','replay_sha256')):parser.error('Pinned replay required')
        result=run_record(**args)
    print(json.dumps(result,ensure_ascii=False));return 0 if result.get('success',True) else 1


if __name__=='__main__':raise SystemExit(main())
