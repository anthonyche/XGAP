"""Source/scale input integrity on a tiny graph, without database/model calls."""
import json
import sqlite3
import pytest
from xgap.experiments.ch6_fact_index import CORES,add_nodes,add_edges,pin,write
from xgap.experiments.ch6_heldout import publish
from xgap.experiments.ch6_rebound_cohort import publish as rebound,select_cases
from xgap.experiments.ch6_cost_pool import load
from xgap.experiments.ch6_core_profile import publish as profile
from xgap.experiments.ch6_profile_revision import revise
from test_ch6_fact_materialization import CoreMaterializationTest
from test_compact_roles_v2 import PARENT,PIN


def test_real_source_rebinding_keeps_queries_answers_and_sampling_frame(tmp_path):
    db=sqlite3.connect(tmp_path/'facts.sqlite')
    db.executescript('CREATE TABLE nodes(id TEXT PRIMARY KEY,kind TEXT,props TEXT);'
        'CREATE TABLE edges(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE,src TEXT,dst TEXT,ts INTEGER,value REAL);')
    add_nodes(db,[dict(id='p'+str(i),type='Person',gender='male' if i%2 else 'female') for i in range(8)])
    add_edges(db,[dict(id='k'+str(i),**{'from':'p'+str(i),'to':'p'+str((i+1)%8)},timestamp=i,value=1) for i in range(8)])
    db.close();index=tmp_path/'index.json'
    write(index,dict(schema_version='xgap-ch6-fact-index-v1',success=True,dataset='D1',core=CORES['D1'],database=pin(tmp_path/'facts.sqlite'),scope_cut_ms=4))
    fixture=CoreMaterializationTest();prepared={}
    for sources in (2,8):
        root=tmp_path/str(sources);root.mkdir();fixture.generate(root/'facts',index,source_count=sources)
        parent=profile(root/'facts/receipt.json',PARENT,PIN,root/'profile')
        write(root/'build.json',dict(profile=parent));write(root/'prepared.json',dict(success=True,profile=parent,input_seal=pin(root/'build.json'),stores={}))
        prepared[sources]=revise(pin(root/'prepared.json'),root/'revised')
    base_profile=load(prepared[2])['profile']
    parent=publish(index_receipt=index,profile_path=base_profile['path'],profile_sha256=base_profile['sha256'],
        output=tmp_path/'test',split='test',anchors_per_template=1,deployment_selection='all')
    assert parent['success'],parent
    base=load(parent['bundle']);chosen=select_cases([base]);assert len(chosen)==2
    variant=load(rebound(base_bundles=[parent['bundle']],index_receipt=index,prepared_pin=prepared[8],factor='sources',output=tmp_path/'rebound'))
    assert variant['source_count']==8 and len(variant['cases'])==2
    for before,after in zip(chosen,variant['cases']):
        assert load(before['oracle'])['query']==load(after['oracle'])['query']
        assert load(before['reference'])['rows']==load(after['reference'])['rows']
        assert after['case_id']!=before['case_id'] and after['base_case_id']==before['case_id']
        assert after['source_snapshot_sha256']!=before['source_snapshot_sha256']
        assert after['max_operators']<=64 and len(after['contributing_sources'])==8
        assert (after['actual_N'],after['actual_u'])==(8,3)
    with pytest.raises(ValueError,match='frozen sample'):select_cases([base],per_frame=2)
    with pytest.raises(ValueError,match='Duplicated'):select_cases([base,base])
