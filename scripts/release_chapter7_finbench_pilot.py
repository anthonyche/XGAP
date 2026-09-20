#!/usr/bin/env python3
"""Create the pinned 24-case pilot before opening any method result."""
import argparse
import json
from run_bounded_joint_batch import source_commit
from xgap.experiments.chapter7_finbench_pilot import release
from xgap.experiments.external_federation import deadline

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','lock-path','prepared-path','prepared-sha256','output'):p.add_argument('--'+name,required=True)
    args=vars(p.parse_args());args['source_commit']=source_commit()
    with deadline(300):pin=release(**args)
    print(json.dumps(pin))
