"""New compact semantics only, executed against saved tiny RDF source facts.

These are compiler/correctness checks, not native-service or latency evidence.
The intents and expected answers are independent of financial_program.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.financial_nl_profile import schema_and_catalog, verified_inputs
from xgap.experiments.finbench_rdf import RESOURCE, SCHEMA
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.semantic.binding import SemanticBindingValue, bind_semantic_query
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import validate_query
from xgap.semantic.program import SemanticHoleKind, hard_constraints_sha256
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


DATA = Path('/Users/anthonyche/xgap-data/financial-binding-native-20260912-v1/rdf')


def node(var, kind, entity=None):
    return {'var': var, 'type': 'XGAPFinBench'+kind.title(), 'entity': entity}


def edge(var, kind, source, target):
    return {'var': var, 'type': kind, 'source': source, 'target': target}


def ref(var, prop=None):
    return {'var': var, 'property': prop}


def pred(var, prop, op, value, *, timestamp=False):
    return {'left': ref(var, prop), 'op': op, 'right': {'value': value},
        'value_type': 'timestamp_ms' if timestamp else 'scalar'}


def window(var, inclusive=True):
    return [pred(var, 'createTime', 'ge', '2020-01-01 00:00:00.000', timestamp=True),
        pred(var, 'createTime', 'le' if inclusive else 'lt', '2020-01-04 00:00:00.000', timestamp=True)]


def query(nodes, edges, select, *, where=(), path=None, dedup=None, order=(), limit=None):
    return {'nodes': nodes, 'edges': edges, 'path': path, 'where': list(where), 'select': select,
        'deduplicate_by': dedup, 'order_by': [{'field': f, 'direction': d} for f, d in order], 'limit': limit}


def sum_amount():
    return {'aggregate': 'sum', 'field': ref('transfer', 'amount'), 'distinct': False}


def financial_intents():
    f1 = query([node('person', 'person', 'Alice'), node('sender', 'account'),
        node('account', 'account'), node('company', 'company')],
        [edge('person_owns', 'OWNS_ACCOUNT', 'person', 'sender'),
         edge('transfer', 'TRANSFERRED_TO', 'sender', 'account'),
         edge('company_owns', 'OWNS_ACCOUNT', 'company', 'account')],
        {'company_id': ref('company', 'id'), 'account_id': ref('account', 'id'), 'total_amount': sum_amount()},
        where=[pred('account', 'isBlocked', 'eq', True), *window('transfer')],
        order=[('total_amount', 'desc'), ('company_id', 'asc'), ('account_id', 'asc')])
    path = {'var': 'reach', 'type': 'TRANSFERRED_TO', 'source': 'start', 'target': 'other',
        'min_hops': 1, 'max_hops': 3, 'mode': 'ACYCLIC', 'time': {'property': 'createTime',
            'lower': '2020-01-01 00:00:00.000', 'upper': '2020-01-04 00:00:00.000',
            'lower_inclusive': True, 'upper_inclusive': True, 'increasing': True}}
    f2 = query([node('start', 'account', 'account 1'), node('other', 'account'), node('medium', 'medium')],
        [edge('signin', 'SIGNED_IN_TO', 'medium', 'other')],
        {'other_id': ref('other', 'id'), 'account_distance': ref('reach', 'length'),
         'medium_id': ref('medium', 'id'), 'medium_type': ref('medium', 'mediumType')},
        path=path, where=[pred('medium', 'isBlocked', 'eq', True)],
        order=[('account_distance', 'asc'), ('other_id', 'asc'), ('medium_id', 'asc')])
    f3 = query([node('company', 'company'), node('account', 'account'),
        node('sender', 'account'), node('medium', 'medium')],
        [edge('owns', 'OWNS_ACCOUNT', 'company', 'account'),
         edge('signin', 'SIGNED_IN_TO', 'medium', 'account'),
         edge('transfer', 'TRANSFERRED_TO', 'sender', 'account')],
        {'company_id': ref('company', 'id'), 'total_amount': sum_amount()},
        where=[pred('medium', 'riskLevel', 'eq', 'High risk'), *window('transfer', False)],
        dedup=['company', 'transfer'], order=[('total_amount', 'desc'), ('company_id', 'asc')], limit=10)
    return [f1, f2, f3]


EXPECTED = [
    [{'company_id': '1', 'account_id': '2', 'total_amount': 66.0},
     {'company_id': '1', 'account_id': '3', 'total_amount': 9.0}],
    [{'other_id': '2', 'account_distance': 1, 'medium_id': '1', 'medium_type': 'PHONE'},
     {'other_id': '2', 'account_distance': 1, 'medium_id': '2', 'medium_type': 'PHONE'},
     {'other_id': '3', 'account_distance': 1, 'medium_id': '1', 'medium_type': 'PHONE'},
     {'other_id': '3', 'account_distance': 2, 'medium_id': '1', 'medium_type': 'PHONE'}],
    [{'company_id': '1', 'total_amount': 56.0}],
]


@pytest.fixture
def inputs():
    schema, catalog, bindings, mapping = schema_and_catalog(*verified_inputs())
    graphs = {name: Graph().parse(DATA/(name+'.ttl')) for name in ('graph', 'control')}
    return schema, catalog, bindings, mapping, graphs


def execute(intent, inputs, *, version='v1'):
    schema, catalog, bindings, mapping, graphs = inputs
    program, sources = lower_compact_query(intent, schema, version=version)
    sets = []
    for hole in program.holes:
        choices = [e['candidate_id'] for e in catalog['entries'] if e['kind'] == 'entity'
            and e['canonical_label'] == hole.mention]
        assert len(choices) == 1
        sets.append({'hole_id': hole.hole_id, 'candidate_ids': choices, 'authoritative': False,
            'selection_policy': 'predicted_catalog_choice', 'sources': ['frozen-tiny']})
    if sets:
        values = {c: SemanticBindingValue(SemanticHoleKind.ENTITY, bindings[c]['value'], 'xgap_id')
            for s in sets for c in s['candidate_ids']}
        bound = bind_semantic_query(program, {'program_id': program.program_id,
            'hard_constraints_sha256': hard_constraints_sha256(program), 'hard_constraints_preserved': True,
            'candidate_sets': sets}, binding_values=values, operator_sources=sources, allow_predicted_entities=True)
        assert all(not b['authoritative'] for b in bound.bindings.values())
        program = bound.program
    backend = SemanticBackend('fuseki', RESOURCE, 'xgap_id', backend_mapping=mapping['backend_mapping'],
        rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']), rdf_node_classes=tuple(mapping['rdf_node_classes']))
    plan = compile_semantic_program(program, source_bindings={op: 'fuseki' for op in sources},
        backends={'fuseki': backend}, max_remote_calls=64, max_parallelism=1)
    calls = []
    class LocalSources(FusekiClient):
        def execute(self, artifact):
            self.source = sources[artifact.artifact_id.removesuffix('-match')]
            return super().execute(artifact)

        def _post_query(self, text):
            calls.append(self.source)
            return json.loads(graphs[self.source].query(text).serialize(format='json'))

    registry = BackendPluginRegistry()
    registry.register(NativeBackendPlugin('fuseki', LocalSources(BackendDescriptor('fuseki', 'fuseki', 'sparql', 'rdf'))))
    result = FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
    assert result.success, result.to_dict()
    assert len(calls) == len(sources) == result.total_remote_calls
    return list(result.final_rows), program, sources


@pytest.mark.parametrize('index', [0, 1, 2], ids=['direct-sum', 'temporal-reachability', 'risk-dedup-sum'])
def test_compact_financial_meanings_on_separate_source_facts(inputs, index):
    rows, program, sources = execute(financial_intents()[index], inputs)
    assert rows == EXPECTED[index]
    assert set(sources.values()) == {'graph', 'control'}
    assert len(program.operators) <= 64
    # Control predicates must cause control reads, never a fabricated property on graph.
    for op in program.operators:
        if op.operator_id in sources:
            properties = op.parameters.get('properties', {})
            assert not set(properties).intersection({op.parameters.get('entity_field'),
                op.parameters.get('source_field'), op.parameters.get('target_field')})


def test_equal_valued_parallel_edges_survive_medium_dedup(inputs):
    graph = inputs[-1]['graph']; fb = Namespace(SCHEMA)
    original = next(e for e in graph.subjects(fb.amount, Literal(10.125)))
    duplicate = URIRef(RESOURCE+'independent-parallel-transfer')
    for p, value in list(graph.predicate_objects(original)):
        graph.add((duplicate, p, Literal('independent-parallel-transfer') if p == fb.xgap_id else value))
    assert (duplicate, RDF.type, fb.Edge) in graph
    rows, _, _ = execute(financial_intents()[2], inputs)
    assert rows == [{'company_id': '1', 'total_amount': 66.125}]


def test_every_repeated_endpoint_is_a_join_equality(inputs):
    intent = query([node('a', 'account'), node('b', 'account')],
        [edge('x', 'TRANSFERRED_TO', 'a', 'b'), edge('y', 'TRANSFERRED_TO', 'a', 'b')],
        {'pairs': {'aggregate': 'count', 'field': None, 'distinct': False}})
    # Three parallel 1->2 edges give9 pairs, five other endpoint pairs give1 each.
    # Joining on source alone would incorrectly produce24.
    rows, _, _ = execute(intent, inputs)
    assert rows == [{'pairs': 14}]


def test_temporal_boundary_rejects_equal_times_and_window_endpoint(inputs):
    intent = financial_intents()[1]
    intent['path']['time']['lower_inclusive'] = False
    rows, _, _ = execute(intent, inputs)
    assert rows == EXPECTED[1][:3]


def test_closed_temporal_cycle_is_walk_but_not_acyclic(inputs):
    path = deepcopy(financial_intents()[1]['path'])
    path['target'] = 'start'
    intent = query([node('start', 'account', 'account 1')], [],
        {'distance': ref('reach', 'length')}, path=path, order=[('distance', 'asc')])
    # 1->2 on Jan1, 2->3 on Jan2, 3->1 on Jan3; parallel paths collapse by length.
    rows, _, _ = execute(intent, inputs)
    assert rows == []
    intent['path']['mode'] = 'WALK'
    rows, _, _ = execute(intent, inputs)
    assert rows == [{'distance': 3}]


def test_hop_bounds_are_integers_and_simple_is_not_redefined():
    for key, value in [('min_hops', True), ('max_hops', 3.0), ('mode', 'SIMPLE')]:
        intent = financial_intents()[1]; intent['path'][key] = value
        with pytest.raises(ValueError): validate_query(intent)


def test_coverage_and_identity_errors_fail_before_any_execution(inputs):
    intent = financial_intents()[0]
    missing = deepcopy(intent); missing['select']['x'] = ref('account', 'does_not_exist')
    with pytest.raises(ValueError, match='No declared source'): lower_compact_query(missing, inputs[0])
    partial = deepcopy(inputs[0]); partial['extra'] = deepcopy(partial['graph'])
    for e in partial['extra']['edges']:
        if e['label'] == 'TRANSFERRED_TO': e['properties'].remove('amount')
    with pytest.raises(ValueError, match='Partial edge-attribute coverage'): lower_compact_query(intent, partial)
    identity = deepcopy(intent); identity['where'].append(pred('person', None, 'eq', 'person_31'))
    with pytest.raises(ValueError, match='canonical identity'): lower_compact_query(identity, inputs[0])
    wrong_key = deepcopy(intent); wrong_key['deduplicate_by'] = ['company']
    with pytest.raises(ValueError, match='Post-distinct'): lower_compact_query(wrong_key, inputs[0])
    huge = deepcopy(intent); huge['path'] = financial_intents()[1]['path']; huge['path']['max_hops'] = 4
    with pytest.raises(ValueError): validate_query(huge)
