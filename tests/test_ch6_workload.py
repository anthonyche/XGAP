from copy import deepcopy
import pytest
from xgap.experiments.ch6_sources import finish,verified_wikidata_mapping
from xgap.experiments.ch6_workload import make_query,reference,build_development


def tiny():
    nodes=[dict(id=i,type='Account',blocked=False) for i in ('a','b','c')]
    edges=[dict(id='e1',**{'from':'a','to':'b'},amount=2,timestamp=1),
           dict(id='e2',**{'from':'a','to':'b'},amount=3,timestamp=2),
           dict(id='e3',**{'from':'b','to':'c'},amount=5,timestamp=3),
           dict(id='e4',**{'from':'c','to':'a'},amount=7,timestamp=4)]
    return finish('D3',nodes,edges,kind='Account',relation='TRANSFER',measure='amount',control='blocked',control_values=[False,True],
                  provenance={'source':'authored unit fixture'},sum_meaningful=True)


def test_independent_reference_preserves_parallel_edge_contributions_and_cycle_closure():
    facts=tiny()
    assert reference(make_query(facts,'S07','a'),facts)==[{'result':'b','total':5}]
    assert reference(make_query(facts,'S06','a'),facts)==[{'result':'b','total':2}]
    assert reference(make_query(facts,'S04','a'),facts)==[{'result':'b','via':'c'}]
    assert reference(make_query(facts,'S05','a'),facts)==[{'result':'b','distance':1},{'result':'c','distance':2}]


def test_mapping_rejects_missing_and_ambiguous_without_name_fallback():
    links={'1':{'imdbId':'114709'},'2':{'imdbId':'113497'},'3':{'imdbId':'999999'}}
    claims=[dict(property='P345',value='tt0114709',qid='Q1',revision=1),
            dict(property='P345',value='tt0113497',qid='Q2',revision=2),
            dict(property='P345',value='tt0113497',qid='Q3',revision=3)]
    accepted,rejected=verified_wikidata_mapping(links,claims)
    assert len(accepted)==1 and {r['reason'] for r in rejected}=={'missing','ambiguous'}
    with pytest.raises(ValueError):verified_wikidata_mapping(links,[dict(property='P345',value='tt0114709',qid='Q1')])


def test_builder_hides_intent_and_reserves_template_families(tmp_path):
    import json
    root=tmp_path/'dev';r=build_development(tiny(),root)
    assert r['cases']==10
    public=(root/'public_cases.jsonl').read_text();controlled=(root/'controlled_states.jsonl').read_text()
    assert all(k not in public+controlled for k in ('intended_query','selected_candidate','reference_rows'))
    split=json.loads((root/'split_manifest.json').read_text())
    assert not split['test'] and not split['formal_test_published']
    with pytest.raises(FileExistsError):build_development(tiny(),root)
