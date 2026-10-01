#!/usr/bin/env python3
"""Persist two deterministic tiny failure replays; no model/service/evaluation run."""
import argparse
import json
from pathlib import Path
import sys
import tracemalloc

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tests'))
from test_compact_lowering import inputs, execute, EXPECTED, RESOURCE
from test_early_path_constraints import fanout_case, work
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.one_shot_records import write_once
from xgap.runtime.contracts import RuntimeNode, RuntimeNodeKind
from xgap.runtime.scheduler import FederatedScheduler, _deduplicate
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    report={'scope':'tiny failure replay; internal legacy/new compiler comparison, not a baseline study',
        'model_calls':0,'native_service_calls':0,'cases':[],'success':True}
    for outside in (False,True):
        data=inputs.__wrapped__();q=fanout_case(data,outside_window=outside)
        path=root/('time-and-anchor' if outside else 'anchor');path.mkdir()
        write_once(path/'case.json',{'query':q,'expected_rows':EXPECTED[1],
            'added_nodes':8,'added_edges':64,'scope':'disconnected dense noise cannot change the anchored reference'})
        for name,graph in data[-1].items():graph.serialize(path/(name+'.ttl'),format='turtle')
        mapping=data[3]
        backend=SemanticBackend('fuseki',RESOURCE,'xgap_id',backend_mapping=mapping['backend_mapping'],
            rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
            rdf_node_classes=tuple(mapping['rdf_node_classes']))
        results={}
        for label,optimized in [('legacy',False),('early_constraints',True)]:
            rows,program,sources,result=execute(q,data,optimize=optimized,return_runtime=True)
            plan=compile_semantic_program(program,source_bindings={op:'fuseki' for op in sources},
                backends={'fuseki':backend},max_remote_calls=64,max_parallelism=1)
            pin=write_once(path/(label+'.json'),{'program':program.to_dict(),'operator_sources':sources,
                'physical_plan_and_target_queries':plan.to_dict(),'runtime':result.to_dict(),
                'work':work(result),'answer_rows':rows,'correct':rows==EXPECTED[1]})
            results[label]={'artifact':pin,'work':work(result),'correct':rows==EXPECTED[1]}
        report['cases'].append({'id':path.name,'variants':results})
        report['success'] &= all(r['correct'] for r in results.values())
    node=RuntimeNode('join',RuntimeNodeKind.COORDINATOR_JOIN,('l','r'),{'left_on':'k','right_on':'k'})
    left=tuple({'k':1,'a':'x'} for _ in range(120));right=tuple({'k':1,'b':'y'} for _ in range(120))
    peaks={}
    for label,fn in [('legacy_pair_buffer',lambda:_deduplicate([{**l,**r} for l in left for r in right])),
            ('streamed_distinct',lambda:FederatedScheduler._join(node,left,right))]:
        tracemalloc.start()
        try:
            rows=fn();peaks[label]={'peak_python_allocated_bytes':tracemalloc.get_traced_memory()[1],
                'answer_rows':rows,'correct':rows==({'k':1,'a':'x','b':'y'},)}
        finally:tracemalloc.stop()
    report['join_buffer']={'left_rows':120,'right_rows':120,'raw_pairs':14400,'variants':peaks,
        'measurement_scope':'tracemalloc Python allocations inside join; not process RSS or native service RAM'}
    report['success'] &= all(v['correct'] for v in peaks.values())
    pin=write_once(root/'receipt.json',report)
    print(json.dumps({'success':report['success'],'receipt':pin,'cases':report['cases'],'join_buffer':report['join_buffer']}))
    return 0 if report['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    raise SystemExit(main(**vars(p.parse_args())))
