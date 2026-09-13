"""Reusable compact provider defaults; no question, gold or dataset file reads."""

from pathlib import Path

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.experiments.external_toy_interpretation import BoundedExternalChatTransport
from xgap.experiments.hashing import content_hash
from xgap.experiments.one_shot_toy import BASE_URL, MODEL, OneShotChatRequestGuard
from xgap.llm.compact_interpretation import (CompactInterpretationProviderConfig,
    OpenAICompatibleCompactInterpretationProvider, WIRE_PROFILE, WIRE_PROFILE_V2)
from xgap.semantic.compact_query import compact_schema


def load_compact_graph_provider(*, mode='performance', disable_thinking=True, prompt_version='v1', language_version='v1'):
    if prompt_version not in ('v1', 'v2'):
        raise ValueError('Unknown compact prompt version')
    if language_version not in ('v1', 'v2') or language_version == 'v2' and prompt_version != 'v2':
        raise ValueError('Compact language-v2 requires its explicit v2 contribution prompt')
    policy = OneShotPolicy.for_mode(mode)
    filename = 'compact_contribution_v2.txt' if language_version == 'v2' else 'compact_graph_'+prompt_version+'.txt'
    prompt = (Path(__file__).resolve().parents[3]/'prompts/interpretation'/filename).read_text()
    output = 6144 if mode == 'precision' else 4096
    suffix = '' if prompt_version == 'v1' else ':prompt-'+prompt_version
    wire = WIRE_PROFILE if language_version == 'v1' else WIRE_PROFILE_V2
    config = CompactInterpretationProviderConfig(provider_id=wire+':'+mode+':'+MODEL+suffix,
        base_url=BASE_URL, api_key_env='XGAP_EXTERNAL_LLM_API_KEY', model=MODEL,
        temperature=0.0, top_p=1.0, max_tokens=output, candidate_cap=policy.candidate_cap,
        timeout_seconds=60, structured_output_mode='json_schema', structured_schema=compact_schema(policy.candidate_cap, version=language_version),
        language_version=language_version,
        prompt_hash=content_hash(prompt), max_repair_calls=0,
        extra_parameters={'chat_template_kwargs': {'enable_thinking': False}} if disable_thinking else {})
    return OpenAICompatibleCompactInterpretationProvider(config, prompt,
        OneShotChatRequestGuard(MODEL, output_limit=output), BoundedExternalChatTransport())


def derive_compact_prompt_profile(*, parent_path, parent_sha256, output, prompt_version='v2'):
    """Offline prompt-only child; no data/model/catalog rebuild or question reads."""
    import hashlib
    import json
    from xgap.experiments.one_shot_profile import FrozenOneShotProfile
    from xgap.experiments.one_shot_records import write_once

    if prompt_version != 'v2':
        raise ValueError('This explicit revision publishes prompt-v2 only')
    parent = FrozenOneShotProfile.load(parent_path, expected_sha256=parent_sha256)
    doc = json.loads(parent.document_json)
    if any(m['provider']['wire_profile'] != WIRE_PROFILE for m in doc['modes'].values()):
        raise ValueError('Prompt-only revision requires existing compact modes')
    if doc['offline'].get('interpretation_revision', {}).get('prompt_version') == prompt_version:
        raise ValueError('Refuse to republish the same prompt revision')
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    prompt = load_compact_graph_provider(prompt_version=prompt_version).system_prompt
    prompt_path = root/'prompt.txt'
    with prompt_path.open('x') as f: f.write(prompt)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    for key in ('catalog', 'estimator'):
        doc[key]['path'] = str((parent.root/doc[key]['path']).resolve())
    for mode in doc['modes'].values():
        provider = mode['provider']
        provider['provider_id'] += ':prompt-'+prompt_version
        provider['prompt'] = {'path': str(prompt_path), 'sha256': prompt_hash}
    doc['profile_id'] += ':prompt-'+prompt_version
    doc['offline']['interpretation_revision'] = {
        'parent': {'path': str(Path(parent_path).resolve()), 'sha256': parent_sha256},
        'prompt_version': prompt_version, 'scope': 'prompt and provider/profile identity only; frozen facts/schema/catalog/model/policy unchanged',
        'query_reads': 0, 'answer_reads': 0, 'model_calls': 0, 'backend_calls': 0,
        'catalog_builds': 0, 'fit_calls': 0, 'historical_results_not_replaced': True}
    pin = write_once(root/'profile.json', doc)
    FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    return pin


def derive_compact_contribution_profile(*, parent_path, parent_sha256, output):
    """Explicit language+prompt child, never reinterpret a saved v1 response."""
    import hashlib
    import json
    from xgap.experiments.one_shot_profile import FrozenOneShotProfile
    from xgap.experiments.one_shot_records import write_once

    parent = FrozenOneShotProfile.load(parent_path, expected_sha256=parent_sha256)
    doc = json.loads(parent.document_json)
    if any(m['provider']['wire_profile'] != WIRE_PROFILE for m in doc['modes'].values()):
        raise ValueError('Contribution-v2 revision requires a compact-v1 parent')
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    prompt = load_compact_graph_provider(prompt_version='v2', language_version='v2').system_prompt
    prompt_path = root/'prompt.txt'
    with prompt_path.open('x') as f: f.write(prompt)
    for key in ('catalog', 'estimator'):
        doc[key]['path'] = str((parent.root/doc[key]['path']).resolve())
    for mode in doc['modes'].values():
        provider = mode['provider']
        provider['wire_profile'] = WIRE_PROFILE_V2
        provider['provider_id'] += ':contribution-v2'
        provider['prompt'] = {'path': str(prompt_path), 'sha256': hashlib.sha256(prompt.encode()).hexdigest()}
    doc['profile_id'] += ':contribution-v2'
    doc['offline']['interpretation_revision'] = {
        'parent': {'path': str(Path(parent_path).resolve()), 'sha256': parent_sha256},
        'language_version': 'v2', 'prompt_version': 'contribution-v2',
        'scope': 'explicit compact schema/lowering and prompt revision; frozen facts/schema/catalog/model/policy unchanged',
        'query_reads': 0, 'answer_reads': 0, 'model_calls': 0, 'backend_calls': 0,
        'catalog_builds': 0, 'fit_calls': 0, 'historical_results_not_replaced': True}
    pin = write_once(root/'profile.json', doc)
    FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    return pin
