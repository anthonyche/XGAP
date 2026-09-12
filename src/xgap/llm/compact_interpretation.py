"""One model response -> independently lowered compact graph candidates.

The transport/recording contract is unchanged. Lowering is language compilation,
not a second model call or an attempt to repair a rejected interpretation.
"""

from dataclasses import dataclass, replace
import json
import math
import time

from xgap.experiments.hashing import content_hash
from xgap.llm.interpretation import OpenAICompatibleInterpretationProvider
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import SCHEMA, LOWERING, compact_schema
from xgap.semantic.interpretation import InterpretationFailure
from xgap.semantic.interpretation_candidates import SCHEMA as CANDIDATE_SCHEMA


WIRE_PROFILE = 'compact-graph-schema-v1'


@dataclass(frozen=True)
class CompactInterpretationProviderConfig(OpenAICompatibleProviderConfig):
    def __post_init__(self):
        super().__post_init__()
        if self.structured_output_mode != 'json_schema' or self.max_repair_calls != 0:
            raise ValueError('Compact interpretation requires JSON schema and zero repairs')
        if content_hash(self.structured_schema) != content_hash(compact_schema(self.candidate_cap)):
            raise ValueError('Compact schema differs from its bounded wire contract')

    def safe_dict(self):
        return {**super().safe_dict(), 'wire_profile': WIRE_PROFILE,
            'compact_schema': SCHEMA, 'lowering_profile': LOWERING,
            'lowered_candidate_schema': CANDIDATE_SCHEMA}


@dataclass
class OpenAICompatibleCompactInterpretationProvider(OpenAICompatibleInterpretationProvider):
    def __post_init__(self):
        if not isinstance(self.config, CompactInterpretationProviderConfig):
            raise ValueError('Explicit compact interpretation configuration required')
        if not self.system_prompt.strip() or self.config.prompt_hash != content_hash(self.system_prompt):
            raise ValueError('Compact prompt differs from its pinned hash')
        if set(self.config.extra_parameters) - {'chat_template_kwargs'}:
            raise ValueError('Only explicit chat-template overrides are supported')
        if not all(math.isfinite(n) for n in (self.config.timeout_seconds, self.config.temperature, self.config.top_p)):
            raise ValueError('Compact request bounds must be finite')

    def build_request_payload(self, request):
        if request.required_constraints:
            raise ValueError('Compact-v1 cannot map legacy operator-ID hard constraints; use the full-SGP profile')
        if not isinstance(request.context.get('source_schema'), dict):
            raise ValueError('Compact interpretation requires a frozen source schema')
        payload = super().build_request_payload(request)
        payload['messages'][1]['content'] = json.dumps({**request.to_dict(),
            'schema_version': SCHEMA, 'candidate_cap': self.config.candidate_cap}, ensure_ascii=False)
        payload['response_format']['json_schema']['name'] = 'xgap_compact_graph_candidates'
        return payload

    def interpret(self, request):
        response = super().interpret(request)
        started = time.perf_counter()
        raw = response.payload
        provenance = {**response.provenance, 'raw_compact_response': raw,
            'compact_lowering': {'profile': LOWERING, 'response_repair': False, 'candidates': []}}

        def finish():
            elapsed = (time.perf_counter()-started)*1000
            provenance['compact_lowering']['elapsed_ms'] = elapsed
            provenance['elapsed_ms'] = response.provenance['elapsed_ms'] + elapsed
            self.last_invocation = provenance

        if (not isinstance(raw, dict) or set(raw) != {'schema_version', 'candidates'}
                or raw['schema_version'] != SCHEMA or not isinstance(raw['candidates'], list)
                or not 1 <= len(raw['candidates']) <= self.config.candidate_cap):
            finish()
            raise InterpretationFailure('compact_envelope_invalid', 'Invalid compact envelope or candidate count',
                usage=response.usage, provenance=provenance)
        candidates = []
        for index, item in enumerate(raw['candidates']):
            identifier = item.get('candidate_id') if isinstance(item, dict) else None
            quality = item.get('quality_proxy') if isinstance(item, dict) else None
            lowered = {'candidate_id': identifier, 'quality_proxy': quality, 'program': None, 'operator_sources': {}}
            record = {'candidate_index': index, 'candidate_id': identifier, 'status': 'invalid'}
            try:
                if not isinstance(item, dict) or set(item) != {'candidate_id', 'quality_proxy', 'query'}:
                    raise ValueError('Compact candidate requires exactly candidate_id, quality_proxy and query')
                if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 256:
                    raise ValueError('Candidate ID must be nonblank and at most256 characters')
                if quality is not None and (type(quality) not in (int, float) or not math.isfinite(quality) or not 0 <= quality <= 1):
                    raise ValueError('Quality proxy must lie in [0,1] or be null')
                program, sources = lower_compact_query(item['query'], request.context['source_schema'],
                    program_id='compact-'+str(index))
                lowered.update(program=program.to_dict(), operator_sources=sources)
                record.update(status='lowered', operators=len(program.operators), source_reads=len(sources))
            except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
                record['error'] = str(error)
            # Failed candidates remain invalid entries in the existing envelope;
            # duplicate IDs and output contracts still face ordinary admission.
            candidates.append(lowered)
            provenance['compact_lowering']['candidates'].append(record)
        finish()
        return replace(response, payload={'schema_version': CANDIDATE_SCHEMA, 'candidates': candidates}, provenance=provenance)
