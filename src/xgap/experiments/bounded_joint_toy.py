"""Portable synthetic development slice, never a benchmark/model-quality score."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import re

from xgap.agent.intent_certificate import IntentSlot
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.finbench_rdf import RESOURCE
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.intent_scope import ScopePolicy, ScopeDomain
from xgap.semantic.interpretation import InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA

FIXTURE = Path(__file__).resolve().parents[3]/'datasets/bounded_joint_toy_v1'
QUESTION = 'For account 1, find reachable accounts and their blocked sign-in media, using the intended path and time conventions.'


def load_inputs():
    from rdflib import Graph
    data = json.loads((FIXTURE/'fixture.json').read_text())
    graphs = {name: Graph().parse(FIXTURE/(name+'.ttl')) for name in ('graph','control')}
    return data, graphs


def toy_scope():
    return ScopePolicy('finite-path-and-window-v1', (
        ScopeDomain(IntentSlot('hops', ('path','max_hops'), weight=2), (1,3)),
        ScopeDomain(IntentSlot('lower', ('path','time','lower_inclusive')), (False,True)),
        ScopeDomain(IntentSlot('upper', ('path','time','upper_inclusive')), (False,True))))


class TemplateProposalProvider:
    """Explicit bounded English grammar. Other language can use the compact LLM provider."""
    provider_id = 'bounded-path-template-v1'

    def __init__(self, query_template):
        self.template = deepcopy(query_template)

    def interpret(self, request):
        match = re.fullmatch(r'For account ([0-9]{1,20}), find reachable accounts and their blocked sign-in media, using the intended path and time conventions\.', request.question)
        if not match:
            raise ValueError('Question is outside this deterministic template grammar')
        query = deepcopy(self.template)
        query['where'][-1]['right']['value'] = match.group(1)
        program, sources = lower_compact_query(query, request.context['source_schema'])
        return InterpretationResponse({'schema_version': SCHEMA, 'candidates': [dict(candidate_id='parsed',
            quality_proxy=None, program=program.to_dict(), operator_sources=sources)]},
            provenance={'usage_reported': True, 'raw_compact_response': {'candidates': [dict(candidate_id='parsed',query=query)]},
                        'interpretation_kind': 'declared_template_grammar'}, external_calls=0, input_tokens=0, output_tokens=0)


def local_runtime():
    data, graphs = load_inputs()
    calls = []
    class LocalSource(FusekiClient):
        def _post_query(self, text):
            calls.append(self.backend_id)
            return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))
    sources = {n: LogicalSource(n,'tiny-v1',(n,)) for n in graphs}
    mapping = data['mapping']; bm = deepcopy(mapping['backend_mapping'])
    for key in ('backends','term_mappings'):
        bm[key] = {n: bm[key]['fuseki'] for n in graphs}
    backends = {n: SemanticBackend(n,RESOURCE,'xgap_id',backend_mapping=bm,
        profile=replace(default_profile('fuseki'),backend_id=n),rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
        rdf_node_classes=tuple(mapping['rdf_node_classes'])) for n in graphs}
    clients = {n: LocalSource(BackendDescriptor(n,'fuseki','sparql','rdf')) for n in graphs}
    return data, dict(source_schema=data['schema'],sources=sources,backends=backends,backend_clients=clients,
        physical_profile=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)), calls
