"""Bounded information adapters for the practical strong-policy boundary.

Provider construction may load an already frozen artifact. Only invoke performs
resolution; neither action construction nor symbolic search calls the provider.
Candidate sets are not intent validation. Ambiguity and failures have explicit
outcomes, and malformed paid responses retain their reported resource usage.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import time

from xgap.agent.practical_planning import BindingAction, program_identity
from xgap.agent.strong_planning import ResourceUsage
from xgap.compilers.features import default_profile
from xgap.semantic.program import SemanticHoleKind, hard_constraints_sha256
from xgap.tools.contracts import ToolSpec, ToolResult, ToolStatus
from xgap.tools.resolution import (ResolutionCandidateRequest, ResolutionCandidateResponse,
    ResolutionProviderFailure)


@dataclass(frozen=True)
class CandidateAcquisitionTool:
    action: BindingAction
    request: ResolutionCandidateRequest
    program_sha256: str
    provider: object
    kind: str
    artifact_sha256: str | None = None

    def __post_init__(self):
        if self.kind not in ('catalog', 'llm'):
            raise ValueError('Unknown practical provider kind')
        if self.action.slot != self.request.hole_id:
            raise ValueError('Provider request and action slot differ')
        if self.kind == 'llm' and (self.action.authority is not None or
                self.request.hole_kind is SemanticHoleKind.ENTITY):
            raise ValueError('LLM proposals cannot validate intent or resolve entity identity')
        if self.kind == 'catalog' and (self.action.authority != 'frozen_catalog' or not self.artifact_sha256):
            raise ValueError('Catalog validation requires a pinned frozen artifact')
        if any(dict(self.action.outcomes).get(label, 'absent') is not None for label in ('unavailable', 'error')):
            raise ValueError('Provider actions must retain unavailable and error outcomes')

    @property
    def spec(self):
        return ToolSpec(self.action.tool_name, 'Resolve one bounded semantic slot with explicit failures',
            {'type': 'object'}, 'scoped_binding', remote=self.kind == 'llm')

    def invoke(self, arguments, context):
        started = time.perf_counter()
        metrics = {'model_calls': 0, 'tokens': 0, 'remote_calls': 0}
        metadata = {'provider_kind': self.kind, 'source_id': self.action.source_id,
                    'version': self.action.version}
        def finish(status, *, candidate=None, error=None):
            metrics['elapsed_ms'] = (time.perf_counter() - started) * 1000
            value = ({k: arguments[k] for k in ('slot', 'program_sha256', 'source_id', 'version')}
                     | {'candidate_id': candidate}) if status is ToolStatus.SUCCESS else None
            return ToolResult(self.spec.name, status, value=value, error=error,
                              metrics=metrics, metadata=metadata)
        def account(response):
            calls = response.external_calls
            metrics.update(model_calls=calls if self.kind == 'llm' else 0, remote_calls=calls)
            if self.kind == 'llm' and calls and response.metadata.get('usage_reported') is not True:
                metrics.pop('tokens', None)
                metadata['usage_unavailable'] = True
            else:
                metrics['tokens'] = response.input_tokens + response.output_tokens
        try:
            expected = {'action_id': self.action.action_id, 'slot': self.request.hole_id,
                'program_sha256': self.program_sha256, 'source_id': self.action.source_id,
                'version': self.action.version, 'candidates': list(self.request.candidate_ids)}
            if arguments != expected:
                raise ValueError('Acquisition scope or pinned provenance changed')
            # Unexpected exceptions after entering a remote provider cannot prove zero spend.
            if self.kind == 'llm':
                metrics.clear()
            response = self.provider.resolve(self.request, context)
            if not isinstance(response, ResolutionCandidateResponse):
                raise ValueError('Provider returned an invalid response type')
            account(response)
            if response.source_id != self.action.source_id or response.hole_id != self.request.hole_id:
                raise ValueError('Provider response provenance or slot mismatch')
            if self.kind == 'catalog' and response.metadata.get('artifact_sha256') != self.artifact_sha256:
                raise ValueError('Provider response artifact version mismatch')
            if self.kind == 'llm' and response.authoritative:
                raise ValueError('Model response cannot claim authoritative validation')
            if not set(response.candidate_ids) <= set(self.request.candidate_ids):
                raise ValueError('Provider introduced an undeclared candidate')
            if len(response.candidate_ids) > self.request.max_candidates:
                raise ValueError('Provider exceeded its candidate cap')
            metadata.update(candidate_count=len(response.candidate_ids), authoritative=response.authoritative)
            incomplete = (response.metadata.get('truncated', False) or
                response.metadata.get('candidate_set_truncated', False) or response.metadata.get('scan_complete') is False)
            if len(response.candidate_ids) != 1 or incomplete or (
                    self.kind == 'catalog' and not response.authoritative):
                return finish(ToolStatus.UNAVAILABLE, error='No complete singleton binding with the required authority')
            return finish(ToolStatus.SUCCESS, candidate=response.candidate_ids[0])
        except ResolutionProviderFailure as error:
            account(error)
            metadata['failure_category'] = error.failure_category
            return finish(ToolStatus.ERROR, error=str(error))
        except (ValueError, TypeError, KeyError, OSError) as error:
            return finish(ToolStatus.ERROR, error=str(error))


def candidate_acquisition(program, slot, candidate_ids, provider, *, kind, source_id, version,
                          question, estimated_ms=1, token_budget=4096, artifact_sha256=None,
                          search_priority=0):
    """Build a finite action/tool pair without asking the provider for outcomes."""
    candidates = tuple(candidate_ids)
    if not 1 <= len(candidates) <= 254 or len(set(candidates)) != len(candidates):
        raise ValueError('Candidate acquisition needs 1..254 distinct declared candidates')
    hole = next(h for h in program.holes if h.hole_id == slot)
    if kind == 'catalog' and hole.kind is not SemanticHoleKind.ENTITY:
        raise ValueError('Catalog schema existence is not authoritative user intent')
    action_id = kind + ':' + slot
    action = BindingAction(action_id, slot, 'practical.' + action_id,
        tuple((f'candidate-{i}', c) for i, c in enumerate(candidates)) + (('unavailable', None), ('error', None)),
        source_id, version, 'frozen_catalog' if kind == 'catalog' else None, estimated_ms,
        ResourceUsage(1, token_budget, 1) if kind == 'llm' else ResourceUsage(),
        search_priority=search_priority)
    request = ResolutionCandidateRequest(program.program_id, slot, hole.kind, hole.mention, candidates,
        question, hard_constraints_sha256(program), len(candidates))
    return action, CandidateAcquisitionTool(action, request, program_identity(program), provider, kind, artifact_sha256)


def frozen_catalog_acquisition(program, slot, candidate_ids, catalog, **options):
    return candidate_acquisition(program, slot, candidate_ids, catalog, kind='catalog',
        source_id=catalog.source_id, version=catalog.artifact_sha256,
        artifact_sha256=catalog.artifact_sha256, **options)


def _provider_pin(provider):
    return hashlib.sha256(json.dumps({'config': provider.config.safe_dict(),
        'actual_prompt_sha256': hashlib.sha256(provider.system_prompt.encode()).hexdigest()},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class _PinnedOpenAIProposal:
    provider: object
    version: str
    source_id: str

    def resolve(self, request, context):
        if _provider_pin(self.provider) != self.version:
            raise ResolutionProviderFailure('Frozen model configuration or prompt changed',
                source_id=self.source_id,failure_category='configuration_changed',external_calls=0)
        return self.provider.resolve(request, context)


def openai_candidate_acquisition(program, slot, candidate_ids, provider, **options):
    """Reuse the one-call/no-repair provider; pin configuration and actual prompt.

    Total token reservation is checked against returned usage by the follower;
    it is not a tokenizer-based upper-bound certificate for arbitrary providers.
    The model credential remains solely in the existing provider environment.
    """
    from xgap.llm.resolution import OpenAICompatibleResolutionCandidateProvider
    if not isinstance(provider, OpenAICompatibleResolutionCandidateProvider):
        raise ValueError('Expected the bounded OpenAI-compatible resolution provider')
    source_id = f'llm:{provider.config.provider_id}:{provider.config.model}'
    version = _provider_pin(provider)
    return candidate_acquisition(program, slot, candidate_ids,
        _PinnedOpenAIProposal(provider,version,source_id), kind='llm', source_id=source_id,
        version=version, **options)


def lookup_practical_capabilities(sources, backends, backend_clients):
    """Local declared capability lookup, not a network health probe or intent oracle.

Actual per-operator capability witnesses are still enforced by the compiler.
Only known configured client adapters are admitted before strong-policy search.
"""
    started = time.perf_counter()
    admitted, records = {}, []
    for source_id, source in sorted(sources.items()):
        replicas = []
        for backend_id in source.replica_backend_ids:
            backend = backends.get(backend_id)
            known = backend_id in backend_clients and backend is not None
            profile = (backend.profile or default_profile(backend_id)) if backend else None
            records.append({'source_id': source_id, 'snapshot_version': source.snapshot_version,
                'backend_id': backend_id, 'adapter_available': known,
                'language': profile.language if profile else None,
                'data_model': profile.data_model if profile else None})
            if known:
                replicas.append(backend_id)
        if replicas:
            admitted[source_id] = replace(source, replica_backend_ids=tuple(replicas))
    identity = hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return admitted, {'schema_version': 'xgap-practical-capabilities-v1', 'sha256': identity,
        'records': records, 'external_calls': 0, 'elapsed_ms': (time.perf_counter() - started) * 1000,
        'live_health_verified': False, 'semantic_authority': False,
        'native_capability_admission': 'compiled per-operator witnesses'}
