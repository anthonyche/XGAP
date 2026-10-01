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

    def test_existential_witness_keeps_joint_conditions_and_parameter_identity(self):
        q=template_query(CORES['D3'],'witnessed_sum','a',2)
        q['edges'][1]['type']='TRANSFERRED_TO_EARLY'
        result=evaluate(q,self.index)
        self.assertEqual(result['rows'],[dict(result='b',total=3),dict(result='d',total=5)])
        self.assertIn('EXISTS (SELECT 1 FROM edges e1 CROSS JOIN nodes n2',result['sql'])
        # Restrict the same witness, rather than satisfying its properties using
        # unrelated nodes. Parallel contributing edges must remain separate.
        q['where'].append(dict(left=dict(var='c',property='id'),op='eq',right={'value':'b'},value_type='scalar'))
        self.assertEqual(evaluate(q,self.index)['rows'],[])

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

    def test_independent_covering_index_copy_keeps_facts_and_reference_answers(self):
        from prepare_ch6_reference_workspace import prepare
        from xgap.experiments.ch6_formal_protocol import load_pin
        original=pin(self.root/'facts.sqlite')
        receipt=load_pin(prepare(pin(self.index),self.root/'indexed',self.root/'work'))
        self.assertEqual(pin(self.root/'facts.sqlite'),original)
        self.assertEqual(receipt['row_mutations'],0)
        self.assertEqual(receipt['original_database'],original)
        with sqlite3.connect(receipt['database']['path']) as db:
            detail=list(db.execute('EXPLAIN QUERY PLAN SELECT src FROM edges WHERE dst=?',('b',)))
            self.assertIn('COVERING INDEX reference_dst_src',str(detail))
        for name in ('zigzag','cycle','witnessed_sum'):
            q=template_query(CORES['D3'],name,'a',0)
            self.assertEqual(evaluate(q,self.index)['rows'],
                evaluate(q,self.index,execution_database=receipt['database']['path'])['rows'])

    def test_set_projection_exists_matches_general_reference_and_keeps_coupled_edges(self):
        from xgap.experiments.ch6_sql_reference import compile_reference
        from xgap.experiments.ch6_fact_index import read_index
        for name in ('window_edge','zigzag','ordered_star','cycle'):
            for cross in (False,True):
                for scale in ('1','.25','4'):
                    q=template_query(CORES['D3'],name,'a',0,cross=cross);q['limit']=2
                    optimized=compile_reference(q,self.index,scale=scale)
                    general=compile_reference(q,self.index,scale=scale,projection_exists=False)
                    self.assertTrue(optimized['sql'].startswith('SELECT DISTINCT'))
                    with read_index(optimized['database']) as db:
                        expected=list(db.execute(general['sql'],general['parameters']))
                        self.assertEqual(list(db.execute(optimized['sql'],optimized['parameters'])),expected)
                    actual=evaluate(q,self.index,scale=scale)
                    self.assertEqual([tuple(r.values()) for r in actual['rows']],expected)
                    self.assertEqual(actual['engine'],'independent_ordered_adjacency')
        q=template_query(CORES['D3'],'cycle','a',0)
        q['where'].append(dict(left=dict(var='e',property='amount'),op='lt',
            right=dict(var='f',property='amount'),value_type='scalar'))
        self.assertTrue(compile_reference(q,self.index)['sql'].startswith('WITH RECURSIVE'))

    def test_ordered_adjacency_preserves_descending_limit_and_avoids_node_cartesian(self):
        from xgap.experiments.ch6_sql_reference import compile_reference
        db=sqlite3.connect(self.root/'facts.sqlite')
        db.executescript('CREATE INDEX edge_src ON edges(src,ordinal); CREATE INDEX edge_dst ON edges(dst,ordinal);'
                        'CREATE INDEX node_kind ON nodes(kind,id);')
        add_nodes(db,[dict(id='isolated:'+str(i),type='Account') for i in range(20000)])
        db.close()
        for name in ('window_edge','zigzag','cycle','ordered_star'):
            q=template_query(CORES['D3'],name,'a',0);q['limit']=2
            for order in q['order_by']:order['direction']='desc'
            original=compile_reference(q,self.index,projection_exists=False)
            steps=compile_reference(q,self.index)['ordered_adjacency']['steps']
            # Earlier edge witnesses were already checked by the prefix. Do
            # not scan those adjacencies again for each later bound node.
            if name in ('zigzag','cycle'):
                self.assertNotIn('edges e0',steps[2]['sql'])
            if name=='cycle':
                self.assertNotIn('edges e1',steps[3]['sql'])
            with sqlite3.connect(self.root/'facts.sqlite') as db:
                expected=list(db.execute(original['sql'],original['parameters']))
            result=evaluate(q,self.index)
            self.assertEqual([tuple(r.values()) for r in result['rows']],expected)
            self.assertLess(result['step_calls'],30)
            self.assertTrue(any('edge_src' in str(s) for s in result['explain']))

    def test_star_reference_joins_edges_before_unanchored_node_ranges(self):
        db=sqlite3.connect(self.root/'facts.sqlite')
        db.executescript('CREATE INDEX edge_src ON edges(src,ordinal); CREATE INDEX edge_dst ON edges(dst,ordinal);'
                        'CREATE INDEX node_kind ON nodes(kind,id);')
        add_nodes(db,[dict(id='isolated:'+str(i),type='Account') for i in range(20000)])
        db.close()
        q=template_query(CORES['D3'],'outgoing_maximum','a',0)
        result=evaluate(q,self.index)
        self.assertEqual(result['rows'],[dict(result='a',total=1),dict(result='b',total=3)])
        scans=[r[3] for r in result['explain'] if 'SEARCH' in r[3] or 'SCAN' in r[3]]
        self.assertTrue(any('e0' in s and 'edge_src' in s for s in scans),scans)
        self.assertLess(next(i for i,s in enumerate(scans) if 'e0' in s),next(i for i,s in enumerate(scans) if 'n1' in s))
        self.assertIn('CROSS JOIN edges e0 CROSS JOIN nodes n1',result['sql'])
        # An untyped string inequality is not silently reinterpreted by SQL.
        q['where'][1]['value_type']='scalar'
        self.assertEqual(evaluate(q,self.index)['rows'],[])

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
