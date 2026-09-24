"""Exact single-source select/project/join and final top-K for a bounded profile.

Independent MATCH clauses deliberately retain relationship reuse. Joins compare
declared logical identity properties, not native object identity; duplicate IDs
are therefore not silently assumed unique. No intermediate relation is limited.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json

from xgap.compilers.cypher import _cypher_identifier as ident
from xgap.compilers.features import default_profile
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.semantic.program import SemanticOperatorKind as S


PROFILE = 'native-spj-final-topk-v1'


@dataclass(frozen=True)
class Value:
    text: str
    kind: str
    origin: tuple | None = None


def compile_native_spj(program, backend, schema, source_bindings):
    """Compile only admitted meaning; unsupported input raises before execution."""
    raw = program.to_dict()
    if (program.holes or len(program.roots) != 1 or not 1 <= len(program.operators) <= 64
            or len(json.dumps(raw).encode()) > 131072):
        raise ValueError('Native SPJ needs a grounded bounded single-root program')
    profile = backend.profile or default_profile(backend.backend_id)
    if profile.engine != 'neo4j' or profile.language.lower() != 'cypher':
        raise ValueError('Native SPJ requires the Neo4j capability profile')
    if schema.get('identity_property') != backend.identity_property:
        raise ValueError('Native SPJ identity declaration differs')
    types = schema.get('scalar_semantics', {})
    scalar_types = {'string': 'string', 'boolean': 'boolean',
                    'integer milliseconds': 'integer', 'integer': 'integer', 'number': 'number'}
    allowed = {S.MATCH, S.FILTER, S.JOIN, S.PROJECT, S.ORDER_LIMIT}
    if any(o.kind not in allowed or o.constraints or o.required_capabilities for o in program.operators):
        raise ValueError('Native SPJ excludes union, aggregation, traversal and extra capabilities')
    if any(o.kind is S.ORDER_LIMIT and o.operator_id != program.roots[0] for o in program.operators):
        raise ValueError('Native SPJ only admits final OrderLimit')
    consumers = Counter(i for o in program.operators for i in o.input_ids)
    if any(n > 1 for n in consumers.values()):
        raise ValueError('Native SPJ tree bound excludes shared semantic subexpressions')
    matches = {o.operator_id: o for o in program.operators if o.kind is S.MATCH}
    if not matches or set(source_bindings) != set(matches) or set(source_bindings.values()) != {backend.backend_id}:
        raise ValueError('Every required Match must use the same placed backend')
    # Reuse semantic admission, column renaming, and the authoritative schemas.
    bare = compile_semantic_program(program, source_bindings=source_bindings,
        backends={backend.backend_id: backend}, max_remote_calls=64, max_parallelism=1)
    relations = {}; patterns = []; conditions = []; parameters = {}; predicate_count = 0
    access_equalities = []
    work_graph = dict(nodes={}, edges=[], identity_equalities=[], constant_equalities=[])
    namespace = backend.resource_namespace

    def param(value):
        name = 'spj_p' + str(len(parameters)); parameters[name] = value
        return '$' + name

    ns = param(namespace)

    def render(value):
        return '(' + ns + ' + ' + value.text + ')' if value.kind == 'identity' else value.text

    def prop(variable, name):
        kind = scalar_types.get(types.get(name))
        if kind is None:
            raise ValueError('Native SPJ scalar property has no admitted frozen type')
        return Value(variable + '.' + ident(name), kind, (variable, name))

    def condition(c, fields, guaranteed=True):
        nonlocal predicate_count
        predicate_count += 1
        if predicate_count > 512:
            raise ValueError('Native SPJ predicate bound exceeded')
        op = c['op']
        if op in ('and', 'or'):
            return '(' + (' AND ' if op == 'and' else ' OR ').join(condition(a, fields, guaranteed and op == 'and') for a in c['args']) + ')'
        if op == 'not':
            return '(NOT ' + condition(c['arg'], fields, False) + ')'
        left = fields[c['field']]
        if op in ('is_null', 'is_not_null'):
            return '(' + render(left) + (' IS NULL)' if op == 'is_null' else ' IS NOT NULL)')
        if 'right_field' in c:
            right = fields[c['right_field']]
        else:
            value = c['value']
            if value is None:
                return 'false'
            kind = {str: 'string', bool: 'boolean', int: 'integer'}.get(type(value))
            if kind is None or kind == 'integer' and abs(value) > 2**53:
                raise ValueError('Native SPJ constants require string, boolean or exact-range integer')
            right = Value(param(value), kind)
        value_type = c.get('value_type')
        if guaranteed and op == 'eq':
            if left.kind == right.kind == 'identity':
                work_graph['identity_equalities'].append([left.origin[0], right.origin[0]])
            elif 'value' in c and left.origin and left.origin[0] in work_graph['nodes']:
                work_graph['constant_equalities'].append(list(left.origin))
        if value_type == 'timestamp_ms':
            raise ValueError('Calendar-string timestamp conversion is outside native SPJ')
        lk = 'string' if left.kind == 'identity' else left.kind
        rk = 'string' if right.kind == 'identity' else right.kind
        numeric = lk in ('number', 'integer') and rk in ('number', 'integer')
        if numeric and 'right_field' in c and 'number' in (lk, rk):
            raise ValueError('Mixed floating field comparison requires a separate proof')
        if value_type == 'lexical_string' and (lk != 'string' or rk != 'string'):
            return 'false'
        if value_type != 'lexical_string' and op not in ('eq', 'ne') and not numeric:
            return 'false'
        # Existing typed equality never coerces strings/bools to numbers. All
        # comparisons, including !=, are false when either operand is null.
        if not numeric and lk != rk:
            comparison = 'true' if op == 'ne' else 'false'
        else:
            a, b = (left.text, right.text) if left.kind == right.kind == 'identity' else (render(left), render(right))
            comparison = a + ' ' + {'eq': '=', 'ne': '<>', 'lt': '<', 'le': '<=', 'gt': '>', 'ge': '>='}[op] + ' ' + b
            # A true guarded equality necessarily makes this equality true.
            # Expose it to native index/join planning without removing any
            # total nullable predicate. Never lift out of OR or NOT: those
            # contexts need not make this particular equality true.
            if guaranteed and op == 'eq':
                access_equalities.append(comparison)
        return '(coalesce((' + render(left) + ' IS NOT NULL AND ' + render(right) + ' IS NOT NULL AND (' + comparison + ')), false))'

    for node in bare.nodes:
        p = node.parameters; kind = node.kind
        if kind is R.REMOTE_QUERY:
            op = matches[node.semantic_operator_ids[0]]; spec = op.parameters
            prefix = 'm' + str(len(patterns)); values = {}
            def vertex(descriptor, suffix):
                if descriptor.get('properties') or not descriptor.get('label'):
                    raise ValueError('Native SPJ requires mandatory labels without unresolved entity constraints')
                name = prefix + suffix
                work_graph['nodes'][name] = descriptor['label']
                return name, '(' + name + ':' + ident(descriptor['label']) + ')'
            if 'edge' in spec:
                if spec['edge'].get('properties'):
                    raise ValueError('Native SPJ edge descriptor predicates require a separate proof')
                a, left = vertex(spec.get('source', {}), 'a'); b, right = vertex(spec.get('target', {}), 'b')
                e = prefix + 'e'; label = spec['edge'].get('label')
                if not label:
                    raise ValueError('Native SPJ requires a mandatory edge label')
                patterns.append('MATCH ' + left + '-[' + e + ':' + ident(label) + ']->' + right)
                work_graph['edges'].append(dict(variable=e, source=a, target=b, label=label))
                names = {'entity': e, 'source': a, 'target': b}; entity = e
            else:
                entity, pattern = vertex(spec.get('node', {}), 'n')
                patterns.append('MATCH ' + pattern); names = {'entity': entity}
            values.update({f: Value(v + '.' + ident(backend.identity_property), 'identity', (v, backend.identity_property)) for f, v in names.items()})
            values.update({f: prop(entity, name) for f, name in spec.get('properties', {}).items()})
        else:
            values = dict(relations[node.inputs[0]])
            if kind is R.NORMALIZE_NODE_BINDINGS:
                aliases = p.get('identity_fields', {'entity': p['entity_field']})
                values = {**{target: values[source] for source, target in aliases.items()},
                          **{f: values[f] for f in p['scalar_fields']}}
            elif kind is R.COORDINATOR_FILTER:
                conditions.append(condition(p['condition'], values))
            elif kind is R.COORDINATOR_ROW_PROJECT:
                if any(s.get('kind') != 'field' for s in p['projections'].values()):
                    raise ValueError('Native SPJ admits field-only projections')
                values = {f: values[s['field']] for f, s in p['projections'].items()}
            elif kind is R.COORDINATOR_JOIN:
                right = relations[node.inputs[1]]
                if values[p['left_on']].kind != 'identity' or right[p['right_on']].kind != 'identity':
                    raise ValueError('Native SPJ joins require declared logical identities')
                conditions.append(condition({'op': 'eq', 'field': 'l', 'right_field': 'r'},
                    {'l': values[p['left_on']], 'r': right[p['right_on']]}))
                if set(values) & set(right) - {p['left_on']}:
                    raise ValueError('Native SPJ requires the checked join column renaming')
                values.update({k: v for k, v in right.items() if k not in values})
            elif kind is R.COORDINATOR_SORT_LIMIT:
                if node.node_id != bare.roots[0]:
                    raise ValueError('Native SPJ only limits the complete final relation')
            else:
                raise ValueError('Unsupported native SPJ runtime primitive')
        relations[node.node_id] = values
    root = bare.nodes[-1]
    if root.kind is not R.COORDINATOR_SORT_LIMIT or root.node_id != bare.roots[0]:
        raise ValueError('Native SPJ requires final ordered bounded output')
    limit = root.parameters['limit']; ordering = root.parameters['order_by']; values = relations[root.node_id]
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Native SPJ requires bounded output of 1..1000 rows')
    if {o['field'] for o in ordering} != set(values):
        raise ValueError('Native SPJ top-K order must cover every output column')
    if any(v.kind not in ('identity', 'string', 'boolean', 'integer') for v in values.values()):
        raise ValueError('Native SPJ final output excludes mixed floating representatives')
    access_equalities = list(dict.fromkeys(access_equalities))
    text = '\n'.join(patterns) + ('\nWHERE ' + ' AND '.join(access_equalities + conditions) if conditions else '')
    text += '\nRETURN DISTINCT ' + ', '.join(render(v) + ' AS ' + ident(f) for f, v in values.items())
    order = []
    for o in ordering:
        f = ident(o['field']); null_direction = 'ASC' if o.get('nulls', 'last') == 'last' else 'DESC'
        order.extend(['(' + f + ' IS NULL) ' + null_direction, f + ' ' + o.get('direction', 'asc').upper()])
    text += '\nORDER BY ' + ', '.join(order) + '\nLIMIT ' + str(limit)
    if len(text.encode()) > 131072:
        raise ValueError('Native SPJ query byte bound exceeded')
    proof = dict(profile=PROFILE, program_sha256=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
        scalar_semantics=dict(types), backend_id=backend.backend_id, required_matches=sorted(matches),
        final_output_limit=limit, intermediate_limits=0, independent_match_clauses=True,
        joins_use_logical_identity=True, final_distinct=True, order_covers_all_columns=True)
    proof.update(access_profile='necessary-positive-equalities-v1', access_equalities=access_equalities,
        nullable_predicates_retained=True, native_identity_coalescing=False)
    return QueryArtifact(PROFILE, 'cypher', text, kind='compiled', parameters={
        **parameters, 'compiler': PROFILE, 'target_backend_id': backend.backend_id,
        'output_columns': list(values), 'source_pushdown': proof, 'source_work_graph': work_graph}), bare
