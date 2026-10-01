#!/usr/bin/env python3
"""Seal and check three development shapes, not a formal evaluation sample.

Uses one lexically first source ID per entity type, the full frozen time window,
and every legal intent. No answer-based resampling, LLM or backend calls.
"""
import argparse
import json
from pathlib import Path
import subprocess

from xgap.experiments.chapter7_finbench_families import TEMPLATES, make_family, reference_rows
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.compact_lowering import lower_compact_query


def check(*, archive, lock_path, prepared_path, prepared_sha256, output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    prepared = json.loads(read_pinned(prepared_path, prepared_sha256))
    profile = prepared['profile']
    frozen = FrozenOneShotProfile.load(profile['path'], expected_sha256=profile['sha256'])
    document = json.loads(frozen.document_json)
    lock = load_finbench_artifact_lock(lock_path)
    if document['dataset']['version'] != lock.artifact.digest_value:
        raise ValueError('Frozen source/profile mismatch')
    data = load_finbench_query_data(archive, lock)
    lower, upper = data.minimum_transfer_time, data.maximum_transfer_time
    families, selected = [], []
    for template in TEMPLATES:
        anchor = min(data.companies if template == 'company_transfer_summary' else data.accounts)
        family, scope, question, normalization = make_family(template, anchor, lower, upper, profile['sha256'])
        families.append((template, family, normalization))
        selected.append(dict(template=template, anchor=anchor, question=question, scope=scope.to_dict(),
                             candidates=[json.loads(c.query_json) for c in family.candidates]))
    # This immutable selection is written before the first reference calculation.
    selection = write_once(root / 'selection.json', dict(
        schema_version='xgap-ch7-constructor-check-selection-v1', formal_result=False,
        policy='lexically first source ID per type, full snapshot window, all 16 intents per shape',
        cases=selected, prepared=dict(path=str(Path(prepared_path).resolve()), sha256=prepared_sha256),
        source_archive_sha256=lock.artifact.digest_value, profile=profile))
    checks = []
    for template, family, normalization in families:
        for candidate in family.candidates:
            query = json.loads(candidate.query_json)
            program, assignments = lower_compact_query(query, document['source_schema'], version='v2', optimize=True)
            if program.holes or not assignments:
                raise ValueError('Complete candidate did not lower to a source-backed program')
            rows = reference_rows(data, template, query)
            reference = write_once(root / (candidate.candidate_id + '.reference.json'),
                                   dict(rows=rows, normalization=normalization))
            checks.append(dict(template=template, candidate_id=candidate.candidate_id,
                               operators=len(program.operators), reference_row_count=len(rows), reference=reference))
    repo = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__).resolve(), repo/'src/xgap/experiments/chapter7_finbench_families.py',
                    repo/'src/xgap/semantic/intent_scope.py']
    receipt = write_once(root / 'receipt.json', dict(
        schema_version='xgap-ch7-constructor-reference-check-v1', success=True,
        source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
        implementation=[file_pin(p) for p in source_paths], selection=selection, checks=checks,
        llm_calls=0, backend_calls=0, formal_result=False, answers_checked_against_native=False,
        scope='Compiler admission and independent CSV references only; not measured system answers'))
    print(json.dumps(dict(success=True, receipt=receipt, candidates=len(checks),
                          nonempty_references=sum(c['reference_row_count'] > 0 for c in checks))))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'lock-path', 'prepared-path', 'prepared-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    check(**vars(parser.parse_args()))
