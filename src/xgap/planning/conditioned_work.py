"""Probe valuation in execution-work units, with nonlinear cost propagation.

Average costs over declared outcomes, rather than pricing average cardinalities.
Unknown observations leave the prior unchanged. Multiple target priors are
explicitly factorized; the finite product is bounded, not an unbounded search.
"""
from itertools import product
import math
import json
from xgap.planning.runtime_estimator import _hash
from xgap.runtime.contracts import RuntimeNodeKind as R


def conditioned_cost(model,plan,candidate_id,targets,facts):
    groups=[];handled=set();owned=set();observed_filters={}
    for target in targets:
        if target.kind!='probe' or not target.bindings:continue
        # Scoped cardinalities must never fall back to a backend-wide additive
        # penalty when a rewrite no longer exposes their measured predicate.
        handled.add(target.name)
        probe_filters=json.loads(target.artifact_json)['parameters'].get('necessary_row_filters',{}).get('conditions',[])
        nodes=tuple(n.node_id for n in plan.nodes if n.kind in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY)
            and target.applies(candidate_id,n) and n.parameters['artifact']['parameters'].get('compiler')
            in ('semantic_node_match_v1','semantic_edge_match_v1')
            and {_hash(c) for c in probe_filters}<={_hash(c) for c in n.parameters['artifact']['parameters'].get('necessary_row_filters',{}).get('conditions',[])})
        if not nodes:continue
        if plan.metadata.get('source_identities',{}).get(target.backend)!={'source_id':target.source_id,'snapshot_version':target.version}:
            raise ValueError('Probe source snapshot differs from the physical plan')
        observed_filters.update({n:probe_filters for n in nodes})
        if owned.intersection(nodes):raise ValueError('Overlapping scoped probe cardinalities')
        owned.update(nodes)
        label=facts.get(target.name,'unknown')
        if label!='unknown':options=((target.row_estimates[target.labels.index(label)],1.),)
        elif target.probabilities is not None and sum(target.probabilities[:-1])>0:
            known=math.fsum(target.probabilities[:-1])
            options=tuple((row,p/known) for row,p in zip(target.row_estimates[:-1],target.probabilities[:-1]) if p)
        else:options=((target.prior_rows if target.prior_rows is not None else target.row_estimates[-1],1.),)
        groups.append((nodes,options))
    if not groups:return None,handled
    if math.prod(len(options) for _,options in groups)>256:
        raise ValueError('Probe prior exceeds 256 conditional cost scenarios')
    costs=[]
    for scenario in product(*(options for _,options in groups)):
        observations={node:outcome[0] for (nodes,_),outcome in zip(groups,scenario) for node in nodes}
        probability=math.prod(outcome[1] for outcome in scenario)
        costs.append(probability*model.predict_conditioned(plan,observations,observed_filters=observed_filters).relative_cost)
    return math.fsum(costs),handled
