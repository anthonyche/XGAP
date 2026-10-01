"""Frozen source-only sampling and independent CSV-reference evaluation inputs.

No model, native engine, estimator fit or previous answer is called/read. Gold
programs and queries are separate artifacts, never ordinary inference inputs.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

from xgap.experiments.finbench_rdf import FAMILIES, fixed_semantics_query
from xgap.experiments.finbench_semantic import financial_program
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows


DESIGN = Path('experiments/protocols/finbench_one_shot_population_v1.json')


def milliseconds(text):
    epoch = datetime(1970, 1, 1)
    delta = datetime.strptime(text, '%Y-%m-%d %H:%M:%S.%f')-epoch
    return (delta.days*86400+delta.seconds)*1000+delta.microseconds//1000


def timestamp(value):
    return (datetime(1970, 1, 1)+timedelta(milliseconds=value)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def overlap(left, right):
    a,b,c,d = (milliseconds(p[k]) for p in (left,right) for k in ('start_time','end_time'))
    return Decimal(max(0,min(b,d)-max(a,c)))/Decimal(max(b,d)-min(a,c))


def select_population(data, old_instances, design):
    """Equal allocation across four source-structure/time rank strata.

    A group is an anchor within F1/F2, or a disjoint time interval within F3.
    No correctness or nonempty-answer test participates in this function.
    """
    old = {f:[q['parameters'] for q in old_instances if q['family_id']==f] for f in FAMILIES}
    blocked_people = {p['person_id'] for p in old[FAMILIES[0]]}
    blocked_accounts = {p['start_account_id'] for p in old[FAMILIES[1]]}
    degree = Counter()
    for t in data.transfers:
        owner = data.person_by_account.get(t.from_id)
        if owner is not None and t.to_id in data.company_by_account: degree[owner] += 1
    window = {'start_time':data.minimum_transfer_time, 'end_time':data.maximum_transfer_time}
    frames = [
        [{'key':p,'feature':degree[p], 'parameters':{**window,'person_id':p}}
            for p in sorted(set(data.person_by_account.values())-blocked_people)],
        [{'key':a,'feature':len(data.outgoing.get(a,())), 'parameters':{**window,'start_account_id':a,'max_hops':3}}
            for a in sorted(set(data.accounts)-blocked_accounts)], []]
    risks = sorted({m['riskLevel'] for m in data.media.values() if m['riskLevel']})
    if not risks: raise ValueError('No source risk labels')
    start,end = milliseconds(window['start_time']),milliseconds(window['end_time'])+1
    bins = design['time_bins']
    if end-start < bins: raise ValueError('Insufficient distinct millisecond time bins')
    excluded_intervals = 0
    for index in range(bins):
        p = {'start_time':timestamp(start+(end-start)*index//bins),
            'end_time':timestamp(start+(end-start)*(index+1)//bins),
            'risk_level':risks[index%len(risks)],'top_k':10}
        if any(p['risk_level']==o['risk_level'] and overlap(p,o)>=Decimal(design['near_duplicate_interval_iou']) for o in old[FAMILIES[2]]):
            excluded_intervals += 1
            continue
        frames[2].append({'key':'time-bin-'+str(index),'feature':index,'parameters':p})
    counts = design['per_stratum_split_counts']; per_stratum = sum(counts.values())
    selected, summaries = [], []
    for family, frame in zip(FAMILIES,frames):
        frame = sorted(frame,key=lambda c:(c['feature'],c['key']))
        bands = [[] for _ in range(design['strata'])]
        for index,candidate in enumerate(frame): bands[index*len(bands)//len(frame)].append(candidate)
        summary = {'family':family,'candidate_count':len(frame),'frame_sha256':content_hash(frame),
            'stratum_sizes':[len(b) for b in bands], 'selected_count':per_stratum*len(bands)}
        for stratum,band in enumerate(bands):
            if len(band)<per_stratum: raise ValueError('Insufficient candidate frame; no silent sample reduction: '+family)
            def score(c, purpose): return content_hash([design['seed'],purpose,family,stratum,c['key']])
            chosen = sorted(band,key=lambda c:(score(c,'sample'),c['key']))[:per_stratum]
            chosen.sort(key=lambda c:(score(c,'split'),c['key']))
            position = 0
            for split,count in counts.items():
                for c in chosen[position:position+count]:
                    identifier = 'FBNS-'+str(FAMILIES.index(family)+1)+'-'+content_hash([family,c['key']])[:16]
                    selected.append({'question_id':identifier,'family_id':family,'group_key':c['key'],
                        'split':split,'stratum':stratum,'structural_feature':c['feature'],
                        'sample_score':score(c,'sample'),'parameters':c['parameters']})
                position += count
        summaries.append(summary)
    return selected, {'frames':summaries,'excluded_people':len(blocked_people),
        'excluded_accounts':len(blocked_accounts),'excluded_near_duplicate_intervals':excluded_intervals}


def normalization(family):
    fields = ({'company_id':'text','account_id':'text','total_amount':'decimal3-half-up'} if family==FAMILIES[0] else
        {'other_id':'text','account_distance':'integer','medium_id':'text','medium_type':'text'} if family==FAMILIES[1] else
        {'company_id':'text','total_amount':'decimal3-half-up'})
    return {'schema_version':'xgap-row-normalization-v1','fields':fields}


def reference_rows(data, family, p):
    """Direct independent evaluation over original CSV records, not XGAP plans."""
    start,end = p['start_time'],p['end_time']
    if family==FAMILIES[0]:
        totals = defaultdict(Decimal)
        for t in data.transfers:
            company = data.company_by_account.get(t.to_id)
            if (data.person_by_account.get(t.from_id)==p['person_id'] and company is not None
                    and data.accounts[t.to_id]['isBlocked']=='true' and start<=t.create_time<=end):
                totals[company,t.to_id] += t.amount
        return [{'company_id':c,'account_id':a,'total_amount':str(v)} for (c,a),v in sorted(totals.items())]
    if family==FAMILIES[1]:
        rows = set()
        def visit(account, visited, last_time, depth):
            if depth==p['max_hops']: return
            for edge in data.outgoing.get(account,()):
                if edge.to_id in visited or not start<=edge.create_time<=end or last_time is not None and edge.create_time<=last_time: continue
                for medium in data.media_by_account.get(edge.to_id,()):
                    if data.media[medium]['isBlocked']=='true':
                        rows.add((edge.to_id,depth+1,medium,data.media[medium]['mediumType']))
                visit(edge.to_id,visited|{edge.to_id},edge.create_time,depth+1)
        visit(p['start_account_id'],{p['start_account_id']},None,0)
        return [dict(zip(('other_id','account_distance','medium_id','medium_type'),row))
            for row in sorted(rows,key=lambda r:(r[1],r[0],r[2]))]
    if family!=FAMILIES[2]: raise ValueError('Unknown reference family')
    eligible = {a for a,media in data.media_by_account.items() if a in data.company_by_account
        and any(data.media[m]['riskLevel']==p['risk_level'] for m in media)}
    totals = defaultdict(Decimal)
    for t in data.transfers:
        if t.to_id in eligible and start<=t.create_time<end: totals[data.company_by_account[t.to_id]] += t.amount
    return [{'company_id':c,'total_amount':str(v)} for c,v in sorted(totals.items(),key=lambda r:(-r[1],r[0]))[:p['top_k']]]


def question_text(family,p,variant):
    """Equivalent authored wordings, chosen by hash; not separate query groups."""
    window=f"between {p['start_time']} and {p['end_time']}"
    if family==FAMILIES[0]:
        lead = [f"Find direct transfers from accounts owned by the person with business ID {p['person_id']} to blocked company-owned accounts",
            f"Which blocked company-owned accounts received direct transfers from accounts owned by person {p['person_id']} (business ID)",
            f"For the person whose business ID is {p['person_id']}, list blocked company-owned accounts that received direct transfers from this person's accounts"][variant]
        return (lead+f", {window}, including both bounds. Sum transfer amounts for each destination account and its owning company, "
            "counting parallel transfers separately. Return all company_id, account_id (business IDs) and total_amount rows, ordered by company_id then account_id ascending.")
    if family==FAMILIES[1]:
        lead=["Find accounts reachable", "List accounts that can be reached", "Report reachable destination accounts"][variant]
        return (lead+f" from the account with business ID {p['start_account_id']} by one to three outgoing transfers {window}, inclusive. "
            "Require strictly increasing edge timestamps and no repeated account, including no return to the starting account. "
            "For each reachable account signed into by a blocked medium, return distinct other_id (account business ID), account_distance (path length), "
            "medium_id (medium business ID), and medium_type. Different paths with the same endpoint and length count once per medium. "
            "Sort by account_distance, other_id, then medium_id ascending; return all rows.")
    lead=["Rank companies", "Find the leading companies", "List companies in descending rank"][variant]
    return (lead+f" by the sum of incoming transfers to their accounts {window}, including the lower bound and excluding the upper bound. "
        f"An account qualifies if any medium whose riskLevel is exactly {json.dumps(p['risk_level'])} signed into it. "
        "Count each qualifying account once even if several media qualify, and count parallel transfers separately. "
        f"Return the top {p['top_k']} rows as company_id (business ID) and total_amount, ordered by total_amount descending and company_id ascending for ties.")


def build_population(*, archive, lock_path, excluded_public, output, design_path=DESIGN):
    started=time.perf_counter(); root=Path(output); root.mkdir(parents=True,exist_ok=False)
    design_bytes=Path(design_path).read_bytes(); design=json.loads(design_bytes)
    if (design['schema_version']!='xgap-finbench-one-shot-population-design-v1'
            or design['strata']!=4 or design['time_bins']!=80 or design['max_hops']!=3 or design['top_k']!=10
            or design['per_stratum_split_counts']!={'development':2,'estimator_training':4,'evaluation':4}
            or design['sampling_uses_method_outputs'] is not False or design['sampling_uses_answer_nonemptiness'] is not False):
        raise ValueError('The frozen initial design cannot silently change population or sampling rules')
    lock_bytes=read_pinned(lock_path,design['source_lock_sha256'])
    old_bytes=read_pinned(excluded_public,design['excluded_public_sha256']); old=json.loads(old_bytes)['instances']
    lock=load_finbench_artifact_lock(lock_path)
    data=load_finbench_query_data(archive,lock)
    selected,summary=select_population(data,old,design)
    dataset={'dataset_id':'financial-sf0.1-one-shot','version':lock.artifact.digest_value}
    if len(selected)!=120: raise ValueError('The approved initial cohort requires120 parameter groups')
    # Seal selection before computing any reference answer.
    selection=write_once(root/'selection.json',{'design':design,'selected':selected,'source_only_summary':summary,
        'method_output_reads':0,'answer_reads_at_selection':0})
    for name in ('requests','references','gold'): (root/name).mkdir()
    empty=Counter(); paths=[]
    for item in selected:
        qid,family,p=item['question_id'],item['family_id'],item['parameters']
        variant=int(content_hash([design['seed'],'wording',qid]),16)%3
        request={'schema_version':'xgap-one-shot-evaluation-request-v1','question_id':qid,
            'question':question_text(family,p,variant),'population':design['population_id'],
            'exposure':item['split']+':new_anchor_or_disjoint_window;templates_shared;not_template_held_out'}
        rows=normalize_rows(reference_rows(data,family,p),normalization(family))
        empty[family,item['split'],not rows]+=1
        reference={'schema_version':'xgap-normalized-row-reference-v1','question_id':qid,'dataset':dataset,
            'ordered':True,'rows':rows,'normalization':normalization(family),
            'provenance':{'kind':'independent_decimal_csv_evaluator','source_archive_sha256':lock.artifact.digest_value}}
        program,sources=financial_program('F'+str(FAMILIES.index(family)+1),p)
        files={'request':write_once(root/'requests'/(qid+'.json'),request),
            'reference':write_once(root/'references'/(qid+'.json'),reference),
            'gold':write_once(root/'gold'/(qid+'.json'),{'family':family,'parameters':p,'program':program.to_dict(),
                'operator_sources':sources,'reference_sparql':fixed_semantics_query(family,p),'runtime_input':False})}
        paths.append({'question_id':qid,'split':item['split'],'family':family,'wording_variant':variant,'files':files})
    report={'schema_version':'xgap-finbench-one-shot-population-v1','dataset':dataset,'population_id':design['population_id'],
        'selection':selection,'design_sha256':hashlib.sha256(design_bytes).hexdigest(),
        'source_lock_sha256':hashlib.sha256(lock_bytes).hexdigest(),'excluded_public_sha256':hashlib.sha256(old_bytes).hexdigest(),
        'instance_count':len(selected),'split_counts':dict(Counter(i['split'] for i in selected)),
        'emptiness':[{'family':f,'split':s,'empty':e,'count':n} for (f,s,e),n in sorted(empty.items())],
        'artifacts':paths,'offline_preparation_ms':(time.perf_counter()-started)*1000,
        'method_runs':0,'model_calls':0,'backend_calls':0,'fit_calls':0,'formal_campaign_ready':False}
    return write_once(root/'manifest.json',report)
