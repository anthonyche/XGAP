#!/usr/bin/env python3
"""Publish the pinned FinBench metadata as explicitly resolved strong inputs."""
import argparse
import json

from xgap.experiments.resolved_strong_inputs import publish_resolved_cohort


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('population-path', 'population-sha256', 'base-profile-path', 'base-profile-sha256',
                 'modes-path', 'modes-sha256', 'output'):
        parser.add_argument('--' + flag, required=True)
    print(json.dumps(publish_resolved_cohort(**vars(parser.parse_args()))), flush=True)
