"""Opt-in public type constraints for one-call compact graph interpretation.

This adapter changes the request contract, not a received proposal. It never
deletes duplicate variables, fills missing endpoints, or reads intent authority.
"""

from dataclasses import dataclass, fields, replace

from xgap.experiments.hashing import content_hash
from xgap.llm.compact_interpretation import (
    CompactInterpretationProviderConfig, OpenAICompatibleCompactInterpretationProvider,
)
from xgap.semantic.compact_query import compact_schema
from xgap.semantic.interpretation import InterpretationFailure


PROFILE = 'compact-public-types-v1'
ROLE_INSTRUCTIONS = """
Public graph declaration roles (compact-public-types-v1):
The nodes array declares graph vertices only; choose its type from the public
node labels. The edges array declares directed relationships only; choose its
type from the public edge labels. Every relationship variable occurs exactly
once, in edges, with source and target naming declared node variables. Refer to
an edge property using its edge variable; an expression such as e.timestamp does
not require or permit declaring e again in nodes. Node, edge, and path variables
share one namespace and must all be distinct. A relationship label is not a node
label unless the public source schema explicitly declares both roles. Keep both
endpoint nodes for each relationship. Genuine node-only questions may use an
empty edges array. Do not infer or invent an omitted endpoint or relationship.
""".strip()


def public_typed_schema(source_schema, candidate_cap, *, version='v2'):
    """Specialize only role type domains from the supplied public source views."""
    if not isinstance(source_schema, dict):
        raise ValueError('Public typed compact requires a frozen source schema')
    views = [v for v in source_schema.values()
             if isinstance(v, dict) and 'nodes' in v and 'edges' in v]
    if not 1 <= len(views) <= 64:
        raise ValueError('Public typed compact needs 1..64 public source views')
    nodes, edges = set(), set()
    for view in views:
        if not isinstance(view['nodes'], dict) or not isinstance(view['edges'], list):
            raise ValueError('Invalid public node/edge declarations')
        if any(not isinstance(label, str) or not label.strip() for label in view['nodes']):
            raise ValueError('Invalid public node label')
        nodes.update(view['nodes'])
        for edge in view['edges']:
            if (not isinstance(edge, dict) or not isinstance(edge.get('label'), str)
                    or not edge['label'].strip() or edge.get('source') not in view['nodes']
                    or edge.get('target') not in view['nodes']):
                raise ValueError('Invalid public edge label or endpoint type')
            edges.add(edge['label'])
    if not nodes:
        raise ValueError('Public typed compact requires a declared node type')
    schema = compact_schema(candidate_cap, version=version)
    query = schema['properties']['candidates']['items']['properties']['query']['properties']
    query['nodes']['items']['properties']['type'] = {'type': 'string', 'enum': sorted(nodes)}
    if edges:
        enum = {'type': 'string', 'enum': sorted(edges)}
        query['edges']['items']['properties']['type'] = dict(enum)
        query['path']['anyOf'][1]['properties']['type'] = dict(enum)
    else:
        # Avoid an invalid empty JSON-schema enum while allowing node-only graphs.
        query['edges']['maxItems'] = 0
        query['path'] = {'type': 'null'}
    return schema


@dataclass(frozen=True)
class PublicTypedCompactConfig(CompactInterpretationProviderConfig):
    def safe_dict(self):
        original = super().safe_dict()
        return {**original, 'wire_profile': original['wire_profile'] + ':' + PROFILE,
                'request_schema_profile': PROFILE,
                'structured_schema_scope': 'generic template; actual public specialization recorded per request'}


class PublicTypedCompactProvider(OpenAICompatibleCompactInterpretationProvider):
    def build_request_payload(self, request):
        payload = super().build_request_payload(request)
        public = request.context['source_schema']
        schema = public_typed_schema(public, self.config.candidate_cap,
                                    version=self.config.language_version)
        payload['response_format']['json_schema']['schema'] = schema
        # The existing select map uses arbitrary output aliases. Do not request
        # strict mode: this schema is not in the closed-object strict subset.
        self._public_request_contract = {
            'profile': PROFILE, 'basis': 'request.context.source_schema only',
            'public_source_schema_sha256': content_hash(public),
            'actual_structured_schema_sha256': content_hash(schema),
            'actual_prompt_sha256': content_hash(self.system_prompt),
            'role_instructions_sha256': content_hash(ROLE_INSTRUCTIONS),
            'source_contract': 'public schema, no private intent or outcomes',
            'server_strict_mode': 'not_requested_dynamic_select_keys',
            'response_repair': False, 'max_model_calls': 1,
        }
        return payload

    def interpret(self, request):
        self._public_request_contract = None
        try:
            response = super().interpret(request)
        except InterpretationFailure as error:
            provenance = {**error.provenance,
                          'public_type_contract': self._public_request_contract}
            self.last_invocation = provenance
            raise InterpretationFailure(error.category, str(error), usage=error.usage,
                                        provenance=provenance) from error
        provenance = {**response.provenance,
                      'public_type_contract': self._public_request_contract}
        self.last_invocation = provenance
        return replace(response, provenance=provenance)


def adapt_public_typed_compact_provider(provider):
    """Return an independent explicit adapter; retain existing equivalences/guard.

    Input must already be a verified materialized compact provider. The parent
    provider, prompt, frozen profile and historical results remain unchanged.
    """
    if not isinstance(provider, OpenAICompatibleCompactInterpretationProvider):
        raise ValueError('A materialized compact provider is required')
    if isinstance(provider, PublicTypedCompactProvider):
        raise ValueError('Public type request contract is already active')
    prompt = provider.system_prompt.rstrip() + '\n\n' + ROLE_INSTRUCTIONS + '\n'
    settings = {field.name: getattr(provider.config, field.name)
                for field in fields(CompactInterpretationProviderConfig)}
    settings.update(provider_id=provider.config.provider_id + ':' + PROFILE,
                    prompt_hash=content_hash(prompt))
    return PublicTypedCompactProvider(PublicTypedCompactConfig(**settings), prompt,
                                      provider.token_guard, provider.transport)
