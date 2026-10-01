"""Public bounded workload shapes and independent original-CSV references.

No answer-driven sampling, physical plans, native queries or estimator inputs.
Template/anchor/window choice must be sealed before calling reference_rows.
"""
from collections import defaultdict
from decimal import Decimal

from xgap.agent.intent_certificate import IntentSlot, fingerprint
from xgap.semantic.intent_scope import ScopeDomain, ScopePolicy, construct_scope


TEMPLATES = ('temporal_reachability', 'outgoing_transfer_summary', 'company_transfer_summary')


def ref(variable, property):
    return {'var': variable, 'property': property}


def predicate(variable, property, op, value, *, temporal=False):
    return {'left': ref(variable, property), 'op': op, 'right': {'value': value},
            'value_type': 'timestamp_ms' if temporal else 'scalar'}


def node(variable, kind):
    return {'var': variable, 'type': 'XGAPFinBench'+kind, 'entity': None}


def make_family(template, anchor, lower, upper, snapshot):
    if template not in TEMPLATES or not lower < upper:
        raise ValueError('Known template and increasing frozen time bounds required')
    anchor = str(anchor)
    is_path = template == 'temporal_reachability'
    is_company = template == 'company_transfer_summary'
    anchor_var = 'company' if is_company else 'start'
    query = dict(nodes=[node('start','Account'),node('recipient','Account')],edges=[],path=None,
        where=[predicate(anchor_var,'id','eq',anchor),predicate('recipient','isBlocked','eq',False)],
        select={},contribution_by=None,order_by=[],limit=None)
    blocked = ScopeDomain(IntentSlot('blocked_status',('where',1,'right','value'),weight=2),
                          (False,True),{'property':'isBlocked','operators':['eq']})
    if is_path:
        query['path'] = dict(var='reach',type='TRANSFERRED_TO',source='start',target='recipient',
            min_hops=1,max_hops=1,mode='ACYCLIC',time=dict(property='createTime',lower=lower,upper=upper,
            lower_inclusive=False,upper_inclusive=False,increasing=True))
        query['select'] = {'account_id':ref('recipient','id'),'distance':ref('reach','length')}
        query['order_by'] = [{'field':f,'direction':'asc'} for f in ('distance','account_id')]
        domains = (ScopeDomain(IntentSlot('hops',('path','max_hops'),weight=2),(1,2)),blocked,
            ScopeDomain(IntentSlot('lower_inclusive',('path','time','lower_inclusive')),(False,True)),
            ScopeDomain(IntentSlot('upper_inclusive',('path','time','upper_inclusive')),(False,True)))
        question = (f'From account business ID {anchor}, follow outgoing TRANSFERRED_TO edges on acyclic paths '
            f'with strictly increasing createTime between {lower} and {upper}. The maximum depth (one or two), '
            'required recipient isBlocked flag (true or false), and inclusivity of each time boundary are '
            'unspecified conventions; clarify them with the user when necessary. Paths start at one hop. '
            'Return distinct account_id and distance, ordered by distance then account_id ascending, without a limit.')
        normalization = {'account_id':'text','distance':'integer'}
    else:
        query['edges'] = [dict(var='transfer',type='TRANSFERRED_TO',source='start',target='recipient')]
        if is_company:
            query['nodes'].append(node('company','Company'))
            query['edges'].append(dict(var='ownership',type='OWNS_ACCOUNT',source='company',target='recipient'))
        query['where'] += [predicate('transfer','createTime','ge',lower,temporal=True),
                           predicate('transfer','createTime','le',upper,temporal=True)]
        query['select'] = {'account_id':ref('recipient','id'),
            'total':{'aggregate':'sum','field':ref('transfer','amount'),'distinct':False}}
        query['contribution_by'] = ['transfer']
        query['order_by'] = [{'field':'account_id','direction':'asc'}]
        domains = (ScopeDomain(IntentSlot('aggregation',('select','total','aggregate'),weight=2),('sum','count')),
            blocked,ScopeDomain(IntentSlot('lower_comparison',('where',2,'op')),('ge','gt'),
                                 {'property':'createTime','operators':['ge','gt']}),
            ScopeDomain(IntentSlot('upper_comparison',('where',3,'op')),('le','lt'),
                        {'property':'createTime','operators':['le','lt']}))
        subject = (f'For recipient accounts owned by company business ID {anchor}, consider incoming transfers '
                   'from any account' if is_company else
                   f'For outgoing transfers from account business ID {anchor}, consider their recipient accounts')
        question = (subject+f' with transfer createTime between {lower} and {upper}. The required recipient '
            'isBlocked flag (true or false), inclusivity of each time boundary, and total aggregation '
            '(sum of transfer amount or count of non-null transfer amounts) are unspecified conventions; '
            'clarify them with the user when necessary. Each distinct transfer edge contributes once; '
            'parallel transfers remain separate. Group by recipient business ID and return account_id and total, '
            'ordered by account_id ascending, without a limit. Do not create rows for recipients with no qualifying transfers.')
        normalization = {'account_id':'text','total':'decimal3-half-up'}
    policy = ScopePolicy('ch7-finbench-'+fingerprint([template,anchor,lower,upper]),domains,language_version='v2')
    family = construct_scope([query],policy,snapshot)
    return family,policy,question,{'schema_version':'xgap-row-normalization-v1','fields':normalization}


def reference_rows(data, template, query):
    """Plain CSV scan/DFS; no shared compiler, planner or backend evaluator."""
    if template not in TEMPLATES:
        raise ValueError('Unknown reference template')
    conditions = query['where']
    anchor = next(c['right']['value'] for c in conditions if c['left']['property']=='id')
    blocked = next(c['right']['value'] for c in conditions if c['left']['property']=='isBlocked')
    if type(blocked) is not bool:
        raise ValueError('Boolean recipient flag required')
    eligible = lambda account: data.accounts[account]['isBlocked'] == ('true' if blocked else 'false')
    if template == 'temporal_reachability':
        path=query['path'];window=path['time'];found=set()
        if path['max_hops'] not in (1,2) or path['mode']!='ACYCLIC' or not window['increasing']:
            raise ValueError('Reference admits increasing acyclic paths of one or two hops')
        def visit(current, visited, last, depth):
            if depth == path['max_hops']:return
            for transfer in data.outgoing.get(current,()):
                stamp=transfer.create_time
                if (transfer.to_id in visited or last is not None and stamp<=last or
                    stamp<window['lower'] or stamp==window['lower'] and not window['lower_inclusive'] or
                    stamp>window['upper'] or stamp==window['upper'] and not window['upper_inclusive']):continue
                if eligible(transfer.to_id):found.add((depth+1,transfer.to_id))
                visit(transfer.to_id,visited|{transfer.to_id},stamp,depth+1)
        visit(anchor,{anchor},None,0)
        return [{'account_id':account,'distance':distance} for distance,account in sorted(found)]
    low=next(c for c in conditions if c['left']['property']=='createTime' and c['op'] in ('ge','gt'))
    high=next(c for c in conditions if c['left']['property']=='createTime' and c['op'] in ('le','lt'))
    buckets=defaultdict(list)
    for transfer in data.transfers:
        if (template=='outgoing_transfer_summary' and transfer.from_id!=anchor or
            template=='company_transfer_summary' and data.company_by_account.get(transfer.to_id)!=anchor or
            not eligible(transfer.to_id)):continue
        stamp=transfer.create_time
        if (stamp<low['right']['value'] or stamp==low['right']['value'] and low['op']=='gt' or
            stamp>high['right']['value'] or stamp==high['right']['value'] and high['op']=='lt'):continue
        buckets[transfer.to_id].append(transfer.amount)
    aggregation=query['select']['total']['aggregate']
    if aggregation not in ('sum','count'):raise ValueError('Reference admits sum/count')
    return [{'account_id':account,'total':str(sum(values,Decimal(0)) if aggregation=='sum' else len(values))}
            for account,values in sorted(buckets.items())]
