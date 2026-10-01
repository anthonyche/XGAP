"""Ranking perturbation exercises the production terminal controller, not runtime."""
import json
import pytest

from xgap.experiments.ch6_cost_selection import select
from xgap.runtime.unified_physical import PhysicalMoves, identity


def test_terminal_only_internal_variants_follow_estimates_with_no_backend_calls():
    from test_unified_actions import fixture
    _,options,calls,family,prepare,_=fixture()
    seed=prepare(family.candidates[0],None)
    alternative=next(iter(PhysicalMoves(family,options['source_schema'],options['backends'],options['physical_profile']).neighbors(0,seed)))
    plans=[seed,alternative];a,b=map(identity,plans)
    query=json.loads(family.candidates[0].query_json)
    for method in ('XGAP','NP','SH','GR'):
        for estimates,winner in (({a:.1,b:.8},a),({a:.8,b:.1},b)):
            picked=select(query,family.source_snapshot,plans,estimates,method,language_version=family.language_version)
            assert picked['plan_id']==winner
            assert picked['backend_calls']==picked['model_calls']==0
    assert not calls
    with pytest.raises(ValueError,match='External TS'):
        select(query,family.source_snapshot,plans,{a:0,b:1},'TS',language_version=family.language_version)
