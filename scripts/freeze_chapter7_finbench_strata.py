#!/usr/bin/env python3
"""Seal source-only frames, optionally a pre-answer formal family selection."""
import argparse
import json
from pathlib import Path
import time

from run_bounded_joint_batch import source_commit
from xgap.experiments.chapter7_finbench_pilot import windows
from xgap.experiments.chapter7_finbench_strata import structural_frames, select_families
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_records import write_once


def freeze(*, archive, lock_path, output, per_shape=None):
    started=time.perf_counter();commit=source_commit()
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    lock=load_finbench_artifact_lock(lock_path)
    data=load_finbench_query_data(archive,lock)
    frames=structural_frames(data.accounts,data.companies,data.transfers,data.company_by_account)
    frame_pin=write_once(root/'frames.json',frames)
    selection=None
    if per_shape is not None:
        (root/'private').mkdir()
        selection=write_once(root/'private/selection.json',select_families(frames,per_shape=per_shape))
    receipt=write_once(root/'receipt.json',dict(schema_version='xgap-ch7-source-only-frames-v1',
        source_commit=commit,source_lock=file_pin(lock_path),archive_sha256=lock.artifact.digest_value,
        frames=frame_pin,selection=selection,
        counts={s:{k:len(v) for k,v in f.items()} for s,f in frames.items()},
        time_windows=windows(data.minimum_transfer_time,data.maximum_transfer_time),
        answer_reads=0,model_calls=0,backend_calls=0,method_output_reads=0,
        formal_execution_manifest=False,offline_elapsed_ms=(time.perf_counter()-started)*1000))
    print(json.dumps(dict(receipt=receipt,selection=selection,counts={s:{k:len(v) for k,v in f.items()} for s,f in frames.items()})))
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','lock-path','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--per-shape',type=int,help='Omit for frame inventory only; no formal anchors are selected.')
    with deadline(300):freeze(**vars(p.parse_args()))
