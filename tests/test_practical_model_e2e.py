"""Same ordinary request: controlled wire -> strong policy -> real local SPARQL.

Only these new outcome/admission risks run here; no live network or benchmark.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from practical_model_fixture import FIXTURE, KEY_ENV, model_provider, prepare_model
from test_m15_llm_resolution_provider import _Transport, _envelope
from test_strong_planning import Domain, action
from xgap.agent.practical_execution import run_practical_semantic_query
from xgap.agent.practical_planning import PracticalMode
from xgap.agent.question import run_question
from xgap.agent.strong_planning import TerminalAlternative, search_strong_policy
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.tools import ToolRegistry


def local_setup(tmp_path,transport):
    proposal=model_provider(transport)
    case,request,provider,program,bundle,ref,sources,backends,options=prepare_model(tmp_path,proposal)
    rdf=pytest.importorskip('rdflib',minversion='7.1.4'); calls=[];lock=threading.Lock()
    graph=rdf.Graph().parse(FIXTURE/'load.ttl',format='turtle')
    class Client(FusekiClient):
        def __init__(self,name):
            super().__init__(BackendDescriptor(name,'fuseki','sparql','rdf'))
        def _post_query(self,text):
            calls.append((self.backend_id,text))
            with lock:return json.loads(graph.query(text).serialize(format='json'))
    mapping=RdfBackendMapping.from_artifact(json.loads((FIXTURE/'mapping.json').read_text()),backend_id='fuseki')
    original=backends['fuseki']; names=('rdf-paths','rdf-people')
    backends={name:replace(original,backend_id=name,backend_mapping=replace(mapping,backend_id=name),
        profile=replace(default_profile('fuseki'),backend_id=name)) for name in names}
    sources={k:replace(sources[k],replica_backend_ids=(name,)) for k,name in zip(('toy','toy-people'),names)}
    kwargs=dict(catalog_root=FIXTURE/'snapshot',catalog_hash=ref['bundle_hash'],sources=sources,
        backends=backends,backend_clients={n:Client(n) for n in names},estimator=None)
    return proposal,request,provider,program,bundle,options,kwargs,calls


@pytest.mark.parametrize('candidate,clarifications,edge',[
    ('predicate:knows',0,'e4'),('predicate:follows',0,'e9'),('multiple',1,'e4'),('invalid',1,'e4')])
def test_single_request_all_model_outcomes_have_real_continuations(tmp_path,monkeypatch,candidate,clarifications,edge):
    monkeypatch.setenv(KEY_ENV,'local-test-placeholder')
    candidates=['predicate:knows','predicate:follows'] if candidate=='multiple' else [candidate]
    transport=_Transport([_envelope({'hole_id':'predicate','candidate_ids':candidates})])
    proposal,request,provider,program,bundle,options,kwargs,calls=local_setup(tmp_path,transport)
    reads=[];read=Path.read_text
    def watched(self,*args,**kw):
        if self==tmp_path/'clarification-bindings-only.json':reads.append(str(self))
        if self==FIXTURE/'gold.json':raise AssertionError('Gold entered live selection')
        return read(self,*args,**kw)
    monkeypatch.setattr(Path,'read_text',watched)
    planned=run_practical_semantic_query(program,initial_state=options.initial_state,mode=options.mode,
        actions=options.actions,resolution_tools=options.resolution_tools,limits=options.limits,
        operator_sources=provider.operator_sources,binding_values=bundle.bindings,
        sources=kwargs['sources'],backends=kwargs['backends'],backend_clients=kwargs['backend_clients'],execute=False)
    tree=planned['search']['policy']
    assert tree['action_id']=='llm:predicate'
    assert set(tree['children'])=={'candidate-0','candidate-1','error','unavailable'}
    assert all(tree['children'][k]['action_id']=='clarify-predicate' for k in ('error','unavailable'))
    assert not reads and not calls and not transport.calls
    result=run_question(request,provider,practical_options=options,**kwargs)
    assert result['success'],result
    assert len(transport.calls)==result['model_calls']==result['acquisition_remote_calls']==1
    assert result['clarification_calls']==len(reads)==clarifications
    assert len(calls)==result['backend_remote_calls']==2 and result['final_plan_executions']==1
    assert result['answer_rows']==[{'person':'https://xgap.test/toy/'+('z' if edge=='e9' else 'c'),
                                  'edge':'https://xgap.test/toy/'+edge}]
    assert result['execution']['unvalidated_bindings']==([] if clarifications else ['predicate'])
    assert all(result['execution']['bindings'][s]['authoritative'] for s in ('person','age','source','type'))
    assert result['search']['selected_estimated_cost'] is None
    assert result['search']['external_calls_during_search']==0 and result['discrepancy_status']=='metric_deferred'


def test_exact_uses_authority_without_calling_proposal_only_model(tmp_path,monkeypatch):
    monkeypatch.setenv(KEY_ENV,'local-test-placeholder')
    transport=_Transport([_envelope({'hole_id':'predicate','candidate_ids':['predicate:follows']})])
    _,request,provider,_,_,options,kwargs,calls=local_setup(tmp_path,transport)
    result=run_question(request,provider,practical_options=replace(options,mode=PracticalMode()),**kwargs)
    assert result['success'],result
    # Current evidence-progress pruning already skips a model that cannot
    # discharge any EXACT authority obligation. It must not pay a useless call.
    assert result['model_calls']==len(transport.calls)==0 and result['clarification_calls']==1
    assert result['execution']['unvalidated_bindings']==[] and result['answer_rows'][0]['edge'].endswith('e4')
    assert len(calls)==2


def test_model_without_complete_failure_continuation_never_calls_remote(tmp_path,monkeypatch):
    monkeypatch.setenv(KEY_ENV,'local-test-placeholder')
    transport=_Transport([])
    _,request,provider,_,_,options,kwargs,calls=local_setup(tmp_path,transport)
    registry=ToolRegistry();registry.register(options.resolution_tools.get('practical.llm:predicate'))
    options=replace(options,actions=(options.actions[0],),resolution_tools=registry)
    result=run_question(request,provider,practical_options=options,**kwargs)
    assert result['status']=='no_feasible_plan' and not calls and not transport.calls


def test_unknown_acquisition_cost_is_not_zero_and_known_incumbent_survives():
    domain=Domain({'done':[TerminalAlternative('done',2,{})]},
        {'root':[action('unknown',[('known','done')],None)]})
    result=search_strong_policy('root',domain)
    assert result.policy and result.policy.estimated_cost is None
    domain.t['root']=[TerminalAlternative('root-known',100,{})]
    result=search_strong_policy('root',domain)
    assert result.policy.terminal.terminal_id=='root-known'
    assert result.policy.estimated_cost==100 and result.action_records[0]['estimated_cost'] is None


def test_search_priority_is_explicit_and_reordering_changes_first_feasible_policy(tmp_path):
    transport=_Transport([])
    _,request,provider,_,_,options,kwargs,calls=local_setup(tmp_path,transport)
    # Zero priority difference retains the legacy known-cost ordering. The new
    # ordering is explicit; neither value is silently substituted for elapsed time.
    options=replace(options,actions=(replace(options.actions[0],search_priority=2),options.actions[1]))
    result=run_question(request,provider,practical_options=options,**kwargs)
    assert result['success'] and result['search']['policy']['action_id']=='clarify-predicate'
    assert not transport.calls and result['model_calls']==0 and result['clarification_calls']==1
    assert result['acquisition_actions'][0]['estimated_ms'] is None
