"""Snapshot-safe training import and the new per-sample fitting boundary only."""

from dataclasses import replace
import json

import pytest

from xgap.experiments.edge_bind_training import (fixture, prepare_entries, verified_parent_records,
    PARENT_ROOT, PARENT_HASH, ORDER, EXCLUDED_IDS)
from xgap.planning.runtime_estimator import RuntimeTrainingSample, _hash
from xgap.planning.runtime_work_estimator import FrozenWorkEstimator, extract_work_features, fit_work_estimator


def test_four_declared_plans_cover_new_bound_endpoints_without_observation():
    stats,entries,_=prepare_entries()
    assert [(e['target_backend'],e['endpoint']) for e in entries]==list(ORDER)
    assert not set(e['query_id'] for e in entries)&set(EXCLUDED_IDS)
    data,_,_,_,_=fixture()
    assert len(data['nodes'])==4 and len(data['edges'])==6
    for entry in entries:
        plan=entry['plan'];f=extract_work_features(plan,stats)
        assert not f.unknown_fields
        bound=[n for n in plan.nodes if n.kind.value=='remote_bind_query']
        assert len(bound)==1
        assert bound[0].parameters['artifact']['parameters']['bound_identity_column']==entry['endpoint']
        values=dict(zip(f.names,f.values))
        assert values[f'backend.{entry["target_backend"]}.path.bind.calls']==1


def test_parent_import_reconstructs_only_pinned_training_samples(monkeypatch):
    from pathlib import Path
    if not (PARENT_ROOT/'frozen_work_estimator.json').is_file():pytest.skip('Pinned native parent artifact unavailable')
    original=Path.read_bytes
    def guarded(path,*a,**k):
        assert not path.name.startswith('heldout'), 'Heldout observations must not be imported'
        return original(path,*a,**k)
    monkeypatch.setattr(Path,'read_bytes',guarded)
    parent,samples,receipt=verified_parent_records()
    assert parent.model_sha256==PARENT_HASH and len(samples)==28 and receipt['new_collection_calls']==0
    assert len(receipt['files'])==30


def test_per_sample_snapshot_fit_roundtrip_and_wrong_snapshot_rejected():
    stats,entries,_=prepare_entries()
    first=entries[0];second=entries[1]
    other=replace(stats,statistics_id='another-independent-analytic-toy',version='other',
        entries=tuple(replace(s,snapshot_version='other',total_rows=20) for s in stats.entries))
    other_plan=replace(second['plan'],metadata={**second['plan'].metadata,
        'source_snapshot_versions':{s.backend_id:s.snapshot_version for s in other.entries},
        'source_identities':{s.backend_id:{'source_id':s.source_id,'snapshot_version':s.snapshot_version} for s in other.entries}})
    samples=[RuntimeTrainingSample('analytic-a',first['query_id'],first['plan'],5,'a'*64),
             RuntimeTrainingSample('analytic-b',second['query_id'],other_plan,7,'b'*64)]
    options=dict(statistics=stats,training_id='unit-snapshot-fit',model_version='unit-only',training_kind='toy_correctness',
        excluded_query_ids=EXCLUDED_IDS,collection_ref='unit:two-analytic-labels-not-native',
        collection_elapsed_ms=None,collection_remote_calls=0,fit_sweeps=2)
    assignments={'analytic-a':stats,'analytic-b':other}
    model=fit_work_estimator(samples,sample_statistics=assignments,**options)
    restored=FrozenWorkEstimator.from_dict(model.to_dict())
    assert restored.model_sha256==model.model_sha256
    p=json.loads(restored.training_provenance_json)
    assert p['sample_source_statistics']=={name:stat.sha256 for name,stat in assignments.items()}
    for wrong in ({'analytic-a':stats},{'analytic-a':stats,'analytic-b':stats}):
        with pytest.raises(ValueError,match='statistics'):
            fit_work_estimator(samples,sample_statistics=wrong,**options)
    tampered=model.to_dict();tampered['training_provenance']['sample_source_statistics']['analytic-b']='0'*64
    body={k:v for k,v in tampered.items() if k!='model_sha256'};tampered['model_sha256']=_hash(body)
    with pytest.raises(ValueError,match='statistics'):FrozenWorkEstimator.from_dict(tampered)
