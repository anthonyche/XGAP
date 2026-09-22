"""Prepare source-derived development artifacts locally. No API/backend execution."""
import argparse
from collections import Counter
import json
from pathlib import Path
from xgap.experiments.ch6_sources import snb,finbench,movielens,sha
from xgap.experiments.ch6_workload import build_development
from xgap.experiments.ch6_structures import extract


def main():
    p=argparse.ArgumentParser();p.add_argument('--intake',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--finbench-archive',type=Path,required=True);p.add_argument('--lcquad-limit',type=int,default=128)
    args=p.parse_args()
    if not 1<=args.lcquad_limit<=512:raise ValueError('Development extraction bound is 1..512')
    args.output.mkdir(parents=True,exist_ok=False)
    summaries=[]
    for dataset,load in [('D3',lambda:finbench(args.finbench_archive,'experiments/artifacts/m15_finbench_v010_sf0_1_sources.json')),
                         ('D1',lambda:snb(args.intake/'snb-official-tiny')),('D2',lambda:movielens(args.intake/'ml-latest-small.zip'))]:
        summary=build_development(load(),args.output/dataset);summaries.append(summary);print(json.dumps(summary),flush=True)
    raw=json.loads((args.intake/'lcquad-test.json').read_text());counts=Counter();categories=Counter()
    source=dict(commit='0a5f8f85b6f863c3b80f0fa02839e25d438af3ae',sha256=sha(args.intake/'lcquad-test.json'))
    with (args.output/'lcquad_template_registry.jsonl').open('x') as templates,(args.output/'lcquad_rejections.jsonl').open('x') as rejects:
        for row in raw[:args.lcquad_limit]:
            for field in ('sparql_wikidata','sparql_dbpedia18'):
                if field not in row:continue
                item=extract(row,source_version=source,field=field);counts[item['status']]+=1
                categories.update(item.get('structure_categories',[]));templates.write(json.dumps(item,ensure_ascii=False)+'\n')
                if item['status']=='rejected':rejects.write(json.dumps({k:v for k,v in item.items() if k in ('uid','source_field','raw_query_sha256','reasons','error')})+'\n')
    report=dict(datasets=summaries,lcquad=dict(counts=counts,categories=categories,source_rows=args.lcquad_limit,
        selection='prefix in published order for development; no success-based filtering',compiler_admission='none; source extraction is separate from authored domain templates'),
        paid_model_calls=0,backend_calls=0,formal_result=False)
    (args.output/'preparation_receipt.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)

if __name__=='__main__':main()
