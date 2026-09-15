#!/usr/bin/env python3
"""Publish the declared derived inputs; no model/backend call or answer lookup."""
import argparse
import json
from xgap.experiments.partial_strong_inputs import publish_partial_cohort

p=argparse.ArgumentParser(description=__doc__)
for field in ('cohort-path','cohort-sha256','policy-path','policy-sha256','output'):
    p.add_argument('--'+field,required=True)
for field in ('rdf-mapping-path','rdf-mapping-sha256'):p.add_argument('--'+field)
args=p.parse_args()
print(json.dumps(publish_partial_cohort(**vars(args))))
