"""Reusable compact provider defaults; no question, gold or dataset file reads."""

from pathlib import Path

from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.experiments.external_toy_interpretation import BoundedExternalChatTransport
from xgap.experiments.hashing import content_hash
from xgap.experiments.one_shot_toy import BASE_URL, MODEL, OneShotChatRequestGuard
from xgap.llm.compact_interpretation import (CompactInterpretationProviderConfig,
    OpenAICompatibleCompactInterpretationProvider, WIRE_PROFILE)
from xgap.semantic.compact_query import compact_schema


def load_compact_graph_provider(*, mode='performance', disable_thinking=True):
    policy = OneShotPolicy.for_mode(mode)
    prompt = (Path(__file__).resolve().parents[3]/'prompts/interpretation/compact_graph_v1.txt').read_text()
    output = 6144 if mode == 'precision' else 4096
    config = CompactInterpretationProviderConfig(provider_id=WIRE_PROFILE+':'+mode+':'+MODEL,
        base_url=BASE_URL, api_key_env='XGAP_EXTERNAL_LLM_API_KEY', model=MODEL,
        temperature=0.0, top_p=1.0, max_tokens=output, candidate_cap=policy.candidate_cap,
        timeout_seconds=60, structured_output_mode='json_schema', structured_schema=compact_schema(policy.candidate_cap),
        prompt_hash=content_hash(prompt), max_repair_calls=0,
        extra_parameters={'chat_template_kwargs': {'enable_thinking': False}} if disable_thinking else {})
    return OpenAICompatibleCompactInterpretationProvider(config, prompt,
        OneShotChatRequestGuard(MODEL, output_limit=output), BoundedExternalChatTransport())
