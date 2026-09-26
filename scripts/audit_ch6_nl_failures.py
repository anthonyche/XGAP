#!/usr/bin/env python3
"""Post-seal NL failure grouping/replay; never create or revise method results.

Private intent may be compared offline, but values are never emitted or fed to
an online method. Inputs must be an extracted completed/sealed evidence snapshot.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re

from xgap.experiments.interpretation_diagnostics import summarize_interpretation
from xgap.semantic.compact_identity import IDENTITY_VERSION, representation_key
from xgap.semantic.compact_equivalence import canonicalize_compact_surface
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.intent_scope import ScopePolicy, construct_scope, upgrade_edge_type_domains

LIMIT=64*1024**2


def safe_error(error):
    text=str(error)[:2048]
    text=re.sub(r'(?i)bearer\s+\S+', '[redacted credential]', text)
    text=re.sub(r'(?i)(api[_ -]?key\s*[:=]\s*)[^,;\s]+', r'\1[redacted]', text)
    return re.sub(r'\b[0-9a-fA-F]{32,}\b', '[redacted long token]', text)


class Pins:
    def __init__(self,mappings=()):
        self.mappings=sorted(((Path(a),Path(b)) for a,b in mappings),key=lambda x:-len(str(x[0])))
    def read(self,pin):
        candidates=[];path=Path(pin['path'])
        for old,new in self.mappings:
            if path.is_relative_to(old):candidates.append(new/path.relative_to(old))
        if not candidates:candidates=[path]
        for path in candidates:
            if not path.is_file():continue
            if path.stat().st_size>LIMIT:raise ValueError('Pinned artifact exceeds offline bound')
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=pin['sha256']:raise ValueError('Pinned artifact changed')
            if pin.get('bytes',len(data))!=len(data):raise ValueError('Pinned artifact size changed')
            if pin.get('encoding')=='gzip' or path.suffix=='.gz':
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:data=f.read(LIMIT+1)
                if len(data)>LIMIT:raise ValueError('Expanded core exceeds offline bound')
                if pin.get('logical_sha256') and hashlib.sha256(data).hexdigest()!=pin['logical_sha256']:
                    raise ValueError('Core logical hash changed')
            return json.loads(data)
        raise FileNotFoundError('Pinned artifact absent from supplied mirrors')


def difference_paths(a,b,prefix=''):
    """AST paths only, never private values; list-length and missing keys explicit."""
    if type(a)!=type(b):return [prefix or '/']
    if isinstance(a,dict):
        out=[]
        for k in sorted(set(a)|set(b)):
            p=prefix+'/'+str(k).replace('~','~0').replace('/','~1')
            out += [p] if k not in a or k not in b else difference_paths(a[k],b[k],p)
        return out
    if isinstance(a,list):
        out=[prefix+'/length'] if len(a)!=len(b) else []
        for i,(x,y) in enumerate(zip(a,b)):out+=difference_paths(x,y,prefix+'/'+str(i))
        return out
    return [] if a==b else [prefix or '/']


def private_artifact(roots,qid,name,sha,pins):
    for root in roots:
        for path in sorted(Path(root).glob('**/'+qid+'/'+name)):
            if hashlib.sha256(path.read_bytes()).hexdigest()==sha:
                return pins.read(dict(path=str(path),sha256=sha))
    raise FileNotFoundError('Required post-seal private/scope pin not in supplied case banks')


def audit(evidence_root,output,*,mappings=(),case_banks=(),replay_equivalence=False,replay_edge_type_domains=False):
    reader=Pins(mappings);rows=[];all_statuses=Counter()
    for path in sorted(Path(evidence_root).glob('**/cells/*/terminal.json')):
        terminal=json.loads(path.read_text())
        if terminal['cell_id']!=path.parent.name:raise ValueError('Terminal cell identity differs')
        trial=reader.read(terminal['outcome']);all_statuses[trial['status']]+=1
        if trial['status'] not in ('proposal_failed','intent_outside_proposed_scope'):continue
        row=dict(cell_id=terminal['cell_id'],case_id=trial['question_id'],method=trial['method'],
                 recorded_status=trial['status'],outcome_sha256=terminal['outcome']['sha256'],
                 original_stage='scope_authority' if trial['status']=='intent_outside_proposed_scope' else 'proposal',
                 current_replay_is_method_result=False)
        if not trial.get('core'):
            row['diagnostic_status']='missing_core';rows.append(row);continue
        core=reader.read(trial['core']);row['core_sha256']=trial['core']['sha256']
        diagnostics=summarize_interpretation(core) or {}
        row['recorded_candidate_failures']=[dict(stage=c.get('failure_stage'),error=safe_error(c.get('error') or ''))
            for c in diagnostics.get('candidates',[]) if c.get('failure_stage')]
        report=core.get('interpretation') or {};provenance=report.get('provenance') or {}
        raw=provenance.get('raw_compact_response') or {}
        schema=((report.get('request') or {}).get('context') or {}).get('source_schema')
        proposals=[];replayed=[]
        for i,c in enumerate(raw.get('candidates',[])[:8]):
            try:
                query=c['query'];rewrites=[]
                if replay_equivalence:query,rewrites=canonicalize_compact_surface(query,schema)
                lower_compact_query(query,schema,version='v2',optimize=True)
                proposals.append(query);replayed.append(dict(index=i,status='lowered',equivalence_rules=[r['rule'] for r in rewrites]))
            except (ValueError,KeyError,TypeError) as error:
                replayed.append(dict(index=i,status='rejected',error_type=type(error).__name__,error=safe_error(error)))
        row['current_proposal_replay']=replayed
        if trial['status']=='intent_outside_proposed_scope':
            try:
                private=private_artifact(case_banks,trial['question_id'],'private-user.json',trial['oracle_sha256'],reader)
                scope=private_artifact(case_banks,trial['question_id'],'scope.json',trial['scope_sha256'],reader)
                row.update(oracle_sha256=trial['oracle_sha256'],scope_sha256=trial['scope_sha256'])
                if not proposals:raise ValueError('No proposal admitted by current offline compiler')
                policy=ScopePolicy.from_dict(scope)
                if replay_edge_type_domains:policy=upgrade_edge_type_domains(policy)
                effective=policy.to_dict()
                row.update(effective_scope_policy_sha256=hashlib.sha256(json.dumps(effective,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                    effective_scope_policy_id=policy.policy_id,
                    scope_adapter='edge-type-domain-v1' if replay_edge_type_domains else None)
                family=construct_scope(proposals,policy,'post-seal-diagnostic-only')
                truth=json.loads(representation_key(private['query'],version='v2'))['query']
                diffs=[difference_paths(json.loads(representation_key(json.loads(c.query_json),version='v2'))['query'],truth)
                       for c in family.candidates]
                closest=min(diffs,key=lambda d:(len(d),d))
                row.update(current_scope_covered=any(not d for d in diffs),diagnostic_family_size=len(diffs),
                    closest_ast_difference_paths=closest[:128],ast_paths_truncated=len(closest)>128,
                    difference_top_level=sorted(set(p.split('/')[1] for p in closest)))
            except FileNotFoundError as error:row['diagnostic_status']='missing_private_or_scope_evidence'
            except (ValueError,KeyError,TypeError) as error:
                row.update(diagnostic_status='scope_replay_error',replay_error_type=type(error).__name__,replay_error=safe_error(error))
        rows.append(row)
    stage=Counter();paths=Counter();replay=Counter()
    for row in rows:
        stages={f['stage'] for f in row['recorded_candidate_failures']} if row.get('recorded_candidate_failures') else {row['original_stage']}
        for s in stages:stage[s]+=1
        for p in row.get('closest_ast_difference_paths',[]):paths[p]+=1
        if 'current_scope_covered' in row:replay['scope_covered' if row['current_scope_covered'] else 'scope_still_outside']+=1
        if row['recorded_status']=='proposal_failed':
            replay['proposal_lowers' if any(x['status']=='lowered' for x in row.get('current_proposal_replay',[])) else 'proposal_still_rejected']+=1
    result=dict(schema_version='xgap-post-seal-nl-failure-audit-v1',sealed_statuses=dict(all_statuses),failure_cells=len(rows),
        failures_by_stage=dict(stage),ast_difference_path_counts=dict(paths),current_offline_replay=dict(replay),rows=rows,
        identity_version=IDENTITY_VERSION,equivalence_adapter_replayed=replay_equivalence,
        edge_type_domain_adapter_replayed=replay_edge_type_domains,
        private_access='Post-seal diagnostic only; AST values omitted; no feedback to online methods',
        closest_candidate='Diagnostic minimum AST differences only; never an online selection or repaired answer',
        method_results_created=0,recorded_statuses_changed=0,model_calls=0,backend_calls=0)
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    (root/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence-root','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--pin-mirror',action='append',default=[],help='Original absolute prefix=extracted mirror root; repeatable')
    p.add_argument('--case-bank-root',action='append',default=[],help='Post-seal source case-bank mirror; repeatable')
    p.add_argument('--replay-equivalence',action='store_true')
    p.add_argument('--replay-edge-type-domains',action='store_true',help='Explicit public edge-domain selector adapter; old scope bytes/statuses stay unchanged')
    a=vars(p.parse_args());a['mappings']=[s.split('=',1) for s in a.pop('pin_mirror')];a['case_banks']=a.pop('case_bank_root')
    result=audit(**a)
    print(json.dumps({k:result[k] for k in ('sealed_statuses','failure_cells','failures_by_stage','current_offline_replay','model_calls','backend_calls')}))
