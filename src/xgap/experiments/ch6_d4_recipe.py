"""Pinned CPU-only D4 preprocessing recipe; no evaluated model/backend calls."""
import json
import os
from pathlib import Path
import subprocess

from xgap.experiments.ch6_fact_index import pin, write
from xgap.experiments.ch6_synthetic import generate
from xgap.experiments.ch6_materialize import materialize
from xgap.experiments.ch6_sql_reference import evaluate

REMOTE = '/home/hxc859/xgap-ch6-artifacts'
SIZES = ((".25", 16384), ("1", 65536), ("4", 262144))
RUNTIME = {
    'admission': dict(path=REMOTE+'/linux-admission-v4/receipt.json', sha256='8f470e779c7b91bded8c1cb496497de8d980e40f8c74c0a36b0137f2241af515'),
    'bootstrap': dict(path=REMOTE+'/linux-runtime-v3/receipt.json', sha256='1a66283611a50d30c134ce7201777127db61d29874a0c2cf953404c698df6602'),
    'profile': dict(path=REMOTE+'/linux-admission-v4/profile.json', sha256='281081bddeb8a7090a95d2fb0250cbe6da1459d5996c610d02581d3e4ec4fe8e'),
    'external_runtime': dict(path=REMOTE+'/linux-admission-v4/external-runtime.json', sha256='e6b70fcdc73e63b0a363f0f21312f1bbb1ad4e62ba12e5827008996ec27a71bb'),
    'java': dict(path=REMOTE+'/linux-runtime-v1/java/jdk-21.0.8+9/bin/java', sha256='90d0a6d25da103678013f193db078b90ed8aeb27b66ebe78e0149616c9c1b811'),
    'fuseki': dict(path=REMOTE+'/linux-runtime-v3/inputs/fuseki-server.jar', sha256='d28c1eaf703122ee628895a460c20fa4aa60a892f435d403ea8c036f241da1f8'),
}


def queries():
    from xgap.experiments.ch6_heldout import predicate, ref
    base = dict(nodes=[dict(var='a', type='Entity', entity=None), dict(var='b', type='Entity', entity=None)],
                edges=[dict(var='e', type='LINKS', source='a', target='b')], path=None,
                where=[predicate('a', 'id', 'eq', 'entity:000000000')],
                select={'result': ref('b')}, contribution_by=None,
                order_by=[dict(field='result', direction='asc')], limit=20)
    from copy import deepcopy
    cross = deepcopy(base)
    cross['where'].append(predicate('b', 'isMarked', 'eq', True))
    return {'anchored_edge': base, 'anchored_marked_edge': cross}


def prepare(output, *, source_commit, remote_output):
    import re
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise ValueError('Exact source revision required')
    target = Path(remote_output)
    if not target.is_absolute() or not target.is_relative_to(Path(REMOTE)):
        raise ValueError('New absolute server artifact directory required')
    recipe = dict(schema_version='xgap-d4-preprocessing-recipe-v1', source_commit=source_commit,
        output_root=str(target), runtime=RUNTIME, generator='xgap-d4-ring-chords-v1', seed=20260926,
        degree=8, levels=[dict(scale=s, nodes=n, edges=n*8, source_count=2, materializer_scale='1') for s,n in SIZES],
        reference_queries=queries(), reference_seconds=60, reference_row_cap=100000,
        service_preparation=dict(deployment='rdf', large=False, max_store_bytes=10*1024**3,
                                 load_seconds_per_source=900, heap_mib=2048),
        recommended_allocation=dict(partition='batch', cpu=8, memory_gib=24, wall_seconds=7200, node=None, gpu=0),
        minimum_materialization_free_bytes=22*1024**3,
        model_calls=0, evaluated_backend_calls=0, submitted_jobs=0, formal_campaign_ready=False,
        pending=['Serve immutable store copies under the frozen direct/lazy Jena contract',
                 'Publish actual controlled/NL inputs and five-method configurations separately',
                 'Run graph-backend answer checks and method measurements; references are not observations'],
        scope='Offline source/index/store loading and independent reference construction only; no paper measurements')
    target = Path(output).resolve(); target.mkdir(parents=True, exist_ok=False)
    write(target/'recipe.json', recipe)
    return pin(target/'recipe.json')


def verify_sha(ref):
    if pin(ref['path'])['sha256'] != ref['sha256']:
        raise ValueError('Frozen runtime or recipe changed: '+ref['path'])


def execute(recipe_path, recipe_sha256, *, run=False):
    verify_sha(dict(path=str(recipe_path), sha256=recipe_sha256))
    doc=json.loads(Path(recipe_path).read_text())
    if doc['schema_version']!='xgap-d4-preprocessing-recipe-v1' or doc['runtime']!=RUNTIME:
        raise ValueError('Unknown runtime recipe')
    expected=[dict(scale=s,nodes=n,edges=n*8,source_count=2,materializer_scale='1') for s,n in SIZES]
    if (doc['levels']!=expected or doc['degree']!=8 or doc['seed']!=20260926
            or doc['reference_queries']!=queries()):
        raise ValueError('Frozen D4 grid or reference query changed')
    if not run:
        return dict(valid_recipe=True, executed=False, levels=doc['levels'], model_calls=0, backend_calls=0)
    if not os.environ.get('SLURM_JOB_ID') or os.environ.get('SLURM_JOB_GPUS'):
        raise ValueError('Explicit CPU-only allocation required')
    repo=Path(__file__).resolve().parents[3]
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()!=doc['source_commit']:
        raise ValueError('Source revision differs')
    if subprocess.check_output(['git','status','--porcelain'],cwd=repo):
        raise ValueError('Use a clean checkout; do not modify the running small study')
    for item in RUNTIME.values(): verify_sha(item)
    # The existing helper derives its JAR path relative to bootstrap; verify that actual path above.
    bootstrap=json.loads(Path(RUNTIME['bootstrap']['path']).read_text())
    admission=json.loads(Path(RUNTIME['admission']['path']).read_text())
    if (bootstrap['java']['sha256']!=RUNTIME['java']['sha256'] or admission['profile']['sha256']!=RUNTIME['profile']['sha256']
            or admission['external_runtime']['sha256']!=RUNTIME['external_runtime']['sha256']):
        raise ValueError('Nested runtime identity changed')
    root=Path(doc['output_root']); root.mkdir(parents=True,exist_ok=False)
    result=dict(success=False, levels=[], model_calls=0, evaluated_backend_calls=0, formal_campaign_ready=False)
    try:
        from prepare_ch6_core_services import prepare as prepare_services
        for level in doc['levels']:
            base=root/('n'+str(level['nodes'])); base.mkdir()
            index=generate(base/'index',nodes=level['nodes'],degree=8,seed=20260926)
            material=materialize(index['path'],base/'materialized',scale='1',source_count=2)
            if not material['success']: raise ValueError('D4 materialization failed; preserve partial output')
            references={name:evaluate(q,index['path'],seconds=60,row_cap=100000,scale='1')
                        for name,q in queries().items()}
            write(base/'references.json',dict(queries=queries(),references=references,independent=True,not_backend_results=True))
            code=prepare_services(str(base/'materialized/receipt.json'),RUNTIME['admission']['path'],
                RUNTIME['bootstrap']['path'],base/'services',root/'cache',deployment='rdf',large=False)
            result['levels'].append(dict(**level,index=index,materialization=pin(base/'materialized/receipt.json'),
                references=pin(base/'references.json'),services=pin(base/'services/receipt.json')))
            if code:raise ValueError('D4 offline service preparation failed; no automatic retry')
        result['success']=True
    except Exception as error:
        result.update(error_type=type(error).__name__,error=str(error))
    write(root/'receipt.json',result)
    return result
