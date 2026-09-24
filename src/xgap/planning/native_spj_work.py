"""Answer-blind source work proxy; final top-K never caps join/scan work."""
from xgap.compilers.native_spj import PROFILE


def source_work(parameters, backend, populations, endpoint_degrees, unique_properties):
    if parameters.get('compiler') != PROFILE:
        raise ValueError('Unknown native source-work compiler')
    graph = parameters['source_work_graph']; proof = parameters['source_pushdown']
    nodes, edges = graph['nodes'], graph['edges']
    limit = proof['final_output_limit']
    if (not 1 <= len(nodes) <= 192 or len(edges) > 64
            or len(graph['identity_equalities']) > 512 or len(graph['constant_equalities']) > 512
            or type(limit) is not int or not 1 <= limit <= 1000):
        raise ValueError('Invalid native source-work representation bound')
    vertices = set(nodes) | {e['variable'] for e in edges}
    parent = {v:v for v in vertices}
    def root(v):
        if v not in parent:raise ValueError('Unknown source-work identity')
        while parent[v] != v:
            parent[v] = parent[parent[v]];v = parent[v]
        return v
    for a,b in graph['identity_equalities']:
        a,b=root(a),root(b);parent[max(a,b)] = min(a,b)
    known = {root(v) for v,p in graph['constant_equalities'] if v in nodes and p in unique_properties}
    node_rows, edge_rows = populations
    # Full domain scans remain charged. No claim that LIMIT permits bounded
    # adjacency scanning, that an index exists, or that native join order is known.
    scan = float(node_rows)*len({root(v) for v in nodes}) + float(edge_rows)*len(edges)
    rows = 1. if known else float(node_rows)
    if not known:known.add(root(sorted(nodes)[0]))
    pending = list(enumerate(edges)); join_work = 0.; steps = []
    while pending:
        choices=[]
        for i,e in pending:
            a,b=root(e['source']),root(e['target'])
            endpoints=[role for role,v in [('source',a),('target',b)] if v in known]
            estimates=[]
            for role in endpoints:
                info=endpoint_degrees.get((backend,e['label'],role))
                fanout=(info[2]/max(1,info[0]) if steps else info[0]/max(1,info[1])) if info else edge_rows/max(1,node_rows)
                estimates.append((fanout,role))
            fanout,role=min(estimates) if estimates else (float(edge_rows),None)
            choices.append((role is None,fanout,i,e,role))
        _,fanout,i,e,role=min(choices,key=lambda x:x[:3])
        rows=min(1e100,rows*fanout);join_work+=rows
        known.update((root(e['source']),root(e['target'])))
        pending=[pair for pair in pending if pair[0]!=i]
        steps.append(dict(edge=e['variable'],label=e['label'],bound_endpoint=role,
            fanout_proxy=fanout,intermediate_rows_proxy=rows))
    return dict(scan_records=scan,join_records=join_work,output_records=min(rows,limit),
        profile='native-spj-source-work-v1',steps=steps,
        assumptions='Frozen mean then size-biased degree; greedy connected join proxy, not native EXPLAIN or a bound; full scans charged; LIMIT caps output only',
        measured_latency=False,current_query_observation_calls=0)
