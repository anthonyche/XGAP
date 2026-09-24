"""Freeze and check the shared RDF repair deployment; never run a query.

The contract identifies the engine and local overlay sources. A successful
diagnostic subset is deliberately insufficient to release a formal batch.
"""
import argparse
import json
from pathlib import Path
import re

from prepare_rdf_tdb import stream_pin
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

SCHEMA = 'xgap-shared-source-runtime-v1'
RUNTIME = 'jena-direct-lazy-v2'
JAVA_ROOT = Path(__file__).parent / 'java'
SOURCES = ('XgapStorageMode.java', 'jena_lazy_range/BPTreeRangeIterator.java',
           'jena_lazy_range/BPTreeRangeIteratorMapper.java')
ORIGINALS = {
    'BPTreeRangeIterator': 'cd48a47afe150e1b4cd2a8645e8c6ad6b6d1d758d7bf1708bdae6d17c80f696d',
    'BPTreeRangeIteratorMapper': '8dfbaeb5bec7a7c9312f87467a50b15634c0000bb98ddb88f4b96704ea7538c2',
}


def load(pin):
    if (not isinstance(pin, dict) or not isinstance(pin.get('path'), str)
            or not Path(pin['path']).is_absolute()
            or not re.fullmatch(r'[a-f0-9]{64}', pin.get('sha256', ''))):
        raise ValueError('Pinned absolute runtime evidence required')
    return json.loads(read_pinned(pin['path'], pin['sha256']))


def validate_contract(doc):
    if (set(doc) != {'schema_version', 'runtime_id', 'artifacts', 'original_classes'}
            or doc['schema_version'] != SCHEMA or doc['runtime_id'] != RUNTIME
            or doc['original_classes'] != ORIGINALS
            or set(doc['artifacts']) != {'fuseki_jar', 'java', 'javac', *SOURCES}
            or any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{64}', v)
                   for v in doc['artifacts'].values())):
        raise ValueError('Unknown shared source runtime contract')
    return doc


def current_contract(build):
    artifacts = {}
    for key in ('fuseki_jar', 'java'):
        actual = stream_pin(build[key]['path'])
        if actual != build[key]:
            raise ValueError('Prepared engine changed before runtime admission')
        artifacts[key] = actual['sha256']
    artifacts['javac'] = stream_pin(Path(build['java']['path']).with_name('javac'))['sha256']
    artifacts.update({name: stream_pin(JAVA_ROOT / name)['sha256'] for name in SOURCES})
    return dict(schema_version=SCHEMA, runtime_id=RUNTIME, artifacts=artifacts,
                original_classes=dict(ORIGINALS))


def verify_current(contract_pin, build):
    expected = validate_contract(load(contract_pin))
    if current_contract(build) != expected:
        raise ValueError('Shared source runtime differs from frozen contract')
    return expected


def freeze(prepared_pin, output):
    prepared = load(prepared_pin)
    if not prepared.get('success'):
        raise ValueError('Successful frozen stores required')
    build = load(prepared['input_seal'])
    if build['profile'] != prepared['profile']:
        raise ValueError('Prepared profile differs from sealed engine input')
    return write_once(Path(output).resolve(), current_contract(build))


def validate_admission(design, deployment, prepared_pin, *, bundle_pin=None, cells=None):
    """Inspect only public deployment/admission evidence, never private intent."""
    config = design.get('source_runtime')
    if config is None:
        return None
    if deployment != 'rdf' or not isinstance(config, dict) or set(config) != {'contract', 'admission'}:
        raise ValueError('Shared source runtime requires RDF contract and full admission')
    validate_contract(load(config['contract']))
    gate = load(config['admission'])
    if (gate.get('success') is not True or gate.get('backend_roundtrip') is not True
            or gate.get('admission_scope') != 'complete_bundle'
            or gate.get('full_bundle_admitted') is not True
            or (gate.get('source_runtime') or {}).get('sha256') != config['contract']['sha256']
            or gate.get('prepared', {}).get('sha256') != prepared_pin['sha256']
            or not all(gate.get('closure', {}).get(k) is True for k in
                       ('owned_groups_drained', 'owned_processes_terminal', 'observer_stopped'))):
        raise ValueError('Matching complete shared-runtime admission required; diagnostics cannot release')
    ready = load(gate['source_ready'])
    if ((ready.get('source_runtime') or {}).get('sha256') != config['contract']['sha256']
            or ready.get('prepared', {}).get('sha256') != prepared_pin['sha256']
            or ready.get('tdb2_file_mode') != 'direct' or ready.get('experimental_lazy_range') is not True):
        raise ValueError('Actual serving runtime differs from admission contract')
    if bundle_pin is not None and gate['bundle']['sha256'] != bundle_pin['sha256']:
        raise ValueError('Runtime admission belongs to a different frozen bundle')
    if cells is not None:
        bundle = load(gate['bundle'])
        admitted = {(c['request']['sha256'], c['reference']['sha256']) for c in bundle['cases']}
        if any((c['request']['sha256'], c['reference']['sha256']) not in admitted for c in cells):
            raise ValueError('Batch contains cases outside the admitted runtime cohort')
    return config


def session_options(config):
    return {} if config is None else dict(file_mode='direct', experimental_lazy_range=True,
                                         runtime_contract=config['contract'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared-path', 'prepared-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(dict(path=args.prepared_path, sha256=args.prepared_sha256), args.output)))
