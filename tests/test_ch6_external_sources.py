import hashlib
import pytest
from check_chapter7_aruqula_fedup import admission_case, public_source_loads, reference_for_case


def test_external_sources_use_profile_loads_instead_of_materialization_parent(tmp_path):
    graph=tmp_path/'declared-graph.ttl';control=tmp_path/'declared-control.ttl';metadata=tmp_path/'metadata.nt'
    graph.write_text('<urn:g> <urn:p> <urn:x> .\n')
    control.write_text('<urn:c> <urn:p> <urn:y> .\n')
    metadata.write_text('<urn:schema> <urn:p> <urn:z> .\n')
    profile={'offline':{'materialization_root':'must-not-be-opened','rdf_loads':{
        n:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for n,p in [('graph',graph),('control',control)]}}}
    output=tmp_path/'output';output.mkdir()
    a,b=public_source_loads(profile,metadata,output)
    assert a.read_bytes()==graph.read_bytes()+b'\n'+metadata.read_bytes() and b==control
    control.write_bytes(graph.read_bytes())
    with pytest.raises(ValueError,match='hash mismatch'):public_source_loads(profile,metadata,output)
    profile['offline']['rdf_loads']['control']['sha256']=hashlib.sha256(control.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='overlap'):public_source_loads(profile,metadata,output)


def test_source_strata_have_separate_inputs_without_reference_leakage():
    single, cross = admission_case('single-source'), admission_case('cross-source')
    assert single['sources'] == ('graph',)
    assert cross['sources'] == ('graph','control')
    assert single['question_id'] != cross['question_id']
    assert set(single) == set(cross) == {'question_id','question','sources','workload_stratum'}
    rows, spec = reference_for_case('single-source')
    assert rows == [{'account_id':str(i)} for i in (1,2,3,4)]
    assert spec['fields'] == {'account_id':'text'}
    with pytest.raises(ValueError): admission_case('unknown')
