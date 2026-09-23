"""Experimental integrity, input boundaries and capacity regressions, no API."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from xgap.experiments.ch6_formal_protocol import FIGURES,METHOD_ORDER,matrix,audit_observation
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily,IntentSlot
from xgap.agent.unified_contract import UnifiedTerminalContract
from xgap.agent.unified_lookahead import Limits


def test_all_figures_keep_five_methods_single_axes_and_real_reference_identity():
    rows=matrix()
    assert len(FIGURES)==21 and len({f.id for f in FIGURES})==21
    for f in FIGURES:
        group=[r for r in rows if r['figure']==f.id]
        assert {r['method'] for r in group}==set(METHOD_ORDER)
        assert {r['x_factor'] for r in group}=={f.x}
        assert {r['y_metric'] for r in group}=={f.y}
        assert all(r['value'] is None for r in group)
    references=[r for r in rows if r['figure']=='E5' and r['method']=='SH']
    assert len({r['reference_key'] for r in references})==1
    assert all(r['defaults']['depth']==1 for r in references)
    assert len([r for r in rows if r['figure']=='F7' and r['deployment']=='rdf'])==5
    assert all(r['status']=='unsupported_deployment' for r in rows if r['method']=='TS' and r['deployment']=='native')


def test_missing_is_not_zero_or_invented_curve():
    row=next(r for r in matrix() if r['status']=='unsupported_deployment')
    audit_observation(row)
    with pytest.raises(ValueError,match='invented'):audit_observation({**row,'value':0})
    with pytest.raises(ValueError,match='sealed evidence'):audit_observation({**row,'status':'measured','value':1})


def test_large_family_certificate_is_exact_without_quadratic_cache():
    from test_compact_lowering import financial_intents,pred
    q=financial_intents()[1];q['nodes'][0]['entity']=None
    q['where'].append(pred('start','id','eq','0'));slot=IntentSlot('anchor',('where',len(q['where'])-1,'right','value'))
    candidates=[]
    for i in range(1024):
        v=deepcopy(q);v['where'][-1]['right']['value']=str(i)
        candidates.append(IntentCandidate.create(str(i),v))
    family=IntentFamily('capacity-only',tuple(candidates),(slot,),'synthetic-gate',coverage_basis='authored gate')
    contract=UnifiedTerminalContract(family,(),epsilon='1')
    assert contract.check(0)['upper_bound']=={'numerator':1,'denominator':1}
    assert 'distances' not in family.__dict__
    assert family.worst_distance(0,(0,))==0
    with pytest.raises(ValueError,match='1024'):
        replace(family,candidates=(*candidates,IntentCandidate.create('overflow',q)))


def test_on_demand_certificate_matches_all_small_hard_and_soft_bounds():
    from test_intent_certificate import family
    from itertools import combinations
    for hard in (False,True):
        f=family(hard=hard)
        for n in range(1,5):
            for remaining in combinations(range(4),n):
                for selected in remaining:
                    distances=[f.distances[selected][i] for i in remaining]
                    expected=None if None in distances else max(distances)
                    assert f.worst_distance(selected,remaining)==expected


def test_depth_ten_still_preserves_completion_under_search_cap():
    from test_unified_lookahead import Domain,run
    report,calls,executed=run(Domain(True),Limits(depth=10,horizon=2,max_states=1))
    assert report['success'] and calls==['validate','validate'] and executed==['answer']
    with pytest.raises(ValueError):Limits(depth=11)


def test_external_manifest_never_passes_private_inputs_or_native_deployment(tmp_path):
    from test_bounded_joint_batch import fixture
    from run_bounded_joint_batch import validate,FORMAL_SCHEMA
    m=fixture(tmp_path);m['schema_version']=FORMAL_SCHEMA;m['deployment']='rdf';m['external_runtime']=m['prepared']
    c=m['cells'][0];m['cells']=[{k:c[k] for k in ('cell_id','request','reference')}|{'method':'aruqula-fedx'}]
    validate(m)
    m['cells'][0]['oracle']=c['oracle']
    with pytest.raises(ValueError,match='private'):validate(m)
    del m['cells'][0]['oracle'];m['deployment']='native'
    with pytest.raises(ValueError,match='RDF'):validate(m)


def test_incomplete_release_cannot_be_presented_as_ready():
    from xgap.experiments.ch6_release_audit import audit_release
    r=audit_release(dict(schema_version='xgap-ch6-formal-release-v1',methods=list(METHOD_ORDER),
        figures=[f.id for f in FIGURES],automatic_retries=0,method_results_read_at_release=0),free_bytes=10**12)
    assert not r['success'] and r['failed_checks']
