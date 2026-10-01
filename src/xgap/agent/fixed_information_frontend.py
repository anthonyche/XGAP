"""Fixed acquisition order plus one global compilation; no physical-plan search."""
from dataclasses import asdict
import time

from xgap.agent.practical_planning import PracticalSemanticDomain
from xgap.agent.strong_planning import ResourceUsage
from xgap.compilers.global_semantic_sparql import compile_global_program
from xgap.tools.contracts import ToolContext, ToolResult, ToolStatus


def _observed_child(action, spec, result):
    if not isinstance(result, ToolResult) or result.tool_name != action.tool_name:
        raise ValueError('Observed tool does not match the declared acquisition')
    if result.status is ToolStatus.SUCCESS:
        value = result.value
        if not isinstance(value, dict) or set(value) != {'slot', 'candidate_id', 'program_sha256', 'source_id', 'version'}:
            raise ValueError('Expected exactly one scoped binding response')
        if any(value[k] != action.arguments[k] for k in ('slot', 'program_sha256', 'source_id', 'version')):
            raise ValueError('Observed binding authority/version/query differs')
        labels = [label for label, candidate in spec.outcomes if candidate is not None and candidate == value['candidate_id']]
        if len(labels) != 1:
            raise ValueError('Observed binding is outside the declared outcomes')
        label = labels[0]
    else:
        label = 'unavailable' if result.status is ToolStatus.UNAVAILABLE else 'error'
        if dict(spec.outcomes).get(label, 'not-declared') is not None:
            raise ValueError('Unmodeled acquisition failure; no automatic recovery')
    return next(outcome.state for outcome in action.outcomes if outcome.outcome_id == label), label


def prepare_fixed_information_query(program, *, initial_state, mode, actions, predictions,
        resolution_tools, limits, physical_profile, operator_sources, binding_values, sources, backends, mapping):
    """A predeclared sequence is a composite baseline, not a strong-policy claim.

    Every action is attempted at most once. Failed declared outcomes may advance
    within that sequence; malformed/unmodeled outcomes cannot. This function
    never calls a backend, an estimator, another interpretation, or an answer oracle.
    """
    started = time.perf_counter()
    r = {'schema_version': 'xgap-fixed-information-frontend-v1', 'success': False, 'status': 'preparing',
        'policy': 'fixed_action_order_v1', 'mode': mode.mode, 'strong_plan': None,
        'automatic_retries': 0, 'physical_candidates': 0, 'estimator_calls': 0, 'fit_calls': 0,
        'source_calls': 0, 'compilations': 0, 'compilation_ms': 0., 'binding_ms': 0.,
        'model_calls': 0, 'tokens': 0, 'acquisition_remote_calls': 0, 'clarification_calls': 0,
        'acquisition_attempts': 0, 'acquisition_ms': 0., 'usage_complete': True, 'actions': [],
        'selected_program': None, 'artifact': None, 'unvalidated_bindings': None,
        'semantic_validation': None, 'semantic_discrepancy_upper_bound': None, 'discrepancy_status': 'metric_deferred'}
    usage = ResourceUsage()
    def finish():
        r['resource_usage_for_admission'] = asdict(usage)
        r['resource_scope'] = 'unknown acquisition usage reserves its declared bound; author source calls are independently observed and guarded'
        r['frontend_ms'] = (time.perf_counter() - started) * 1000
        return r
    try:
        domain = PracticalSemanticDomain(program, operator_sources=operator_sources, binding_values=binding_values,
            sources=sources, backends=backends, mode=mode, actions=actions, predictions=predictions,
            physical_profile=physical_profile, estimator=None)
        state = initial_state
        def bound():
            at = time.perf_counter()
            try:
                return domain.bind_terminal(state)
            finally:
                r['binding_ms'] += (time.perf_counter() - at) * 1000
        admitted = bound()
        available = {spec.name for spec in resolution_tools.specs()}
        r['declared_action_order'] = [spec.action_id for spec in domain.action_specs]
        for spec in domain.action_specs:
            if admitted is not None:
                break
            if r['acquisition_attempts'] >= min(limits.max_depth, limits.max_actions):
                r['status'] = 'acquisition_step_budget'
                break
            if spec.slot in {e.slot for e in state.evidence} or spec.action_id in state.attempted_actions:
                continue
            record = {'action_id': spec.action_id, 'tool_name': spec.tool_name, 'status': 'considered',
                'reserved_resources': asdict(spec.resources)}
            r['actions'].append(record)
            if spec.tool_name not in available:
                record['status'] = 'adapter_unavailable'
                continue
            if not (usage + spec.resources).fits(limits.resources):
                record['status'] = 'resource_budget'
                continue
            action = next(a for a in domain.actions(state) if a.action_id == spec.action_id)
            record.update(status='started', arguments=dict(action.arguments))
            r['acquisition_attempts'] += 1
            at = time.perf_counter()
            try:
                result = resolution_tools.get(spec.tool_name).invoke(action.arguments,
                    ToolContext(program.program_id, r['acquisition_attempts'], spec.action_id))
            except Exception:
                if spec.resources.model_calls:
                    r.update(model_calls=None, tokens=None, acquisition_remote_calls=None, usage_complete=False)
                raise
            finally:
                r['acquisition_ms'] += (time.perf_counter() - at) * 1000
            if not isinstance(result, ToolResult):
                if spec.resources.model_calls:
                    r.update(model_calls=None, tokens=None, acquisition_remote_calls=None, usage_complete=False)
                raise ValueError('Invalid acquisition result')
            record.update(status='returned', result=result.to_dict())
            # Admission can reserve an unknown cost; it cannot report that reserve
            # as actual paid usage. Preserve unknown independently for each field.
            for key, metric in (('model_calls', 'model_calls'), ('tokens', 'tokens'), ('acquisition_remote_calls', 'remote_calls')):
                value = result.metrics.get(metric, 0 if getattr(spec.resources, metric) == 0 else None)
                if value is None:
                    r[key] = None
                    r['usage_complete'] = False
                elif type(value) is not int or value < 0:
                    r.update(model_calls=None, tokens=None, acquisition_remote_calls=None, usage_complete=False)
                    raise ValueError('Invalid acquisition usage counter')
                elif r[key] is not None:
                    r[key] += value
            r['clarification_calls'] += result.metrics.get('clarification_calls', 0)
            actual = ResourceUsage(*(getattr(spec.resources, k) if result.metrics.get(k) is None
                else result.metrics[k] for k in asdict(usage)))
            usage = usage + actual
            if not actual.fits(spec.resources) or not usage.fits(limits.resources):
                raise ValueError('Acquisition exceeded its resource reservation')
            state, label = _observed_child(action, spec, result)
            record['observed_outcome'] = label
            admitted = bound()
        if admitted is None:
            if r['status'] == 'preparing':
                r['status'] = 'no_admitted_binding'
            return finish()
        bound_query, unresolved = admitted
        r.update(selected_program=bound_query.program.to_dict(), unvalidated_bindings=list(unresolved),
            validation_records=[asdict(e) for e in state.evidence],
            semantic_validation='authorized_prediction' if unresolved else 'all_declared_slots')
        at = time.perf_counter()
        r['compilations'] = 1
        try:
            r['artifact'] = compile_global_program(bound_query.program, mapping).to_dict()
        except Exception as error:
            r.update(status='global_compilation_failed', error_type=type(error).__name__, error=str(error))
            return finish()
        finally:
            r['compilation_ms'] = (time.perf_counter() - at) * 1000
        r.update(success=True, status='query_prepared')
    except Exception as error:
        r.update(status='frontend_failed', error_type=type(error).__name__, error=str(error))
    return finish()
