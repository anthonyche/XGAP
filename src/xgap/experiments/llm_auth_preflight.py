"""One tiny, separately metered startup request before costly source loading.

This checks credentials and usage reporting, not semantic output quality. It is
never an evaluation query, retry policy, or substitute for the frozen provider.
"""
from datetime import datetime, timezone
import time

from xgap.experiments.external_toy_interpretation import BoundedExternalChatTransport


def check_authentication(*, base_url, model, api_key, transport=None):
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError('Empty credential; no authentication request sent')
    key = api_key.strip()
    payload = dict(model=model, messages=[dict(role='user', content='Reply OK.')],
        max_tokens=8, temperature=0, stream=False,
        chat_template_kwargs=dict(enable_thinking=False))
    report = dict(schema_version='xgap-llm-auth-preflight-v1', success=False,
        purpose='startup_authentication_only', formal_result=False,
        timestamp_utc=datetime.now(timezone.utc).isoformat(), base_url=base_url, model=model,
        model_calls=1, automatic_retries=0, backend_calls=0, max_output_tokens=8,
        input_tokens=None, output_tokens=None, token_usage_complete=False)
    started = time.perf_counter()
    try:
        reply = (transport or BoundedExternalChatTransport()).post_json(
            url=base_url.rstrip('/')+'/chat/completions', api_key=key,
            payload=payload, timeout_seconds=20)
        report['returned_model'] = reply.get('model')
        usage = reply.get('usage') or {}
        counts = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        complete = all(type(v) is int and v >= 0 for v in counts) and counts[0]+counts[1] == counts[2]
        if complete:
            report.update(input_tokens=counts[0], output_tokens=counts[1], token_usage_complete=True)
        if reply.get('model') != model or not isinstance(reply.get('choices'), list) or not reply['choices']:
            report['error'] = 'Endpoint did not return the requested model and chat choices'
        elif not complete:
            report['error'] = 'Endpoint did not report complete token usage'
        else:
            report['success'] = True
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error).replace(key, '[REDACTED]'))
    report['elapsed_ms'] = (time.perf_counter()-started)*1000
    return report
