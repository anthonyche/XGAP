"""Chapter 6 figure and launch contracts. No measurements are manufactured here.

This module is deliberately independent of model/backend imports. It describes
one-factor experiments, aliases repeated reference measurements, and validates
the evidence required before an experimental release can be executed.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
import csv
import hashlib
import json
import math
from pathlib import Path

METHODS = {
    'XGAP': 'xgap-unified-lookahead',
    'NP': 'xgap-unified-no-probe',
    'SH': 'xgap-unified-shallow',
    'GR': 'xgap-unified-myopic',
    'TS': 'aruqula-fedx',
}
METHOD_ORDER = tuple(METHODS)
DEFAULTS = dict(dataset='D1', workload='W3', depth=2, horizon=12,
                candidates=8, unbound_fields=3, epsilon='1/3',
                probe_price=1, clarification_price=1, sources=2, graph_scale=1)
STATES = ('pending', 'measured', 'fixed_reference', 'unsupported_deployment',
          'unsupported_interface', 'unscorable_metric', 'resource_censored',
          'failed', 'not_run')


@dataclass(frozen=True)
class Figure:
    id: str
    caption: str
    x: str
    y: str
    levels: tuple
    unit: str
    cohort: str
    track: str
    statistic: str = 'mean'
    note: str = ''


FIGURES = (
    Figure('E1','End-to-end latency vs. dataset','dataset','e2e_ms',('D1','D2','D3'),'ms','overall','nl',
           note='Native and same-facts RDF panels; no speedup across deployments.'),
    Figure('E2','Backend calls vs. dataset','dataset','backend_calls',('D1','D2','D3'),'calls','overall','nl',
           note='All actual source attempts, including recovered and terminal failures.'),
    Figure('E3','Request latency vs. candidate count','candidates','request_ms',(10,50,100,500,1000),'ms','candidate','controlled'),
    Figure('E4','Request latency vs. unbound field count','unbound_fields','request_ms',(1,2,3,5,8),'ms','fields','controlled',
           note='N=8 uses an explicit finite correlated family; do not claim independent binary Cartesian domains.'),
    Figure('E5','Planning time vs. lookahead depth','depth','planning_ms',(1,2,3,5,10),'ms','depth','controlled',
           note='Fixed-D polynomial theorem does not imply polynomial dependence on D; report cap hits.'),
    Figure('E6','Request latency vs. action limit','horizon','request_ms',(2,4,8,12,16),'ms','horizon','controlled',
           note='Report completion/coverage beside the figure; early failure is not a speedup.'),
    Figure('E7','Backend calls vs. probe price ratio','probe_price','backend_calls',(.1,.5,1,2,5),'calls','probe_price','controlled'),
    Figure('E8','Clarification calls vs. clarification price ratio','clarification_price','clarification_calls',(.1,.5,1,2,5),'calls','clarification_price','controlled'),
    Figure('F1','Interpretation loss vs. dataset','dataset','interpretation_loss',('D1','D2','D3'),'loss','overall','nl',
           note='Report scoring coverage; unalignable external queries are not assigned zero loss.'),
    Figure('F2','Correct-answer rate vs. dataset','dataset','answer_em',('D1','D2','D3'),'fraction','overall','nl',
           note='All applicable requests, including wrong answers, timeouts and safe non-answers.'),
    Figure('F3','Maximum interpretation loss vs. tolerance','epsilon','interpretation_loss',('0','1/6','1/3','1/2','1'),'loss','epsilon','controlled','max',
           'Empirical d is distinct from rho; y=epsilon is a reference, not proof of certification.'),
    Figure('F4','Answer F1 vs. tolerance','epsilon','answer_f1',('0','1/6','1/3','1/2','1'),'fraction','epsilon','controlled'),
    Figure('F5','Trace cost vs. lookahead depth','depth','trace_cost',(1,2,3,5,10),'work_units','depth','controlled'),
    Figure('F6','Terminal cost gap vs. estimation error','eta','terminal_cost_gap',(0,.05,.1,.2,.5),'normalized_cost','estimator','offline',
           note='Five methods. Fixed Q and same deployment. 2eta only for exact estimated argmin on the audited retained pool; no policy guarantee.'),
    Figure('F7','Trace cost vs. algorithm variant','method','trace_cost',METHOD_ORDER,'work_units','variant','nl',
           note='Five bars, not a five-by-five diagonal matrix; reuse matched D1 W3 overall records.'),
    Figure('F8','Correct-answer rate vs. algorithm variant','method','answer_em',METHOD_ORDER,'fraction','variant','nl'),
    Figure('S1','Planning time vs. candidate count','candidates','planning_ms',(16,64,256,1024),'ms','candidate_scaling','controlled',
           note='Log-log; resource-censored points remain present and are not extrapolated.'),
    Figure('S2','Request latency vs. source count','sources','request_ms',(2,4,8),'ms','sources','controlled',
           note='Same total facts/hardware. Source partition changes must preserve every reference answer.'),
    Figure('S3','Request latency vs. graph size','graph_scale','request_ms',(.25,1,4),'ms','scale','controlled',
           note='Record actual nodes, edges, triples; replicas/synthetic extensions labeled explicitly.'),
    Figure('S4','Peak coordinator memory vs. graph size','graph_scale','coordinator_rss_bytes',(.25,1,4),'bytes','scale','controlled'),
    Figure('C1','Action and state vs. round','round','action_state',('realized_trace',),'categorical','case','trace',
           note='Five method panels; actual rounds only. TS original action sequence, no invented AND/OR tree.'),
)


def registry():
    return dict(schema_version='xgap-ch6-figure-contract-v1', figure_count=21,
        methods=METHODS, method_order=list(METHOD_ORDER), defaults=DEFAULTS,
        figures=[{**asdict(f), 'methods':list(METHOD_ORDER)} for f in FIGURES],
        tables=[dict(id='T1',columns=['method','round','action','observation','preferred_query',
            'rho','preferred_plan','evidence_pin'], counts_as_figure=False)],
        missing_value_rule='null plus explicit status/reason; never zero or an invented curve',
        reference_rule='one frozen observation set referenced at all inapplicable levels; no extra samples',
        deployment_rule='native TS unsupported; paired comparisons require same dataset, deployment, input and timing scope',
        source_attachment_sha256='TO_BE_BOUND_BY_PREPARATION_SCRIPT')


def parameter_applies(method, parameter):
    if method not in METHODS: raise ValueError('Unknown method')
    if method=='TS':
        return parameter in ('dataset','method','sources','graph_scale','round')
    if method=='SH' and parameter=='depth': return False
    if method=='GR' and parameter=='depth': return False
    if method=='NP' and parameter=='probe_price': return False
    return True


def matrix(*, overall_panels=('native','rdf')):
    """Design cells, not trial observations. All five methods remain visible."""
    rows=[]
    for fig in FIGURES:
        panels=overall_panels if fig.cohort in ('overall','variant') else ('rdf',)
        for panel in panels:
            for level in fig.levels:
                for method in METHOD_ORDER:
                    if fig.x=='method' and method!=level: continue
                    kind='varying'; reason=''; status='pending'; effective=level
                    if method=='TS' and panel=='native':
                        kind='unsupported';status='unsupported_deployment'
                        reason='Original ARUQULA->FedX consumes RDF endpoints, not Neo4j/Fuseki native federation.'
                    elif not parameter_applies(method,fig.x):
                        kind='fixed_reference';effective=DEFAULTS.get(fig.x,0)
                        reason='Original method does not consume this parameter; retain a pinned fixed configuration.'
                    if fig.track=='controlled' and method=='TS':
                        reason+=' TS has no controlled-state entry: separately labeled NL reference only; no paired controlled-vs-NL speedup.'
                    if fig.y=='planning_ms' and method=='TS':
                        status='unscorable_metric';reason+=' Original API exposes no isolated planner timing; total API time is not planning time.'
                    if fig.id=='F6' and method=='TS':
                        reason+=' Requires a returned plan for the identical Q and an audited comparable cost; otherwise unscorable, not zero.'
                    setting=deepcopy(DEFAULTS)
                    if fig.x in setting:setting[fig.x]=effective
                    if method=='SH':setting['depth']=1
                    if method=='GR':setting['depth']=1
                    logical_group='overall' if fig.cohort=='variant' else fig.cohort
                    reference_key=f'{logical_group}:{panel}:{method}:{fig.x}:{effective}'
                    rows.append(dict(figure=fig.id,caption=fig.caption,x_factor=fig.x,x_value=level,
                        y_metric=fig.y,y_unit=fig.unit,statistic=fig.statistic,method=method,
                        method_id=METHODS[method],deployment=panel,input_track=fig.track,
                        timing_scope='nl_reference' if method=='TS' and fig.track=='controlled' else fig.track,
                        configuration_kind=kind,status=status,reason=reason.strip(),
                        reference_key=reference_key,defaults=setting,value=None,ci_low=None,ci_high=None,
                        applicable_requests=None,scored_requests=None,evidence_pin=None))
    return rows


def write_csv(path,rows):
    if not rows:raise ValueError('No rows')
    with Path(path).open('x',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list,tuple)) else v
                             for k,v in row.items()})


def pin_file(path):
    path=Path(path).resolve();h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return dict(path=str(path),sha256=h.hexdigest(),bytes=path.stat().st_size)


def load_pin(pin):
    if (not isinstance(pin,dict) or not Path(pin.get('path','')).is_absolute()
            or pin_file(pin['path'])['sha256']!=pin.get('sha256')):
        raise ValueError('Missing or changed artifact pin')
    return json.loads(Path(pin['path']).read_text())


def audit_observation(row):
    """Refuse convenient but invalid numbers before aggregation/plotting."""
    if row['method'] not in METHODS or row['status'] not in STATES:raise ValueError('Unknown method/status')
    value=row.get('value')
    if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
        raise ValueError('Metric must be finite or null')
    if row['status'] not in ('measured','fixed_reference') and value is not None:
        raise ValueError('Missing/unsupported/failed cell cannot contain an invented metric')
    if row['status'] in ('measured','fixed_reference') and (value is None or not row.get('evidence_pin')):
        raise ValueError('Measured metrics require sealed evidence')
    if row['status']=='fixed_reference' and not row.get('reference_key'):
        raise ValueError('Fixed reference requires the original observation identity')
    return row
