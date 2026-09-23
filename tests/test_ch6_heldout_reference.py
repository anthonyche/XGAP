"""Changed source-reference and publication contracts on a tiny parallel-edge graph."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from xgap.experiments.ch6_fact_index import CORES,add_nodes,add_edges,pin,write
from xgap.experiments.ch6_heldout import TEMPLATES,template_query,make_family,structure_identity,choose_anchors
from xgap.experiments.ch6_sql_reference import evaluate
from xgap.experiments.controlled_state import publish_state,read_state
from xgap.experiments.ch6_factor_inputs import build_family,source_bounds,N_LEVELS,U_LEVELS


class HeldoutReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        db=sqlite3.connect(self.root/'facts.sqlite')
        db.executescript('CREATE TABLE nodes(id TEXT PRIMARY KEY,kind TEXT,props TEXT);'
            'CREATE TABLE edges(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE,src TEXT,dst TEXT,ts INTEGER,value REAL);')
        add_nodes(db,[dict(id=n,type='Account',isBlocked=False) for n in 'abcde'])
        rows=[('a','b',2),('a','b',3),('c','b',9),('c','d',7),('a','d',5),('b','c',4),('d','a',6),('a','a',1)]
        add_edges(db,[dict(id=str(i),**{'from':a,'to':b},timestamp=i,value=v) for i,(a,b,v) in enumerate(rows,1)])
        db.close();self.index=self.root/'index.json'
        write(self.index,dict(schema_version='xgap-ch6-fact-index-v1',success=True,dataset='D3',core=CORES['D3'],
                             database=pin(self.root/'facts.sqlite'),scope_cut_ms=4))
    def tearDown(self):self.tmp.cleanup()

    def test_contribution_identity_preserves_parallel_edges_without_witness_multiplication(self):
        q=template_query(CORES['D3'],'witnessed_sum','a',0)
        self.assertEqual(evaluate(q,self.index)['rows'],[dict(result='a',total=1),dict(result='b',total=5),dict(result='d',total=5)])
        q['select']['total']['aggregate']='count'
        self.assertEqual(evaluate(q,self.index)['rows'],[dict(result='a',total=1),dict(result='b',total=2),dict(result='d',total=1)])

    def test_path_acyclic_length_and_parallel_projection(self):
        q=template_query(CORES['D3'],'bounded_path','a',0)
        self.assertEqual(evaluate(q,self.index)['rows'],[dict(result='c',distance=2),dict(result='d',distance=3)])
        q['path']['mode']='WALK'
        self.assertTrue(any(r['result']=='a' for r in evaluate(q,self.index)['rows']))
        q['path']['time']={'property':'timestamp'}
        with self.assertRaisesRegex(ValueError,'untimed'):evaluate(q,self.index)

    def test_scale_reference_rejects_unanchored_shortcut_and_respects_edge_ordinal(self):
        q=template_query(CORES['D3'],'window_edge','a',0)
        self.assertEqual(evaluate(q,self.index,scale='.25')['rows'],[dict(result='a')])
        self.assertEqual(evaluate(q,self.index,scale='4')['rows'],evaluate(q,self.index)['rows'])
        q['where']=q['where'][1:]
        with self.assertRaisesRegex(ValueError,'every component'):evaluate(q,self.index,scale='4')
        with self.assertRaisesRegex(ValueError,'not an empty answer'):evaluate(q,self.index,row_cap=1)

    def test_frames_use_source_activity_not_query_answers(self):
        meta=json.loads(self.index.read_text())
        self.assertIn('e',choose_anchors(meta,stratum='uniform',size=5,seed=1))
        self.assertNotIn('e',choose_anchors(meta,stratum='active-anchor',size=4,seed=1))
        with self.assertRaises(ValueError):choose_anchors(meta,stratum='active-anchor',size=5,seed=1)

    def test_split_structure_and_actual_candidate_ambiguity(self):
        for dataset,core in CORES.items():
            registries={p:set() for p in TEMPLATES}
            for split,names in TEMPLATES.items():
                for name in names:
                    if name=='bounded_path' and dataset=='D2' or name=='witnessed_sum' and dataset=='D1':continue
                    for w in ('W1','W2','W3','W4'):
                        q,p,f=make_family(core,name,['a','b'],4,w,'s','case')
                        registries[split].add(structure_identity(q))
                        changed=deepcopy(q);changed['where'][0]['right']['value']='changed'
                        self.assertEqual(structure_identity(q),structure_identity(changed))
                        choices=[dict(name=s.name,type='coordinate',slots=[s.name]) for s in f.slots]
                        doc=publish_state('q',f,json.loads(f.candidates[-1].query_json),semantic_choices=choices)
                        _,_,state=read_state(doc,'q')
                        self.assertEqual((state['initial_candidate_count'],state['initial_ambiguity']),
                                         (1,0) if w=='W1' else (2,1) if w=='W2' else (8,3))
            self.assertFalse(registries['test']&(registries['development']|registries['pilot']))
            self.assertFalse(registries['development']&registries['pilot'])

    def test_real_factor_cardinality_and_correlated_ambiguity(self):
        bounds=source_bounds(json.loads(self.index.read_text()))
        anchors=['account:'+str(i) for i in range(256)]
        for n,u in [(n,3) for n in N_LEVELS]+[(8,u) for u in U_LEVELS]:
            family=build_family(CORES['D3'],bounds,anchors,n=n,u=u,snapshot='s',family_id='factor')
            choices=[dict(name=s.name,type='coordinate',slots=[s.name]) for s in family.slots]
            state=publish_state('factor',family,json.loads(family.candidates[0].query_json),semantic_choices=choices)
            _,_,actual=read_state(state,'factor')
            self.assertEqual((actual['initial_candidate_count'],actual['initial_ambiguity']),(n,u))
            self.assertEqual(len({c.query_json for c in family.candidates}),n)
        bounds['measure']=(1,1,1)
        family=build_family(CORES['D1'],bounds,anchors,n=8,u=8,snapshot='s',family_id='factor')
        self.assertEqual(family.slots[4].name,'lower_edge_id')


if __name__=='__main__':unittest.main()
