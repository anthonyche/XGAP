"""Conservative compact equivalences proved by a frozen public source contract.

The contract is supplied by the deployment, never inferred from an answer or an
intent. Its source proof must be verified by the caller before use. These rules
are bounded scans of a finite query; they are not a query-equivalence solver.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re

from xgap.semantic.compact_query import validate_query


SCHEMA = 'xgap-compact-public-constraints-v1'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class PublicCompactConstraints:
    document_json: str

    @classmethod
    def from_dict(cls, value):
        raw = _canonical(value)
        if len(raw.encode()) > 65536 or set(value) != {
                'schema_version', 'contract_id', 'source_schema_sha256', 'source_proof',
                'scale', 'nodes', 'edges'} or value['schema_version'] != SCHEMA:
            raise ValueError('Invalid public compact constraint contract')
        if not isinstance(value['contract_id'], str) or not 1 <= len(value['contract_id']) <= 256:
            raise ValueError('Invalid constraint contract identity')
        if not re.fullmatch('[0-9a-f]{64}', value['source_schema_sha256']):
            raise ValueError('Invalid constrained source schema hash')
        # The first proof profile covers the original index and its subgraph.
        # Replicated edge business IDs are deliberately outside this version.
        if value['scale'] not in ('1', '.25'):
            raise ValueError('Public key constraints require an unreplicated source scale')
        proof = value['source_proof']
        if (not isinstance(proof, dict) or set(proof) != {'path', 'sha256', 'bytes'}
                or not isinstance(proof['path'], str) or not proof['path']
                or not re.fullmatch('[0-9a-f]{64}', proof['sha256'])
                or type(proof['bytes']) is not int or proof['bytes'] < 1):
            raise ValueError('Invalid public source proof pin')
        for kind in ('nodes', 'edges'):
            domains = value[kind]
            if not isinstance(domains, dict) or len(domains) > 64:
                raise ValueError('Public constraint type bound exceeded')
            for label, properties in domains.items():
                if (not isinstance(label, str) or not 1 <= len(label) <= 256
                        or not isinstance(properties, dict)
                        or set(properties) != {'identity_keys', 'nonnull', 'functional'}):
                    raise ValueError('Invalid public constraint property domain')
                for names in properties.values():
                    if (not isinstance(names, list) or len(names) > 64
                            or any(not isinstance(p, str) or not 1 <= len(p) <= 128 for p in names)
                            or len(set(names)) != len(names)):
                        raise ValueError('Invalid public constraint property list')
                if (not set(properties['identity_keys']) <= set(properties['nonnull'])
                        or not set(properties['nonnull']) <= set(properties['functional'])):
                    raise ValueError('An identity key must be total, scalar and non-null')
        return cls(raw)

    def to_dict(self):
        return json.loads(self.document_json)

    @property
    def identity(self):
        return hashlib.sha256(self.document_json.encode()).hexdigest()

    def validate_source_schema(self, schema):
        document = self.to_dict()
        if _digest(schema) != document['source_schema_sha256']:
            raise ValueError('Public constraints refer to a different source schema')
        views = [v for v in schema.values() if isinstance(v, dict) and 'nodes' in v and 'edges' in v]
        for kind in ('nodes', 'edges'):
            for label, rule in document[kind].items():
                declared = set()
                for view in views:
                    if kind == 'nodes':
                        declared.update(view['nodes'].get(label, {}).get('properties', []))
                    else:
                        for edge in view['edges']:
                            if edge['label'] == label:
                                declared.update(edge['properties'])
                if not set(rule['functional']) <= declared:
                    raise ValueError('Constraint refers to an undeclared source property')
                if schema.get('identity_property') not in rule['identity_keys']:
                    raise ValueError('Constraint omits the canonical source identity key')
        return self


def canonicalize_with_constraints(query, constraints):
    """Equivalent representation under an explicit, verified public contract.

Only same-type node key eq/ne comparisons change. Mixed keys, literals, output
properties and ordering never do. COUNT normalization additionally requires a
single edge contribution key and functionally determined retained variables;
otherwise witness multiplicities can change COUNT and the rule must decline.
"""
    if not isinstance(constraints, PublicCompactConstraints):
        raise ValueError('Explicit public compact constraints required')
    value = deepcopy(validate_query(query, version='v2'))
    contract = constraints.to_dict()
    nodes = {n['var']: n['type'] for n in value['nodes']}
    edges = {e['var']: e for e in value['edges']}
    rewrites = []
    for index, predicate in enumerate(value['where']):
        left, right = predicate['left'], predicate['right']
        kind = nodes.get(left.get('var'))
        rule = contract['nodes'].get(kind, {})
        if (predicate['op'] in ('eq', 'ne') and predicate['value_type'] == 'scalar'
                and kind is not None and nodes.get(right.get('var')) == kind
                and left.get('property') == right.get('property')
                and left.get('property') in rule.get('identity_keys', [])):
            left['property'] = right['property'] = None
            rewrites.append(dict(rule='public_same_type_total_key_equality', where_index=index))

    grain = value['contribution_by']
    if grain is not None and len(grain) == 1 and grain[0] in edges:
        edge_var = grain[0]
        edge = edges[edge_var]
        edge_rule = contract['edges'].get(edge['type'], {})

        def determined(reference):
            var, prop = reference['var'], reference['property']
            if var == edge_var:
                rule = edge_rule
            elif var in (edge['source'], edge['target']):
                rule = contract['nodes'].get(nodes[var], {})
            else:
                return False
            return bool(rule) and (prop is None or prop in rule['functional'])

        # Lowering retains the identity of each selected variable as well as its
        # scalar. An unrelated witness can duplicate a contribution inside one
        # output group even when its selected scalar equals another witness's.
        output_refs = [e if 'var' in e else e['field'] for e in value['select'].values()]
        safe_grain = bool(edge_rule) and all(ref is None or determined(ref) for ref in output_refs)
        if safe_grain:
            for alias, expression in value['select'].items():
                reference = expression.get('field')
                if (expression.get('aggregate') != 'count' or reference is None
                        or reference['var'] != edge_var):
                    continue
                prop = reference['property']
                total = prop is None or prop in edge_rule['nonnull']
                unique = prop is None or prop in edge_rule['identity_keys']
                if total and (not expression['distinct'] or unique):
                    expression['field'] = dict(var=edge_var, property=None)
                    expression['distinct'] = False
                    rewrites.append(dict(rule='public_single_edge_contribution_count', output_alias=alias))
    return value, rewrites
