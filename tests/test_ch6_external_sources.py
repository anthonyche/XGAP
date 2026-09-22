import hashlib
import pytest
from check_chapter7_aruqula_fedup import public_source_loads


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
