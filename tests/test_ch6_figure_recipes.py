"""Figure aliases must not inflate requests or turn TS timing into planner time."""
from copy import deepcopy
import pytest
from xgap.experiments.ch6_figure_recipes import build


def fixture():
    docs={};entries=[]
    def add(cid,kind,cases,**kw):
        docs[cid]=dict(dataset='D1',deployment='rdf',split='test',cases=cases,**kw)
        entries.append(dict(cohort_id=cid,kind=kind,bundle=cid,unit_prefix=cid+'-final'))
    for dataset in ('D1','D2','D3'):
        for deployment in ('native','rdf'):
            cid=dataset+'-'+deployment
            cases=[dict(case_id=cid+'-'+s,stratum=s,workload='W3') for s in ('uniform','active-anchor')]
            add(cid,'overall',cases);docs[cid].update(dataset=dataset,deployment=deployment)
    cases=[]
    for factor,levels in [('N',(10,50,100,500,1000,16,64,256,1024)),('u',(1,2,3,5,8))]:
        for level in levels:
            for s in ('uniform','active-anchor'):
                cases.append(dict(case_id=f'{factor}-{level}-{s}',factor=factor,level=level,stratum=s))
    add('nu','factor',cases,schema_version='xgap-ch6-factor-inputs-v1')
    for factor,levels in [('sources',(2,4,8)),('graph_scale',(.25,1,4))]:
        for level in levels:
            cid=f'{factor}-{level}'
            add(cid,'factor',[dict(case_id=cid+'-'+s,stratum=s) for s in ('uniform','active-anchor')],
                schema_version='xgap-ch6-deployment-factor-v1',factor=factor,level=level)
    return dict(schema_version='xgap-ch6-figure-recipe-input-v1',method_results_read=0,repetitions=3,
                probe_axis_active=False,cohorts=entries),docs


def test_all_figures_reuse_fixed_references_and_never_merge_nl_with_controlled():
    spec,docs=fixture();r=build(spec,load=docs.__getitem__)
    assert r['counts']['figures']==21 and r['counts']['positions']==390
    def row(f,m,x):return next(d for d in r['recipes'] if (d['figure'],d['method'],d['x_value'])==(f,m,x))
    assert row('E1','XGAP','D1')['future_cells']==row('F2','XGAP','D1')['future_cells']
    assert row('F3','XGAP','1/3')['future_cells']==row('F4','XGAP','1/3')['future_cells']
    assert row('E5','SH',1)['future_cells']==row('E5','SH',10)['future_cells']
    assert row('E7','XGAP',.1)['future_cells']==row('E7','XGAP',5)['future_cells']
    assert row('E7','XGAP',.1)['inactive_factor']
    assert row('E3','TS',10)['future_cells']==row('E3','TS',1000)['future_cells']
    assert row('E5','TS',2)['status']=='unscorable_metric' and not row('E5','TS',2)['future_cells']
    assert row('S2','TS',2)['future_cells']!=row('S2','TS',8)['future_cells']
    assert len(row('C1','XGAP','realized_trace')['future_cells'])==1
    controlled=row('E5','XGAP',2)['future_cells'];nl=row('F7','XGAP','XGAP')['future_cells']
    assert not {d['unit_id'] for d in controlled}&{d['unit_id'] for d in nl}
    assert r['counts']['proposed_method_requests']==r['counts']['overall_unique_cases']*12+6*3+480+360+36
    assert r['model_calls']==r['backend_calls']==r['submitted_jobs']==0 and not r['formal_campaign_ready']


def test_missing_level_and_outcome_selection_are_not_silently_omitted():
    spec,docs=fixture();bad=deepcopy(spec);bad['method_results_read']=1
    with pytest.raises(ValueError):build(bad,load=docs.__getitem__)
    docs['sources-8']['level']=4
    with pytest.raises(ValueError,match='Unique deployment'):build(spec,load=docs.__getitem__)


def test_original_unit_identity_is_not_replaced_by_duplicate_work():
    spec,docs=fixture();r=build(spec,load=docs.__getitem__)
    assert len(r['unit_requests'])==36
    assert all(u['figures'] for u in r['unit_requests'])
    assert sum(u['existing_preparation'] for u in r['unit_requests'])==13
    assert len([u for u in r['unit_requests'] if u['ts_nl_reference']])==6
