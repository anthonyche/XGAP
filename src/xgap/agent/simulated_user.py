"""Bounded, private intent oracle and a metered full-intent clarification policy.

This is an experimental user role, not a query-equivalence solver. Exact JSON
agreement means confirmation; any difference returns the authoritative section.
Only invoke reveals intent. Preflight validates private configuration locally.
"""
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

from xgap.agent.practical_planning import BindingEvidence, BindingState, program_identity
from xgap.semantic.binding import SemanticBindingValue
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import validate_query
from xgap.semantic.program import SemanticHoleKind
from xgap.tools.contracts import ToolContext, ToolEffect, ToolResult, ToolSpec, ToolStatus


SCHEMA = 'xgap-simulated-user-intent-v1'
PROFILE = 'nl-simulated-user-full-intent-v1'
MAX_BYTES = 131072


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_intent(data):
    if not isinstance(data, dict) or set(data) != {
            'schema_version', 'source_id', 'version', 'question_sha256',
            'language_version', 'query', 'entity_bindings'} or data['schema_version'] != SCHEMA:
        raise ValueError('Oracle configuration must contain only semantic intent and entity identities')
    if any(not isinstance(data[k], str) or not data[k] for k in ('source_id', 'version', 'question_sha256')):
        raise ValueError('Oracle provenance and question identity are required')
    query = validate_query(data['query'], version=data['language_version'])
    required = {n['var'] for n in query['nodes'] if n['entity'] is not None}
    bindings = data['entity_bindings']
    if not isinstance(bindings, dict) or set(bindings) != required or any(
            not isinstance(v, str) or not v for v in bindings.values()):
        raise ValueError('Oracle configuration must resolve exactly every named entity')
    return data


def intent_state(question, query, entity_bindings, *, source_id, version, language_version='v1'):
    """Offline preparation only; no answer rows, placement or physical plan input."""
    data = dict(schema_version=SCHEMA, source_id=source_id, version=version,
        question_sha256=identity(question), language_version=language_version,
        query=deepcopy(query), entity_bindings=dict(entity_bindings))
    validate_intent(data)
    if len(json.dumps(data, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError('Oracle intent exceeds its byte bound')
    return data


@dataclass(frozen=True)
class SimulatedUserTool:
    response_path: Path
    expected_sha256: str
    name: str = 'user.simulated'

    @property
    def spec(self):
        return ToolSpec(self.name, 'Ask an authoritative simulated user about a declared intent scope',
            {'type': 'object'}, 'scoped_user_intent', ToolEffect.READ_ONLY)

    def _load(self, question_sha256):
        with Path(self.response_path).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != self.expected_sha256:
            raise ValueError('Oracle private artifact size/hash mismatch')
        data = validate_intent(json.loads(raw))
        if data['question_sha256'] != question_sha256:
            raise ValueError('Oracle belongs to a different question')
        return data

    def preflight(self, question):
        self._load(identity(question))
        return {'ready': True, 'artifact_sha256': self.expected_sha256,
            'scope': 'private configuration validation; no intent disclosed'}

    def invoke(self, arguments, context):
        started = time.perf_counter()
        try:
            if set(arguments) != {'question_sha256', 'scope', 'query_sha256', 'proposal', 'candidates'}:
                raise ValueError('Unknown simulated-user request fields')
            if len(json.dumps(arguments, allow_nan=False).encode()) > MAX_BYTES:
                raise ValueError('Oracle request exceeds byte bound')
            candidates = arguments['candidates']
            if not isinstance(candidates, list) or len(candidates) > 64 or any(
                    not isinstance(c, str) for c in candidates):
                raise ValueError('Oracle accepts at most64 candidate identity values')
            data = self._load(arguments['question_sha256'])
            query = data['query']; scope = arguments['scope']
            query_hash = identity(query)
            value = dict(question_sha256=data['question_sha256'], scope=scope,
                query_sha256=query_hash, source_id=data['source_id'], version=data['version'],
                artifact_sha256=self.expected_sha256, language_version=data['language_version'])
            if scope == 'query_intent':
                if arguments['query_sha256'] is not None or candidates:
                    raise ValueError('Full query-intent action has no preselected entities')
                answer = query
            else:
                if arguments['query_sha256'] != query_hash:
                    raise ValueError('Scoped reply requires the current authoritative query identity')
                if scope.startswith('entity:') and scope[7:] in data['entity_bindings']:
                    answer = data['entity_bindings'][scope[7:]]
                elif scope in ('edges', 'path', 'where', 'select', 'order_by', 'limit'):
                    answer = query[scope]
                else:
                    raise ValueError('Unknown or unconfigured user intent scope')
            outcome = 'confirmed' if arguments['proposal'] == answer else 'corrected'
            if scope.startswith('entity:') and candidates and answer not in candidates:
                outcome = 'none_of_these'
            value.update(answer=answer, outcome=outcome)
            result = ToolResult.success(self.name, value)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            result = ToolResult.error_result(self.name, str(error))
        return ToolResult(result.tool_name, result.status, result.value, result.error,
            metrics={'clarification_calls': 1, 'elapsed_ms': (time.perf_counter()-started)*1000,
                'model_calls': 0, 'tokens': 0, 'remote_calls': 0})


@dataclass(frozen=True)
class SimulatedUserPolicy:
    max_calls: int = 9  # one complete query statement plus at most8 named entities
    declared_user_wait_ms_per_call: float = 0.0

    def __post_init__(self):
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 9:
            raise ValueError('Simulated-user call budget must lie in1..9')
        v = self.declared_user_wait_ms_per_call
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            raise ValueError('Declared user waiting cost must be finite and nonnegative')


def acquire_user_intent(request, interpreted, oracle, policy, report, *, on_observation=None):
    """Fixed bounded policy before strong planning, not joint AND/OR optimality.

The oracle is invoked only for the realized information action. The received
query is compiled from generic source coverage, never from a gold placement.
"""
    ledger = report['clarification_ledger']

    def ask(scope, *, proposal=None, query_sha256=None, candidates=()):
        if len(ledger) >= policy.max_calls:
            raise ValueError('Simulated-user clarification budget exhausted')
        arguments = dict(question_sha256=identity(request.question), scope=scope,
            query_sha256=query_sha256, proposal=proposal, candidates=list(candidates))
        result = oracle.invoke(arguments, ToolContext('nl-simulated-user', len(ledger), str(len(ledger))))
        record = dict(request=arguments, response=result.to_dict())
        ledger.append(record)
        report['clarification_calls'] = len(ledger)
        report['oracle_processing_ms'] += result.metrics.get('elapsed_ms', 0)
        report['declared_user_wait_ms'] = len(ledger)*policy.declared_user_wait_ms_per_call
        if on_observation is not None:
            on_observation(record)
        if result.status is not ToolStatus.SUCCESS:
            raise ValueError('Simulated-user action failed: '+str(result.error))
        value = result.value
        if (value['question_sha256'] != arguments['question_sha256'] or value['scope'] != scope
                or value['artifact_sha256'] != oracle.expected_sha256
                or query_sha256 is not None and value['query_sha256'] != query_sha256):
            raise ValueError('Simulated-user response scope or provenance mismatch')
        return value

    raw = interpreted.get('provenance', {}).get('raw_compact_response', {})
    candidates = raw.get('candidates', []) if isinstance(raw, dict) else []
    proposal = candidates[0].get('query') if candidates and isinstance(candidates[0], dict) else None
    reply = ask('query_intent', proposal=proposal)
    query = validate_query(reply['answer'], version=reply['language_version'])
    if identity(query) != reply['query_sha256']:
        raise ValueError('Received query does not match its scoped identity')
    at = time.perf_counter()
    program, sources = lower_compact_query(query, request.context['source_schema'],
        version=reply['language_version'], optimize=True)
    report['oracle_lowering_ms'] = (time.perf_counter()-at)*1000
    evidence = [BindingEvidence('$structure', program_identity(program), 'clarification',
        reply['source_id'], reply['artifact_sha256'])]
    choices, values = {}, {}
    for i, node in enumerate(query['nodes']):
        if node['entity'] is None:
            continue
        answer = ask('entity:'+node['var'], query_sha256=reply['query_sha256'])
        binding = SemanticBindingValue(SemanticHoleKind.ENTITY, answer['answer'],
            request.context['source_schema']['identity_property'])
        key = 'user-entity:'+identity(answer['answer']); hole = 'ce'+str(i)
        values[key] = binding; choices[hole] = key
        evidence.append(BindingEvidence(hole, key, 'clarification', answer['source_id'], answer['artifact_sha256']))
    report.update(user_intent_verified=True, structure_validation='simulated_user_confirmed',
        structure_provenance={k: reply[k] for k in ('source_id', 'version', 'artifact_sha256', 'query_sha256')},
        oracle_outcome=reply['outcome'], intent_information_scope='full query intent plus all named entity identities')
    return program, sources, values, BindingState(tuple(sorted(choices.items())), tuple(evidence))
