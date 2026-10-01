"""Owned loopback verifies startup authentication without real model calls."""
import json
import pytest

from test_external_toy_interpretation import _loopback, SECRET, MODEL
from xgap.experiments.llm_auth_preflight import check_authentication


@pytest.mark.parametrize('status,usage,model,success', [
    (200, {'prompt_tokens':15,'completion_tokens':2,'total_tokens':17}, MODEL, True),
    (200, None, MODEL, False),
    (200, {'prompt_tokens':15,'completion_tokens':2,'total_tokens':16}, MODEL, False),
    (200, {'prompt_tokens':15,'completion_tokens':2,'total_tokens':17}, 'wrong-model', False),
    (401, None, MODEL, False),
    (302, None, MODEL, False),
])
def test_preflight_is_one_bounded_metered_request(status,usage,model,success,monkeypatch):
    monkeypatch.setenv('NO_PROXY','127.0.0.1,localhost')
    monkeypatch.setenv('no_proxy','127.0.0.1,localhost')
    def respond(path, body):
        reply = dict(model=model, choices=[{'message':{'content':'OK'}}], usage=usage)
        if status != 200:reply={'error':'Unauthorized '+SECRET}
        return status, {'Location':'/must-not-follow'}, json.dumps(reply).encode()
    with _loopback(respond) as (url, received):
        report=check_authentication(base_url=url,model=MODEL,api_key=SECRET)
    assert len(received)==report['model_calls']==1
    assert received[0]['authorization']=='Bearer '+SECRET
    payload=json.loads(received[0]['body'])
    assert payload['max_tokens']==8 and payload['chat_template_kwargs']=={'enable_thinking':False}
    assert report['success'] is success
    assert report['automatic_retries']==report['backend_calls']==0
    assert not report['formal_result'] and SECRET not in json.dumps(report)
    if success:assert (report['input_tokens'],report['output_tokens'])==(15,2)
    if status!=200:assert report['input_tokens'] is report['output_tokens'] is None


def test_empty_key_sends_nothing():
    with pytest.raises(ValueError,match='no authentication request'):
        check_authentication(base_url='http://unused.invalid/v1',model=MODEL,api_key=' ')
