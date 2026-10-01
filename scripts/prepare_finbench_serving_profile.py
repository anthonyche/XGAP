#!/usr/bin/env python3
"""One offline publication with a 120-second deadline; no automatic retry."""
import argparse
import json
from pathlib import Path

from xgap.experiments.external_federation import deadline
from xgap.experiments.finbench_serving_profile import publish_serving_profile
from xgap.experiments.one_shot_records import write_once

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('rdf-root', 'manifest-sha256', 'model-path', 'model-sha256',
                 'output', 'dataset-id', 'neo4j-url', 'fuseki-url'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--fuseki-dataset', default='finbench')
    args = vars(parser.parse_args())
    args['endpoints'] = {'neo4j': args.pop('neo4j_url'), 'fuseki': args.pop('fuseki_url')}
    root = Path(args['output'])
    if root.exists():
        raise SystemExit('Output exists; no overwrite or automatic retry')
    try:
        with deadline(120):
            pin = publish_serving_profile(**args)
        print(json.dumps(pin))
    except Exception as error:
        root.mkdir(parents=True, exist_ok=True)
        write_once(root/'failure.json', {'success': False, 'error_type': type(error).__name__,
            'error': str(error), 'model_calls': 0, 'backend_calls': 0})
        raise
