"""Frozen two-predicate fixture for a same-request live strong-policy gate."""
import hashlib
import json
from pathlib import Path

from xgap.agent.practical_execution import FrozenClarificationTool
from xgap.agent.practical_planning import BindingAction, BindingEvidence, BindingState, PracticalMode, program_identity
from xgap.agent.practical_question import PracticalQuestionOptions
from xgap.agent.practical_tools import openai_candidate_acquisition
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.toy_semantic import toy_backends
from xgap.llm.openai_compatible import OpenAICompatibleProviderConfig
from xgap.llm.resolution import M15_RESOLUTION_BASE_SCHEMA, OpenAICompatibleResolutionCandidateProvider
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.intake import DeterministicSemanticIntake
from xgap.semantic.interpretation import InterpretationRequest, TemplateInterpretationProvider
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import ToolRegistry


FIXTURE = Path(__file__).resolve().parents[1] / 'datasets/practical_model_toy_v1'
KEY_ENV = 'XGAP_EXTERNAL_LLM_API_KEY'


def model_provider(transport=None):
    prompt = ('Select the single candidate ID that best matches the requested semantic slot. '
        'Use only the supplied candidate IDs. Return a JSON object with hole_id and candidate_ids. '
        'Never return a native query or claim semantic authority.')
    config = OpenAICompatibleProviderConfig(provider_id='practical-live-slot-v1',
        base_url='http://112.95.75.67:9018/v1', api_key_env=KEY_ENV, model='qwen3.8-27b',
        temperature=0, top_p=1, max_tokens=512, candidate_cap=2, timeout_seconds=45,
        structured_output_mode='json_schema', structured_schema=M15_RESOLUTION_BASE_SCHEMA,
        prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(), max_repair_calls=0,
        extra_parameters={'chat_template_kwargs': {'enable_thinking': False}})
    options = {} if transport is None else {'transport': transport}
    return OpenAICompatibleResolutionCandidateProvider(config, prompt, **options)


def prepare_model(root, proposal):
    manifest = json.loads((FIXTURE/'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if hashlib.sha256((FIXTURE/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen model toy input drift: ' + name)
    raw = json.loads((FIXTURE/'request.json').read_text())
    intake = DeterministicSemanticIntake.from_path(FIXTURE/'intake.json',
        expected_sha256=manifest['files']['intake.json'])
    request = InterpretationRequest(raw['question'], {'query_profile': 'bounded-core-v1'},
        intake.required_hard_constraints)
    provider = TemplateInterpretationProvider(intake, raw['operator_sources'])
    # Deterministic trusted intake, never a preliminary live model call.
    program = SemanticGraphProgram.from_dict(provider.interpret(request).payload['program'])
    bundle = FrozenResolutionBundle.load(FIXTURE/'snapshot', expected_bundle_hash=manifest['bundle_hash'])
    values = raw['trusted_bindings']
    evidence = (BindingEvidence('$structure', program_identity(program), 'trusted_request', 'two-predicate-template',
        manifest['files']['intake.json']), *(BindingEvidence(s, c, 'trusted_request', 'toy-request',
        manifest['files']['request.json']) for s, c in values.items()))
    initial = BindingState(tuple(sorted(values.items())), evidence)
    action, tool = openai_candidate_acquisition(program, 'predicate', tuple(raw['candidate_ids']),
        proposal, question=request.question, estimated_ms=None, search_priority=0)
    fallback = BindingAction('clarify-predicate', 'predicate', 'practical.clarify',
        (('knows','predicate:knows'), ('follows','predicate:follows')),
        'toy-predicate-clarification', 'v1', 'clarification', None, search_priority=1)
    response = root/'clarification-bindings-only.json'
    write_once(response, {'schema_version':'xgap-clarification-bindings-v1',
        'program_sha256':program_identity(program), 'source_id':fallback.source_id,
        'version':fallback.version, 'bindings':{'predicate':'predicate:knows'}})
    registry = ToolRegistry(); registry.register(tool); registry.register(FrozenClarificationTool(response))
    options = PracticalQuestionOptions(initial, PracticalMode('performance', tuple(raw['allowed_unvalidated']),
        improve_physical=False), actions=(action, fallback), resolution_tools=registry,
        limits=StrongSearchLimits(improvement_actions=0))
    snapshot = manifest['files']['graph.json']
    sources = {'toy':LogicalSource('toy',snapshot,('neo4j',)),
        'toy-people':LogicalSource('toy-people',snapshot,('fuseki',))}
    mapping = json.loads((FIXTURE/'mapping.json').read_text())
    # Gold is not loaded here; it is scored only after execution is durably saved.
    case = {'id':'practical-model-toy', 'nl':request.question, 'gold_path':str(FIXTURE/'gold.json')}
    ref = {'base_root':FIXTURE, 'root':'snapshot', 'bundle_hash':manifest['bundle_hash']}
    return case, request, provider, program, bundle, ref, sources, toy_backends(mapping), options
