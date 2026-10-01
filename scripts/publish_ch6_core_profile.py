#!/usr/bin/env python3
import argparse
import json
from xgap.experiments.ch6_core_profile import publish

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Source-only formal core profile; no experiment execution.')
    for n in ('materialization','trained-profile','trained-profile-sha256','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--deployment',choices=['rdf','native'],default='rdf')
    print(json.dumps(publish(**vars(p.parse_args()))))
