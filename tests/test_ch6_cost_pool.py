"""Freeze/scoring contract only; artificial test costs are never experiments."""
import tempfile
from pathlib import Path
import unittest
from xgap.experiments.ch6_cost_pool import freeze,score_selection


class CostPoolTests(unittest.TestCase):
    def fixture(self):
        pool=dict(schema_version='xgap-ch6-offline-cost-pool-v1',plans=[dict(plan_id=p,plan={'test':p}) for p in ('a','b')],
            query_sha256='query',source_snapshot_sha256='source',unit='ms',timing_scope='scheduler',order_seed=1,
            order=[dict(plan_id=p,repeat=r) for p in ('a','b') for r in range(3)])
        rows=[{**v,'query_sha256':'query','source_snapshot_sha256':'source','unit':'ms','timing_scope':'scheduler',
               'success':True,'answer_em':1,'actual_cost':10 if v['plan_id']=='a' else 20} for v in pool['order']]
        return pool,rows
    def test_costs_units_complete_repeats_and_error_envelope(self):
        pool,rows=self.fixture()
        with tempfile.TemporaryDirectory() as td:
            result=freeze(pool,rows,Path(td)/'good.json')
            self.assertEqual(result['normalizer'],20)
            self.assertIsNone(result['TS']['value'])
            for row in result['perturbations']:
                self.assertLessEqual(row['actual_uniform_error'],row['eta']+1e-12)
                selected=min(row['estimates'],key=row['estimates'].get)
                selection=dict(query_sha256='query',equivalence_admitted=True,actual_cost=10 if selected=='a' else 20,
                    plan_id=selected,unit='ms',timing_scope='scheduler',uses_perturbed_estimator=True,estimates=row['estimates'])
                score=score_selection(result,row['eta'],selection)
                self.assertTrue(score['bound_applicable']);self.assertFalse(score['bound_violation'])
            for field,value in [('query_sha256','other'),('source_snapshot_sha256','other'),('unit','seconds'),('success',False),('answer_em',0)]:
                invalid=[dict(r) for r in rows];invalid[0][field]=value
                with self.assertRaises(ValueError):freeze(pool,invalid,Path(td)/'bad.json')
            with self.assertRaises(ValueError):freeze(pool,rows[:-1],Path(td)/'missing.json')
            with self.assertRaises(ValueError):freeze(pool,rows+[rows[0]],Path(td)/'duplicate.json')
            self.assertIsNone(score_selection(result,0,dict(unit='seconds',timing_scope='scheduler'))['value'])

if __name__=='__main__':unittest.main()
