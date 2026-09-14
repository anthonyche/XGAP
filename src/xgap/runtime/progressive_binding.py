"""One polynomial, semantics-preserving composition of entity semijoin binds."""
from collections import Counter
from dataclasses import replace
from functools import lru_cache

from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.anchor_reduction import depends_on
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.semantic.program import SemanticOperatorKind as S


def progressive_bind(program, seed, *, source_bindings, backends, max_bindings, max_binding_bytes):
    # Imported here to keep the strategy module's existing compiler helpers as
    # the single authority for native syntax and exclusive target admission.
    from xgap.runtime.physical_strategies import _entity_lineage, _target_match, _bound_match_artifact, _NotAdmitted
    operators = {op.operator_id: op for op in program.operators}
    consumers = Counter(i for op in program.operators for i in op.input_ids)
    is_entity = _entity_lineage(operators, seed.metadata['schemas'])

    @lru_cache(None)
    def depth(identifier):
        return 1 + max((depth(i) for i in operators[identifier].input_ids), default=0)

    joins = sorted((op for op in program.operators if op.kind is S.JOIN),
                   key=lambda op: (depth(op.operator_id), op.operator_id))
    plan = seed; rewrites = []; skipped = []
    for join in joins:
        for driving_index in (0, 1):
            direction = 'left_to_right' if driving_index == 0 else 'right_to_left'
            driver_id, target_id = join.input_ids[driving_index], join.input_ids[1-driving_index]
            driver_field = join.parameters['left_on' if driving_index == 0 else 'right_on']
            target_field = join.parameters['right_on' if driving_index == 0 else 'left_on']
            try:
                if not is_entity(driver_id, driver_field):
                    raise _NotAdmitted('Driving key has no canonical entity lineage')
                target, chain, column = _target_match(target_id, target_field, operators, consumers, set(program.roots))
                remote_id = target.operator_id + '/native'
                by_id = {n.node_id: n for n in plan.nodes}
                remote = by_id[remote_id]
                if remote.kind is not R.REMOTE_QUERY:
                    raise _NotAdmitted('Target already bound by an earlier step')
                output = plan.metadata['operator_outputs'][driver_id]
                if depends_on(plan, output, remote_id):
                    raise _NotAdmitted('Accumulated bind dependency would create a cycle')
                artifact, parameter = _bound_match_artifact(QueryArtifact.from_dict(remote.parameters['artifact']),
                    backends[source_bindings[target.operator_id]], max_bindings=max_bindings,
                    max_binding_bytes=max_binding_bytes, identity_column=column)
                bound = replace(remote, kind=R.REMOTE_BIND_QUERY, inputs=(output,),
                    parameters={**dict(remote.parameters), 'artifact':artifact.to_dict(),
                        'bind_field':driver_field, 'parameter':parameter, 'max_bindings':max_bindings})
                plan = replace(plan, nodes=tuple(bound if n.node_id == remote_id else n for n in plan.nodes))
                rewrites.append({'join':join.operator_id,'direction':direction,'driver':driver_id,
                    'driver_output':output,'driver_field':driver_field,'target_match':target.operator_id,
                    'target_chain':list(chain),'native_identity_column':column})
                break
            except _NotAdmitted as error:
                skipped.append({'join':join.operator_id,'direction':direction,'reason':str(error)})
    return plan, {'rewrite_count':len(rewrites),'rewrites':rewrites,'skipped':skipped,
        'seed_strategy':seed.metadata.get('physical_strategy','coordinator'),
        'seed_bind_count':sum(n.kind is R.REMOTE_BIND_QUERY for n in seed.nodes),
        'order':'semantic_depth_then_id_left_driver_first','max_bindings':max_bindings,
        'sparql_max_binding_bytes':max_binding_bytes,'extra_remote_call_slots':0,
        'combination_enumeration':False,'actual_cost_optimality_claim':False}
