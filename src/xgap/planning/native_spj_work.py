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
    prefix=proof.get('prefix_topk');passes=1
    if prefix:
        width=prefix.get('width');cap=prefix.get('maximum_prefixes')
        if (prefix.get('profile')!='complete-prefix-topk-v1' or type(width) is not int
                or not 1<=width<=8 or type(cap) is not int or cap!=limit
                or prefix.get('maximum_prefix_subqueries')!=1+(width-1)*cap
                or not prefix.get('completion_checks_before_limits')
                or not prefix.get('value_prefix_regeneration')):
            raise ValueError('Invalid exact-prefix source-work proof')
        # Charge a full scan/join proxy per possible prefix subquery. EXISTS
        # may stop early but no unmeasured benefit or K-capped edge work is assumed.
        passes=prefix['maximum_prefix_subqueries']
    return dict(scan_records=scan*passes,join_records=join_work*passes,output_records=min(rows,limit),
        profile='native-prefix-source-work-v1' if prefix else 'native-spj-source-work-v1',steps=steps,
        prefix_passes_charged=passes,
        assumptions='Frozen mean then size-biased degree; greedy join proxy, not native EXPLAIN or a bound; full scan/join proxy charged per possible prefix subquery; no assumed EXISTS early-stop benefit',
        measured_latency=False,current_query_observation_calls=0)
