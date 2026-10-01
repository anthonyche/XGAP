"""One new controller boundary on two saved tiny RDF sources; no native claim."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_compact_lowering import inputs, EXPECTED, RESOURCE
from test_intent_certificate import family
from test_intent_policy import private_oracle, QUESTION
from xgap.agent.intent_certificate import TerminalContract
from xgap.agent.intent_execution import snapshot_identity, run_family_query
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource


def runtime(inputs):
    schema, _, _, mapping, graphs = inputs
    calls=[]
    class LocalSource(FusekiClient):
        def _post_query(self,text):
            calls.append(self.backend_id)
            return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))
    sources={n:LogicalSource(n,'tiny-v1',(n,)) for n in graphs}
    bm=deepcopy(mapping['backend_mapping'])
    for key in ('backends','term_mappings'):
        bm[key]={n:bm[key]['fuseki'] for n in graphs}
    backends={n:SemanticBackend(n,RESOURCE,'xgap_id',backend_mapping=bm,
        profile=replace(default_profile('fuseki'),backend_id=n),
        rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
        rdf_node_classes=tuple(mapping['rdf_node_classes'])) for n in graphs}
    clients={n:LocalSource(BackendDescriptor(n,'fuseki','sparql','rdf')) for n in graphs}
    return dict(source_schema=schema,sources=sources,backends=backends,backend_clients=clients,
        physical_profile=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)),calls


def case(inputs,tmp_path,mode,eps,budget):
    options,calls=runtime(inputs)
    f=family(snapshot_identity(options['sources'],options['backends'],options['source_schema']))
    r=run_family_query(QUESTION,TerminalContract(f,mode=mode,epsilon=eps),private_oracle(tmp_path,f),
        max_clarifications=budget,**options)
    return r,calls


def test_terminal_first_clarification_through_compiler_and_two_sources(inputs,tmp_path):
    exact,ec=case(inputs,tmp_path,'exact','0',2)
    bounded,bc=case(inputs,tmp_path,'performance','1/2',1)
    limited,lc=case(inputs,tmp_path,'exact','0',1)
    assert exact['success'],exact
    assert bounded['success'],bounded
    assert exact['answer_rows']==EXPECTED[1][:3]
    assert bounded['answer_rows']==EXPECTED[1]  # Intent relaxation has a real extra row.
    assert exact['clarification_calls']==2 and bounded['clarification_calls']==1
    assert exact['physical_prepare_attempts']==bounded['physical_prepare_attempts']==1
    assert exact['final_plan_executions']==bounded['final_plan_executions']==1
    assert set(ec)==set(bc)=={'graph','control'}
    for r,calls in ((exact,ec),(bounded,bc)):
        assert r['execution']['result']['metrics']['remote_calls']==len(calls)>0
        assert r['model_calls']==r['tokens']==0 and not r['answer_quality_verified']
    assert not limited['success'] and not lc and limited['physical_prepare_attempts']==0


def test_snapshot_and_truncation_fail_before_acquisition(inputs,tmp_path):
    options,calls=runtime(inputs);f=family('another-snapshot');oracle=private_oracle(tmp_path,f)
    with pytest.raises(ValueError,match='snapshot'):
        run_family_query(QUESTION,TerminalContract(f),oracle,**options)
    assert not calls
