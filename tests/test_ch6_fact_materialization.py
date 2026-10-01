import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from collections import namedtuple
from rdflib import Graph, Namespace, RDF

from xgap.experiments.ch6_fact_index import CORES,add_nodes,add_edges,pin,write,calendar_milliseconds
from xgap.experiments.ch6_materialize import materialize,NS,RESOURCE


class CoreMaterializationTest(unittest.TestCase):
    def test_finbench_optional_fraction_replay(self):
        self.assertEqual(calendar_milliseconds('2021-11-06 23:25:05'),calendar_milliseconds('2021-11-06 23:25:05.000'))
        self.assertEqual(calendar_milliseconds('2021-11-06 23:25:05.814')-calendar_milliseconds('2021-11-06 23:25:05'),814)
        with self.assertRaises(ValueError):calendar_milliseconds('2021-11-06 23:25:05.000001')
    def index(self, root):
        db=sqlite3.connect(root/'facts.sqlite')
        db.executescript('CREATE TABLE nodes(id TEXT PRIMARY KEY,kind TEXT,props TEXT);'
            'CREATE TABLE edges(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE,src TEXT,dst TEXT,ts INTEGER,value REAL);')
        add_nodes(db,[dict(id='user:1',type='User'),dict(id='movie:1',type='Movie',title='A "quote"\nfilm',isDrama=True),
                      dict(id='movie:2',type='Movie',title='Other',isDrama=False)])
        add_edges(db,[dict(id='row:'+str(i),**{'from':'user:1','to':'movie:1'},timestamp=i,value=4.5) for i in range(1,5)])
        db.close()
        write(root/'index.json',dict(schema_version='xgap-ch6-fact-index-v1',success=True,dataset='D2',core=CORES['D2'],
                                    database=pin(root/'facts.sqlite'),scope_cut_ms=2))
        return root/'index.json'

    def generate(self, root, index, **kwargs):
        usage=namedtuple('Usage','total used free')(100*1024**3,0,100*1024**3)
        with patch('xgap.experiments.ch6_materialize.shutil.disk_usage',return_value=usage):
            receipt=materialize(index,root,**kwargs)
        self.assertTrue(receipt['success'],receipt.get('error'))
        graphs={n:Graph().parse(data=gzip.open(p['path'],'rt').read(),format='turtle') for n,p in receipt['rdf_loads'].items()}
        return receipt,graphs

    def test_same_facts_preserve_parallel_edges_and_control_placement(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);index=self.index(root);r,g=self.generate(root/'out',index)
            s=Namespace(NS)
            self.assertEqual(len(list(g['graph'].subjects(RDF.type,s.Edge))),8)
            self.assertEqual(len(list(g['graph'].triples((None,s.isDrama,None)))),0)
            self.assertEqual(len(list(g['control'].triples((None,s.isDrama,None)))),2)
            self.assertEqual(len(list(g['graph'].triples((None,s.edgeLabel,s.RATED)))),4)
            self.assertEqual(len(list(g['graph'].triples((None,s.edgeLabel,s.RATED_EARLY)))),2)
            batches=[json.loads(line) for line in gzip.open(r['native_load']['path'],'rt')]
            self.assertEqual(len([b for b in batches if b['kind']=='relationships']),3)
            edges=[v for b in batches if b['kind']=='relationships' for v in b['parameters']['rows']]
            self.assertEqual(len({e['props']['xgap_id'] for e in edges}),8)
            self.assertEqual(r['counts'],dict(nodes=3,original_edges=4,view_edges=8))

    def test_source_repartition_has_identical_logical_graph(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);index=self.index(root)
            first,g=self.generate(root/'two',index);second,h=self.generate(root/'four',index,source_count=4)
            self.assertEqual(first['logical_facts_sha256'],second['logical_facts_sha256'])
            self.assertEqual(set(g['graph']),set().union(*(set(v) for k,v in h.items() if k!='control')))
            self.assertEqual(set(g['control']),set(h['control']))

    def test_scale_is_explicit_and_does_not_merge_copies(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);index=self.index(root)
            small,_=self.generate(root/'quarter',index,scale='.25')
            large,g=self.generate(root/'four',index,scale='4')
            self.assertEqual(small['counts'],dict(nodes=3,original_edges=1,view_edges=2))
            self.assertEqual(large['counts'],dict(nodes=12,original_edges=16,view_edges=32))
            s=Namespace(NS)
            for edge in g['graph'].subjects(RDF.type,s.Edge):
                source=str(g['graph'].value(edge,s.source)).removeprefix(RESOURCE).split('_')[0]
                target=str(g['graph'].value(edge,s.target)).removeprefix(RESOURCE).split('_')[0]
                self.assertEqual(source,target)


if __name__=='__main__':unittest.main()
