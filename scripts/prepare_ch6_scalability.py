#!/usr/bin/env python3
"""Freeze existing factor pins, D4 generator settings and real parallelism scope."""
import argparse
import json
from pathlib import Path

from xgap.experiments.ch6_formal_protocol import pin_file
from xgap.experiments.ch6_fact_index import write


def prepare(publication_root, output):
    publication=Path(publication_root).resolve()
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    names=['D1-N-u-final','D1-sources-base-two-final','D1-sources-sources-four-final',
           'D1-sources-sources-eight-final','D1-graph_scale-scale-quarter-final',
           'D1-graph_scale-base-two-final','D1-graph_scale-scale-four-final']
    existing=[]
    for name in names:
        path=publication/name/'spec.json'
        spec=json.loads(path.read_text())
        existing.append(dict(cohort=name,local_spec=pin_file(path),bundle=spec['bundle'],
            prepared=spec['prepared'],backend_admission=spec['backend_admission'],
            figures=spec['figures'],configuration_requires_live_probe_refresh=True,
            repetitions=1,method_results_used_for_selection=False))
    d4=[]
    for scale,nodes in ((.25,16384),(1,65536),(4,262144)):
        d4.append(dict(dataset='D4',scale=scale,nodes=nodes,degree=8,edges=nodes*8,seed=20260926,
            generator='xgap-d4-ring-chords-v1',source_count=2,
            command=['python','scripts/generate_ch6_synthetic.py','--output',f'${{OUTPUT_ROOT}}/D4/n{nodes}',
                     '--nodes',str(nodes),'--degree','8','--seed','20260926'],
            downstream=['scripts/materialize_ch6_core.py --scale 1 --source-count 2',
                        'scripts/prepare_ch6_core_services.py --deployment rdf',
                        'scripts/publish_ch6_factor_inputs.py'],
            source_materialized=False,backend_admitted=False))
    result=dict(schema_version='xgap-ch6-scalability-parallel-preparation-v1',
        preserves_figure_count=21,existing_D1_factors=existing,
        factors=dict(S1=dict(levels=[16,64,256,1024],fixed_depth=2,input_track='controlled',
            controls=['same source','actual distinct candidates','bounded resources','uniform/active separate']),
            S2=dict(levels=[2,4,8],fixed_total_facts=True,constant_total_cpu_ram=True),
            S3=dict(levels=[.25,1,4],source_count=2,
                    D1_scale_semantics='.25 edge ordinal subset plus all nodes; 4 disconnected renamed replicas'),
            S4=dict(levels=[.25,1,4],metric='measured peak coordinator RSS, not total allocated memory')),
        D4=d4,D4_description='New synthetic regular ring-chord graphs; independent vertices at each size, never real-world observations',
        parallel=dict(levels=[1,2,4,8],output='supplemental table; does not add a figure',
            x='max concurrent ready remote DAG nodes',y='execution latency',
            companion_metrics=['observed_peak_inflight','backend_calls','bytes','answer equality','coordinator RSS'],
            fixed=['one selected final plan','query artifacts','source snapshot','total CPU/RAM','cache protocol'],
            implementation='xgap.experiments.ch6_parallel.execute',
            methods={m:('fixed reference: external concurrency knob unavailable' if m=='TS' else 'vary scheduler parallelism on its own frozen plan')
                     for m in ['XGAP','NP','SH','GR','TS']},
            not_measured='parallel user-query throughput and backend internal worker count',
            workload_rule='Prespecify from graph/DAG structure; do not select measured speedup winners',
            neutral_control='width-one dependency chain retained; nominal parallelism may have no effect'),
        missing=['D2/D3 source-count and graph-scale deployments not yet materialized',
                 'D4 graph-service materialization and independent references',
                 'Real selected plan pins and same-source parallel execution session',
                 'Live-probe refreshed factor configurations'],
        model_calls=0,backend_calls=0,submitted_jobs=0,launch_ready=False)
    write(root/'scalability-spec.json',result)
    return pin_file(root/'scalability-spec.json')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--publication-root',required=True);p.add_argument('--output',required=True)
    print(json.dumps(prepare(**vars(p.parse_args()))))
