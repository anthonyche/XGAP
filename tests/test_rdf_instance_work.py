"""Only instance routing/projection risks; no refit, query or old gate rerun."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import socket

import pytest

from test_finbench_serving_profile import publish, MODEL
from test_finbench_rdf import parameters
from xgap.experiments.finbench_rdf_profile import publish_rdf_profile
from xgap.experiments.finbench_semantic import financial_program
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict, REMOTE
from xgap.runtime.one_shot_planning import prepare_one_shot_domain


@pytest.fixture(scope='module')
def profiles(tmp_path_factory):
    root=tmp_path_factory.mktemp('rdf-instances')
    with pytest.MonkeyPatch.context() as m:
        m.setattr(socket.socket,'connect',lambda *a,**kw:pytest.fail('Network in offline publication'))
        from xgap.planning import runtime_work_estimator
        m.setattr(runtime_work_estimator,'fit_work_estimator',lambda *a,**kw:pytest.fail('Refit in deployment'))
        original=Path.open
        def guarded(path,*a,**kw):
            if any(p in path.parts for p in ('references','gold','requests')):
                pytest.fail('Source publication accessed query/reference files')
            return original(path,*a,**kw)
        m.setattr(Path,'open',guarded)
        base=publish(root/'base')
        rdf=publish_rdf_profile(base_profile=base['path'],base_sha256=base['sha256'],output=root/'rdf',
            endpoints={'rdf_graph':'http://localhost:3','rdf_control':'http://localhost:4'})
        return tuple(FrozenOneShotProfile.load(p['path'],expected_sha256=p['sha256']) for p in (base,rdf))


def candidates(profile,index=0):
    _,model,_,sources,backends,_,modes=profile.materialize()
    program,slots=financial_program(f'F{index+1}',parameters()[index])
    domain,bound=prepare_one_shot_domain(program,operator_sources=slots,sources=sources,backends=backends,
        policy=replace(modes['performance'][0],max_parallelism=1))
    assert len(domain)<=bound['construction_bound']
    return model,domain


def test_shared_scorer_identity_projection_preserves_existing_native_prediction(profiles):
    original,domain=candidates(profiles[0])
    projected=FrozenInstanceWorkDeployment('identity-test',original.trained_model,original.statistics,
        tuple((s.backend_id,s.backend_id) for s in original.statistics.entries),'test:identity')
    for candidate in domain:
        before,after=original.predict(candidate.plan),projected.predict(candidate.plan)
        assert before.features==after.features
        assert before.status==after.status=='estimated'
        assert before.estimated_ms==after.estimated_ms
        assert before.out_of_training_range==after.out_of_training_range


def test_two_instances_keep_own_statistics_before_projection_and_compile_all_three_families(profiles):
    profile=profiles[1];doc,model,_,_,_,specs,modes=profile.materialize()
    assert set(modes)=={'precision','performance'}
    assert model.to_dict()['trained_model']==json.loads(MODEL.read_text())
    assert frozen_estimator_from_dict(model.to_dict()).to_dict()==model.to_dict()
    clients=native_clients(specs)
    assert {k:(v.backend_id,v.base_url,v.dataset) for k,v in clients.items()}=={
        'rdf_graph':('rdf_graph','http://localhost:3','graph'),
        'rdf_control':('rdf_control','http://localhost:4','control')}
    assert {s.backend_id:s.total_rows for s in model.statistics.entries}=={'rdf_graph':24,'rdf_control':8}
    for index in range(3):
        _,domain=candidates(profile,index)
        for candidate in domain:
            p=model.predict(candidate.plan)
            assert p.status=='estimated',p.to_dict()
            raw=p.provenance['instance_features'];actual=dict(zip(raw['names'],raw['values']))
            features=dict(zip(p.features.names,p.features.values))
            for name,value in features.items():
                if name.startswith('backend.neo4j.'):assert value==0
                elif name.startswith('backend.fuseki.'):
                    tail=name.removeprefix('backend.fuseki.')
                    assert value==actual['backend.rdf_graph.'+tail]+actual['backend.rdf_control.'+tail]
                else:assert value==actual[name]
            assert not p.provenance['weights_changed'] and not p.provenance['transfer_calibrated']
            assert p.provenance['current_query_observation_calls']==p.provenance['fit_calls']==0
            for node in candidate.plan.nodes:
                if node.kind in REMOTE:
                    assert node.parameters['backend_id'] in clients
                    assert node.parameters['artifact']['language']=='sparql'
    assert doc['offline']['formal_campaign_ready'] is False


def test_source_identity_and_snapshot_mismatch_remain_unavailable(profiles):
    model,domain=candidates(profiles[1]);plan=domain[0].plan
    for field in ('source_id','snapshot_version'):
        metadata=deepcopy(plan.metadata);metadata['source_identities']['rdf_graph'][field]='wrong'
        result=model.predict(replace(plan,metadata=metadata))
        assert result.status=='unavailable_missing_features' and result.estimated_ms is None
        assert any('rdf_graph' in k for k in result.features.unknown_fields)
    with pytest.raises(ValueError,match='reference backend'):
        replace(model,reference_backends=(('rdf_graph','untrained'),('rdf_control','fuseki')))
    with pytest.raises(ValueError,match='reference backend'):
        replace(model,reference_backends=(('rdf_graph','fuseki'),('rdf_graph','fuseki')))
    raw=model.to_dict();raw['reference_backends']['rdf_graph']='neo4j'
    with pytest.raises(ValueError,match='hash mismatch'):frozen_estimator_from_dict(raw)


def test_profile_rejects_engine_capability_and_projection_disagreement(profiles):
    profile=profiles[1]
    for kind in ('capability','client','projection'):
        raw=json.loads(profile.document_json)
        if kind=='capability':raw['backends']['rdf_graph']['semantic']['profile']['backend_id']='fuseki'
        else:
            raw['backends']['rdf_graph']['client']['engine']='neo4j'
            if kind=='projection':raw['backends']['rdf_graph']['semantic']['profile']=None
        with pytest.raises(ValueError,match='engine differ'):
            replace(profile,document_json=json.dumps(raw)).materialize()


def test_rdf_publication_rejects_changed_frozen_load_before_output(profiles,tmp_path):
    profile=profiles[0];raw=json.loads(profile.document_json)
    source=tmp_path/'source';shutil.copytree(raw['offline']['materialization_root'],source)
    with (source/'graph.ttl').open('a') as stream:stream.write('\n')
    raw['offline']['materialization_root']=str(source)
    for name in ('catalog','estimator'):raw[name]['path']=str((profile.root/raw[name]['path']).resolve())
    for mode in raw['modes'].values():
        mode['provider']['prompt']['path']=str((profile.root/mode['provider']['prompt']['path']).resolve())
    base=tmp_path/'base.json';base.write_text(json.dumps(raw));target=tmp_path/'output'
    with pytest.raises(ValueError,match='size/hash mismatch'):
        publish_rdf_profile(base_profile=base,base_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
            output=target,endpoints={'rdf_graph':'http://localhost:3','rdf_control':'http://localhost:4'})
    assert not target.exists()
