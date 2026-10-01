"""Bounded source extraction and typed binding entry; no compiler admission claim."""
import argparse,json
from collections import Counter
from pathlib import Path
from xgap.experiments.ch6_structures import extract
from xgap.experiments.ch6_sources import sha


def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--commit',required=True);p.add_argument('--limit',type=int,default=128);args=p.parse_args()
    if not 1<=args.limit<=512:raise ValueError('Bounded development prefix must be 1..512')
    args.output.mkdir(parents=True,exist_ok=False);raw=json.loads(args.source.read_text());source_sha=sha(args.source)
    counts=Counter();classes=Counter();reasons=Counter()
    with (args.output/'template_registry.jsonl').open('x') as registry,(args.output/'rejections.jsonl').open('x') as rejected:
        for row in raw[:args.limit]:
            for field in ('sparql_wikidata','sparql_dbpedia18'):
                if field not in row:continue
                r=extract(row,source_version={'commit':args.commit,'sha256':source_sha},field=field)
                counts[r['status']]+=1;classes.update(r.get('structure_categories',[]));registry.write(json.dumps(r,ensure_ascii=False)+'\n')
                if r['status']=='rejected':
                    reasons.update(r['reasons']);rejected.write(json.dumps({k:r[k] for k in ('uid','source_field','raw_query_sha256','reasons')})+'\n')
    receipt=dict(source=source_sha,source_rows=min(args.limit,len(raw)),query_counts=counts,categories_including_rejected=classes,
        rejection_reasons=reasons,selection='published prefix for development, no outcome-based filtering',
        extracted_means='AST/typed structure only; requires domain-specific compiler/reference admission')
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
