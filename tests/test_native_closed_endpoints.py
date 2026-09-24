"""Necessary endpoint domains, not physical-node aliasing or guessed selectivity."""
from copy import deepcopy

import pytest

from test_native_spj import compile_query, fixture
from xgap.compilers.native_spj import _bind_closed_endpoints, _render_stage


@pytest.mark.parametrize('prefix', [False, True])
def test_cycle_resolves_both_logical_domains_and_retains_complete_predicates(prefix):
    q, _, _ = fixture()
    q['edges'].append(dict(var='h', type='LINK', source='a', target='d'))
    artifact, _ = compile_query(q, prefix_topk=prefix)
    proof = artifact.parameters['source_pushdown']
    closed = proof['closed_endpoint_access']
    assert closed['logical_identity_domains_preserved']
    assert not proof['native_identity_coalescing']
    for edge in closed['edges']:
        for binding in edge['bindings']:
            assert binding['variable'] != binding['outer']
            assert binding['variable']+'.key = '+binding['outer']+'.key' in artifact.text
    assert all(eq in artifact.text for eq in proof['access_equalities'])
    assert 'coalesce(' in artifact.text
    if prefix:
        assert proof['prefix_topk']['completion_checks_before_limits']
        assert proof['prefix_topk']['value_prefix_regeneration']


@pytest.mark.parametrize('equalities', [[], [['a', 'x']], [['a', 'x'], ['b', 'not_bound']]])
def test_partial_or_nonidentity_links_cannot_bind_two_endpoints(equalities):
    stages = [dict(index=0, variables=('x','y')),
        dict(index=1, variables=('a','e','b'), imports=['x','y'])]
    graph = dict(nodes={v:'N' for v in ('x','y','a','b','not_bound')},
        edges=[dict(variable='e', source='a', target='b')], identity_equalities=equalities)
    assert _bind_closed_endpoints(stages, graph, 'key') == []
    assert 'endpoint_seeks' not in stages[1]


def test_both_endpoints_may_share_logical_key_without_sharing_physical_node():
    stages = [dict(index=0, variables=('x',)),
        dict(index=1, variables=('a','e','b'), imports=['x'], first=False,
            pattern='MATCH (a:N)-[e:R]->(b:N)', predicates=['a.key = x.key','b.key = x.key'])]
    graph = dict(nodes={v:'N' for v in ('x','a','b')},
        edges=[dict(variable='e', source='a', target='b')],
        identity_equalities=[['a','x'],['b','x']])
    proof = _bind_closed_endpoints(stages, graph, 'key')
    assert len(proof)==1
    text = _render_stage(stages[1])
    assert 'MATCH (a:N)' in text and 'MATCH (b:N)' in text
    assert 'MATCH (a:N)-[e:R]->(b:N)' in text
    assert 'MATCH (x:N)-' not in text


def test_open_path_query_and_work_proxy_remain_unchanged():
    artifact, _ = compile_query()
    assert 'closed_endpoint_access' not in artifact.parameters['source_pushdown']
    from xgap.planning.native_spj_work import source_work
    kwargs=dict(backend='neo4j',populations=(100,1000),endpoint_degrees={},unique_properties=('name',))
    before=source_work(artifact.parameters,**kwargs)
    changed=deepcopy(artifact.parameters)
    changed['source_pushdown']['closed_endpoint_access']={'profile':'independent-keyed-endpoints-v1'}
    # No unmeasured speed credit is inserted into the frozen v1/v2/v3 model.
    assert source_work(changed,**kwargs)==before
