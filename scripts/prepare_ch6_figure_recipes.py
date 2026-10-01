#!/usr/bin/env python3
"""Build a zero-call figure recipe inventory, optionally from a verified mirror."""
import argparse
import hashlib
import json
from pathlib import Path

from xgap.experiments.ch6_figure_recipes import build
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_records import write_once


def prepare(spec_path, spec_sha256, output, *, original_root=None, mirror_root=None):
    spec_pin = dict(path=spec_path, sha256=spec_sha256)
    spec = load_pin(spec_pin)
    if bool(original_root) != bool(mirror_root): raise ValueError('Both mirror roots required')
    def read(pin):
        if not original_root: return load_pin(pin)
        relative = Path(pin['path']).relative_to(Path(original_root))
        root = Path(mirror_root).resolve(); local = (root / relative).resolve()
        if not local.is_relative_to(root): raise ValueError('Mirror path escapes root')
        raw = local.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256'] or ('bytes' in pin and len(raw) != pin['bytes']):
            raise ValueError('Changed mirror artifact')
        return json.loads(raw)
    result = build(spec, load=read); result['input'] = spec_pin
    return write_once(Path(output), result)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('spec-path', 'spec-sha256', 'output'): p.add_argument('--' + k, required=True)
    p.add_argument('--original-root'); p.add_argument('--mirror-root')
    print(json.dumps(prepare(**vars(p.parse_args()))))
