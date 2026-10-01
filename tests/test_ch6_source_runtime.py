"""Prevent deploying a repaired engine under historical/default admission."""
from copy import deepcopy
import pytest

import ch6_source_runtime as runtime
import run_bounded_joint_batch as batch
from prepare_rdf_tdb import stream_pin
from test_bounded_joint_batch import fixture, install_fake_runtime, launch
from xgap.experiments.one_shot_records import write_once


def artifacts(root):
    sources=root/'sources';sources.mkdir()
    for name in runtime.SOURCES:
        p=sources/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('source '+name)
    for name in ('java','javac','engine.jar'):(root/name).write_text('binary '+name)
    return sources,dict(fuseki_jar=stream_pin(root/'engine.jar'),java=stream_pin(root/'java'))


def admitted(root,monkeypatch,cells):
    sources,build=artifacts(root);monkeypatch.setattr(runtime,'JAVA_ROOT',sources)
    def save(name,doc):return write_once(root/(name+'.json'),doc)
    contract=save('runtime',runtime.current_contract(build))
    prepared=save('prepared',dict(success=True))
    bundle=save('bundle',dict(cases=cells))
    ready=save('ready',dict(source_runtime=contract,prepared=prepared,tdb2_file_mode='direct',experimental_lazy_range=True))
    gate=dict(success=True,backend_roundtrip=True,admission_scope='complete_bundle',full_bundle_admitted=True,
              prepared=prepared,source_runtime=contract,source_ready=ready,bundle=bundle,
              closure=dict(owned_groups_drained=True,owned_processes_terminal=True,observer_stopped=True))
    return dict(contract=contract,admission=save('admission',gate)),prepared,bundle,gate


def test_frozen_contract_detects_engine_overlay_and_compiler_drift(tmp_path,monkeypatch):
    sources,build=artifacts(tmp_path);monkeypatch.setattr(runtime,'JAVA_ROOT',sources)
    contract=write_once(tmp_path/'contract.json',runtime.current_contract(build))
    assert runtime.verify_current(contract,build)['runtime_id']==runtime.RUNTIME
    for path in (sources/runtime.SOURCES[-1],tmp_path/'javac',tmp_path/'engine.jar'):
        original=path.read_bytes();path.write_bytes(original+b'drift')
        with pytest.raises(ValueError,match='changed|differs'):runtime.verify_current(contract,build)
        path.write_bytes(original)


@pytest.mark.parametrize('change',[
    lambda g:g.update(admission_scope='diagnostic_subset'),
    lambda g:g.update(full_bundle_admitted=False),
    lambda g:g.update(source_runtime=None),
    lambda g:g['prepared'].update(sha256='f'*64),
    lambda g:g['closure'].update(owned_groups_drained=False),
])
def test_repaired_runtime_rejects_partial_or_mismatched_evidence(tmp_path,monkeypatch,change):
    config,prepared,bundle,gate=admitted(tmp_path,monkeypatch,[])
    altered=deepcopy(gate);change(altered)
    config['admission']=write_once(tmp_path/'bad-admission.json',altered)
    with pytest.raises(ValueError,match='complete shared-runtime'):
        runtime.validate_admission(dict(source_runtime=config),'rdf',prepared,bundle_pin=bundle)


def test_ready_attestation_and_case_coverage_are_checked(tmp_path,monkeypatch):
    manifest=fixture(tmp_path)
    config,prepared,bundle,gate=admitted(tmp_path,monkeypatch,manifest['cells'])
    design=dict(source_runtime=config)
    assert runtime.validate_admission(design,'rdf',prepared,cells=manifest['cells'])==config
    with pytest.raises(ValueError,match='requires RDF'):runtime.validate_admission(design,'native',prepared)
    with pytest.raises(ValueError,match='different frozen bundle'):
        runtime.validate_admission(design,'rdf',prepared,bundle_pin=dict(sha256='f'*64))
    outside=deepcopy(manifest['cells']);outside[0]['request']['sha256']='f'*64
    with pytest.raises(ValueError,match='outside'):runtime.validate_admission(design,'rdf',prepared,cells=outside)
    ready=runtime.load(gate['source_ready']);ready['experimental_lazy_range']=False
    gate['source_ready']=write_once(tmp_path/'wrong-ready.json',ready)
    config['admission']=write_once(tmp_path/'wrong-ready-gate.json',gate)
    with pytest.raises(ValueError,match='Actual serving runtime'):runtime.validate_admission(design,'rdf',prepared)


def test_all_five_methods_share_one_pinned_source_session(tmp_path,monkeypatch):
    from xgap.experiments.ch6_formal_protocol import METHODS
    import ch6_external_session as external
    manifest=fixture(tmp_path);base=manifest['cells'][0];cells=[]
    for i,method in enumerate(METHODS.values()):
        cell=deepcopy(base);cell.update(cell_id=str(i),method=method)
        if method==batch.EXTERNAL_METHOD:
            cell={k:v for k,v in cell.items() if k in ('cell_id','method','request','reference')}
        cells.append(cell)
    config,prepared,_,_=admitted(tmp_path,monkeypatch,cells)
    manifest.update(schema_version=batch.FORMAL_SCHEMA,deployment='rdf',prepared=prepared,cells=cells,
                    external_runtime=write_once(tmp_path/'external.json',{}))
    manifest['design']['source_runtime']=config
    seen,sessions=install_fake_runtime(monkeypatch)
    original=batch.NativeStoreSession
    class Shared(original):
        def __init__(self,**kwargs):
            assert kwargs['file_mode']=='direct' and kwargs['experimental_lazy_range'] is True
            assert kwargs['runtime_contract']==config['contract']
            super().__init__(**kwargs)
    monkeypatch.setattr(batch,'RdfTdbSession',Shared)
    class External:
        def __init__(self,*,source_session,**kwargs):
            assert source_session is sessions[0];self.source_session=source_session
        def start(self):pass
        def close(self):return dict(owned_groups_drained=True,owned_processes_terminal=True,observer_stopped=True)
    monkeypatch.setattr(external,'ExternalSession',External)
    def external_trial(**kwargs):
        return batch.run_nl_trial(output=kwargs['output'],method=batch.EXTERNAL_METHOD,
                                 request_sha256=kwargs['request']['sha256'])
    monkeypatch.setattr(external,'run_trial',external_trial)
    result,_=launch(tmp_path,manifest)
    assert result['status']=='returned' and result['counts']['sealed']==5
    assert seen==['0','1','2','3','4'] and len(sessions)==1 and sessions[0].closed


def test_patched_admission_cannot_fall_back_to_default_unit_runtime(tmp_path,monkeypatch):
    import prepare_ch6_execution_units as units
    profile=dict(path='/profile.json',sha256='a'*64)
    spec=dict(schema_version='xgap-ch6-unit-preparation-v1',method_results_read=0,
              input_track='nl',repetitions=1,bundle={},prepared={},backend_admission={},design={})
    values=iter([spec,dict(profile=profile,deployment='rdf'),dict(success=True,profile=profile),
                 dict(success=True,backend_roundtrip=True,profile=profile,source_runtime=dict(sha256='b'*64))])
    monkeypatch.setattr(units,'load_pin',lambda _:next(values))
    with pytest.raises(ValueError,match='silently release the default'):
        units.prepare('/spec.json','a'*64,tmp_path/'not-created')
    assert not (tmp_path/'not-created').exists()
