from copy import deepcopy
import pytest
from xgap.experiments.ch6_support import validate_support,summarize_supported,paired_xgap_subset
from xgap.experiments.ch6_formal_protocol import METHOD_ORDER


def fixture():
    cases=[]
    for cid, deployment in [('single','rdf'),('rdf-cross','rdf'),('heterogeneous','native')]:
        cases.append(dict(case_id=cid,deployment=deployment,source_snapshot_sha256=cid,
            methods={m:dict(status='unsupported_deployment' if m=='TS' and deployment=='native' else 'supported',
                       basis='frozen deployment capability',evidence_pin={'path':'capability.json','sha256':'test'}) for m in METHOD_ORDER}))
    return dict(schema_version='xgap-ch6-case-support-v1',method_outputs_used=False,cases=cases)


def row(cid,method,success=True,scope='nl'):
    return dict(case_id=cid,method=method,repeat=0,deployment='rdf',source_snapshot_sha256=cid,
        execution_success=success,timing_scope=scope,status='answered' if success else 'timeout',answer_em=0)


def test_support_is_independent_of_failures_and_rdf_cross_is_not_unsupported():
    doc=fixture();rows=[row('single','TS',False),row('rdf-cross','TS')]
    s=summarize_supported(doc,rows,'TS')
    assert s['supported_cases']==2 and s['support_rate']==2/3
    assert s['attempted_requests']==2 and s['completed_requests']==1
    assert s['rows'][0]['answer_em']==0 and s['rows'][1]['answer_em']==0
    with pytest.raises(ValueError,match='outcomes'):validate_support({**doc,'method_outputs_used':True})
    with pytest.raises(ValueError,match='unsupported'):summarize_supported(doc,[row('heterogeneous','TS')],'TS')


def test_pairing_does_not_mix_timing_or_select_by_correctness():
    doc=fixture();rows=[row('single','TS',False),row('rdf-cross','TS'),row('single','XGAP'),row('rdf-cross','XGAP')]
    assert len(paired_xgap_subset(doc,rows,'TS'))==2
    assert len(paired_xgap_subset(doc,rows,'TS',completed_only=True))==1
    rows[-1]['timing_scope']='controlled'
    assert not paired_xgap_subset(doc,rows,'TS',completed_only=True)
    with pytest.raises(ValueError,match='duplicated'):summarize_supported(doc,rows+[rows[0]],'TS')
