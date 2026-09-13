"""Bounded fixed-semantics source routing from published schema, never gold slots."""


def source_assignments(program, schema, sources):
    if program.holes:
        raise ValueError('Fixed semantics must already have resolved holes')
    assignments={};evidence={}
    for op in program.operators:
        if op.input_ids:
            continue
        if op.kind.value!='match':
            raise ValueError('Schema router v1 supports Match remote inputs only')
        p=op.parameters;projected=set(p.get('properties',{}).values());eligible=[]
        def node_supported(spec, nodes, projected=()):
            required=set(spec.get('properties',{}))|set(projected)
            return any((not spec.get('label') or label==spec['label']) and
                required<=set(meta['properties']) for label,meta in nodes.items())
        for source in sorted(sources):
            descriptor=schema.get(source)
            if not isinstance(descriptor,dict) or 'nodes' not in descriptor or 'edges' not in descriptor:
                raise ValueError('Every declared source needs a frozen schema descriptor')
            nodes=descriptor['nodes']
            if 'node' in p:
                supported=node_supported(p['node'],nodes,projected)
            elif 'edge' in p:
                edge=p['edge'];required=set(edge.get('properties',{}))|projected
                supported=any((not edge.get('label') or e['label']==edge['label']) and
                    required<=set(e['properties']) and
                    (not p.get('source',{}).get('label') or p['source']['label']==e['source']) and
                    (not p.get('target',{}).get('label') or p['target']['label']==e['target']) and
                    node_supported({**p.get('source',{}),'label':e['source']},nodes) and
                    node_supported({**p.get('target',{}),'label':e['target']},nodes)
                    for e in descriptor['edges'])
            else:
                raise ValueError('Match needs a node or edge contract')
            if supported:eligible.append(source)
        if not eligible:raise ValueError('No declared source covers required fields for '+op.operator_id)
        assignments[op.operator_id]=eligible[0]
        evidence[op.operator_id]={'eligible_sources':eligible,'selected_source':eligible[0]}
    return assignments,{'policy':'schema_required_fields_then_stable_source_id_v1',
        'source_assignment_from_gold':False,'operators':evidence,'backend_calls':0}
